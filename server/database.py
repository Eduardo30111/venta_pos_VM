import os
import logging
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings, DEFAULT_SQLITE_URL
from .aiosqlite_compat import asegurar_aiosqlite

logger = logging.getLogger("vmpos.database")

if "aiosqlite" in settings.DATABASE_URL:
    asegurar_aiosqlite()

_echo_sql = os.environ.get("VMPOS_SQL_ECHO", "0") == "1"


def _migrar_archivo_sqlite_directo(db_url: str):
    """Aplica migraciones DDL directamente en SQLite antes de inicializar SQLAlchemy."""
    try:
        clean_url = db_url.split("?")[0]
        db_path = clean_url
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if clean_url.startswith(prefix):
                db_path = clean_url[len(prefix):]
                break
        if not db_path or not os.path.exists(db_path):
            return
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=12)
        cur = conn.cursor()
        try:
            # 1. Sesiones de Caja
            cur.execute("PRAGMA table_info(sesiones_caja);")
            cols_caja = {r[1] for r in cur.fetchall()}
            if cols_caja:
                cols_sesion = [
                    ("arqueo_apertura_json", "TEXT"),
                    ("arqueo_cierre_json", "TEXT"),
                    ("monto_transferencias_esperado", "REAL DEFAULT 0.0"),
                    ("monto_transferencias_verificado", "REAL DEFAULT 0.0"),
                    ("diferencia_banco", "REAL DEFAULT 0.0"),
                    ("estado_banco", "TEXT DEFAULT 'Pendiente'"),
                    ("terminal_id", "INTEGER"),
                    ("terminal_nombre", "TEXT"),
                    ("observaciones", "TEXT"),
                    ("fecha_cierre", "TEXT"),
                    ("hora_cierre", "TEXT"),
                    ("usuario_cierre", "TEXT"),
                    ("monto_esperado_efectivo", "REAL DEFAULT 0.0"),
                    ("monto_real_contado", "REAL DEFAULT 0.0"),
                    ("diferencia", "REAL DEFAULT 0.0"),
                    ("created_at", "TIMESTAMP"),
                ]
                for c_nom, c_def in cols_sesion:
                    if c_nom not in cols_caja:
                        try:
                            cur.execute(f"ALTER TABLE sesiones_caja ADD COLUMN {c_nom} {c_def};")
                        except Exception:
                            pass
                try:
                    cur.execute("UPDATE sesiones_caja SET created_at = datetime('now') WHERE created_at IS NULL;")
                except Exception:
                    pass

            # 2. Proveedores
            cur.execute("PRAGMA table_info(proveedores);")
            cols_prov = {r[1] for r in cur.fetchall()}
            if cols_prov:
                cols_p = [
                    ("documento_nit", "TEXT DEFAULT ''"),
                    ("email", "TEXT DEFAULT ''"),
                    ("direccion", "TEXT DEFAULT ''"),
                    ("contacto", "TEXT DEFAULT ''"),
                    ("estado", "TEXT DEFAULT 'Activo'"),
                    ("saldo_acumulado", "REAL DEFAULT 0.0"),
                    ("total_ventas", "REAL DEFAULT 0.0"),
                    ("total_comisiones", "REAL DEFAULT 0.0"),
                    ("total_pagado", "REAL DEFAULT 0.0"),
                ]
                for c_nom, c_def in cols_p:
                    if c_nom not in cols_prov:
                        try:
                            cur.execute(f"ALTER TABLE proveedores ADD COLUMN {c_nom} {c_def};")
                        except Exception:
                            pass
                try:
                    if "nit_documento" in cols_prov:
                        cur.execute("UPDATE proveedores SET documento_nit = nit_documento WHERE (documento_nit IS NULL OR documento_nit = '') AND nit_documento IS NOT NULL;")
                    if "correo" in cols_prov:
                        cur.execute("UPDATE proveedores SET email = correo WHERE (email IS NULL OR email = '') AND correo IS NOT NULL;")
                except Exception:
                    pass

            # 3. Productos (catálogo unificado y tolerante a alias costo/precio)
            cur.execute("PRAGMA table_info(productos);")
            cols_prod = {r[1] for r in cur.fetchall()}
            if cols_prod:
                cols_pr = [
                    ("categoria_id", "INTEGER"),
                    ("categoria", "TEXT DEFAULT 'General'"),
                    ("marca", "TEXT DEFAULT ''"),
                    ("unidad_medida", "TEXT DEFAULT 'Unidad'"),
                    ("precio_costo", "REAL DEFAULT 0.0"),
                    ("costo", "REAL DEFAULT 0.0"),
                    ("precio_venta", "REAL DEFAULT 0.0"),
                    ("precio", "REAL DEFAULT 0.0"),
                    ("stock", "REAL DEFAULT 0.0"),
                    ("stock_minimo", "REAL DEFAULT 0.0"),
                    ("stock_bodega", "REAL DEFAULT 0.0"),
                    ("stock_vitrina", "REAL DEFAULT 0.0"),
                    ("stock_minimo_bodega", "REAL DEFAULT 5.0"),
                    ("stock_minimo_vitrina", "REAL DEFAULT 3.0"),
                    ("proveedor_id", "INTEGER"),
                    ("codigo_barras", "TEXT DEFAULT ''"),
                    ("imagen_url", "TEXT DEFAULT ''"),
                    ("precio_variable", "INTEGER DEFAULT 0"),
                    ("porcentaje_comision", "REAL DEFAULT 0.0"),
                    ("es_material", "INTEGER DEFAULT 0"),
                    ("presentacion_defecto", "TEXT DEFAULT 'Paquete'"),
                    ("factor_conversion_defecto", "REAL DEFAULT 1.0"),
                    ("unidad_consumo_defecto", "TEXT DEFAULT 'Unidad'"),
                    ("tipo_producto", "TEXT DEFAULT 'Producto'"),
                    ("estado", "TEXT DEFAULT 'Activo'"),
                    ("fecha_creacion", "TEXT"),
                    ("fecha_modificacion", "TEXT"),
                    ("created_at", "TIMESTAMP"),
                    ("updated_at", "TIMESTAMP"),
                ]
                for c_nom, c_def in cols_pr:
                    if c_nom not in cols_prod:
                        try:
                            cur.execute(f"ALTER TABLE productos ADD COLUMN {c_nom} {c_def};")
                        except Exception:
                            pass
                try:
                    if "costo" in cols_prod:
                        cur.execute("UPDATE productos SET precio_costo = costo WHERE (precio_costo IS NULL OR precio_costo = 0.0) AND costo IS NOT NULL AND costo > 0.0;")
                    if "precio_costo" in cols_prod:
                        cur.execute("UPDATE productos SET costo = precio_costo WHERE (costo IS NULL OR costo = 0.0) AND precio_costo IS NOT NULL AND precio_costo > 0.0;")
                    if "precio" in cols_prod:
                        cur.execute("UPDATE productos SET precio_venta = precio WHERE (precio_venta IS NULL OR precio_venta = 0.0) AND precio IS NOT NULL AND precio > 0.0;")
                    if "precio_venta" in cols_prod:
                        cur.execute("UPDATE productos SET precio = precio_venta WHERE (precio IS NULL OR precio = 0.0) AND precio_venta IS NOT NULL AND precio_venta > 0.0;")
                    if "stock" in cols_prod:
                        cur.execute("UPDATE productos SET stock_vitrina = stock WHERE (stock_vitrina IS NULL OR stock_vitrina = 0.0) AND (stock_bodega IS NULL OR stock_bodega = 0.0) AND stock > 0.0;")
                    cur.execute("UPDATE productos SET tipo_producto = 'Producto' WHERE tipo_producto IS NULL OR tipo_producto = '';")
                    cur.execute("UPDATE productos SET created_at = datetime('now') WHERE created_at IS NULL;")
                    cur.execute("UPDATE productos SET updated_at = datetime('now') WHERE updated_at IS NULL;")
                except Exception:
                    pass

            # 4. Movimientos de Inventario (Kárdex tolerante a tipo y tipo_movimiento)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS movimientos_inventario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fecha TEXT,
                    hora TEXT,
                    producto_id INTEGER NOT NULL,
                    codigo_producto TEXT,
                    nombre_producto TEXT,
                    tipo TEXT,
                    tipo_movimiento TEXT,
                    cantidad REAL NOT NULL,
                    unidad_medida TEXT DEFAULT 'Unidad',
                    ubicacion_origen TEXT DEFAULT '',
                    ubicacion_destino TEXT DEFAULT '',
                    stock_anterior REAL DEFAULT 0.0,
                    stock_nuevo REAL DEFAULT 0.0,
                    stock_origen_ant REAL DEFAULT 0.0,
                    stock_origen_des REAL DEFAULT 0.0,
                    stock_destino_ant REAL DEFAULT 0.0,
                    stock_destino_des REAL DEFAULT 0.0,
                    costo_unitario REAL DEFAULT 0.0,
                    valor_total REAL DEFAULT 0.0,
                    referencia TEXT DEFAULT '',
                    usuario_id INTEGER,
                    usuario_nombre TEXT DEFAULT '',
                    usuario TEXT DEFAULT 'Administrador',
                    terminal_id INTEGER,
                    observacion TEXT DEFAULT '',
                    observaciones TEXT DEFAULT '',
                    estado TEXT DEFAULT 'Completado',
                    created_at TIMESTAMP
                );
            """)
            cur.execute("PRAGMA table_info(movimientos_inventario);")
            cols_mov = {r[1] for r in cur.fetchall()}
            if cols_mov:
                cols_m = [
                    ("fecha", "TEXT"),
                    ("hora", "TEXT"),
                    ("codigo_producto", "TEXT"),
                    ("nombre_producto", "TEXT"),
                    ("tipo", "TEXT"),
                    ("tipo_movimiento", "TEXT"),
                    ("cantidad", "REAL DEFAULT 0.0"),
                    ("unidad_medida", "TEXT DEFAULT 'Unidad'"),
                    ("ubicacion_origen", "TEXT DEFAULT ''"),
                    ("ubicacion_destino", "TEXT DEFAULT ''"),
                    ("stock_anterior", "REAL DEFAULT 0.0"),
                    ("stock_nuevo", "REAL DEFAULT 0.0"),
                    ("stock_origen_ant", "REAL DEFAULT 0.0"),
                    ("stock_origen_des", "REAL DEFAULT 0.0"),
                    ("stock_destino_ant", "REAL DEFAULT 0.0"),
                    ("stock_destino_des", "REAL DEFAULT 0.0"),
                    ("costo_unitario", "REAL DEFAULT 0.0"),
                    ("valor_total", "REAL DEFAULT 0.0"),
                    ("referencia", "TEXT DEFAULT ''"),
                    ("usuario_id", "INTEGER"),
                    ("usuario_nombre", "TEXT DEFAULT ''"),
                    ("usuario", "TEXT DEFAULT 'Administrador'"),
                    ("terminal_id", "INTEGER"),
                    ("observacion", "TEXT DEFAULT ''"),
                    ("observaciones", "TEXT DEFAULT ''"),
                    ("estado", "TEXT DEFAULT 'Completado'"),
                    ("created_at", "TIMESTAMP"),
                ]
                for c_nom, c_def in cols_m:
                    if c_nom not in cols_mov:
                        try:
                            cur.execute(f"ALTER TABLE movimientos_inventario ADD COLUMN {c_nom} {c_def};")
                        except Exception:
                            pass
                try:
                    if "tipo_movimiento" in cols_mov:
                        cur.execute("UPDATE movimientos_inventario SET tipo = tipo_movimiento WHERE (tipo IS NULL OR tipo = '') AND tipo_movimiento IS NOT NULL;")
                    if "tipo" in cols_mov:
                        cur.execute("UPDATE movimientos_inventario SET tipo_movimiento = tipo WHERE (tipo_movimiento IS NULL OR tipo_movimiento = '') AND tipo IS NOT NULL;")
                    if "usuario" in cols_mov:
                        cur.execute("UPDATE movimientos_inventario SET usuario_nombre = usuario WHERE (usuario_nombre IS NULL OR usuario_nombre = '') AND usuario IS NOT NULL;")
                    if "usuario_nombre" in cols_mov:
                        cur.execute("UPDATE movimientos_inventario SET usuario = usuario_nombre WHERE (usuario IS NULL OR usuario = '') AND usuario_nombre IS NOT NULL;")
                    if "observaciones" in cols_mov:
                        cur.execute("UPDATE movimientos_inventario SET observacion = observaciones WHERE (observacion IS NULL OR observacion = '') AND observaciones IS NOT NULL;")
                    if "observacion" in cols_mov:
                        cur.execute("UPDATE movimientos_inventario SET observaciones = observacion WHERE (observaciones IS NULL OR observaciones = '') AND observacion IS NOT NULL;")
                    cur.execute("UPDATE movimientos_inventario SET created_at = datetime('now') WHERE created_at IS NULL;")
                except Exception:
                    pass

            # 5. Compras de Inventario
            cur.execute("""
                CREATE TABLE IF NOT EXISTS compras_inventario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    numero_compra TEXT UNIQUE NOT NULL,
                    fecha TEXT NOT NULL,
                    hora TEXT NOT NULL,
                    proveedor_id INTEGER,
                    proveedor_nombre TEXT,
                    documento_referencia TEXT,
                    ubicacion_destino TEXT DEFAULT 'BODEGA',
                    total_compra REAL DEFAULT 0.0,
                    usuario TEXT DEFAULT 'Administrador',
                    observaciones TEXT DEFAULT '',
                    estado TEXT DEFAULT 'Recibida',
                    created_at TIMESTAMP
                );
            """)
            cur.execute("PRAGMA table_info(compras_inventario);")
            cols_ci = {r[1] for r in cur.fetchall()}
            if "created_at" not in cols_ci:
                try:
                    cur.execute("ALTER TABLE compras_inventario ADD COLUMN created_at TIMESTAMP;")
                    cur.execute("UPDATE compras_inventario SET created_at = datetime('now') WHERE created_at IS NULL;")
                except Exception:
                    pass

            # 6. Detalle Compras
            cur.execute("""
                CREATE TABLE IF NOT EXISTS detalle_compras (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    compra_id INTEGER NOT NULL,
                    producto_id INTEGER NOT NULL,
                    codigo_producto TEXT NOT NULL,
                    nombre_producto TEXT NOT NULL,
                    unidad_compra TEXT DEFAULT 'Unidad',
                    factor_conversion REAL DEFAULT 1.0,
                    cantidad_comprada REAL DEFAULT 1.0,
                    cantidad_unidades REAL DEFAULT 1.0,
                    costo_unidad_compra REAL DEFAULT 0.0,
                    costo_unitario_convertido REAL DEFAULT 0.0,
                    subtotal REAL DEFAULT 0.0
                );
            """)

            # 7. Traslados de Inventario
            cur.execute("""
                CREATE TABLE IF NOT EXISTS traslados_inventario (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    numero_traslado TEXT UNIQUE NOT NULL,
                    fecha TEXT NOT NULL,
                    hora TEXT NOT NULL,
                    producto_id INTEGER NOT NULL,
                    codigo_producto TEXT NOT NULL,
                    nombre_producto TEXT NOT NULL,
                    ubicacion_origen TEXT NOT NULL,
                    ubicacion_destino TEXT NOT NULL,
                    cantidad REAL NOT NULL,
                    usuario TEXT NOT NULL DEFAULT 'Administrador',
                    estado TEXT NOT NULL DEFAULT 'Completado',
                    observaciones TEXT DEFAULT '',
                    created_at TIMESTAMP
                );
            """)
            cur.execute("PRAGMA table_info(traslados_inventario);")
            cols_ti = {r[1] for r in cur.fetchall()}
            if "created_at" not in cols_ti:
                try:
                    cur.execute("ALTER TABLE traslados_inventario ADD COLUMN created_at TIMESTAMP;")
                    cur.execute("UPDATE traslados_inventario SET created_at = datetime('now') WHERE created_at IS NULL;")
                except Exception:
                    pass

            # 8. Servicios
            cur.execute("PRAGMA table_info(servicios);")
            cols_srv = {r[1] for r in cur.fetchall()}
            if cols_srv:
                cols_s_defs = [
                    ("categoria", "TEXT DEFAULT 'Servicios'"),
                    ("marca", "TEXT DEFAULT ''"),
                    ("codigo_barras", "TEXT DEFAULT ''"),
                    ("unidad_medida", "TEXT DEFAULT 'Servicio'"),
                    ("precio_variable", "INTEGER DEFAULT 0"),
                    ("solo_operarios", "INTEGER DEFAULT 0"),
                    ("creado_por_operario_id", "INTEGER"),
                ]
                for c_nom, c_def in cols_s_defs:
                    if c_nom not in cols_srv:
                        try:
                            cur.execute(f"ALTER TABLE servicios ADD COLUMN {c_nom} {c_def};")
                        except Exception:
                            pass

            # 9. Tablas de Materiales, Operarios y Consumos
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventario_operarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    usuario_id INTEGER,
                    usuario_nombre TEXT NOT NULL,
                    rol TEXT NOT NULL DEFAULT 'Operario',
                    producto_id INTEGER NOT NULL,
                    codigo_producto TEXT NOT NULL,
                    nombre_producto TEXT NOT NULL,
                    unidad_medida TEXT NOT NULL DEFAULT 'Unidad',
                    stock_disponible REAL NOT NULL DEFAULT 0.0,
                    total_recibido REAL NOT NULL DEFAULT 0.0,
                    total_consumido REAL NOT NULL DEFAULT 0.0,
                    total_desperdiciado REAL NOT NULL DEFAULT 0.0,
                    total_devuelto REAL NOT NULL DEFAULT 0.0,
                    ultimo_movimiento TEXT,
                    fecha_actualizacion TEXT,
                    UNIQUE(usuario_nombre, producto_id)
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS presentaciones_producto (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    producto_id INTEGER NOT NULL,
                    codigo_producto TEXT NOT NULL,
                    nombre_presentacion TEXT NOT NULL,
                    unidad_compra TEXT NOT NULL DEFAULT 'Paquete',
                    cantidad_unidades_base REAL NOT NULL DEFAULT 1.0,
                    unidad_consumo TEXT NOT NULL DEFAULT 'Unidad',
                    costo_defecto REAL DEFAULT 0.0,
                    codigo_barras TEXT DEFAULT '',
                    activo INTEGER NOT NULL DEFAULT 1,
                    fecha_creacion TEXT
                );
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS consumos_materiales_venta (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venta_id INTEGER NOT NULL,
                    numero_factura TEXT DEFAULT '',
                    usuario_responsable TEXT NOT NULL,
                    producto_id INTEGER NOT NULL,
                    codigo_producto TEXT NOT NULL,
                    nombre_producto TEXT NOT NULL,
                    cantidad_consumida REAL NOT NULL,
                    unidad_medida TEXT NOT NULL DEFAULT 'Unidad',
                    saldo_anterior REAL NOT NULL DEFAULT 0.0,
                    saldo_restante REAL NOT NULL DEFAULT 0.0,
                    costo_unitario REAL DEFAULT 0.0,
                    costo_total REAL DEFAULT 0.0,
                    fecha TEXT NOT NULL,
                    hora TEXT NOT NULL,
                    estado TEXT NOT NULL DEFAULT 'Aplicado',
                    observaciones TEXT DEFAULT '',
                    created_at TIMESTAMP
                );
            """)
            # 10. Idempotencia y columnas transaccionales
            idem_tablas = [
                "compras_inventario",
                "movimientos_inventario",
                "traslados_inventario",
                "gastos",
                "liquidaciones_proveedores",
                "liquidaciones",
                "ventas",
                "abonos",
                "movimientos_caja",
                "movimientos_financieros",
            ]
            for t_nom in idem_tablas:
                try:
                    cur.execute(f"PRAGMA table_info({t_nom});")
                    t_cols = {r[1] for r in cur.fetchall()}
                    if t_cols and "idempotency_key" not in t_cols:
                        cur.execute(f"ALTER TABLE {t_nom} ADD COLUMN idempotency_key TEXT;")
                    if t_cols and "observaciones" not in t_cols and t_nom in ("compras_inventario", "traslados_inventario", "movimientos_inventario"):
                        cur.execute(f"ALTER TABLE {t_nom} ADD COLUMN observaciones TEXT DEFAULT '';")
                    if t_cols and "created_at" not in t_cols:
                        cur.execute(f"ALTER TABLE {t_nom} ADD COLUMN created_at TIMESTAMP;")
                except Exception as e_mig_col:
                    if "duplicate column" not in str(e_mig_col).lower():
                        logger.debug("Aviso columna en %s: %s", t_nom, e_mig_col)
            for t_nom in idem_tablas:
                try:
                    cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{t_nom}_idempotency_key ON {t_nom}(idempotency_key);")
                except Exception as e_mig_idx:
                    if "already exists" not in str(e_mig_idx).lower():
                        logger.debug("Aviso índice en %s: %s", t_nom, e_mig_idx)

            conn.commit()
        finally:
            conn.close()
    except Exception as e_mig:
        logger.warning("Aviso en migración SQLite directa: %s", e_mig)


def asegurar_migraciones_sqlite(db_url_or_path: str = None):
    """Garantiza de forma inmediata y tolerante que todas las tablas y columnas SQLite existan."""
    if not db_url_or_path:
        db_url_or_path = settings.DATABASE_URL
    _migrar_archivo_sqlite_directo(db_url_or_path)


def _crear_engine(db_url: str):
    if "sqlite" in db_url:
        _migrar_archivo_sqlite_directo(db_url)
        asegurar_aiosqlite()
        eng = create_async_engine(
            db_url,
            echo=_echo_sql,
            connect_args={"timeout": 15, "check_same_thread": False},
        )

        @event.listens_for(eng.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):
            try:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=15000;")

                # Migración preventiva inmediata de columnas en SQLite
                try:
                    cursor.execute("PRAGMA table_info(sesiones_caja);")
                    cols_caja = [r[1] for r in cursor.fetchall()]
                    if cols_caja:
                        cols_sesion = [
                            ("arqueo_apertura_json", "TEXT"),
                    ("arqueo_cierre_json", "TEXT"),
                            ("monto_transferencias_esperado", "REAL DEFAULT 0.0"),
                            ("monto_transferencias_verificado", "REAL DEFAULT 0.0"),
                            ("diferencia_banco", "REAL DEFAULT 0.0"),
                            ("estado_banco", "TEXT DEFAULT 'Pendiente'"),
                            ("terminal_id", "INTEGER"),
                            ("terminal_nombre", "TEXT"),
                            ("observaciones", "TEXT"),
                            ("fecha_cierre", "TEXT"),
                            ("hora_cierre", "TEXT"),
                            ("usuario_cierre", "TEXT"),
                            ("monto_esperado_efectivo", "REAL DEFAULT 0.0"),
                            ("monto_real_contado", "REAL DEFAULT 0.0"),
                            ("diferencia", "REAL DEFAULT 0.0"),
                            ("created_at", "TIMESTAMP"),
                        ]
                        for c_nom, c_def in cols_sesion:
                            if c_nom not in cols_caja:
                                try:
                                    cursor.execute(f"ALTER TABLE sesiones_caja ADD COLUMN {c_nom} {c_def};")
                                except Exception:
                                    pass
                        try:
                            cursor.execute("UPDATE sesiones_caja SET created_at = datetime('now') WHERE created_at IS NULL;")
                        except Exception:
                            pass

                    cursor.execute("PRAGMA table_info(proveedores);")
                    cols_prov = [r[1] for r in cursor.fetchall()]
                    if cols_prov:
                        cols_p = [
                            ("documento_nit", "TEXT DEFAULT ''"),
                            ("email", "TEXT DEFAULT ''"),
                            ("direccion", "TEXT DEFAULT ''"),
                            ("contacto", "TEXT DEFAULT ''"),
                            ("estado", "TEXT DEFAULT 'Activo'"),
                            ("saldo_acumulado", "REAL DEFAULT 0.0"),
                            ("total_ventas", "REAL DEFAULT 0.0"),
                            ("total_comisiones", "REAL DEFAULT 0.0"),
                            ("total_pagado", "REAL DEFAULT 0.0"),
                        ]
                        for c_nom, c_def in cols_p:
                            if c_nom not in cols_prov:
                                try:
                                    cursor.execute(f"ALTER TABLE proveedores ADD COLUMN {c_nom} {c_def};")
                                except Exception:
                                    pass
                    for t_nom in ("compras_inventario", "movimientos_inventario", "traslados_inventario", "gastos", "liquidaciones_proveedores", "liquidaciones", "ventas", "abonos", "movimientos_caja", "movimientos_financieros"):
                        try:
                            cursor.execute(f"PRAGMA table_info({t_nom});")
                            t_cols = {r[1] for r in cursor.fetchall()}
                            if t_cols and "idempotency_key" not in t_cols:
                                cursor.execute(f"ALTER TABLE {t_nom} ADD COLUMN idempotency_key TEXT;")
                                cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{t_nom}_idempotency_key ON {t_nom}(idempotency_key);")
                        except Exception as e_prg:
                            if "duplicate column" not in str(e_prg).lower() and "already exists" not in str(e_prg).lower():
                                logger.debug("Aviso pragma idempotencia %s: %s", t_nom, e_prg)
                    dbapi_connection.commit()
                except Exception:
                    pass

                cursor.close()
            except Exception:
                pass

        return eng
    return create_async_engine(db_url, echo=_echo_sql)


engine = _crear_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


def activar_fallback_sqlite():
    """Conmuta dinámicamente el motor central a SQLite/WAL si PostgreSQL falla al iniciar."""
    global engine, SessionLocal
    settings.DATABASE_URL = DEFAULT_SQLITE_URL
    engine = _crear_engine(DEFAULT_SQLITE_URL)
    SessionLocal.configure(bind=engine)
    return engine


async def get_db():
    async with SessionLocal() as session:
        yield session


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


class MigrationError(RuntimeError):
    """Excepción lanzada cuando ocurre un error crítico e irrecuperable en una migración de base de datos."""
    pass

def _is_benign_ddl_error(error: Exception) -> bool:
    msg = str(error).lower()
    return "duplicate column" in msg or "already exists" in msg

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

        def _safe_alter_column_direct(c, sql: str, desc: str = ""):
            try:
                c.execute(sql)
            except Exception as e:
                if _is_benign_ddl_error(e):
                    return
                logger.critical("Error crítico fatal en migración DDL directa (%s): %s", desc or sql[:50], e)
                raise MigrationError(f"Error fatal de migración DDL ({desc}): {e}") from e

        def _safe_update_direct(c, sql: str, desc: str = ""):
            try:
                c.execute(sql)
            except Exception as e:
                logger.critical("Error crítico fatal en UPDATE migración directa (%s): %s", desc or sql[:50], e)
                raise MigrationError(f"Error fatal de UPDATE migración ({desc}): {e}") from e

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
                        _safe_alter_column_direct(cur, f"ALTER TABLE sesiones_caja ADD COLUMN {c_nom} {c_def};", f"sesiones_caja.{c_nom}")
                _safe_update_direct(cur, "UPDATE sesiones_caja SET created_at = datetime('now') WHERE created_at IS NULL;", "sesiones_caja created_at")

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
                        _safe_alter_column_direct(cur, f"ALTER TABLE proveedores ADD COLUMN {c_nom} {c_def};", f"proveedores.{c_nom}")
                if "nit_documento" in cols_prov:
                    _safe_update_direct(cur, "UPDATE proveedores SET documento_nit = nit_documento WHERE (documento_nit IS NULL OR documento_nit = '') AND nit_documento IS NOT NULL;", "proveedores nit_documento")
                if "correo" in cols_prov:
                    _safe_update_direct(cur, "UPDATE proveedores SET email = correo WHERE (email IS NULL OR email = '') AND correo IS NOT NULL;", "proveedores correo")

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
                        _safe_alter_column_direct(cur, f"ALTER TABLE productos ADD COLUMN {c_nom} {c_def};", f"productos.{c_nom}")
                if "costo" in cols_prod:
                    _safe_update_direct(cur, "UPDATE productos SET precio_costo = costo WHERE (precio_costo IS NULL OR precio_costo = 0.0) AND costo IS NOT NULL AND costo > 0.0;", "productos costo -> precio_costo")
                if "precio_costo" in cols_prod:
                    _safe_update_direct(cur, "UPDATE productos SET costo = precio_costo WHERE (costo IS NULL OR costo = 0.0) AND precio_costo IS NOT NULL AND precio_costo > 0.0;", "productos precio_costo -> costo")
                if "precio" in cols_prod:
                    _safe_update_direct(cur, "UPDATE productos SET precio_venta = precio WHERE (precio_venta IS NULL OR precio_venta = 0.0) AND precio IS NOT NULL AND precio > 0.0;", "productos precio -> precio_venta")
                if "precio_venta" in cols_prod:
                    _safe_update_direct(cur, "UPDATE productos SET precio = precio_venta WHERE (precio IS NULL OR precio = 0.0) AND precio_venta IS NOT NULL AND precio_venta > 0.0;", "productos precio_venta -> precio")
                if "stock" in cols_prod:
                    _safe_update_direct(cur, "UPDATE productos SET stock_vitrina = stock WHERE (stock_vitrina IS NULL OR stock_vitrina = 0.0) AND (stock_bodega IS NULL OR stock_bodega = 0.0) AND stock > 0.0;", "productos stock -> stock_vitrina")
                _safe_update_direct(cur, "UPDATE productos SET tipo_producto = 'Producto' WHERE tipo_producto IS NULL OR tipo_producto = '';", "productos tipo_producto default")
                _safe_update_direct(cur, "UPDATE productos SET created_at = datetime('now') WHERE created_at IS NULL;", "productos created_at")
                _safe_update_direct(cur, "UPDATE productos SET updated_at = datetime('now') WHERE updated_at IS NULL;", "productos updated_at")

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
                        _safe_alter_column_direct(cur, f"ALTER TABLE movimientos_inventario ADD COLUMN {c_nom} {c_def};", f"movimientos_inventario.{c_nom}")
                if "tipo_movimiento" in cols_mov:
                    _safe_update_direct(cur, "UPDATE movimientos_inventario SET tipo = tipo_movimiento WHERE (tipo IS NULL OR tipo = '') AND tipo_movimiento IS NOT NULL;", "movimientos tipo_movimiento -> tipo")
                if "tipo" in cols_mov:
                    _safe_update_direct(cur, "UPDATE movimientos_inventario SET tipo_movimiento = tipo WHERE (tipo_movimiento IS NULL OR tipo_movimiento = '') AND tipo IS NOT NULL;", "movimientos tipo -> tipo_movimiento")
                if "usuario" in cols_mov:
                    _safe_update_direct(cur, "UPDATE movimientos_inventario SET usuario_nombre = usuario WHERE (usuario_nombre IS NULL OR usuario_nombre = '') AND usuario IS NOT NULL;", "movimientos usuario -> usuario_nombre")
                if "usuario_nombre" in cols_mov:
                    _safe_update_direct(cur, "UPDATE movimientos_inventario SET usuario = usuario_nombre WHERE (usuario IS NULL OR usuario = '') AND usuario_nombre IS NOT NULL;", "movimientos usuario_nombre -> usuario")
                if "observaciones" in cols_mov:
                    _safe_update_direct(cur, "UPDATE movimientos_inventario SET observacion = observaciones WHERE (observacion IS NULL OR observacion = '') AND observaciones IS NOT NULL;", "movimientos observaciones -> observacion")
                if "observacion" in cols_mov:
                    _safe_update_direct(cur, "UPDATE movimientos_inventario SET observaciones = observacion WHERE (observaciones IS NULL OR observaciones = '') AND observacion IS NOT NULL;", "movimientos observacion -> observaciones")
                _safe_update_direct(cur, "UPDATE movimientos_inventario SET created_at = datetime('now') WHERE created_at IS NULL;", "movimientos created_at")

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
                _safe_alter_column_direct(cur, "ALTER TABLE compras_inventario ADD COLUMN created_at TIMESTAMP;", "compras_inventario.created_at")
                _safe_update_direct(cur, "UPDATE compras_inventario SET created_at = datetime('now') WHERE created_at IS NULL;", "compras_inventario created_at")

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
                _safe_alter_column_direct(cur, "ALTER TABLE traslados_inventario ADD COLUMN created_at TIMESTAMP;", "traslados_inventario.created_at")
                _safe_update_direct(cur, "UPDATE traslados_inventario SET created_at = datetime('now') WHERE created_at IS NULL;", "traslados_inventario created_at")

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
                        _safe_alter_column_direct(cur, f"ALTER TABLE servicios ADD COLUMN {c_nom} {c_def};", f"servicios.{c_nom}")

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
            # 9b. Usuarios, Asistencias y Liquidaciones (seguridad y control de pagos únicos)
            cur.execute("PRAGMA table_info(usuarios);")
            cols_usr = {r[1] for r in cur.fetchall()}
            if cols_usr and "requiere_cambio_password" not in cols_usr:
                _safe_alter_column_direct(
                    cur,
                    "ALTER TABLE usuarios ADD COLUMN requiere_cambio_password INTEGER DEFAULT 0;",
                    "usuarios.requiere_cambio_password",
                )

            cur.execute("PRAGMA table_info(asistencias);")
            cols_asi = {r[1] for r in cur.fetchall()}
            if cols_asi and "liquidacion_id" not in cols_asi:
                _safe_alter_column_direct(
                    cur,
                    "ALTER TABLE asistencias ADD COLUMN liquidacion_id INTEGER;",
                    "asistencias.liquidacion_id",
                )

            cur.execute("PRAGMA table_info(liquidaciones);")
            cols_liq = {r[1] for r in cur.fetchall()}
            if cols_liq and "metodo_pago" not in cols_liq:
                _safe_alter_column_direct(
                    cur,
                    "ALTER TABLE liquidaciones ADD COLUMN metodo_pago TEXT DEFAULT 'Efectivo';",
                    "liquidaciones.metodo_pago",
                )

            for t_nom in idem_tablas:
                cur.execute(f"PRAGMA table_info({t_nom});")
                t_cols = {r[1] for r in cur.fetchall()}
                if not t_cols:
                    continue
                if "idempotency_key" not in t_cols:
                    _safe_alter_column_direct(cur, f"ALTER TABLE {t_nom} ADD COLUMN idempotency_key TEXT;", f"{t_nom}.idempotency_key")
                if "observaciones" not in t_cols and t_nom in ("compras_inventario", "traslados_inventario", "movimientos_inventario"):
                    _safe_alter_column_direct(cur, f"ALTER TABLE {t_nom} ADD COLUMN observaciones TEXT DEFAULT '';", f"{t_nom}.observaciones")
                if "created_at" not in t_cols:
                    _safe_alter_column_direct(cur, f"ALTER TABLE {t_nom} ADD COLUMN created_at TIMESTAMP;", f"{t_nom}.created_at")
                _safe_alter_column_direct(
                    cur,
                    f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{t_nom}_idempotency_key ON {t_nom}(idempotency_key);",
                    f"uq_{t_nom}_idempotency_key",
                )

            conn.commit()
        finally:
            conn.close()
    except MigrationError:
        raise
    except Exception as e_mig:
        logger.critical("Error fatal en migración SQLite directa: %s", e_mig)
        raise MigrationError(f"Fallo irrecuperable en migración de base de datos: {e_mig}") from e_mig


def asegurar_migraciones_sqlite(db_url_or_path: str = None):
    """Garantiza de forma inmediata y estricta que todas las tablas y columnas SQLite existan."""
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
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=15000;")
            finally:
                cursor.close()

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


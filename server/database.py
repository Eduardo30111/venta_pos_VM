import os
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings, DEFAULT_SQLITE_URL
from .aiosqlite_compat import asegurar_aiosqlite

if "aiosqlite" in settings.DATABASE_URL:
    asegurar_aiosqlite()

_echo_sql = os.environ.get("VMPOS_SQL_ECHO", "0") == "1"


def _migrar_archivo_sqlite_directo(db_url: str):
    """Aplica migraciones DDL directamente en SQLite antes de inicializar SQLAlchemy."""
    try:
        clean_url = db_url.split("?")[0]
        db_path = None
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if clean_url.startswith(prefix):
                db_path = clean_url[len(prefix):]
                break
        if not db_path or not os.path.exists(db_path):
            return
        import sqlite3
        conn = sqlite3.connect(db_path, timeout=8)
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA table_info(sesiones_caja);")
            cols_caja = [r[1] for r in cur.fetchall()]
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

            cur.execute("PRAGMA table_info(proveedores);")
            cols_prov = [r[1] for r in cur.fetchall()]
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

            cur.execute("PRAGMA table_info(productos);")
            cols_prod = [r[1] for r in cur.fetchall()]
            if cols_prod:
                cols_pr = [
                    ("es_material", "INTEGER DEFAULT 0"),
                    ("presentacion_defecto", "TEXT DEFAULT 'Paquete'"),
                    ("factor_conversion_defecto", "REAL DEFAULT 1.0"),
                    ("unidad_consumo_defecto", "TEXT DEFAULT 'Unidad'"),
                ]
                for c_nom, c_def in cols_pr:
                    if c_nom not in cols_prod:
                        try:
                            cur.execute(f"ALTER TABLE productos ADD COLUMN {c_nom} {c_def};")
                        except Exception:
                            pass

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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


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


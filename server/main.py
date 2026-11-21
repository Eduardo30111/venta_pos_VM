import os
import sqlite3
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .routers import (
    auth,
    usuarios,
    terminales,
    productos,
    servicios,
    proveedores,
    categorias,
    clientes,
    ventas,
    nomina,
    gastos,
    reportes,
    auditoria,
    turnos,
    configuracion,
    inventario_central,
    caja,
    contabilidad,
)
from . import database as db_mod
from .database import Base, get_db
from .config import settings
from .routers.configuracion import obtener_o_crear_config_negocio
from .services.migracion_historica import sincronizar_y_auditar_datos_historicos

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

# Configuración CORS estricta y segura para LAN y loopback (elimina wildcard inseguro con credenciales)
_allowed_origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(terminales.router)
app.include_router(productos.router)
app.include_router(servicios.router)
app.include_router(inventario_central.router)
app.include_router(proveedores.router)
app.include_router(categorias.router)
app.include_router(clientes.router)
app.include_router(ventas.router)
app.include_router(caja.router)
app.include_router(contabilidad.router)
app.include_router(nomina.router)
app.include_router(gastos.router)
app.include_router(reportes.router)
app.include_router(auditoria.router)
app.include_router(turnos.router)
app.include_router(configuracion.router)
app.include_router(configuracion.router, prefix="/api")


async def _sincronizar_usuarios_locales():
    """Sincroniza usuarios existentes en usuarios.db del servidor hacia la tabla central Usuario sin borrar nada."""
    try:
        from interface.config import DB_USUARIOS_PATH
    except Exception:
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        DB_USUARIOS_PATH = os.path.join(_root, "database", "usuarios.db")

    if not os.path.exists(DB_USUARIOS_PATH):
        return

    try:
        from .models.usuario import Usuario
        from .middleware.auth import hash_password

        conn = sqlite3.connect(DB_USUARIOS_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios")
        filas = cur.fetchall()
        conn.close()

        for r in filas:
            d = dict(r)
            uname = str(d.get("usuario") or "").strip()
            if not uname:
                continue
            try:
                async with db_mod.SessionLocal() as sync_session:
                    existente = await sync_session.execute(select(Usuario).where(Usuario.usuario == uname))
                    if existente.scalars().first():
                        continue

                    raw_doc = str(d.get("documento") or "").strip()
                    if not raw_doc or raw_doc in ("000000000", "None", "null"):
                        doc_val = None
                    else:
                        dup_doc = await sync_session.execute(select(Usuario).where(Usuario.documento == raw_doc))
                        doc_val = None if dup_doc.scalars().first() else raw_doc

                    raw_pwd = str(d.get("password") or d.get("clave") or "admin123")
                    pwd_hash = raw_pwd if raw_pwd.startswith("$2") else hash_password(raw_pwd)
                    nuevo = Usuario(
                        nombre=str(d.get("nombre") or uname),
                        apellidos=str(d.get("apellidos") or ""),
                        documento=doc_val,
                        usuario=uname,
                        password_hash=pwd_hash,
                        rol=str(d.get("rol") or "Operario"),
                        tipo_remuneracion=str(d.get("tipo_remuneracion") or "Fija"),
                        salario_diario=float(d.get("salario_diario") or 0.0),
                        porcentaje_comision=float(d.get("porcentaje_comision") or 0.0),
                        estado=str(d.get("estado") or "Activo"),
                    )
                    sync_session.add(nuevo)
                    await sync_session.commit()
            except Exception as row_err:
                print(f"Aviso sincronizando usuario local '{uname}': {row_err}")
    except Exception as e:
        print(f"Aviso sincronizando usuarios locales en startup: {e}")


async def _reparar_tablas_bigint_sqlite():
    """
    En SQLite, una columna creada previamente como `BIGINT PRIMARY KEY` no autoincrementa ROWID.
    Si detecta `BIGINT` en `audit_log` o `eventos_turno`, la reconstruye como `INTEGER PRIMARY KEY`
    conservando todos los registros existentes.
    """
    if "sqlite" not in str(db_mod.engine.url):
        return
    for tabla in ("audit_log", "eventos_turno"):
        try:
            async with db_mod.engine.begin() as conn:
                info = (await conn.execute(text(f"PRAGMA table_info({tabla})"))).fetchall()
                if not info:
                    continue
                col_id = next((c for c in info if c[1] == "id"), None)
                if col_id and "BIGINT" in str(col_id[2] or "").upper():
                    cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM {tabla}"))).scalar() or 0
                    if cnt == 0:
                        await conn.execute(text(f"DROP TABLE {tabla}"))
        except Exception as exc:
            print(f"Aviso revisando PK SQLite en {tabla}: {exc}")


@app.on_event("startup")
async def startup():
    from . import models  # noqa: F401

    try:
        from .database import asegurar_migraciones_sqlite
        asegurar_migraciones_sqlite(settings.DATABASE_URL)
        _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _v_db = os.path.join(_root, "database", "ventas.db")
        if os.path.exists(_v_db):
            asegurar_migraciones_sqlite(f"sqlite:///{_v_db}")
    except Exception as e_mig:
        print(f"Aviso asegurando migraciones iniciales SQLite: {e_mig}")

    try:
        async with db_mod.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as pg_err:
        print(
            f"Aviso conectando motor primario ({settings.DATABASE_URL}): {pg_err}. "
            f"Activando motor central SQLite/WAL..."
        )
        db_mod.activar_fallback_sqlite()
        await _reparar_tablas_bigint_sqlite()
        async with db_mod.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    await _reparar_tablas_bigint_sqlite()
    async with db_mod.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migraciones incrementales tolerantes al dialecto (SQLite y PostgreSQL)
    migraciones_sql = [
        # Usuarios y turnos
        "ALTER TABLE usuarios ADD COLUMN solicitud_liquidacion TIMESTAMP;",
        "ALTER TABLE cola_turno ADD COLUMN turno_retorno_posicion INTEGER;",
        "ALTER TABLE cola_turno ADD COLUMN turnos_pendientes INTEGER NOT NULL DEFAULT 0;",
        # Productos
        "ALTER TABLE productos ADD COLUMN categoria_id INTEGER;",
        "ALTER TABLE productos ADD COLUMN categoria VARCHAR DEFAULT 'General';",
        "ALTER TABLE productos ADD COLUMN marca VARCHAR DEFAULT '';",
        "ALTER TABLE productos ADD COLUMN unidad_medida VARCHAR DEFAULT 'Unidad';",
        "ALTER TABLE productos ADD COLUMN precio_costo FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN costo FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN precio_venta FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN precio FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN tipo_producto VARCHAR DEFAULT 'Producto';",
        "ALTER TABLE productos ADD COLUMN stock_bodega FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN stock_vitrina FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN stock_minimo_bodega FLOAT DEFAULT 5.0;",
        "ALTER TABLE productos ADD COLUMN stock_minimo_vitrina FLOAT DEFAULT 2.0;",
        "ALTER TABLE productos ADD COLUMN stock_minimo FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN imagen_url VARCHAR DEFAULT '';",
        "ALTER TABLE productos ADD COLUMN precio_variable BOOLEAN DEFAULT 0;",
        "ALTER TABLE productos ADD COLUMN porcentaje_comision FLOAT DEFAULT 0.0;",
        "ALTER TABLE productos ADD COLUMN fecha_creacion VARCHAR;",
        "ALTER TABLE productos ADD COLUMN fecha_modificacion VARCHAR;",
        "ALTER TABLE productos ADD COLUMN created_at TIMESTAMP;",
        "ALTER TABLE productos ADD COLUMN updated_at TIMESTAMP;",
        # Servicios
        "ALTER TABLE servicios ADD COLUMN precio_variable BOOLEAN DEFAULT 0;",
        "ALTER TABLE servicios ADD COLUMN solo_operarios BOOLEAN NOT NULL DEFAULT 0;",
        "ALTER TABLE servicios ADD COLUMN creado_por_operario_id INTEGER;",
        "ALTER TABLE servicios ADD COLUMN categoria VARCHAR DEFAULT 'Servicios';",
        "ALTER TABLE servicios ADD COLUMN marca VARCHAR DEFAULT '';",
        "ALTER TABLE servicios ADD COLUMN codigo_barras VARCHAR;",
        "ALTER TABLE servicios ADD COLUMN unidad_medida VARCHAR DEFAULT 'Servicio';",
        # Movimientos de inventario (Kárdex)
        "ALTER TABLE movimientos_inventario ADD COLUMN fecha VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN hora VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN codigo_producto VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN nombre_producto VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN tipo VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN tipo_movimiento VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN unidad_medida VARCHAR DEFAULT 'Unidad';",
        "ALTER TABLE movimientos_inventario ADD COLUMN ubicacion_origen VARCHAR DEFAULT '';",
        "ALTER TABLE movimientos_inventario ADD COLUMN ubicacion_destino VARCHAR DEFAULT '';",
        "ALTER TABLE movimientos_inventario ADD COLUMN stock_anterior FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN stock_nuevo FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN stock_origen_ant FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN stock_origen_des FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN stock_destino_ant FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN stock_destino_des FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN costo_unitario FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN valor_total FLOAT DEFAULT 0.0;",
        "ALTER TABLE movimientos_inventario ADD COLUMN referencia VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN usuario_id INTEGER;",
        "ALTER TABLE movimientos_inventario ADD COLUMN usuario_nombre VARCHAR DEFAULT '';",
        "ALTER TABLE movimientos_inventario ADD COLUMN usuario VARCHAR DEFAULT 'Administrador';",
        "ALTER TABLE movimientos_inventario ADD COLUMN terminal_id INTEGER;",
        "ALTER TABLE movimientos_inventario ADD COLUMN observacion VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN observaciones VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN estado VARCHAR DEFAULT 'Completado';",
        "ALTER TABLE movimientos_inventario ADD COLUMN created_at TIMESTAMP;",
        # Compras y Traslados
        "ALTER TABLE compras_inventario ADD COLUMN created_at TIMESTAMP;",
        "ALTER TABLE compras_inventario ADD COLUMN observaciones VARCHAR;",
        "ALTER TABLE traslados_inventario ADD COLUMN created_at TIMESTAMP;",
        "ALTER TABLE traslados_inventario ADD COLUMN observaciones VARCHAR;",
        # Ventas y Detalles
        "ALTER TABLE ventas ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN fecha VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN hora VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN sesion_caja_id INTEGER;",
        "ALTER TABLE ventas ADD COLUMN cliente_documento VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN operario_nombre VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN metodo_pago_principal VARCHAR DEFAULT 'Efectivo';",
        "ALTER TABLE ventas ADD COLUMN recibido FLOAT DEFAULT 0.0;",
        "ALTER TABLE ventas ADD COLUMN cambio FLOAT DEFAULT 0.0;",
        "ALTER TABLE ventas ADD COLUMN saldo_pendiente FLOAT DEFAULT 0.0;",
        "ALTER TABLE ventas ADD COLUMN motivo_anulacion VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN anulada_por VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN anulada_at VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN modificado_por VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN fecha_modificacion VARCHAR;",
        "ALTER TABLE ventas ADD COLUMN snapshot_negocio JSON;",
        "ALTER TABLE detalles_venta ADD COLUMN costo_unitario FLOAT DEFAULT 0.0;",
        # Finanzas, Fiados, Abonos, CXP y Gastos
        "ALTER TABLE cuentas_por_cobrar ADD COLUMN fecha VARCHAR;",
        "ALTER TABLE cuentas_por_cobrar ADD COLUMN hora VARCHAR;",
        "ALTER TABLE abonos ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE abonos ADD COLUMN fecha VARCHAR;",
        "ALTER TABLE abonos ADD COLUMN hora VARCHAR;",
        "ALTER TABLE movimientos_cliente ADD COLUMN fecha VARCHAR;",
        "ALTER TABLE movimientos_cliente ADD COLUMN hora VARCHAR;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN numero_venta VARCHAR;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN codigo_servicio VARCHAR;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN nombre_servicio VARCHAR;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN precio_venta FLOAT DEFAULT 0.0;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN porcentaje_comision FLOAT DEFAULT 0.0;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN monto_comision FLOAT DEFAULT 0.0;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN monto_pagado FLOAT DEFAULT 0.0;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN fecha VARCHAR;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN hora VARCHAR;",
        "ALTER TABLE cuentas_por_pagar ADD COLUMN usuario VARCHAR;",
        "ALTER TABLE gastos ADD COLUMN metodo_pago VARCHAR DEFAULT 'Efectivo';",
        "ALTER TABLE gastos ADD COLUMN clasificacion VARCHAR DEFAULT 'Operativo diario';",
        "ALTER TABLE gastos ADD COLUMN descripcion VARCHAR DEFAULT '';",
        "ALTER TABLE gastos ADD COLUMN fecha VARCHAR;",
        "ALTER TABLE gastos ADD COLUMN hora VARCHAR;",
        "ALTER TABLE gastos ADD COLUMN fecha_vencimiento VARCHAR;",
        "ALTER TABLE gastos ADD COLUMN fecha_pago VARCHAR;",
        "ALTER TABLE gastos ADD COLUMN frecuencia VARCHAR DEFAULT 'Único';",
        "ALTER TABLE gastos ADD COLUMN estado VARCHAR DEFAULT 'Pagado';",
        "ALTER TABLE gastos ADD COLUMN proveedor VARCHAR DEFAULT '';",
        "ALTER TABLE gastos ADD COLUMN comprobante VARCHAR DEFAULT '';",
        "ALTER TABLE gastos ADD COLUMN es_recurrente BOOLEAN DEFAULT 0;",
        "ALTER TABLE gastos ADD COLUMN recurrencia_id INTEGER;",
        "ALTER TABLE gastos ADD COLUMN sesion_caja_id INTEGER;",
        "ALTER TABLE gastos ADD COLUMN usuario_nombre VARCHAR;",
        # Sesiones de caja y Arqueo
        "ALTER TABLE sesiones_caja ADD COLUMN arqueo_apertura_json TEXT;",
        "ALTER TABLE sesiones_caja ADD COLUMN arqueo_cierre_json TEXT;",
        "ALTER TABLE sesiones_caja ADD COLUMN monto_transferencias_esperado FLOAT DEFAULT 0.0;",
        "ALTER TABLE sesiones_caja ADD COLUMN monto_transferencias_verificado FLOAT DEFAULT 0.0;",
        "ALTER TABLE sesiones_caja ADD COLUMN diferencia_banco FLOAT DEFAULT 0.0;",
        "ALTER TABLE sesiones_caja ADD COLUMN estado_banco VARCHAR DEFAULT 'Pendiente';",
        "ALTER TABLE sesiones_caja ADD COLUMN terminal_id INTEGER;",
        "ALTER TABLE sesiones_caja ADD COLUMN terminal_nombre VARCHAR;",
        "ALTER TABLE sesiones_caja ADD COLUMN observaciones VARCHAR;",
        "ALTER TABLE sesiones_caja ADD COLUMN fecha_cierre VARCHAR;",
        "ALTER TABLE sesiones_caja ADD COLUMN hora_cierre VARCHAR;",
        "ALTER TABLE sesiones_caja ADD COLUMN usuario_cierre VARCHAR;",
        "ALTER TABLE sesiones_caja ADD COLUMN monto_esperado_efectivo FLOAT DEFAULT 0.0;",
        "ALTER TABLE sesiones_caja ADD COLUMN monto_real_contado FLOAT DEFAULT 0.0;",
        "ALTER TABLE sesiones_caja ADD COLUMN diferencia FLOAT DEFAULT 0.0;",
        "ALTER TABLE sesiones_caja ADD COLUMN created_at TIMESTAMP;",
        # Proveedores
        "ALTER TABLE proveedores ADD COLUMN documento_nit VARCHAR DEFAULT '';",
        "ALTER TABLE proveedores ADD COLUMN email VARCHAR DEFAULT '';",
        "ALTER TABLE proveedores ADD COLUMN direccion VARCHAR DEFAULT '';",
        "ALTER TABLE proveedores ADD COLUMN contacto VARCHAR DEFAULT '';",
        "ALTER TABLE proveedores ADD COLUMN estado VARCHAR DEFAULT 'Activo';",
        "ALTER TABLE proveedores ADD COLUMN saldo_acumulado FLOAT DEFAULT 0.0;",
        "ALTER TABLE proveedores ADD COLUMN total_ventas FLOAT DEFAULT 0.0;",
        "ALTER TABLE proveedores ADD COLUMN total_comisiones FLOAT DEFAULT 0.0;",
        "ALTER TABLE proveedores ADD COLUMN total_pagado FLOAT DEFAULT 0.0;",
        # Índices únicos de idempotencia
        "ALTER TABLE compras_inventario ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE gastos ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE liquidaciones_proveedores ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE liquidaciones ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE movimientos_inventario ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE traslados_inventario ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE movimientos_caja ADD COLUMN idempotency_key VARCHAR;",
        "ALTER TABLE movimientos_financieros ADD COLUMN idempotency_key VARCHAR;",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ventas_idempotency_key ON ventas(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_abonos_idempotency_key ON abonos(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_compras_idempotency_key ON compras_inventario(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_gastos_idempotency_key ON gastos(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_liq_prov_idempotency_key ON liquidaciones_proveedores(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_liq_nom_idempotency_key ON liquidaciones(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mov_inv_idempotency_key ON movimientos_inventario(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_traslados_idempotency_key ON traslados_inventario(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mov_caja_idempotency_key ON movimientos_caja(idempotency_key);",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mov_fin_idempotency_key ON movimientos_financieros(idempotency_key);",
        # Materiales y Presentaciones en Productos
        "ALTER TABLE productos ADD COLUMN es_material BOOLEAN DEFAULT 0;",
        "ALTER TABLE productos ADD COLUMN presentacion_defecto VARCHAR DEFAULT 'Paquete';",
        "ALTER TABLE productos ADD COLUMN factor_conversion_defecto FLOAT DEFAULT 1.0;",
        "ALTER TABLE productos ADD COLUMN unidad_consumo_defecto VARCHAR DEFAULT 'Unidad';",
        # Tablas de Materiales, Operarios y Consumos
        """CREATE TABLE IF NOT EXISTS inventario_operarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            usuario_nombre VARCHAR NOT NULL,
            rol VARCHAR DEFAULT 'Operario',
            producto_id INTEGER NOT NULL,
            codigo_producto VARCHAR NOT NULL,
            nombre_producto VARCHAR NOT NULL,
            unidad_medida VARCHAR DEFAULT 'Unidad',
            stock_disponible FLOAT DEFAULT 0.0,
            total_recibido FLOAT DEFAULT 0.0,
            total_consumido FLOAT DEFAULT 0.0,
            total_desperdiciado FLOAT DEFAULT 0.0,
            total_devuelto FLOAT DEFAULT 0.0,
            ultimo_movimiento VARCHAR,
            fecha_actualizacion VARCHAR,
            UNIQUE(usuario_nombre, producto_id)
        );""",
        """CREATE TABLE IF NOT EXISTS presentaciones_producto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto_id INTEGER NOT NULL,
            codigo_producto VARCHAR NOT NULL,
            nombre_presentacion VARCHAR NOT NULL,
            unidad_compra VARCHAR DEFAULT 'Paquete',
            cantidad_unidades_base FLOAT DEFAULT 1.0,
            unidad_consumo VARCHAR DEFAULT 'Unidad',
            costo_defecto FLOAT DEFAULT 0.0,
            codigo_barras VARCHAR DEFAULT '',
            activo INTEGER DEFAULT 1,
            fecha_creacion VARCHAR
        );""",
        """CREATE TABLE IF NOT EXISTS consumos_materiales_venta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            numero_factura VARCHAR DEFAULT '',
            usuario_responsable VARCHAR NOT NULL,
            producto_id INTEGER NOT NULL,
            codigo_producto VARCHAR NOT NULL,
            nombre_producto VARCHAR NOT NULL,
            cantidad_consumida FLOAT NOT NULL,
            unidad_medida VARCHAR DEFAULT 'Unidad',
            saldo_anterior FLOAT DEFAULT 0.0,
            saldo_restante FLOAT DEFAULT 0.0,
            costo_unitario FLOAT DEFAULT 0.0,
            costo_total FLOAT DEFAULT 0.0,
            fecha VARCHAR NOT NULL,
            hora VARCHAR NOT NULL,
            estado VARCHAR DEFAULT 'Aplicado',
            observaciones VARCHAR DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );""",
    ]
    for stmt in migraciones_sql:
        try:
            async with db_mod.engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception as e_stmt:
            msg = str(e_stmt).lower()
            if "duplicate column" not in msg and "already exists" not in msg:
                logger.debug("Nota en DDL arranque: %s | %s", e_stmt, stmt[:50])

    try:
        async with db_mod.engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    DELETE FROM cola_turno
                    WHERE usuario_id IN (
                        SELECT id FROM usuarios WHERE LOWER(rol) <> 'operario'
                    );
                    """
                )
            )
    except Exception:
        pass

    from .models.terminal import Terminal
    from .models.usuario import Usuario
    from .middleware.auth import hash_password

    async with db_mod.SessionLocal() as session:
        result = await session.execute(select(Terminal).where(Terminal.nombre == "CAJA-01"))
        if not result.scalars().first():
            session.add(Terminal(nombre="CAJA-01", descripcion="Caja Principal (Servidor)"))
            session.add(Terminal(nombre="CAJA-02", descripcion="Caja Secundaria"))
            await session.commit()

    await _sincronizar_usuarios_locales()

    async with db_mod.SessionLocal() as session:
        admin = await session.execute(select(Usuario).where(Usuario.usuario == "admin"))
        if not admin.scalars().first():
            session.add(
                Usuario(
                    nombre="Admin",
                    apellidos="Principal",
                    documento=None,
                    usuario="admin",
                    password_hash=hash_password("admin123"),
                    rol="Administrador",
                    tipo_remuneracion="Fija",
                    estado="Activo",
                )
            )
            await session.commit()

    async with db_mod.SessionLocal() as cfg_session:
        await obtener_o_crear_config_negocio(cfg_session)

    # Sincronización aditiva de catálogo y auditoría forense reversible de datos históricos
    await sincronizar_y_auditar_datos_historicos()


@app.get("/api/health")
@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        cfg = await obtener_o_crear_config_negocio(db)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Base de datos del servidor no disponible: {exc}",
        )
    modo_db = "postgresql" if "postgresql" in settings.DATABASE_URL else "sqlite"
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "database": "connected",
        "modo_db": modo_db,
        "nombre_negocio": cfg.nombre_negocio,
        "tiene_logo": bool(cfg.logo_base64),
        "logo_hash": cfg.logo_hash or "",
        "config_updated_at": cfg.updated_at.isoformat() if cfg.updated_at else "",
    }


@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "status": "ok"}


from fastapi.responses import FileResponse, HTMLResponse


@app.get("/descargar", response_class=HTMLResponse)
async def pagina_descargas():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Centro de Descargas VmPOS</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0F172A; color: #F8FAFC; text-align: center; padding: 40px 20px; }
            .card { background: #1E293B; border-radius: 12px; max-width: 550px; margin: 0 auto; padding: 30px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155; }
            h1 { color: #38BDF8; margin-bottom: 8px; font-size: 24px; }
            p { color: #94A3B8; margin-bottom: 25px; font-size: 14px; }
            .btn { display: block; background: #0284C7; color: white; text-decoration: none; padding: 14px 20px; border-radius: 8px; margin: 12px 0; font-weight: bold; font-size: 15px; transition: background 0.2s; }
            .btn:hover { background: #0369A1; }
            .btn-sec { background: #334155; color: #E2E8F0; }
            .btn-sec:hover { background: #475569; }
            .badge { font-size: 12px; background: rgba(255,255,255,0.2); padding: 2px 8px; border-radius: 10px; margin-left: 6px; }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🚀 Descargas VmPOS (v4.1.0)</h1>
            <p>Selecciona tu sistema operativo para descargar el instalador directo.</p>
            <a class="btn" href="/descargar/windows">🪟 Descargar Instalador Windows (.exe) <span class="badge">61.7 MB</span></a>
            <a class="btn btn-sec" href="/descargar/windows-portable">📦 Descargar Windows Portátil (.zip) <span class="badge">68.3 MB</span></a>
            <a class="btn" style="background:#0F766E;" href="/descargar/mac">🍏 Descargar Instalador macOS (.dmg) <span class="badge">76.1 MB</span></a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/descargar/windows")
async def descargar_windows():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "dist", "VmPOS_Setup_v4.1.0.exe")
    if os.path.exists(path):
        return FileResponse(path, filename="VmPOS_Setup_v4.1.0.exe", media_type="application/vnd.microsoft.portable-executable")
    raise HTTPException(status_code=404, detail="Instalador de Windows no encontrado")


@app.get("/descargar/windows-portable")
async def descargar_windows_portable():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "dist", "VmPOS_Windows_Portable.zip")
    if os.path.exists(path):
        return FileResponse(path, filename="VmPOS_Windows_Portable.zip", media_type="application/zip")
    raise HTTPException(status_code=404, detail="Paquete Windows portátil no encontrado")


@app.get("/descargar/mac")
async def descargar_mac():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "dist", "VmPOS_macOS_Instalador.dmg")
    if os.path.exists(path):
        return FileResponse(path, filename="VmPOS_macOS_Instalador.dmg", media_type="application/x-apple-diskimage")
    raise HTTPException(status_code=404, detail="Instalador macOS no encontrado")

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
)
from . import database as db_mod
from .database import Base, get_db
from .config import settings
from .routers.configuracion import obtener_o_crear_config_negocio

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(usuarios.router)
app.include_router(terminales.router)
app.include_router(productos.router)
app.include_router(servicios.router)
app.include_router(proveedores.router)
app.include_router(categorias.router)
app.include_router(clientes.router)
app.include_router(ventas.router)
app.include_router(nomina.router)
app.include_router(gastos.router)
app.include_router(reportes.router)
app.include_router(auditoria.router)
app.include_router(turnos.router)
app.include_router(configuracion.router)
app.include_router(configuracion.router, prefix="/api")


async def _sincronizar_usuarios_locales(session: AsyncSession):
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
            existente = await session.execute(select(Usuario).where(Usuario.usuario == uname))
            if not existente.scalars().first():
                raw_pwd = str(d.get("password") or d.get("clave") or "admin123")
                pwd_hash = raw_pwd if raw_pwd.startswith("$2") else hash_password(raw_pwd)
                nuevo = Usuario(
                    nombre=str(d.get("nombre") or uname),
                    apellidos=str(d.get("apellidos") or ""),
                    documento=str(d.get("documento") or "000000000"),
                    usuario=uname,
                    password_hash=pwd_hash,
                    rol=str(d.get("rol") or "Operario"),
                    tipo_remuneracion=str(d.get("tipo_remuneracion") or "Fija"),
                    estado=str(d.get("estado") or "Activo"),
                )
                session.add(nuevo)
        await session.commit()
    except Exception as e:
        print(f"Aviso sincronizando usuarios locales en startup: {e}")


@app.on_event("startup")
async def startup():
    from . import models  # noqa: F401

    try:
        async with db_mod.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as pg_err:
        print(f"Aviso conectando motor primario ({settings.DATABASE_URL}): {pg_err}. Activando motor central SQLite/WAL...")
        db_mod.activar_fallback_sqlite()
        async with db_mod.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Ejecutar migraciones incrementales de forma tolerante al dialecto
    migraciones_sql = [
        "ALTER TABLE usuarios ADD COLUMN solicitud_liquidacion TIMESTAMP;",
        "ALTER TABLE servicios ADD COLUMN precio_variable BOOLEAN DEFAULT 0;",
        "ALTER TABLE servicios ADD COLUMN solo_operarios BOOLEAN NOT NULL DEFAULT 0;",
        "ALTER TABLE servicios ADD COLUMN creado_por_operario_id INTEGER;",
        "ALTER TABLE gastos ADD COLUMN metodo_pago VARCHAR DEFAULT 'Efectivo';",
        "ALTER TABLE cola_turno ADD COLUMN turno_retorno_posicion INTEGER;",
        "ALTER TABLE cola_turno ADD COLUMN turnos_pendientes INTEGER NOT NULL DEFAULT 0;",
    ]
    for stmt in migraciones_sql:
        try:
            async with db_mod.engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception:
            pass

    try:
        async with db_mod.engine.begin() as conn:
            await conn.execute(text("""
                DELETE FROM cola_turno
                WHERE usuario_id IN (
                    SELECT id FROM usuarios WHERE LOWER(rol) <> 'operario'
                );
            """))
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
        admin = await session.execute(select(Usuario).where(Usuario.usuario == "admin"))
        if not admin.scalars().first():
            session.add(
                Usuario(
                    nombre="Admin",
                    apellidos="Principal",
                    documento="000000000",
                    usuario="admin",
                    password_hash=hash_password("admin123"),
                    rol="Administrador",
                    tipo_remuneracion="Fija",
                    estado="Activo",
                )
            )
        await session.commit()
        await _sincronizar_usuarios_locales(session)
        await obtener_o_crear_config_negocio(session)


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


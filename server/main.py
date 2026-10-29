from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import auth, usuarios, terminales, productos, servicios, proveedores, categorias, clientes, ventas, nomina, gastos, reportes, auditoria, turnos
from .database import engine, Base
from .config import settings

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

@app.on_event("startup")
async def startup():
    from . import models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        from sqlalchemy import text
        try:
            await conn.execute(text("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS solicitud_liquidacion TIMESTAMP WITH TIME ZONE;"))
            await conn.execute(text("ALTER TABLE servicios ADD COLUMN IF NOT EXISTS precio_variable BOOLEAN DEFAULT FALSE;"))
            await conn.execute(text("ALTER TABLE servicios ADD COLUMN IF NOT EXISTS solo_operarios BOOLEAN NOT NULL DEFAULT FALSE;"))
            await conn.execute(text("ALTER TABLE servicios ADD COLUMN IF NOT EXISTS creado_por_operario_id INTEGER REFERENCES usuarios(id);"))
            await conn.execute(text("ALTER TABLE gastos ADD COLUMN IF NOT EXISTS metodo_pago VARCHAR DEFAULT 'Efectivo';"))
            await conn.execute(text("ALTER TABLE cola_turno ADD COLUMN IF NOT EXISTS turno_retorno_posicion INTEGER;"))
            await conn.execute(text("ALTER TABLE cola_turno ADD COLUMN IF NOT EXISTS turnos_pendientes INTEGER NOT NULL DEFAULT 0;"))
            await conn.execute(text("""
                DELETE FROM cola_turno
                WHERE usuario_id IN (
                    SELECT id FROM usuarios WHERE LOWER(rol) <> 'operario'
                );
            """))
            await conn.execute(text("""
                WITH orden AS (
                    SELECT id, ROW_NUMBER() OVER (PARTITION BY ciclo_id ORDER BY posicion, id) AS nueva_posicion
                    FROM cola_turno
                )
                UPDATE cola_turno AS cola
                SET posicion = orden.nueva_posicion
                FROM orden
                WHERE cola.id = orden.id;
            """))
            await conn.execute(text("""
                UPDATE cola_turno AS repetido
                SET estado = 'DISPONIBLE', en_turno_desde = NULL
                WHERE repetido.estado = 'EN_TURNO'
                  AND repetido.id NOT IN (
                      SELECT MIN(id)
                      FROM cola_turno
                      WHERE estado = 'EN_TURNO'
                      GROUP BY ciclo_id
                  );
            """))
        except Exception as ex:
            print(f"Migration note: {ex}")
        from .models.terminal import Terminal
        from sqlalchemy.future import select
        from sqlalchemy.ext.asyncio import AsyncSession
        from .database import SessionLocal
        async with SessionLocal() as session:
            result = await session.execute(select(Terminal).where(Terminal.nombre == "CAJA-01"))
            if not result.scalars().first():
                session.add(Terminal(nombre="CAJA-01", descripcion="Caja Principal (Servidor)"))
                session.add(Terminal(nombre="CAJA-02", descripcion="Caja Secundaria"))
                from .models.usuario import Usuario
                from .middleware.auth import hash_password
                admin = await session.execute(select(Usuario).where(Usuario.usuario == "admin"))
                if not admin.scalars().first():
                    session.add(Usuario(nombre="Admin", apellidos="Principal", documento="000000000", usuario="admin", password_hash=hash_password("admin123"), rol="Administrador", tipo_remuneracion="Fija", estado="Activo"))
                await session.commit()

@app.get("/")
async def root():
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION}

import os
import shutil
import tempfile
import asyncio
from sqlalchemy.future import select
from server.config import settings
import server.database as db_mod
from server.database import Base, _crear_engine, asegurar_migraciones_sqlite
from server.models.usuario import Usuario
from server.models.terminal import Terminal
from server.models.producto import Producto
from server.models.proveedor import Proveedor
from server.middleware.auth import hash_password


async def init_isolated_test_db(db_path: str):
    """
    Inicializa un entorno de base de datos 100% aislado para pruebas unitarias y de integración.
    Crea todas las tablas, migraciones DDL de idempotencia y semillas de prueba
    (usuario admin, terminal CAJA-01, proveedor de prueba y producto de prueba).
    No toca ni modifica bases de datos de producción.
    """
    for ext in ("", "-wal", "-shm"):
        f = f"{db_path}{ext}"
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    clean_url = f"sqlite+aiosqlite:///{os.path.abspath(db_path)}"
    settings.DATABASE_URL = clean_url

    # Reconfigurar motor y SessionLocal hacia la base de datos aislada
    db_mod.engine = _crear_engine(clean_url)
    db_mod.SessionLocal.configure(bind=db_mod.engine)

    # Crear todas las tablas del esquema ORM
    async with db_mod.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Aplicar migraciones DDL e índices únicos de idempotencia
    asegurar_migraciones_sqlite(clean_url)

    # Sembrar datos mínimos estrictamente necesarios para pruebas
    async with db_mod.SessionLocal() as session:
        # 1. Terminal CAJA-01
        res_t = await session.execute(select(Terminal).where(Terminal.nombre == "CAJA-01"))
        if not res_t.scalars().first():
            session.add(Terminal(id=1, nombre="CAJA-01", descripcion="Terminal de Prueba"))

        # 2. Usuario admin (password: 123456)
        res_u = await session.execute(select(Usuario).where(Usuario.usuario == "admin"))
        if not res_u.scalars().first():
            session.add(
                Usuario(
                    id=1,
                    usuario="admin",
                    password_hash=hash_password("123456"),
                    nombre="Administrador",
                    apellidos="Test",
                    rol="Administrador",
                    estado="Activo",
                    porcentaje_comision=0.0,
                )
            )

        # 3. Proveedor de prueba
        res_p = await session.execute(select(Proveedor).where(Proveedor.id == 1))
        if not res_p.scalars().first():
            session.add(
                Proveedor(
                    id=1,
                    nombre="Proveedor Concurrente",
                    documento_nit="900123456-1",
                    saldo_acumulado=500.0,
                    estado="Activo",
                )
            )

        # 4. Producto de prueba
        res_prod = await session.execute(select(Producto).where(Producto.codigo == "00001"))
        if not res_prod.scalars().first():
            session.add(
                Producto(
                    id=1,
                    codigo="00001",
                    nombre="Cuaderno 100 Hojas Norma Pro",
                    categoria="General",
                    unidad_medida="Unidad",
                    precio_costo=5000.0,
                    precio_venta=5800.0,
                    stock=1000.0,
                    stock_bodega=500.0,
                    stock_vitrina=500.0,
                    estado="Activo",
                )
            )

        await session.commit()


async def cleanup_isolated_test_db(db_path: str):
    """Cierra el motor de base de datos de prueba y elimina los archivos temporales."""
    try:
        await db_mod.engine.dispose()
    except Exception:
        pass
    for ext in ("", "-wal", "-shm"):
        f = f"{db_path}{ext}"
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

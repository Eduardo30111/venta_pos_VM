import os
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings, DEFAULT_SQLITE_URL
from .aiosqlite_compat import asegurar_aiosqlite

if "aiosqlite" in settings.DATABASE_URL:
    asegurar_aiosqlite()

_echo_sql = os.environ.get("VMPOS_SQL_ECHO", "0") == "1"


def _crear_engine(db_url: str):
    if "sqlite" in db_url:
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


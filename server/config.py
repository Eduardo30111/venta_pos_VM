import os
import socket
import secrets
from pydantic_settings import BaseSettings

try:
    from interface.config import DATABASE_DIR as _DB_DIR, OFFICIAL_SERVER_PORT
except Exception:
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _DB_DIR = os.path.join(_ROOT, "database")
    OFFICIAL_SERVER_PORT = 8000

os.makedirs(_DB_DIR, exist_ok=True)
_SQLITE_FILE = os.path.abspath(os.path.join(_DB_DIR, "vmpos_server.db")).replace("\\", "/")
DEFAULT_SQLITE_URL = f"sqlite+aiosqlite:///{_SQLITE_FILE}"


def _obtener_o_generar_secret_key() -> str:
    env_sec = os.environ.get("VMPOS_SECRET_KEY", "").strip()
    if env_sec:
        return env_sec

    cfg_dir = os.path.abspath(os.path.join(_DB_DIR, "..", "config"))
    try:
        os.makedirs(cfg_dir, exist_ok=True)
        key_file = os.path.join(cfg_dir, "jwt_secret.key")
        if os.path.exists(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    sec = f.read().strip()
                    if len(sec) >= 32:
                        return sec
            except Exception:
                pass
        nuevo_sec = secrets.token_urlsafe(48)
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            mode = 0o600
            with os.fdopen(os.open(key_file, flags, mode), "w", encoding="utf-8") as f:
                f.write(nuevo_sec)
        except Exception:
            pass
        return nuevo_sec
    except Exception:
        return "vmpos_default_secure_fallback_" + secrets.token_urlsafe(24)


def _detectar_database_url_por_defecto() -> str:
    env_url = os.environ.get("DATABASE_URL", "").strip()
    if env_url:
        return env_url
    # Si el usuario solicita explícitamente PostgreSQL y el puerto 5432 responde
    if os.environ.get("VMPOS_USE_POSTGRES", "").lower() in ("1", "true", "yes"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            if s.connect_ex(("127.0.0.1", 5432)) == 0:
                pg_user = os.environ.get("POSTGRES_USER", "postgres")
                pg_pass = os.environ.get("POSTGRES_PASSWORD", "")
                pg_host = os.environ.get("POSTGRES_HOST", "localhost")
                pg_port = os.environ.get("POSTGRES_PORT", "5432")
                pg_db = os.environ.get("POSTGRES_DB", "vmpos")
                if pg_pass:
                    return f"postgresql+asyncpg://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
        except Exception:
            pass
        finally:
            try:
                s.close()
            except Exception:
                pass
    return DEFAULT_SQLITE_URL


class Settings(BaseSettings):
    DATABASE_URL: str = _detectar_database_url_por_defecto()
    SECRET_KEY: str = _obtener_o_generar_secret_key()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    APP_NAME: str = "VmPOS"
    APP_VERSION: str = "4.1.2"
    SERVER_PORT: int = OFFICIAL_SERVER_PORT

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


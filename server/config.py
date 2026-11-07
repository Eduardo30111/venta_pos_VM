import os
import socket
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
                return "postgresql+asyncpg://postgres:postgres@localhost:5432/vmpos"
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
    SECRET_KEY: str = "supersecretkey"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    APP_NAME: str = "VmPOS"
    APP_VERSION: str = "4.1.0"
    SERVER_PORT: int = OFFICIAL_SERVER_PORT

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


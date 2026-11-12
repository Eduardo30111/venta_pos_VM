import os

# Intentar cargar configuración de red y directorios persistidos
try:
    from interface.config import CONFIG_DIR as _IFACE_CONFIG_DIR, OFFICIAL_SERVER_PORT
except Exception:
    _IFACE_CONFIG_DIR = os.path.expanduser("~/.vmpos")
    OFFICIAL_SERVER_PORT = 8000

try:
    from interface.network_manager import obtener_config_red
    _net_cfg = obtener_config_red()
except Exception:
    try:
        from network_manager import obtener_config_red
        _net_cfg = obtener_config_red()
    except Exception:
        _net_cfg = {}

_modo = str(_net_cfg.get("modo", "servidor")).lower()
_ip = "127.0.0.1" if _modo == "servidor" else _net_cfg.get("servidor_ip", "127.0.0.1")
_puerto = _net_cfg.get("servidor_puerto", OFFICIAL_SERVER_PORT)
_default_url = f"http://{_ip}:{_puerto}" if _ip else f"http://127.0.0.1:{OFFICIAL_SERVER_PORT}"

# Configuracion del cliente
API_BASE_URL = os.getenv("API_BASE_URL", _default_url)
TERMINAL_ID = int(os.getenv("TERMINAL_ID", str(_net_cfg.get("terminal_id", 1))))
TERMINAL_NOMBRE = os.getenv("TERMINAL_NOMBRE", str(_net_cfg.get("terminal_nombre", "CAJA-01")))

# Rutas locales
CONFIG_DIR = _IFACE_CONFIG_DIR
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR, exist_ok=True)


import os

# Intentar cargar configuración de red persistida
try:
    from interface.network_manager import obtener_config_red
    _net_cfg = obtener_config_red()
except Exception:
    try:
        from network_manager import obtener_config_red
        _net_cfg = obtener_config_red()
    except Exception:
        _net_cfg = {}

_ip = _net_cfg.get("servidor_ip", "127.0.0.1")
_puerto = _net_cfg.get("servidor_puerto", 8000)
_default_url = f"http://{_ip}:{_puerto}" if _ip else "http://localhost:8000"

# Configuracion del cliente
API_BASE_URL = os.getenv("API_BASE_URL", _default_url)
TERMINAL_ID = int(os.getenv("TERMINAL_ID", str(_net_cfg.get("terminal_id", 1))))
TERMINAL_NOMBRE = os.getenv("TERMINAL_NOMBRE", str(_net_cfg.get("terminal_nombre", "CAJA-01")))

# Rutas locales
CONFIG_DIR = os.path.expanduser("~/.vmpos")
TOKEN_FILE = os.path.join(CONFIG_DIR, "token.json")

if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR, exist_ok=True)

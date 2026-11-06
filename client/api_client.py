try:
    import httpx
    HTTPX_DISPONIBLE = True
except ImportError:
    httpx = None
    HTTPX_DISPONIBLE = False

import json
import os
import time
from .config import API_BASE_URL, TOKEN_FILE, TERMINAL_ID, TERMINAL_NOMBRE
from tkinter import messagebox


class DummyResponse:
    def __init__(self, status_code=503, data=None, content=b""):
        self.status_code = status_code
        self._data = data or {"detail": "Servidor no disponible o dependencia httpx no instalada"}
        self.content = content

    def json(self):
        return self._data


class APIClient:
    def __init__(self):
        self.base_url = API_BASE_URL
        self.terminal_id = TERMINAL_ID
        self.terminal_nombre = TERMINAL_NOMBRE
        self.modo = "servidor"
        self.token = self._load_token()
        self.timeout = 2.5
        self.servidor_disponible = None
        self._ultimo_check_ts = 0.0
        self._client = None
        self.recargar_configuracion_red()

    def _init_client(self):
        if HTTPX_DISPONIBLE:
            try:
                if self._client is not None:
                    try:
                        self._client.close()
                    except Exception:
                        pass
                self._client = httpx.Client(timeout=self.timeout)
            except Exception:
                self._client = None

    def recargar_configuracion_red(self):
        """Recarga desde network_manager la configuración activa (modo, IP, puerto, terminal)."""
        try:
            from interface.network_manager import obtener_config_red
            cfg = obtener_config_red()
            self.modo = cfg.get("modo", "servidor")
            puerto = int(cfg.get("servidor_puerto", 8000))
            ip = "127.0.0.1" if self.modo == "servidor" else cfg.get("servidor_ip", "127.0.0.1")
            self.base_url = f"http://{ip}:{puerto}"
            self.terminal_id = int(cfg.get("terminal_id", 1))
            self.terminal_nombre = str(cfg.get("terminal_nombre", "CAJA-01"))
        except Exception:
            pass
        self.servidor_disponible = None
        self._ultimo_check_ts = 0.0
        self._init_client()

    def es_modo_cliente(self) -> bool:
        """Indica si esta computadora está configurada como CAJA SECUNDARIA (Cliente)."""
        try:
            from interface.network_manager import obtener_config_red
            return obtener_config_red().get("modo", "servidor") == "cliente"
        except Exception:
            return self.modo == "cliente"

    def actualizar_config_red(self, base_url, terminal_id=None, terminal_nombre=None, modo=None):
        """Actualiza dinámicamente la URL base y los datos de terminal en memoria."""
        if base_url:
            self.base_url = str(base_url).rstrip("/")
        if terminal_id is not None:
            self.terminal_id = int(terminal_id)
        if terminal_nombre is not None:
            self.terminal_nombre = str(terminal_nombre)
        if modo in ("servidor", "cliente"):
            self.modo = modo
        self.servidor_disponible = None
        self._ultimo_check_ts = 0.0
        self._init_client()

    def _load_token(self):
        env_token = os.getenv("VMPOS_TOKEN")
        if env_token:
            return env_token
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("access_token")
            except Exception:
                return None
        return None

    def _save_token(self, token_data):
        try:
            os.makedirs(os.path.dirname(os.path.abspath(TOKEN_FILE)), exist_ok=True)
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(token_data, f)
        except Exception:
            pass
        self.token = token_data.get("access_token")

    def clear_token(self):
        if os.path.exists(TOKEN_FILE):
            try:
                os.remove(TOKEN_FILE)
            except Exception:
                pass
        self.token = None

    def _get_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def esta_disponible(self, forzar: bool = False) -> bool:
        """Verificación real del estado del servidor mediante `/api/health`."""
        if not HTTPX_DISPONIBLE:
            return False
        ahora = time.time()
        if not forzar and self.servidor_disponible is False and (ahora - self._ultimo_check_ts) < 1.0:
            return False
        self._ultimo_check_ts = ahora
        try:
            with httpx.Client(timeout=1.2) as c:
                r = c.get(f"{self.base_url}/api/health")
                if r.status_code == 200:
                    datos = r.json()
                    ok = isinstance(datos, dict) and datos.get("status") == "ok" and datos.get("database") == "connected"
                    self.servidor_disponible = ok
                    return ok
                self.servidor_disponible = False
                return False
        except Exception:
            self.servidor_disponible = False
            return False

    def _asegurar_disponibilidad(self) -> bool:
        if not HTTPX_DISPONIBLE:
            return False
        if self.servidor_disponible is True:
            return True
        return self.esta_disponible()

    def login(self, username, password):
        if not HTTPX_DISPONIBLE:
            return False, "httpx no está instalado en este entorno"
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            data = {"usuario": username, "password": password, "terminal_id": getattr(self, "terminal_id", 1)}
            response = client.post(f"{self.base_url}/auth/login", json=data)

            if response.status_code == 200:
                token_data = response.json()
                self._save_token(token_data)
                self.servidor_disponible = True
                return True, "Login exitoso"
            else:
                return False, response.json().get("detail", "Error de autenticación")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            self.servidor_disponible = False
            return False, f"Servidor no disponible en {self.base_url}: {e}"
        except httpx.RequestError as e:
            return False, f"Error de conexión al servidor: {e}"

    def get(self, endpoint, params=None):
        if not self._asegurar_disponibilidad():
            return DummyResponse(503)
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            resp = client.get(f"{self.base_url}{endpoint}", headers=self._get_headers(), params=params)
            self.servidor_disponible = True
            if resp.status_code == 401 and self.token:
                self.clear_token()
                messagebox.showerror("Sesión Expirada", "Su sesión ha expirado, por favor inicie sesión nuevamente.")
            return resp
        except (httpx.ConnectError, httpx.TimeoutException):
            self.servidor_disponible = False
            return DummyResponse(503, {"detail": "Servidor no responde"})
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})

    def post(self, endpoint, data=None, json=None):
        if not self._asegurar_disponibilidad():
            return DummyResponse(503)
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            resp = client.post(f"{self.base_url}{endpoint}", headers=self._get_headers(), data=data, json=json)
            self.servidor_disponible = True
            if resp.status_code == 401 and self.token:
                self.clear_token()
            return resp
        except (httpx.ConnectError, httpx.TimeoutException):
            self.servidor_disponible = False
            return DummyResponse(503, {"detail": "Servidor no responde"})
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})

    def put(self, endpoint, json=None):
        if not self._asegurar_disponibilidad():
            return DummyResponse(503)
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            resp = client.put(f"{self.base_url}{endpoint}", headers=self._get_headers(), json=json)
            self.servidor_disponible = True
            if resp.status_code == 401 and self.token:
                self.clear_token()
            return resp
        except (httpx.ConnectError, httpx.TimeoutException):
            self.servidor_disponible = False
            return DummyResponse(503, {"detail": "Servidor no responde"})
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})

    def delete(self, endpoint, params=None):
        if not self._asegurar_disponibilidad():
            return DummyResponse(503)
        try:
            client = self._client or httpx.Client(timeout=self.timeout)
            resp = client.delete(f"{self.base_url}{endpoint}", headers=self._get_headers(), params=params)
            self.servidor_disponible = True
            if resp.status_code == 401 and self.token:
                self.clear_token()
            return resp
        except (httpx.ConnectError, httpx.TimeoutException):
            self.servidor_disponible = False
            return DummyResponse(503, {"detail": "Servidor no responde"})
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})


# Instancia global
api = APIClient()

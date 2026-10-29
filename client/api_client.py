try:
    import httpx
    HTTPX_DISPONIBLE = True
except ImportError:
    httpx = None
    HTTPX_DISPONIBLE = False

import json
import os
from .config import API_BASE_URL, TOKEN_FILE, TERMINAL_ID, TERMINAL_NOMBRE
from tkinter import messagebox

class DummyResponse:
    def __init__(self, status_code=503, data=None):
        self.status_code = status_code
        self._data = data or {"detail": "Servidor no disponible o dependencia httpx no instalada"}
    def json(self):
        return self._data

class APIClient:
    def __init__(self):
        self.base_url = API_BASE_URL
        self.terminal_id = TERMINAL_ID
        self.terminal_nombre = TERMINAL_NOMBRE
        self.token = self._load_token()

    def actualizar_config_red(self, base_url, terminal_id=None, terminal_nombre=None):
        """Actualiza dinámicamente la URL base y los datos de terminal en memoria."""
        if base_url:
            self.base_url = str(base_url).rstrip("/")
        if terminal_id is not None:
            self.terminal_id = int(terminal_id)
        if terminal_nombre is not None:
            self.terminal_nombre = str(terminal_nombre)

    def _load_token(self):
        env_token = os.getenv("VMPOS_TOKEN")
        if env_token:
            return env_token
        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r') as f:
                    data = json.load(f)
                    return data.get('access_token')
            except Exception:
                return None
        return None

    def _save_token(self, token_data):
        with open(TOKEN_FILE, 'w') as f:
            json.dump(token_data, f)
        self.token = token_data.get('access_token')

    def clear_token(self):
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        self.token = None

    def _get_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def login(self, username, password):
        if not HTTPX_DISPONIBLE:
            return False, "httpx no está instalado en este entorno"
        try:
            with httpx.Client(timeout=10.0) as client:
                data = {"usuario": username, "password": password, "terminal_id": getattr(self, "terminal_id", 1)}
                response = client.post(f"{self.base_url}/auth/login", json=data)
                
                if response.status_code == 200:
                    token_data = response.json()
                    self._save_token(token_data)
                    return True, "Login exitoso"
                else:
                    return False, response.json().get("detail", "Error de autenticación")
        except httpx.RequestError as e:
            return False, f"Error de conexión al servidor: {e}"

    def get(self, endpoint, params=None):
        if not HTTPX_DISPONIBLE:
            return DummyResponse(503)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{self.base_url}{endpoint}", headers=self._get_headers(), params=params)
                if resp.status_code == 401:
                    self.clear_token()
                    messagebox.showerror("Sesión Expirada", "Su sesión ha expirado, por favor inicie sesión nuevamente.")
                return resp
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})

    def post(self, endpoint, data=None, json=None):
        if not HTTPX_DISPONIBLE:
            return DummyResponse(503)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(f"{self.base_url}{endpoint}", headers=self._get_headers(), data=data, json=json)
                if resp.status_code == 401:
                    self.clear_token()
                return resp
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})

    def put(self, endpoint, json=None):
        if not HTTPX_DISPONIBLE:
            return DummyResponse(503)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.put(f"{self.base_url}{endpoint}", headers=self._get_headers(), json=json)
                if resp.status_code == 401:
                    self.clear_token()
                return resp
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})
            
    def delete(self, endpoint):
        if not HTTPX_DISPONIBLE:
            return DummyResponse(503)
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.delete(f"{self.base_url}{endpoint}", headers=self._get_headers())
                if resp.status_code == 401:
                    self.clear_token()
                return resp
        except Exception as e:
            return DummyResponse(503, {"detail": str(e)})

# Instancia global
api = APIClient()

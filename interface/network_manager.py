#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/network_manager.py
Gestión de red, detección automática de IP/puerto, diagnóstico de conectividad
y persistencia de configuración de terminales para VmPOS.
"""

import os
import sys
import json
import time
import socket
import urllib.request
import urllib.error
import subprocess
from typing import List, Tuple, Dict, Any, Optional

# Rutas de persistencia de configuración de red
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
NETWORK_CONFIG_LOCAL = os.path.join(_PROJECT_ROOT, "network_config.json")
CONFIG_DIR_USER = os.path.expanduser("~/.vmpos")
NETWORK_CONFIG_USER = os.path.join(CONFIG_DIR_USER, "network_config.json")

# Variable global para guardar referencia al proceso del servidor local si se lanza desde la app
_PROCESO_SERVIDOR_LOCAL = None


def obtener_ips_locales() -> List[str]:
    """
    Detecta automáticamente las direcciones IP locales de la computadora
    (WiFi o cable Ethernet), descartando 127.0.0.1 salvo como último recurso.
    """
    ips = []

    # Método 1: Socket UDP hacia un destino externo sin enviar datos reales
    # (El sistema operativo elige la interfaz de red activa de la ruta por defecto)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        if ip and ip != "127.0.0.1" and not ip.startswith("127."):
            ips.append(ip)
        s.close()
    except Exception:
        pass

    # Método 2: socket.gethostbyname_ex del hostname local
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip and ip != "127.0.0.1" and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    # Método 3: En macOS/Linux, fallback con ifconfig o ip addr
    if not ips:
        try:
            cmd = ["ip", "-4", "addr", "show"] if sys.platform != "darwin" else ["ifconfig"]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
            for line in out.splitlines():
                line = line.strip()
                if "inet " in line:
                    parts = line.split()
                    idx = parts.index("inet") + 1
                    if idx < len(parts):
                        c_ip = parts[idx].split("/")[0]
                        if c_ip and c_ip != "127.0.0.1" and not c_ip.startswith("127.") and c_ip not in ips:
                            ips.append(c_ip)
        except Exception:
            pass

    if not ips:
        ips.append("127.0.0.1")

    return ips


def verificar_puerto_abierto(host: str = "127.0.0.1", puerto: int = 8000, timeout: float = 1.0) -> bool:
    """Verifica si un puerto TCP específico está abierto y escuchando."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        resultado = s.connect_ex((host, int(puerto)))
        s.close()
        return resultado == 0
    except Exception:
        return False


def probar_conexion(host_o_url: str, puerto: int = 8000, timeout: float = 3.0) -> Tuple[bool, str, float]:
    """
    Realiza una prueba de conectividad HTTP al servidor VmPOS.
    Retorna: (exito: bool, mensaje: str, latencia_ms: float)
    """
    raw = str(host_o_url or "").strip()
    if not raw:
        return False, "La dirección IP o URL del servidor está vacía", 0.0

    # Normalizar URL
    if not raw.startswith("http://") and not raw.startswith("https://"):
        url = f"http://{raw}:{puerto}"
    else:
        url = raw
        # Si no tiene puerto especificado en la URL y se pasó uno distinto a 80/443
        if ":" not in url.replace("http://", "").replace("https://", ""):
            url = f"{url}:{puerto}"

    url = url.rstrip("/")
    t_inicio = time.time()

    # Intentar endpoint de documentación o raíz de FastAPI
    endpoints_a_probar = [f"{url}/docs", f"{url}/openapi.json", f"{url}/"]

    ultimo_error = ""
    for ep in endpoints_a_probar:
        try:
            req = urllib.request.Request(ep, headers={"User-Agent": "VmPOS-Ping/4.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                codigo = response.getcode()
                latencia_ms = round((time.time() - t_inicio) * 1000, 1)
                if codigo in (200, 301, 302, 307, 308, 404):
                    return True, f"¡Conexión exitosa con el servidor VmPOS! (HTTP {codigo})", latencia_ms
        except urllib.error.HTTPError as e:
            latencia_ms = round((time.time() - t_inicio) * 1000, 1)
            # El servidor respondió (ej: 401 Unauthorized o 404), lo que confirma que está activo y alcanzable
            return True, f"Servidor alcanzado correctamente (HTTP {e.code})", latencia_ms
        except urllib.error.URLError as e:
            ultimo_error = str(e.reason)
        except Exception as e:
            ultimo_error = str(e)

    # Diagnóstico del error
    err_lower = ultimo_error.lower()
    if "connection refused" in err_lower or "111" in err_lower or "10061" in err_lower:
        msg = f"Servidor no responde en {url}. Verifica que VmPOS esté iniciado en la PC Servidor."
    elif "timed out" in err_lower or "timeout" in err_lower:
        msg = f"Tiempo de espera agotado ({timeout}s). Verifica que ambas computadoras estén en la misma red y que el Firewall permita el puerto {puerto}."
    elif "no route to host" in err_lower or "network is unreachable" in err_lower:
        msg = "No hay ruta hacia el servidor. Verifica que el cable de red o WiFi esté conectado."
    else:
        msg = f"No se pudo conectar a {url}: {ultimo_error}"

    return False, msg, 0.0


def obtener_config_red() -> Dict[str, Any]:
    """
    Obtiene la configuración de red actual con fallback a variables de entorno o valores por defecto.
    """
    config_defecto = {
        "modo": "servidor",               # "servidor" o "cliente"
        "servidor_ip": "127.0.0.1",
        "servidor_puerto": 8000,
        "terminal_id": 1,
        "terminal_nombre": "CAJA-01",
        "timeout_segundos": 10
    }

    # Detectar IP real para el valor por defecto si es servidor
    ips = obtener_ips_locales()
    if ips and ips[0] != "127.0.0.1":
        config_defecto["servidor_ip"] = ips[0]

    datos = {}
    # 1. Intentar archivo local de proyecto
    if os.path.exists(NETWORK_CONFIG_LOCAL):
        try:
            with open(NETWORK_CONFIG_LOCAL, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except Exception:
            pass

    # 2. Si no, intentar en el directorio de usuario ~/.vmpos/
    if not datos and os.path.exists(NETWORK_CONFIG_USER):
        try:
            with open(NETWORK_CONFIG_USER, "r", encoding="utf-8") as f:
                datos = json.load(f)
        except Exception:
            pass

    # 3. Mezclar con variables de entorno si existen
    env_url = os.getenv("API_BASE_URL")
    if env_url:
        try:
            limpia = env_url.replace("http://", "").replace("https://", "").rstrip("/")
            if ":" in limpia:
                ip_p, p_p = limpia.split(":", 1)
                datos["servidor_ip"] = ip_p
                datos["servidor_puerto"] = int(p_p)
            else:
                datos["servidor_ip"] = limpia
        except Exception:
            pass

    if os.getenv("TERMINAL_ID"):
        try:
            datos["terminal_id"] = int(os.getenv("TERMINAL_ID"))
        except Exception:
            pass

    if os.getenv("TERMINAL_NOMBRE"):
        datos["terminal_nombre"] = os.getenv("TERMINAL_NOMBRE")

    # Combinar con valores por defecto
    resultado = dict(config_defecto)
    if isinstance(datos, dict):
        resultado.update(datos)

    return resultado


def guardar_config_red(datos: Dict[str, Any]) -> bool:
    """
    Guarda la configuración de red en disco (tanto en el proyecto como en ~/.vmpos/)
    y actualiza la instancia activa de APIClient.
    """
    try:
        actual = obtener_config_red()
        actual.update(datos)

        # Guardar en archivo local del proyecto
        try:
            with open(NETWORK_CONFIG_LOCAL, "w", encoding="utf-8") as f:
                json.dump(actual, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Aviso guardando {NETWORK_CONFIG_LOCAL}: {e}")

        # Guardar en ~/.vmpos/ para compatibilidad con ejecutable empaquetado
        try:
            if not os.path.exists(CONFIG_DIR_USER):
                os.makedirs(CONFIG_DIR_USER, exist_ok=True)
            with open(NETWORK_CONFIG_USER, "w", encoding="utf-8") as f:
                json.dump(actual, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Aviso guardando {NETWORK_CONFIG_USER}: {e}")

        # Actualizar variables de entorno en el proceso actual
        ip = actual.get("servidor_ip", "127.0.0.1")
        puerto = actual.get("servidor_puerto", 8000)
        nueva_url = f"http://{ip}:{puerto}"
        os.environ["API_BASE_URL"] = nueva_url
        os.environ["TERMINAL_ID"] = str(actual.get("terminal_id", 1))
        os.environ["TERMINAL_NOMBRE"] = str(actual.get("terminal_nombre", "CAJA-01"))

        # Actualizar en memoria el cliente API singleton si ya está instanciado
        try:
            from client.api_client import api
            api.base_url = nueva_url
            api.terminal_id = actual.get("terminal_id", 1)
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"Error guardando configuración de red: {e}")
        return False


def construir_url_servidor(ip: str = None, puerto: int = None) -> str:
    """Construye la URL HTTP completa del servidor."""
    if not ip or not puerto:
        cfg = obtener_config_red()
        ip = ip or cfg.get("servidor_ip", "127.0.0.1")
        puerto = puerto or cfg.get("servidor_puerto", 8000)
    return f"http://{ip}:{puerto}"


def iniciar_servidor_segundo_plano() -> Tuple[bool, str]:
    """
    Intenta iniciar el servidor FastAPI local en segundo plano si no está activo.
    """
    global _PROCESO_SERVIDOR_LOCAL

    # Verificar si ya está escuchando
    cfg = obtener_config_red()
    puerto = int(cfg.get("servidor_puerto", 8000))
    if verificar_puerto_abierto("127.0.0.1", puerto, timeout=0.5):
        return True, f"El servidor ya está activo y escuchando en el puerto {puerto}."

    # Intentar levantarlo con uvicorn vía Python del entorno virtual o sistema
    python_bin = sys.executable
    server_dir = os.path.join(_PROJECT_ROOT, "server")

    if not os.path.exists(server_dir):
        return False, f"No se encontró el directorio del servidor en {server_dir}"

    try:
        # Comando para iniciar uvicorn escuchando en 0.0.0.0
        cmd = [
            python_bin, "-m", "uvicorn", "server.main:app",
            "--host", "0.0.0.0",
            "--port", str(puerto)
        ]
        _PROCESO_SERVIDOR_LOCAL = subprocess.Popen(
            cmd,
            cwd=_PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Esperar hasta 4 segundos a que el puerto abra
        for _ in range(8):
            time.sleep(0.5)
            if verificar_puerto_abierto("127.0.0.1", puerto, timeout=0.2):
                return True, f"Servidor iniciado exitosamente en http://0.0.0.0:{puerto}"

        return False, "El proceso se inició pero el puerto aún no responde. Revisa que PostgreSQL o las dependencias estén activas."
    except Exception as e:
        return False, f"Error al iniciar el servidor local: {e}"


def detener_servidor_segundo_plano() -> bool:
    """Detiene el proceso del servidor local si fue iniciado por esta aplicación."""
    global _PROCESO_SERVIDOR_LOCAL
    if _PROCESO_SERVIDOR_LOCAL:
        try:
            _PROCESO_SERVIDOR_LOCAL.terminate()
            _PROCESO_SERVIDOR_LOCAL.wait(timeout=2)
            _PROCESO_SERVIDOR_LOCAL = None
            return True
        except Exception:
            try:
                _PROCESO_SERVIDOR_LOCAL.kill()
                _PROCESO_SERVIDOR_LOCAL = None
                return True
            except Exception:
                pass
    return False

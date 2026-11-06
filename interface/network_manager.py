#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: interface/network_manager.py
Gestión de red, detección automática de IP/puerto, diagnóstico real de salud (/api/health),
control de proceso único del servidor con registro de logs y persistencia de terminales para VmPOS.
"""

import os
import sys
import json
import time
import socket
import shutil
import threading
import traceback
import urllib.request
import urllib.error
import subprocess
from typing import List, Tuple, Dict, Any

try:
    from interface.config import (
        USER_DATA_DIR,
        CONFIG_DIR,
        LOGS_DIR,
        OFFICIAL_SERVER_PORT,
    )
except Exception:
    _CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    USER_DATA_DIR = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))
    CONFIG_DIR = os.path.join(USER_DATA_DIR, "config")
    LOGS_DIR = os.path.join(USER_DATA_DIR, "logs")
    OFFICIAL_SERVER_PORT = 8000

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, ".."))

os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

NETWORK_CONFIG_MAIN = os.path.join(CONFIG_DIR, "network_config.json")
NETWORK_CONFIG_LOCAL = os.path.join(_PROJECT_ROOT, "network_config.json")
CONFIG_DIR_USER = os.path.expanduser("~/.vmpos")
NETWORK_CONFIG_USER = os.path.join(CONFIG_DIR_USER, "network_config.json")

SERVER_LOG_PATH = os.path.join(LOGS_DIR, "server.log")
SERVER_PID_PATH = os.path.join(LOGS_DIR, "server.pid")

_PROCESO_SERVIDOR_LOCAL = None
_UVICORN_SERVER_INSTANCE = None
_LOCK_ARRANQUE = threading.Lock()
_ESTADO_SERVIDOR = "detenido"  # "detenido" | "iniciando" | "activo" | "error" | "deteniendo"
_ULTIMO_ERROR_SERVIDOR = ""


def _registrar_log_servidor(mensaje: str):
    """Escribe una línea con marca de tiempo en logs/server.log."""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(SERVER_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {mensaje}\n")
    except Exception:
        pass


def leer_ultimas_lineas_log(max_lineas: int = 12) -> str:
    """Devuelve las últimas líneas relevantes de server.log para diagnóstico real."""
    if not os.path.exists(SERVER_LOG_PATH):
        return ""
    try:
        with open(SERVER_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            lineas = [ln.rstrip() for ln in f.readlines() if ln.strip()]
        return "\n".join(lineas[-max_lineas:])
    except Exception:
        return ""


def obtener_estado_control_servidor() -> str:
    """Retorna el estado actual del controlador: detenido, iniciando, activo, error, deteniendo."""
    return _ESTADO_SERVIDOR


def _es_ip_valida_lan(ip: str) -> bool:
    """Valida si una IP es una dirección LAN física útil para conectar cajas."""
    if not ip or not isinstance(ip, str):
        return False
    ip = ip.strip()
    if ip in ("127.0.0.1", "0.0.0.0", "255.255.255.255"):
        return False
    if ip.startswith("127.") or ip.startswith("169.254."):
        return False
    if ip.startswith("192.168.56."):
        return False
    return True


def _prioridad_ip(ip: str) -> int:
    """Asigna menor número a las IPs más probablemente conectadas a la red física principal."""
    if ip.startswith("192.168.") and not ip.startswith("192.168.56."):
        return 1
    if ip.startswith("10."):
        return 2
    if ip.startswith("172."):
        partes = ip.split(".")
        if len(partes) == 4 and partes[1].isdigit():
            seg = int(partes[1])
            if 16 <= seg <= 31:
                return 3
    return 4


def obtener_ips_locales() -> List[str]:
    """
    Detecta automáticamente las direcciones IP locales de la computadora (WiFi o Ethernet),
    descartando adaptadores virtuales y ordenando por prioridad de red LAN.
    """
    candidatos = []

    for dest in [("8.8.8.8", 80), ("1.1.1.1", 80), ("192.168.1.1", 80), ("10.0.0.1", 80)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.3)
            s.connect(dest)
            ip = s.getsockname()[0]
            s.close()
            if _es_ip_valida_lan(ip) and ip not in candidatos:
                candidatos.append(ip)
                break
        except Exception:
            pass

    if sys.platform == "win32":
        try:
            out = subprocess.check_output("ipconfig", stderr=subprocess.DEVNULL, text=True, shell=True)
            bloque_virtual = False
            for line in out.splitlines():
                line_lower = line.lower()
                if ":" in line and not line.startswith(" "):
                    if any(v in line_lower for v in ("vethernet", "virtual", "wsl", "vmware", "virtualbox", "host-only", "tap", "npcap", "bluetooth")):
                        bloque_virtual = True
                    else:
                        bloque_virtual = False
                elif ("ipv4" in line_lower or "dirección ipv4" in line_lower) and ":" in line:
                    if not bloque_virtual:
                        partes = line.split(":")
                        if len(partes) > 1:
                            c_ip = partes[1].replace("(Preferido)", "").strip()
                            if _es_ip_valida_lan(c_ip) and c_ip not in candidatos:
                                candidatos.append(c_ip)
        except Exception:
            pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if _es_ip_valida_lan(ip) and ip not in candidatos:
                candidatos.append(ip)
    except Exception:
        pass

    if not candidatos:
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
                        if _es_ip_valida_lan(c_ip) and c_ip not in candidatos:
                            candidatos.append(c_ip)
        except Exception:
            pass

    candidatos.sort(key=_prioridad_ip)
    if not candidatos:
        candidatos.append("127.0.0.1")
    return candidatos


def verificar_puerto_abierto(host: str = "127.0.0.1", puerto: int = OFFICIAL_SERVER_PORT, timeout: float = 0.8) -> bool:
    """Verifica si un puerto TCP específico está abierto y aceptando conexiones."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        resultado = s.connect_ex((host, int(puerto)))
        s.close()
        return resultado == 0
    except Exception:
        return False


def verificar_salud_servidor(
    host_o_url: str = "127.0.0.1",
    puerto: int = OFFICIAL_SERVER_PORT,
    timeout: float = 2.5,
) -> Tuple[bool, Dict[str, Any], str, float]:
    """
    Comprueba de forma real el endpoint `/api/health` del servidor VmPOS:
    - Proceso escuchando en el puerto.
    - FastAPI respondiendo HTTP 200.
    - Base de datos conectada (`database == "connected"`).
    - Identidad de la aplicación (`app == "VmPOS"` y `status == "ok"`).
    Retorna: (saludable: bool, payload: dict, mensaje: str, latencia_ms: float)
    """
    raw = str(host_o_url or "").strip()
    if not raw:
        return False, {}, "La dirección IP del servidor está vacía.", 0.0

    if not raw.startswith("http://") and not raw.startswith("https://"):
        base_url = f"http://{raw}:{int(puerto)}"
    else:
        base_url = raw.rstrip("/")
        sin_proto = base_url.replace("http://", "").replace("https://", "")
        if ":" not in sin_proto:
            base_url = f"{base_url}:{int(puerto)}"

    t_inicio = time.time()
    for ep in [f"{base_url}/api/health", f"{base_url}/health"]:
        try:
            req = urllib.request.Request(ep, headers={"User-Agent": "VmPOS-HealthCheck/4.0"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                codigo = response.getcode()
                cuerpo = response.read().decode("utf-8", errors="replace")
                latencia_ms = round((time.time() - t_inicio) * 1000, 1)
                if codigo == 200:
                    datos = json.loads(cuerpo)
                    if isinstance(datos, dict) and datos.get("status") == "ok" and datos.get("app") == "VmPOS":
                        if datos.get("database") == "connected":
                            neg = datos.get("nombre_negocio") or "VmPOS"
                            return True, datos, f"Servidor VmPOS activo ({neg}) — Base de datos conectada", latencia_ms
                        return False, datos, "El servidor respondió pero la base de datos no está conectada.", latencia_ms
        except urllib.error.HTTPError as e:
            latencia_ms = round((time.time() - t_inicio) * 1000, 1)
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = str(e)
            return False, {}, f"El servidor respondió con error HTTP {e.code}: {err_body}", latencia_ms
        except urllib.error.URLError as e:
            ultimo_error = str(e.reason)
        except Exception as e:
            ultimo_error = str(e)

    err_lower = ultimo_error.lower() if "ultimo_error" in locals() else ""
    if "connection refused" in err_lower or "111" in err_lower or "10061" in err_lower:
        msg = f"El servidor no está escuchando en {base_url}. Verifica que el Servidor VmPOS esté iniciado."
    elif "timed out" in err_lower or "timeout" in err_lower:
        msg = f"Tiempo de espera agotado ({timeout}s) hacia {base_url}. Verifica que ambas computadoras estén en la misma red y que el Firewall permita el puerto {puerto}."
    else:
        msg = f"No se pudo verificar el estado de salud en {base_url}: {locals().get('ultimo_error', 'Sin respuesta')}"
    return False, {}, msg, 0.0


def probar_conexion(host_o_url: str, puerto: int = OFFICIAL_SERVER_PORT, timeout: float = 3.0) -> Tuple[bool, str, float]:
    """
    Realiza una prueba real de conectividad y salud contra `/api/health` del servidor VmPOS.
    Retorna: (exito: bool, mensaje: str, latencia_ms: float)
    """
    ok, _datos, msg, latencia_ms = verificar_salud_servidor(host_o_url, puerto=puerto, timeout=timeout)
    return ok, msg, latencia_ms


def obtener_config_red() -> Dict[str, Any]:
    """
    Obtiene la configuración de red actual desde la fuente oficial (`CONFIG_DIR/network_config.json`),
    normalizando claves heredadas (`tipo_nodo` -> `modo`) y puerto oficial (`8000`).
    """
    config_defecto = {
        "modo": "servidor",
        "servidor_ip": "127.0.0.1",
        "servidor_puerto": OFFICIAL_SERVER_PORT,
        "terminal_id": 1,
        "terminal_nombre": "CAJA-01",
        "timeout_segundos": 10,
    }

    ips = obtener_ips_locales()
    if ips and ips[0] != "127.0.0.1":
        config_defecto["servidor_ip"] = ips[0]

    datos = {}
    for ruta in (NETWORK_CONFIG_MAIN, NETWORK_CONFIG_USER, NETWORK_CONFIG_LOCAL):
        if os.path.exists(ruta):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    cargado = json.load(f)
                if isinstance(cargado, dict) and cargado:
                    datos = cargado
                    break
            except Exception:
                continue

    if isinstance(datos, dict):
        if "modo" not in datos and "tipo_nodo" in datos:
            datos["modo"] = datos.get("tipo_nodo", "servidor")
        if str(datos.get("modo", "")).lower() not in ("servidor", "cliente"):
            datos["modo"] = "servidor"
        try:
            datos["servidor_puerto"] = int(datos.get("servidor_puerto") or OFFICIAL_SERVER_PORT)
        except Exception:
            datos["servidor_puerto"] = OFFICIAL_SERVER_PORT

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

    resultado = dict(config_defecto)
    if isinstance(datos, dict):
        resultado.update(datos)
    resultado.pop("tipo_nodo", None)
    return resultado


def guardar_config_red(datos: Dict[str, Any]) -> bool:
    """
    Guarda la configuración de red en la ubicación oficial (`CONFIG_DIR/network_config.json`),
    actualiza `APIClient` en memoria y sincroniza la configuración comercial si es Caja Secundaria.
    """
    try:
        actual = obtener_config_red()
        actual.update(datos)
        actual.pop("tipo_nodo", None)
        actual["modo"] = "cliente" if str(actual.get("modo", "")).lower() == "cliente" else "servidor"
        actual["servidor_puerto"] = int(actual.get("servidor_puerto") or OFFICIAL_SERVER_PORT)
        actual["terminal_id"] = int(actual.get("terminal_id") or 1)
        actual["terminal_nombre"] = str(actual.get("terminal_nombre") or f"CAJA-{actual['terminal_id']:02d}")

        for ruta in (NETWORK_CONFIG_MAIN, NETWORK_CONFIG_USER, NETWORK_CONFIG_LOCAL):
            try:
                os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
                with open(ruta, "w", encoding="utf-8") as f:
                    json.dump(actual, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

        # Si el equipo es Servidor, el cliente API interno se comunica con 127.0.0.1:<puerto>
        # Si es Caja Secundaria (cliente), se comunica con <servidor_ip>:<puerto>
        ip_efectiva = "127.0.0.1" if actual["modo"] == "servidor" else actual.get("servidor_ip", "127.0.0.1")
        puerto = actual["servidor_puerto"]
        nueva_url = f"http://{ip_efectiva}:{puerto}"
        os.environ["API_BASE_URL"] = nueva_url
        os.environ["TERMINAL_ID"] = str(actual["terminal_id"])
        os.environ["TERMINAL_NOMBRE"] = str(actual["terminal_nombre"])

        try:
            from client.api_client import api
            api.base_url = nueva_url
            api.terminal_id = actual["terminal_id"]
            api.modo = actual["modo"]
            api.esta_disponible()
        except Exception:
            pass

        return True
    except Exception as e:
        _registrar_log_servidor(f"Error guardando configuración de red: {e}")
        return False


def construir_url_servidor(ip: str = None, puerto: int = None) -> str:
    """Construye la URL HTTP completa del servidor."""
    cfg = obtener_config_red()
    if not ip:
        ip = "127.0.0.1" if cfg.get("modo") == "servidor" else cfg.get("servidor_ip", "127.0.0.1")
    if not puerto:
        puerto = int(cfg.get("servidor_puerto", OFFICIAL_SERVER_PORT))
    return f"http://{ip}:{puerto}"


def _iniciar_uvicorn_en_hilo_interno(puerto: int) -> bool:
    """Inicia Uvicorn dentro de un hilo controlado del proceso actual registrando errores en server.log."""
    global _UVICORN_SERVER_INSTANCE
    try:
        import uvicorn
        from server.main import app as fastapi_app

        config = uvicorn.Config(
            fastapi_app,
            host="0.0.0.0",
            port=int(puerto),
            log_level="info",
            access_log=False,
        )
        server = uvicorn.Server(config)
        _UVICORN_SERVER_INSTANCE = server

        def _worker():
            try:
                _registrar_log_servidor(f"Iniciando hilo interno Uvicorn en 0.0.0.0:{puerto}...")
                server.run()
            except BaseException as exc:
                tb = traceback.format_exc()
                _registrar_log_servidor(f"ERROR CRÍTICO en hilo Uvicorn:\n{exc}\n{tb}")

        t = threading.Thread(target=_worker, daemon=True, name=f"VmPOS_Server_{puerto}")
        t.start()
        return True
    except BaseException as exc:
        tb = traceback.format_exc()
        _registrar_log_servidor(f"Fallo al preparar hilo interno Uvicorn: {exc}\n{tb}")
        return False


def iniciar_servidor_segundo_plano() -> Tuple[bool, str]:
    """
    Inicia el servidor central FastAPI de forma controlada y única:
    - Impide ejecuciones duplicadas simultáneas con `_LOCK_ARRANQUE`.
    - Verifica `/api/health` (proceso + puerto + API + base de datos).
    - Registra toda la salida y tracebacks en `logs/server.log`.
    - Solo reporta éxito cuando `/api/health` responde satisfactoriamente.
    """
    global _PROCESO_SERVIDOR_LOCAL, _ESTADO_SERVIDOR, _ULTIMO_ERROR_SERVIDOR

    cfg = obtener_config_red()
    puerto = int(cfg.get("servidor_puerto", OFFICIAL_SERVER_PORT))

    # 1. Comprobar si ya está saludable antes de adquirir bloqueo largo
    ok_previo, datos_salud, msg_previo, _ = verificar_salud_servidor("127.0.0.1", puerto=puerto, timeout=1.2)
    if ok_previo:
        _ESTADO_SERVIDOR = "activo"
        return True, f"El servidor VmPOS ya está activo y saludable en el puerto {puerto}."

    if not _LOCK_ARRANQUE.acquire(blocking=False):
        return False, "El servidor ya se encuentra en proceso de arranque. Por favor espera unos segundos."

    try:
        _ESTADO_SERVIDOR = "iniciando"
        _ULTIMO_ERROR_SERVIDOR = ""

        # Re-verificar salud dentro del lock
        ok_ya, _, _, _ = verificar_salud_servidor("127.0.0.1", puerto=puerto, timeout=1.0)
        if ok_ya:
            _ESTADO_SERVIDOR = "activo"
            return True, f"El servidor VmPOS ya está activo y escuchando en el puerto {puerto}."

        # Comprobar si el puerto está ocupado por una instancia antigua de VmPOS o por otro programa
        if verificar_puerto_abierto("127.0.0.1", puerto=puerto, timeout=0.6):
            ok_retry, _, _, _ = verificar_salud_servidor("127.0.0.1", puerto=puerto, timeout=1.5)
            if ok_retry:
                _ESTADO_SERVIDOR = "activo"
                return True, f"Servidor VmPOS activo en el puerto {puerto}."

            # Intentar detener instancia previa de VmPOS / uvicorn que no tenía /api/health
            try:
                if sys.platform == "win32":
                    out_net = subprocess.check_output(f"netstat -ano | findstr :{puerto}", shell=True, text=True, stderr=subprocess.DEVNULL)
                    for ln in out_net.splitlines():
                        partes = ln.split()
                        if len(partes) >= 5 and "LISTENING" in ln.upper():
                            pid_old = partes[-1]
                            if pid_old.isdigit() and int(pid_old) != os.getpid():
                                subprocess.run(f"taskkill /PID {pid_old} /F", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
                else:
                    out_lsof = subprocess.check_output(["lsof", "-t", f"-iTCP:{puerto}", "-sTCP:LISTEN"], text=True, stderr=subprocess.DEVNULL)
                    for pid_str in out_lsof.splitlines():
                        pid_str = pid_str.strip()
                        if pid_str.isdigit() and int(pid_str) != os.getpid():
                            import signal
                            os.kill(int(pid_str), signal.SIGTERM)
                time.sleep(0.6)
            except Exception:
                pass

            if verificar_puerto_abierto("127.0.0.1", puerto=puerto, timeout=0.4):
                _ESTADO_SERVIDOR = "error"
                msg_ocupado = (
                    f"El puerto {puerto} está siendo ocupado por otro proceso que no responde como VmPOS.\n"
                    f"Cierra la aplicación que usa el puerto {puerto} o verifica el registro en:\n{SERVER_LOG_PATH}"
                )
                _registrar_log_servidor(msg_ocupado)
                return False, msg_ocupado

        # 2. Habilitar regla de Firewall en Windows de forma silenciosa
        if sys.platform == "win32":
            try:
                subprocess.run(
                    f'netsh advfirewall firewall add rule name="VmPOS Server {puerto}" dir=in action=allow protocol=TCP localport={puerto}',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,
                )
            except Exception:
                pass

        # 3. Lanzar subproceso independiente usando `--run-server` (sin abrir ventana GUI)
        #    y redirigiendo stdout/stderr a `logs/server.log`.
        _registrar_log_servidor(f"=== Solicitud de arranque del Servidor VmPOS en puerto {puerto} ===")
        subproceso_lanzado = False

        try:
            log_fh = open(SERVER_LOG_PATH, "a", encoding="utf-8")
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--run-server", "--host", "0.0.0.0", "--port", str(puerto)]
                cwd_srv = os.path.dirname(os.path.abspath(sys.executable))
            else:
                python_candidatos = [
                    os.path.join(_PROJECT_ROOT, ".venv", "Scripts", "python.exe"),
                    os.path.join(_PROJECT_ROOT, "venv", "Scripts", "python.exe"),
                    os.path.join(_PROJECT_ROOT, ".venv", "bin", "python"),
                    os.path.join(_PROJECT_ROOT, "venv", "bin", "python"),
                    sys.executable,
                ]
                python_bin = sys.executable
                for cand in python_candidatos:
                    if cand and os.path.exists(cand):
                        python_bin = cand
                        break
                entry_script = os.path.join(_PROJECT_ROOT, "interface", "inicio_sesion.py")
                cmd = [python_bin, entry_script, "--run-server", "--host", "0.0.0.0", "--port", str(puerto)]
                cwd_srv = _PROJECT_ROOT

            popen_kwargs: Dict[str, Any] = {
                "cwd": cwd_srv,
                "stdout": log_fh,
                "stderr": log_fh,
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

            _PROCESO_SERVIDOR_LOCAL = subprocess.Popen(cmd, **popen_kwargs)
            subproceso_lanzado = True
            try:
                with open(SERVER_PID_PATH, "w", encoding="utf-8") as pf:
                    pf.write(str(_PROCESO_SERVIDOR_LOCAL.pid))
            except Exception:
                pass
        except Exception as e_sub:
            _registrar_log_servidor(f"Aviso al lanzar subproceso del servidor: {e_sub}. Intentando hilo interno...")

        # Esperar y verificar salud del subproceso o iniciar hilo interno si el subproceso terminó prematuramente
        hilo_iniciado = False
        if not subproceso_lanzado:
            hilo_iniciado = _iniciar_uvicorn_en_hilo_interno(puerto)

        for intento in range(24):  # Hasta ~7.2 segundos
            time.sleep(0.3)
            if subproceso_lanzado and _PROCESO_SERVIDOR_LOCAL is not None:
                ret = _PROCESO_SERVIDOR_LOCAL.poll()
                if ret is not None and not hilo_iniciado:
                    _registrar_log_servidor(f"El subproceso del servidor terminó con código {ret}. Activando hilo interno de respaldo...")
                    hilo_iniciado = _iniciar_uvicorn_en_hilo_interno(puerto)

            saludable, datos_h, msg_h, _ = verificar_salud_servidor("127.0.0.1", puerto=puerto, timeout=1.0)
            if saludable:
                _ESTADO_SERVIDOR = "activo"
                _registrar_log_servidor(f"Servidor ACTIVO y saludable en http://0.0.0.0:{puerto} ({msg_h})")
                return True, f"Servidor iniciado y verificado exitosamente en http://0.0.0.0:{puerto}\n({msg_h})"

        # Si tras la espera no respondió `/api/health`, reportar el error real registrado
        _ESTADO_SERVIDOR = "error"
        extracto_log = leer_ultimas_lineas_log(8)
        detalle = f"\n\nÚltimo registro en {SERVER_LOG_PATH}:\n{extracto_log}" if extracto_log else ""
        msg_fallo = f"El servidor no superó la comprobación de salud (/api/health) en el puerto {puerto}.{detalle}"
        _ULTIMO_ERROR_SERVIDOR = msg_fallo
        return False, msg_fallo
    finally:
        _LOCK_ARRANQUE.release()


def detener_servidor_segundo_plano() -> bool:
    """Detiene el proceso o hilo del servidor local si fue iniciado por esta aplicación."""
    global _PROCESO_SERVIDOR_LOCAL, _UVICORN_SERVER_INSTANCE, _ESTADO_SERVIDOR
    _ESTADO_SERVIDOR = "deteniendo"
    detenido = False

    if _UVICORN_SERVER_INSTANCE is not None:
        try:
            _UVICORN_SERVER_INSTANCE.should_exit = True
            _UVICORN_SERVER_INSTANCE = None
            detenido = True
        except Exception:
            pass

    if _PROCESO_SERVIDOR_LOCAL is not None:
        try:
            _PROCESO_SERVIDOR_LOCAL.terminate()
            _PROCESO_SERVIDOR_LOCAL.wait(timeout=3)
            _PROCESO_SERVIDOR_LOCAL = None
            detenido = True
        except Exception:
            try:
                _PROCESO_SERVIDOR_LOCAL.kill()
                _PROCESO_SERVIDOR_LOCAL = None
                detenido = True
            except Exception:
                pass

    if os.path.exists(SERVER_PID_PATH):
        try:
            with open(SERVER_PID_PATH, "r", encoding="utf-8") as pf:
                pid_guardado = int(pf.read().strip())
            if sys.platform == "win32":
                subprocess.run(
                    f"taskkill /PID {pid_guardado} /F",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=0x08000000,
                )
            else:
                import signal
                os.kill(pid_guardado, signal.SIGTERM)
            detenido = True
        except Exception:
            pass
        try:
            os.remove(SERVER_PID_PATH)
        except Exception:
            pass

    _ESTADO_SERVIDOR = "detenido"
    return detenido

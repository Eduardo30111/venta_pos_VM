#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: config.py
Configuración centralizada para la aplicación VmPOS.
Maneja las rutas absolutas para evitar el problema de bases de datos duplicadas.
"""

import os
import sys

import tempfile

# Determinar directorios según si se ejecuta desde PyInstaller o como script de desarrollo
if getattr(sys, 'frozen', False):
    _base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
    _res = os.path.join(os.path.dirname(_base), "Resources")
    if os.path.exists(os.path.join(_res, "config")):
        BUNDLE_DIR = _res
    else:
        BUNDLE_DIR = _base

    # Seleccionar directorio de datos escribible con salvaguarda
    if sys.platform == "darwin":
        candidatos_dir = [
            os.path.expanduser("~/Library/Application Support/VmPOS"),
            os.path.expanduser("~/.vmpos"),
            os.path.join(os.path.expanduser("~"), "VmPOS_Data"),
            os.path.join(tempfile.gettempdir(), "VmPOS"),
        ]
    elif sys.platform.startswith("win"):
        prog_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        app_data = os.environ.get("APPDATA", "")
        candidatos_dir = [
            os.path.join(prog_data, "VmPOS") if prog_data else "",
            os.path.join(app_data, "VmPOS") if app_data else "",
            os.path.expanduser("~/.vmpos"),
            os.path.join(os.path.expanduser("~"), "VmPOS_Data"),
            os.path.join(tempfile.gettempdir(), "VmPOS"),
        ]
    else:
        candidatos_dir = [
            os.path.expanduser("~/.vmpos"),
            os.path.join(os.path.expanduser("~"), "VmPOS_Data"),
            os.path.join(tempfile.gettempdir(), "VmPOS"),
        ]
    USER_DATA_DIR = None
    for cand in candidatos_dir:
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            prueba_f = os.path.join(cand, ".perm_check")
            with open(prueba_f, "w") as f:
                f.write("ok")
            os.remove(prueba_f)
            USER_DATA_DIR = cand
            break
        except Exception:
            continue
    if not USER_DATA_DIR:
        try:
            cand_fallback = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data_usuario"))
            os.makedirs(cand_fallback, exist_ok=True)
            USER_DATA_DIR = cand_fallback
        except Exception:
            USER_DATA_DIR = os.path.join(tempfile.gettempdir(), "VmPOS_Fallback")
            os.makedirs(USER_DATA_DIR, exist_ok=True)

    # En Windows, si se seleccionó C:\ProgramData\VmPOS pero existen datos previos en %APPDATA%\VmPOS,
    # migrar de forma no destructiva los archivos existentes que aún no estén en ProgramData.
    if sys.platform.startswith("win"):
        _old_appdata = os.path.join(os.environ.get("APPDATA", ""), "VmPOS")
        if _old_appdata and os.path.exists(_old_appdata) and os.path.abspath(_old_appdata) != os.path.abspath(USER_DATA_DIR):
            import shutil as _shutil
            for _sub in ["database", "config", os.path.join("assets", "logos")]:
                _src_d = os.path.join(_old_appdata, _sub)
                _dst_d = os.path.join(USER_DATA_DIR, _sub)
                if os.path.isdir(_src_d):
                    os.makedirs(_dst_d, exist_ok=True)
                    for _fn in os.listdir(_src_d):
                        _sf = os.path.join(_src_d, _fn)
                        _df = os.path.join(_dst_d, _fn)
                        if os.path.isfile(_sf) and not os.path.exists(_df):
                            try:
                                _shutil.copy2(_sf, _df)
                            except Exception:
                                pass
else:
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = os.path.abspath(os.path.join(_current_dir, '..'))
    USER_DATA_DIR = BUNDLE_DIR

OFFICIAL_SERVER_PORT = 8000

BASE_DIR = USER_DATA_DIR
DATABASE_DIR = os.path.join(USER_DATA_DIR, 'database')
CONFIG_DIR = os.path.join(USER_DATA_DIR, 'config')
LOGOS_DIR = os.path.join(USER_DATA_DIR, 'assets', 'logos')
LOGS_DIR = os.path.join(USER_DATA_DIR, 'logs')
CACHE_DIR = os.path.join(USER_DATA_DIR, 'cache')
BACKUPS_DIR = os.path.join(USER_DATA_DIR, 'backups')

try:
    os.makedirs(DATABASE_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(LOGOS_DIR, exist_ok=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
except Exception as e:
    print(f"Error creando directorios de usuario en {USER_DATA_DIR}: {e}")

# Si estamos en modo empaquetado (PyInstaller), copiar plantillas iniciales a ~/.vmpos si no existen
if getattr(sys, 'frozen', False):
    import shutil
    plantillas = [
        ('ventas.db', 'database', 'database'),
        ('usuarios.db', 'database', 'database'),
        ('business_config.json', 'config', 'config'),
        ('printer_config.json', 'config', 'config'),
        ('theme_config.json', 'config', 'config'),
        ('network_config.json', '', '')
    ]
    for archivo, sub_origen, sub_destino in plantillas:
        ruta_orig = os.path.join(BUNDLE_DIR, sub_origen, archivo) if sub_origen else os.path.join(BUNDLE_DIR, archivo)
        ruta_dest = os.path.join(USER_DATA_DIR, sub_destino, archivo) if sub_destino else os.path.join(USER_DATA_DIR, archivo)
        if os.path.exists(ruta_orig) and not os.path.exists(ruta_dest):
            try:
                shutil.copy2(ruta_orig, ruta_dest)
            except Exception as e:
                print(f"Aviso copiando plantilla {archivo}: {e}")

# Rutas absolutas a las bases de datos
DB_VENTAS_PATH = os.path.join(DATABASE_DIR, 'ventas.db')
DB_USUARIOS_PATH = os.path.join(DATABASE_DIR, 'usuarios.db')


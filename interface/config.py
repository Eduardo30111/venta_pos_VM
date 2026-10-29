#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: config.py
Configuración centralizada para la aplicación VmPOS.
Maneja las rutas absolutas para evitar el problema de bases de datos duplicadas.
"""

import os
import sys

# Determinar directorios según si se ejecuta desde PyInstaller o como script de desarrollo
if getattr(sys, 'frozen', False):
    _base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.executable)))
    _res = os.path.join(os.path.dirname(_base), "Resources")
    if os.path.exists(os.path.join(_res, "config")):
        BUNDLE_DIR = _res
    else:
        BUNDLE_DIR = _base

    # Seleccionar directorio de datos escribible con salvaguarda
    candidatos_dir = [
        os.path.expanduser("~/Library/Application Support/VmPOS") if sys.platform == "darwin" else os.path.join(os.environ.get("APPDATA", ""), "VmPOS"),
        os.path.expanduser("~/.vmpos"),
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
        USER_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "data_usuario"))
else:
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = os.path.abspath(os.path.join(_current_dir, '..'))
    USER_DATA_DIR = BUNDLE_DIR

BASE_DIR = USER_DATA_DIR
DATABASE_DIR = os.path.join(USER_DATA_DIR, 'database')
CONFIG_DIR = os.path.join(USER_DATA_DIR, 'config')
LOGOS_DIR = os.path.join(USER_DATA_DIR, 'assets', 'logos')

try:
    os.makedirs(DATABASE_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(LOGOS_DIR, exist_ok=True)
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


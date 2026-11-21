#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para corregir las importaciones y hacer la aplicación compatible con PyInstaller
"""

import os
import sys

def fix_relative_imports():
    """Corrige las importaciones relativas en todos los archivos Python"""
    
    # Archivos que necesitan corrección
    archivos_corregir = [
        "interface/inicio_sesion.py",
        "interface/menu_inicio.py",
        "interface/pantalla_carga.py",
        "interface/reportes_menu.py",
        "interface/configuracion_menu.py",
        "interface/usuarios_menu.py",
        "interface/inventario_menu.py",
        "interface/clientes_menu.py",
        "interface/gastos_menu.py"
    ]
    
    for archivo in archivos_corregir:
        if os.path.exists(archivo):
            print(f"🔧 Corrigiendo importaciones en {archivo}")
            corregir_archivo(archivo)
        else:
            print(f"⚠️ Archivo no encontrado: {archivo}")

def corregir_archivo(ruta_archivo):
    """Corrige las importaciones en un archivo específico"""
    try:
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
        
        # Correcciones específicas para cada archivo
        if "inicio_sesion.py" in ruta_archivo:
            contenido = corregir_inicio_sesion(contenido)
        elif "menu_inicio.py" in ruta_archivo:
            contenido = corregir_menu_inicio(contenido)
        elif "pantalla_carga.py" in ruta_archivo:
            contenido = corregir_pantalla_carga(contenido)
        elif "reportes_menu.py" in ruta_archivo:
            contenido = corregir_reportes_menu(contenido)
        elif "configuracion_menu.py" in ruta_archivo:
            contenido = corregir_configuracion_menu(contenido)
        
        # Escribir el archivo corregido
        with open(ruta_archivo, 'w', encoding='utf-8') as f:
            f.write(contenido)
        
        print(f"✅ {ruta_archivo} corregido")
        
    except Exception as e:
        print(f"❌ Error al corregir {ruta_archivo}: {e}")

def corregir_inicio_sesion(contenido):
    """Corrige las importaciones en inicio_sesion.py"""
    # Agregar manejo de rutas para PyInstaller
    nuevo_contenido = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: iniciar_sesion.py
Interfaz de inicio de sesión principal para VmPOS.
Actualizado para usar la base de datos de usuarios.
"""

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import sys
import os

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    # Si está ejecutándose como ejecutable
    BASE_DIR = sys._MEIPASS
else:
    # Si está ejecutándose como script
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Agregar directorios al path
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'interface'))
sys.path.insert(0, os.path.join(BASE_DIR, 'modules'))

# Importaciones con manejo de errores
try:
    import menu_inicio
except ImportError as e:
    print(f"Error importando menu_inicio: {e}")
    menu_inicio = None

try:
    from pantalla_carga import mostrar_carga
except ImportError as e:
    print(f"Error importando pantalla_carga: {e}")
    def mostrar_carga(*args, **kwargs):
        print("Pantalla de carga no disponible")

try:
    from usuarios_db import (
        obtener_usuario_por_credenciales, 
        crear_tablas_iniciales,
        inicializar_admin_default
    )
except ImportError as e:
    print(f"Error importando usuarios_db: {e}")
    def obtener_usuario_por_credenciales(usuario, password):
        # Fail-closed: nunca autenticar mediante contraseñas codificadas en fuente
        raise RuntimeError("El módulo usuarios_db no está disponible; autenticación bloqueada por seguridad.")
    
    def crear_tablas_iniciales():
        raise RuntimeError("Función crear_tablas_iniciales no disponible")
    
    def inicializar_admin_default():
        raise RuntimeError("Función inicializar_admin_default deshabilitada; use activación segura.")

''' + contenido[contenido.find('# --- Variables necesarias'):]
    
    return nuevo_contenido

def corregir_menu_inicio(contenido):
    """Corrige las importaciones en menu_inicio.py"""
    # Buscar el inicio de las importaciones
    inicio_imports = contenido.find('import tkinter as tk')
    
    nuevo_inicio = '''import tkinter as tk
from tkinter import ttk
import subprocess
import datetime
from tkinter import messagebox
import sqlite3
import os
import sys

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'interface'))

# Importaciones con manejo de errores
try:
    from pantalla_carga import mostrar_carga
except ImportError as e:
    print(f"Warning: pantalla_carga module not found: {e}")
    def mostrar_carga(*args, **kwargs):
        print("Pantalla de carga no disponible")

try:
    from reportes_menu import iniciar_reportes
except ImportError as e:
    print(f"Warning: reportes_menu module not found: {e}")
    def iniciar_reportes():
        messagebox.showwarning("Módulo no disponible", "El módulo de reportes no está disponible.")

try:
    from clientes_menu import iniciar_clientes
except ImportError as e:
    print(f"Warning: clientes_menu module not found: {e}")
    def iniciar_clientes():
        messagebox.showwarning("Módulo no disponible", "El módulo de clientes no está disponible.")

try:
    from configuracion_menu import iniciar_configuracion
except ImportError as e:
    print(f"Warning: configuracion_menu module not found: {e}")
    def iniciar_configuracion():
        messagebox.showwarning("Módulo no disponible", "El módulo de configuración no está disponible.")

try:
    from usuarios_menu import iniciar_usuarios
except ImportError as e:
    print(f"Warning: usuarios_menu module not found: {e}")
    def iniciar_usuarios():
        messagebox.showwarning("Módulo no disponible", "El módulo de usuarios no está disponible.")

try:
    from inventario_menu import iniciar_inventario
except ImportError as e:
    print(f"Warning: inventario_menu module not found: {e}")
    def iniciar_inventario():
        messagebox.showwarning("Módulo no disponible", "El módulo de inventario no está disponible.")

'''
    
    # Encontrar donde empiezan las definiciones de funciones/clases
    inicio_codigo = contenido.find('# Ruta de la base de datos')
    if inicio_codigo == -1:
        inicio_codigo = contenido.find('base_dir = os.path.dirname')
    
    if inicio_codigo != -1:
        return nuevo_inicio + contenido[inicio_codigo:]
    else:
        return nuevo_inicio + contenido[contenido.find('PERMISOS = {'):]

def corregir_pantalla_carga(contenido):
    """Corrige las importaciones en pantalla_carga.py"""
    nuevo_inicio = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pantalla de carga optimizada para Sistema VM
Archivo: interface/pantalla_carga.py
"""

import tkinter as tk
import math
import threading
import sys
import os

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Importación opcional de pyttsx3 con manejo de errores
try:
    import pyttsx3
    TTS_DISPONIBLE = True
except ImportError:
    print("Warning: pyttsx3 no disponible, la voz estará deshabilitada")
    TTS_DISPONIBLE = False

'''
    
    # Encontrar la función mostrar_carga
    inicio_funcion = contenido.find('def mostrar_carga(')
    if inicio_funcion != -1:
        return nuevo_inicio + contenido[inicio_funcion:]
    else:
        return nuevo_inicio + contenido

def corregir_reportes_menu(contenido):
    """Corrige las importaciones en reportes_menu.py"""
    nuevo_inicio = '''import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import os
import sys
from datetime import datetime, timedelta
import calendar

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Importaciones opcionales con manejo de errores
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    REPORTLAB_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: ReportLab no disponible: {e}")
    REPORTLAB_DISPONIBLE = False

try:
    import pandas as pd
    PANDAS_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: Pandas no disponible: {e}")
    PANDAS_DISPONIBLE = False

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    OPENPYXL_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: OpenPyXL no disponible: {e}")
    OPENPYXL_DISPONIBLE = False

try:
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.dates as mdates
    MATPLOTLIB_DISPONIBLE = True
except ImportError as e:
    print(f"Warning: Matplotlib no disponible: {e}")
    MATPLOTLIB_DISPONIBLE = False

'''
    
    # Encontrar donde empiezan las definiciones
    inicio_codigo = contenido.find('# ⚠️ The path to the database')
    if inicio_codigo == -1:
        inicio_codigo = contenido.find('base_dir = os.path.dirname')
    
    if inicio_codigo != -1:
        return nuevo_inicio + contenido[inicio_codigo:]
    else:
        return nuevo_inicio + contenido

def corregir_configuracion_menu(contenido):
    """Corrige las importaciones en configuracion_menu.py"""
    nuevo_inicio = '''import tkinter as tk
from tkinter import messagebox, filedialog
import os
import shutil
import sqlite3
import sys
from datetime import datetime

# Configuración de rutas para PyInstaller
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Importación opcional de pandas
try:
    import pandas as pd
    PANDAS_DISPONIBLE = True
except ImportError:
    print("Warning: Pandas no disponible, algunas funciones de exportación estarán limitadas")
    PANDAS_DISPONIBLE = False

'''
    
    # Encontrar donde empiezan las definiciones de funciones
    inicio_codigo = contenido.find('def abrir_config(tipo):')
    if inicio_codigo != -1:
        return nuevo_inicio + contenido[inicio_codigo:]
    else:
        return nuevo_inicio + contenido

if __name__ == "__main__":
    print("🔧 Iniciando corrección de importaciones para PyInstaller...")
    fix_relative_imports()
    print("✅ Correcciones completadas")
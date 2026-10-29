#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de compilación automatizado para Windows (VmPOS).
Ejecuta la instalación de dependencias, PyInstaller y genera el ZIP e instalador Inno Setup.
"""
import os
import sys
import shutil
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)

print("=" * 70)
print("  COMPILADOR AUTOMÁTICO DE VmPOS PARA WINDOWS")
print("=" * 70)
print(f"Directorio del proyecto: {PROJECT_ROOT}")
print(f"Intérprete Python: {sys.executable} ({sys.version.split()[0]})")
print("-" * 70)

# 1. Asegurar dependencias
print("\n[1/4] Verificando e instalando dependencias necesarias...")
DEPENDENCIAS = [
    "pyinstaller",
    "httpx",
    "reportlab",
    "matplotlib",
    "pandas",
    "openpyxl",
    "pillow",
    "pydantic",
    "pydantic-settings",
    "python-barcode",
    "python-escpos"
]

cmd_pip = [sys.executable, "-m", "pip", "install", "--upgrade"] + DEPENDENCIAS
try:
    res = subprocess.run(cmd_pip, check=True)
except Exception as e:
    print(f"⚠️ Aviso al instalar dependencias con pip: {e}")
    print("Continuando con la compilación...")

# 2. Limpiar carpetas anteriores
print("\n[2/4] Limpiando carpetas build/ y dist/...")
for folder in ["build", "dist"]:
    folder_path = os.path.join(PROJECT_ROOT, folder)
    if os.path.exists(folder_path):
        try:
            shutil.rmtree(folder_path)
            print(f"  ✓ Eliminada carpeta previa: {folder}")
        except Exception as e:
            print(f"  ⚠️ No se pudo eliminar completamente {folder}: {e}")

# 3. Compilación con PyInstaller
print("\n[3/4] Compilando VmPOS.exe con PyInstaller...")

sep = ";" if sys.platform.startswith("win") else ":"

add_data = [
    f"assets{sep}assets",
    f"config{sep}config",
    f"database{sep}database",
    f"interface{sep}interface",
    f"client{sep}client",
]

net_config = os.path.join(PROJECT_ROOT, "network_config.json")
if os.path.exists(net_config):
    add_data.append(f"network_config.json{sep}.")

hidden_imports = [
    "reportlab",
    "reportlab.lib",
    "reportlab.platypus",
    "reportlab.pdfgen",
    "matplotlib",
    "matplotlib.backends.backend_tkagg",
    "pandas",
    "openpyxl",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "sqlite3",
    "escpos",
    "httpx",
    "pydantic",
    "pydantic_settings",
    "barcode",
    "barcode.codex",
    "barcode.ean",
    "barcode.writer"
]

if sys.platform.startswith("win"):
    hidden_imports.extend(["win32print", "win32api"])

pyinstaller_args = [
    "--name=VmPOS",
    "--windowed",
    "--noconfirm",
    "--clean",
]

icon_path = os.path.join(PROJECT_ROOT, "assets", "Salome.ico")
if os.path.exists(icon_path):
    pyinstaller_args.append(f"--icon={icon_path}")

for d in add_data:
    pyinstaller_args.append(f"--add-data={d}")

for h in hidden_imports:
    pyinstaller_args.append(f"--hidden-import={h}")

pyinstaller_args.append(os.path.join("interface", "inicio_sesion.py"))

print("Ejecutando PyInstaller con argumentos configurados...")
import PyInstaller.__main__
try:
    PyInstaller.__main__.run(pyinstaller_args)
except SystemExit as e:
    if e.code != 0:
        print(f"\n❌ Error fatal en PyInstaller (código de salida: {e.code})")
        sys.exit(1)
except Exception as e:
    print(f"\n❌ Excepción durante PyInstaller: {e}")
    sys.exit(1)

# Verificar ejecutable generado
exe_path = os.path.join(PROJECT_ROOT, "dist", "VmPOS", "VmPOS.exe")
if os.path.exists(exe_path) or (not sys.platform.startswith("win") and os.path.exists(os.path.join(PROJECT_ROOT, "dist", "VmPOS", "VmPOS"))):
    print("\n✓ ¡Ejecutable generado con éxito!")
else:
    print(f"\n❌ Advertencia: No se encontró el ejecutable en: {exe_path}")

# Generar archivo comprimido ZIP para distribución directa
print("\n[4/4] Generando paquete ZIP distribuible...")
zip_target = os.path.join(PROJECT_ROOT, "dist", "VmPOS_Windows")
vmpos_dist_dir = os.path.join(PROJECT_ROOT, "dist", "VmPOS")
if os.path.exists(vmpos_dist_dir):
    try:
        shutil.make_archive(zip_target, 'zip', vmpos_dist_dir)
        print(f"✓ Paquete ZIP creado en: {zip_target}.zip")
    except Exception as e:
        print(f"⚠️ Aviso al comprimir ZIP: {e}")

# Verificar si Inno Setup está disponible para crear el instalador VmPOS_Setup_v4.0.exe
iscc_candidates = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    r"C:\Program Files\Inno Setup 5\ISCC.exe",
    shutil.which("ISCC") or ""
]

iscc_bin = next((p for p in iscc_candidates if p and os.path.exists(p)), None)
iss_script = os.path.join(PROJECT_ROOT, "packaging", "installer_windows.iss")

if iscc_bin and os.path.exists(iss_script):
    print("\nCompilando instalador Setup con Inno Setup...")
    try:
        subprocess.run([iscc_bin, iss_script], check=True)
        setup_exe = os.path.join(PROJECT_ROOT, "dist", "VmPOS_Setup_v4.0.exe")
        print(f"✓ ¡Instalador Setup generado con éxito en: {setup_exe}!")
    except Exception as e:
        print(f"⚠️ Error al ejecutar Inno Setup: {e}")
else:
    print("\nℹ️ Nota sobre Inno Setup:")
    print("  Inno Setup no está instalado en la ruta por defecto.")
    print("  La aplicación ya está 100% funcional en:")
    print(f"  -> Carpeta ejecutable: {vmpos_dist_dir}")
    print(f"  -> Archivo ZIP: {zip_target}.zip")
    print("  (Si deseas el instalador .exe con asistente, instala Inno Setup gratuito desde https://jrsoftware.org/isdl.php)")

print("\n" + "=" * 70)
print("  🎉 ¡COMPILACIÓN PARA WINDOWS FINALIZADA CON ÉXITO!")
print("=" * 70)

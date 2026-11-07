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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    "python-escpos",
    "fastapi",
    "uvicorn",
    "sqlalchemy[asyncio]",
    "greenlet",
    "aiosqlite",
    "asyncpg",
    "python-jose[cryptography]",
    "passlib[bcrypt]",
    "bcrypt==3.2.2",
    "python-multipart",
]

cmd_pip = [sys.executable, "-m", "pip", "install", "--upgrade"] + DEPENDENCIAS
try:
    res = subprocess.run(cmd_pip, check=True)
except Exception as e:
    print(f"[AVISO] Aviso al instalar dependencias con pip: {e}")
    print("Continuando con la compilacion...")

# 1.5 Verificar importación limpia de todos los módulos UI/Cliente/Servidor en un subproceso aislado
print("\n[1.5/4] Verificando importacion de todos los modulos principales...")
MODULOS_VERIFICAR = [
    "interface.config",
    "interface.business_manager",
    "interface.network_manager",
    "interface.network_dialog",
    "interface.receipt_manager",
    "interface.menu_inicio",
    "interface.ventas_menu",
    "interface.caja_menu",
    "interface.clientes_menu",
    "interface.inventario_menu",
    "interface.gastos_menu",
    "interface.nomina_menu",
    "interface.reportes_menu",
    "interface.configuracion_menu",
    "interface.contabilidad_menu",
    "interface.turnos_menu",
    "interface.usuarios_menu",
    "client.api_client",
    "server.main",
]
check_script = (
    "import importlib, os, sys; "
    f"sys.path.insert(0, {PROJECT_ROOT!r}); "
    f"sys.path.insert(0, os.path.join({PROJECT_ROOT!r}, 'interface')); "
    f"[importlib.import_module(m) for m in {MODULOS_VERIFICAR!r}]"
)
res_imp = subprocess.run([sys.executable, "-c", check_script], capture_output=True, text=True)
temp_vmpos_log = os.path.join(PROJECT_ROOT, "vmpos.log")
if os.path.exists(temp_vmpos_log):
    try:
        os.remove(temp_vmpos_log)
    except Exception:
        pass
if res_imp.returncode != 0:
    print(f"\n[ERROR] Fallo al importar modulos principales:\n{res_imp.stderr}\n{res_imp.stdout}")
    sys.exit(res_imp.returncode)
print(f"  [OK] {len(MODULOS_VERIFICAR)} modulos verificados sin errores de importacion ni anotaciones.")

# 2. Limpiar carpetas y ejecutables anteriores sin borrar instaladores DMG/ZIP de macOS
print("\n[2/4] Limpiando carpetas build/ y ejecutables previos...")
build_dir = os.path.join(PROJECT_ROOT, "build")
if os.path.exists(build_dir):
    try:
        shutil.rmtree(build_dir)
        print("  [OK] Eliminada carpeta previa: build")
    except Exception as e:
        print(f"  [AVISO] Aviso build: {e}")

vmpos_dist = os.path.join(PROJECT_ROOT, "dist", "VmPOS")
if os.path.exists(vmpos_dist):
    try:
        shutil.rmtree(vmpos_dist)
        print("  [OK] Eliminada carpeta previa: dist/VmPOS")
    except Exception as e:
        print(f"  [AVISO] Aviso dist/VmPOS: {e}")

# Eliminar spec previo para evitar conflictos de rutas entre macOS y Windows
old_spec = os.path.join(PROJECT_ROOT, "VmPOS.spec")
if os.path.exists(old_spec):
    try:
        os.remove(old_spec)
        print("  [OK] Eliminado archivo de especificacion anterior: VmPOS.spec")
    except Exception as e:
        print(f"  [AVISO] Aviso spec: {e}")

# 3. Compilación con PyInstaller
print("\n[3/4] Compilando VmPOS.exe con PyInstaller...")

sep = ";" if sys.platform.startswith("win") else ":"

add_data = [
    f"assets{sep}assets",
    f"config{sep}config",
    f"database{sep}database",
    f"interface{sep}interface",
    f"client{sep}client",
    f"server{sep}server",
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
    "barcode.writer",
    "babel",
    "babel.numbers",
    "server",
    "server.main",
    "server.config",
    "server.database",
    "server.aiosqlite_compat",
    "server.models.configuracion",
    "server.routers.configuracion",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "anyio",
    "sniffio",
    "h11",
    "greenlet",
    "greenlet._greenlet",
    "sqlalchemy",
    "sqlalchemy.ext.asyncio",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "sqlalchemy.dialects.postgresql.asyncpg",
    "aiosqlite",
    "asyncpg",
    "jose",
    "cryptography",
    "passlib",
    "passlib.handlers.bcrypt",
    "bcrypt",
    "multipart",
]

if sys.platform.startswith("win"):
    hidden_imports.extend(["win32print", "win32api"])

pyinstaller_args = [
    "--name=VmPOS",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--collect-all=escpos",
    "--collect-all=greenlet",
    "--collect-all=bcrypt",
    "--collect-all=aiosqlite",
    "--collect-submodules=server",
    "--collect-submodules=uvicorn",
    "--collect-submodules=fastapi",
    "--collect-submodules=starlette",
    "--collect-submodules=anyio",
    "--collect-submodules=sqlalchemy",
    "--collect-submodules=jose",
    "--collect-submodules=passlib",
]

icon_path = os.path.join(PROJECT_ROOT, "assets", "Salome.ico")
if os.path.exists(icon_path):
    pyinstaller_args.append(f"--icon={icon_path}")

for d in add_data:
    pyinstaller_args.append(f"--add-data={d}")

for h in hidden_imports:
    pyinstaller_args.append(f"--hidden-import={h}")

pyinstaller_args.append(os.path.join("interface", "inicio_sesion.py"))

pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"] + pyinstaller_args

print("Ejecutando PyInstaller...")
try:
    subprocess.run(pyinstaller_cmd, check=True)
except subprocess.CalledProcessError as e:
    print(f"\n[ERROR] Error fatal en PyInstaller (codigo de salida: {e.returncode})")
    sys.exit(e.returncode)
except Exception as e:
    print(f"\n[ERROR] Excepcion durante PyInstaller: {e}")
    sys.exit(1)

# Verificar ejecutable generado y realizar prueba real de humo del servidor empaquetado
exe_path = os.path.join(PROJECT_ROOT, "dist", "VmPOS", "VmPOS.exe")
bin_test_path = exe_path if sys.platform.startswith("win") else os.path.join(PROJECT_ROOT, "dist", "VmPOS", "VmPOS")
if os.path.exists(bin_test_path):
    print("\n[OK] Ejecutable generado con exito!")
    print("\n[3.5/4] Ejecutando prueba real de arranque del servidor empaquetado (--run-server)...")
    import time
    import urllib.request
    smoke_log = os.path.join(PROJECT_ROOT, "build", "smoke_server.log")
    os.makedirs(os.path.dirname(smoke_log), exist_ok=True)
    with open(smoke_log, "w", encoding="utf-8") as sf:
        proc_test = subprocess.Popen(
            [bin_test_path, "--run-server", "--host", "127.0.0.1", "--port", "18089"],
            stdout=sf,
            stderr=sf,
        )
    salud_ok = False
    for _ in range(25):
        time.sleep(0.4)
        if proc_test.poll() is not None:
            break
        try:
            with urllib.request.urlopen("http://127.0.0.1:18089/api/health", timeout=1.0) as resp:
                if resp.getcode() == 200:
                    body = resp.read().decode("utf-8", errors="replace")
                    print(f"  [OK] /api/health respondio 200 OK: {body}")
                    salud_ok = True
                    break
        except Exception:
            pass
    try:
        proc_test.terminate()
        proc_test.wait(timeout=3)
    except Exception:
        try:
            proc_test.kill()
        except Exception:
            pass
    if not salud_ok:
        print("\n[ERROR] El servidor empaquetado fallo en la prueba de arranque (--run-server)!")
        if os.path.exists(smoke_log):
            with open(smoke_log, "r", encoding="utf-8", errors="replace") as sf_in:
                print(sf_in.read())
        sys.exit(1)
else:
    print(f"\n[ERROR] No se encontro el ejecutable en: {bin_test_path}")
    sys.exit(1)

# Generar archivo comprimido ZIP para distribución directa
print("\n[4/4] Generando paquete ZIP distribuible...")
zip_target = os.path.join(PROJECT_ROOT, "dist", "VmPOS_Windows")
vmpos_dist_dir = os.path.join(PROJECT_ROOT, "dist", "VmPOS")
if os.path.exists(vmpos_dist_dir):
    try:
        shutil.make_archive(zip_target, 'zip', vmpos_dist_dir)
        print(f"[OK] Paquete ZIP creado en: {zip_target}.zip")
    except Exception as e:
        print(f"[AVISO] Error al comprimir ZIP: {e}")

# Verificar si Inno Setup está disponible para crear el instalador VmPOS_Setup_v4.0.exe
iscc_candidates = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
    r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    r"C:\Program Files\Inno Setup 5\ISCC.exe",
    r"C:\tools\InnoSetup\ISCC.exe",
    r"C:\ProgramData\chocolatey\bin\iscc.exe",
    r"C:\ProgramData\chocolatey\lib\innosetup\tools\ISCC.exe",
    shutil.which("ISCC") or "",
    shutil.which("iscc") or "",
]

iscc_bin = next((p for p in iscc_candidates if p and os.path.exists(p)), None)
iss_script = os.path.join(PROJECT_ROOT, "packaging", "installer_windows.iss")

if iscc_bin and os.path.exists(iss_script):
    print(f"\nCompilando instalador Setup con Inno Setup ({iscc_bin})...")
    try:
        subprocess.run(f'"{iscc_bin}" "{iss_script}"', shell=True, check=True)
        setup_exe = os.path.join(PROJECT_ROOT, "dist", "VmPOS_Setup_v4.0.exe")
        print(f"[OK] Instalador Setup generado con exito en: {setup_exe}!")
    except Exception as e:
        print(f"[AVISO] Error al ejecutar Inno Setup: {e}")
else:
    print("\n[INFO] Nota sobre Inno Setup:")
    print("  Inno Setup no esta instalado en la ruta por defecto.")
    print("  La aplicacion ya esta 100% funcional en:")
    print(f"  -> Carpeta ejecutable: {vmpos_dist_dir}")
    print(f"  -> Archivo ZIP: {zip_target}.zip")

print("\n" + "=" * 70)
print("  [EXITO] COMPILACION PARA WINDOWS FINALIZADA CON EXITO!")
print("=" * 70)

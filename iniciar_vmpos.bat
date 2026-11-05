@echo off
chcp 65001 >nul 2>&1
title VmPOS - Sistema Punto de Venta
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0interface"

echo ==============================================================================
echo                      VmPOS - PUNTO DE VENTA Y SERVIDOR
echo ==============================================================================
echo.

REM 1. Detección exhaustiva del intérprete Python
set "PY_EXE="

if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0venv\Scripts\python.exe"
    goto :python_listo
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
    goto :python_listo
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_EXE=py -3"
    goto :python_listo
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_EXE=python"
    goto :python_listo
)

for %%V in (313 312 311 310 39) do (
    if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
        set "PY_EXE=%LocalAppData%\Programs\Python\Python%%V\python.exe"
        goto :python_listo
    )
    if exist "C:\Python%%V\python.exe" (
        set "PY_EXE=C:\Python%%V\python.exe"
        goto :python_listo
    )
    if exist "C:\Program Files\Python%%V\python.exe" (
        set "PY_EXE=C:\Program Files\Python%%V\python.exe"
        goto :python_listo
    )
)

:python_no_encontrado
echo.
echo ==============================================================================
echo  ❌ ERROR: No se encontró Python instalado en este computador.
echo ==============================================================================
echo.
echo  Para ejecutar VmPOS necesitas tener Python instalado:
echo.
echo  1. Descarga Python gratis desde la página oficial:
echo     https://www.python.org/downloads/
echo.
echo  2. ⚠️ MUY IMPORTANTE al instalar:
echo     Marca la casilla: [X] "Add python.exe to PATH"
echo.
echo  3. Una vez instalado, vuelve a hacer doble clic en este archivo.
echo ==============================================================================
echo.
pause
exit /b 1

:python_listo
echo [OK] Python detectado: %PY_EXE%

REM 2. Verificar si las librerías necesarias están instaladas
"%PY_EXE%" -c "import httpx, PIL, reportlab, pandas" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ⚙️ Detectamos que faltan componentes para ejecutar VmPOS.
    echo 📦 Instalando componentes necesarios automáticamente (esto solo se hace una vez)...
    echo.
    "%PY_EXE%" -m pip install --upgrade pip
    "%PY_EXE%" -m pip install httpx Pillow reportlab matplotlib pandas openpyxl pydantic pydantic-settings python-barcode python-escpos uvicorn fastapi sqlalchemy
    echo.
    echo ✅ Componentes instalados con éxito.
    echo.
)

REM 3. Lanzar VmPOS
echo [OK] Iniciando VmPOS Punto de Venta...
echo.
"%PY_EXE%" interface\inicio_sesion.py

if %errorlevel% neq 0 (
    echo.
    echo ==============================================================================
    echo  ⚠️ AVISO: La aplicación se cerró con código de error (%errorlevel%).
    echo  Si ves un error arriba, tómale una foto para ayudarte a solucionarlo.
    echo ==============================================================================
    echo.
    pause
)

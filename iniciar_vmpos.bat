@echo off
title VmPOS - Sistema Punto de Venta
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0interface"

echo ==============================================================================
echo                      VmPOS - PUNTO DE VENTA Y SERVIDOR
echo ==============================================================================
echo.

set "PY_EXE=python"
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_EXE=py -3"
    ) else (
        echo [ERROR] No se encontro Python en este equipo.
        echo Por favor instala Python marcando la casilla Add python.exe to PATH.
        echo.
        pause
        exit /b 1
    )
)

echo [OK] Python detectado correctamente: %PY_EXE%
echo.

REM Verificar componentes necesarios
%PY_EXE% -c "import httpx, PIL, reportlab, pandas" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Instalando componentes necesarios en Windows (solo la primera vez)...
    %PY_EXE% -m pip install --upgrade pip
    %PY_EXE% -m pip install httpx Pillow reportlab matplotlib pandas openpyxl pydantic pydantic-settings python-barcode python-escpos uvicorn fastapi sqlalchemy
    echo.
    echo [OK] Componentes instalados con exito.
    echo.
)

echo [OK] Iniciando VmPOS Punto de Venta...
echo.
%PY_EXE% interface\inicio_sesion.py

if %errorlevel% neq 0 (
    echo.
    echo ==============================================================================
    echo  [AVISO] La aplicacion se cerro con codigo de error (%errorlevel%).
    echo ==============================================================================
    echo.
    pause
)
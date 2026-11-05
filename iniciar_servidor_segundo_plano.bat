@echo off
title VmPOS - Servidor Central
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0interface"

echo ==============================================================================
echo                 VmPOS - SERVIDOR CENTRAL (BASE DE DATOS Y RED)
echo ==============================================================================
echo.

set "PY_BIN=python"
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_BIN=py -3"
    ) else (
        echo [ERROR] No se encontro Python instalado.
        pause
        exit /b 1
    )
)

echo [OK] Python detectado: %PY_BIN%

REM Regla de Firewall
netsh advfirewall firewall show rule name="VmPOS Server 8000" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="VmPOS Server 8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
)

%PY_BIN% -c "import uvicorn, fastapi, sqlalchemy" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Instalando librerias del servidor...
    %PY_BIN% -m pip install uvicorn fastapi sqlalchemy asyncpg httpx pydantic pydantic-settings
)

echo [OK] Levantando Servidor VmPOS en 0.0.0.0:8000...
echo Presiona Ctrl+C para detener el servidor.
echo.
%PY_BIN% -m uvicorn server.main:app --host 0.0.0.0 --port 8000

if %errorlevel% neq 0 (
    echo.
    echo [AVISO] El servidor se detuvo con codigo %errorlevel%.
    pause
)
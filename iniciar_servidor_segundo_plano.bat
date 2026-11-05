@echo off
REM ==============================================================================
REM  VmPOS - Lanzador de Servidor Central en Segundo Plano
REM  Inicia FastAPI / Uvicorn en 0.0.0.0:8000 y habilita regla en Firewall de Windows
REM ==============================================================================
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0interface"

REM 1. Verificar / Crear regla en el Firewall de Windows para el puerto 8000
netsh advfirewall firewall show rule name="VmPOS Server 8000" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="VmPOS Server 8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
)

REM 2. Seleccionar interprete Python disponible
set "PY_BIN=python"
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_BIN=%~dp0venv\Scripts\python.exe"
    goto :ejecutar
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_BIN=%~dp0.venv\Scripts\python.exe"
    goto :ejecutar
)
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_BIN=python"
    goto :ejecutar
)
where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_BIN=py -3"
    goto :ejecutar
)

:ejecutar
"%PY_BIN%" -m uvicorn server.main:app --host 0.0.0.0 --port 8000

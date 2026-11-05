@echo off
chcp 65001 >nul 2>&1
title VmPOS - Servidor Central
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0interface"

echo ==============================================================================
echo                 VmPOS - SERVIDOR CENTRAL (BASE DE DATOS Y RED)
echo ==============================================================================
echo.

REM 1. Detección exhaustiva del intérprete Python
set "PY_BIN="

if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_BIN=%~dp0venv\Scripts\python.exe"
    goto :python_listo
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_BIN=%~dp0.venv\Scripts\python.exe"
    goto :python_listo
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_BIN=py -3"
    goto :python_listo
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_BIN=python"
    goto :python_listo
)

for %%V in (313 312 311 310 39) do (
    if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
        set "PY_BIN=%LocalAppData%\Programs\Python\Python%%V\python.exe"
        goto :python_listo
    )
    if exist "C:\Python%%V\python.exe" (
        set "PY_BIN=C:\Python%%V\python.exe"
        goto :python_listo
    )
    if exist "C:\Program Files\Python%%V\python.exe" (
        set "PY_BIN=C:\Program Files\Python%%V\python.exe"
        goto :python_listo
    )
)

:python_no_encontrado
echo.
echo ❌ ERROR: No se encontró Python instalado en este equipo.
echo Instala Python desde https://www.python.org/downloads/
echo y marca [X] "Add python.exe to PATH".
echo.
pause
exit /b 1

:python_listo
echo [OK] Python detectado: %PY_BIN%

REM 2. Habilitar regla de Firewall
netsh advfirewall firewall show rule name="VmPOS Server 8000" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="VmPOS Server 8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
)

REM 3. Verificar si uvicorn y fastapi están instalados
"%PY_BIN%" -c "import uvicorn, fastapi, sqlalchemy" >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ⚙️ Instalando dependencias del servidor (FastAPI, Uvicorn, SQLAlchemy)...
    "%PY_BIN%" -m pip install uvicorn fastapi sqlalchemy asyncpg httpx pydantic pydantic-settings
    echo.
)

REM 4. Iniciar Servidor
echo [OK] Levantando Servidor VmPOS en 0.0.0.0:8000...
echo Presiona Ctrl+C para detener el servidor.
echo.
"%PY_BIN%" -m uvicorn server.main:app --host 0.0.0.0 --port 8000

if %errorlevel% neq 0 (
    echo.
    echo ==============================================================================
    echo  ⚠️ El servidor se detuvo con código %errorlevel%.
    echo ==============================================================================
    echo.
    pause
)

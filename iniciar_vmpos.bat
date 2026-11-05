@echo off
title VmPOS - Sistema Punto de Venta
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0interface"

REM 1. Deteccion de interprete Python (priorizando venv si existe)
set "PY_EXE="
if exist "%~dp0venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0venv\Scripts\python.exe"
    goto :lanzar
)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0.venv\Scripts\python.exe"
    goto :lanzar
)
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_EXE=python"
    goto :lanzar
)
where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_EXE=py -3"
    goto :lanzar
)

echo ==============================================================================
echo  ERROR: No se encontro Python en este equipo.
echo  Instala Python desde https://www.python.org/downloads/
echo  y marca la casilla [X] "Add python.exe to PATH".
echo ==============================================================================
pause
exit /b 1

:lanzar
"%PY_EXE%" interface\inicio_sesion.py
:fin

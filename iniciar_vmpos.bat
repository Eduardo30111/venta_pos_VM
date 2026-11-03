@echo off
title VmPOS - Sistema Punto de Venta
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0interface"

REM Verificar interprete Python
where python >nul 2>&1
if %errorlevel% equ 0 (
    python interface\inicio_sesion.py
    goto :fin
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py -3 interface\inicio_sesion.py
    goto :fin
)

echo ==============================================================================
echo  ERROR: No se encontro Python en este equipo.
echo  Instala Python desde https://www.python.org/downloads/
echo  y marca la casilla [X] "Add python.exe to PATH".
echo ==============================================================================
pause

:fin

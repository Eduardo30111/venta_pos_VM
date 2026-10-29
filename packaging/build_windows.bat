@echo off
REM ==============================================================================
REM Script: packaging\build_windows.bat
REM Compilador de VmPOS para Windows (Compatible con Windows 10 y 11)
REM ==============================================================================

chcp 65001 >nul 2>&1
title Compilador VmPOS - Windows

echo ==============================================================================
echo                 INICIANDO COMPILACION DE VmPOS PARA WINDOWS
echo ==============================================================================
echo.

set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"

REM 1. Deteccion del interprete Python
set "PYTHON_EXE="

where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
    goto :python_encontrado
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=py -3"
    goto :python_encontrado
)

REM Busqueda en rutas estandar de instalacion de Windows
for %%V in (313 312 311 310 39) do (
    if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" (
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python%%V\python.exe"
        goto :python_encontrado
    )
    if exist "C:\Python%%V\python.exe" (
        set "PYTHON_EXE=C:\Python%%V\python.exe"
        goto :python_encontrado
    )
    if exist "C:\Program Files\Python%%V\python.exe" (
        set "PYTHON_EXE=C:\Program Files\Python%%V\python.exe"
        goto :python_encontrado
    )
)

:python_no_encontrado
echo.
echo ==============================================================================
echo  ERROR: NO SE ENCONTRO PYTHON EN ESTE COMPUTADOR
echo ==============================================================================
echo.
echo  Para compilar VmPOS en Windows necesitas tener Python instalado:
echo.
echo  1. Descarga Python desde la pagina oficial:
echo     https://www.python.org/downloads/
echo.
echo  2. IMPORTANTE: Durante la instalacion, asegurate de MARCAR la casilla:
echo     [X] "Add python.exe to PATH" (Agregar Python al PATH).
echo.
echo  3. Una vez instalado, vuelve a ejecutar este archivo build_windows.bat.
echo.
echo ==============================================================================
echo.
pause
exit /b 1

:python_encontrado
echo [OK] Interprete Python detectado: %PYTHON_EXE%
echo [OK] Directorio de trabajo: %PROJECT_ROOT%
echo.

%PYTHON_EXE% "%~dp0build_windows.py"

if %errorlevel% neq 0 (
    echo.
    echo ==============================================================================
    echo  ERROR: La compilacion finalizo con errores.
    echo  Revisa los mensajes anteriores para identificar la causa.
    echo ==============================================================================
    echo.
    pause
    exit /b 1
)

echo.
echo ==============================================================================
echo  PROCESO COMPLETADO EXITOSAMENTE.
echo  Los archivos generados se encuentran en la carpeta 'dist\'.
echo ==============================================================================
echo.
pause
exit /b 0

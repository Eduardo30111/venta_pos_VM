@echo off
chcp 65001 >nul 2>&1
title VmPOS - Sistema de Punto de Venta
cd /d "%~dp0"
echo ==============================================================================
echo                      INICIANDO VmPOS (MODO WINDOWS)
echo ==============================================================================
echo.
echo Verificando dependencias necesarias...
python -m pip install httpx Pillow reportlab matplotlib pandas openpyxl pydantic pydantic-settings python-barcode python-escpos uvicorn fastapi sqlalchemy aiosqlite greenlet
echo.
echo [OK] Dependencias listas.
echo Iniciando interfaz de VmPOS...
python interface\inicio_sesion.py
if %errorlevel% neq 0 (
    echo.
    echo Ocurrio un error al ejecutar VmPOS.
    pause
)

@echo off
cd /d "%~dp0"
echo Instalando dependencias necesarias...
python -m pip install httpx Pillow reportlab matplotlib pandas openpyxl pydantic pydantic-settings python-barcode python-escpos uvicorn fastapi sqlalchemy
echo.
echo Iniciando VmPOS...
python interface\inicio_sesion.py
pause
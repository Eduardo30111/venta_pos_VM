@echo off
cd /d "%~dp0"
echo Instalando dependencias del servidor...
python -m pip install uvicorn fastapi sqlalchemy asyncpg httpx pydantic pydantic-settings
echo.
echo Iniciando Servidor VmPOS en el puerto 8000...
python -m uvicorn server.main:app --host 0.0.0.0 --port 8000
pause
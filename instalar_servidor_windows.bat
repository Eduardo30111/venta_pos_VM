@echo off
chcp 65001 >nul
title VmPOS - Instalador y Configurador del Servidor Windows
cls

echo ==============================================================================
echo                 VmPOS - INSTALADOR DEL SERVIDOR EN WINDOWS
echo ==============================================================================
echo.
echo Este asistente te ayudará a configurar la computadora del Administrador
echo como SERVIDOR CENTRAL de VmPOS para compartir base de datos con las demás cajas.
echo.
echo Selecciona la opción que prefieras:
echo.
echo  [1] INICIAR CON DOCKER (Recomendado si tienes Docker Desktop instalado)
echo      - Levanta PostgreSQL y la API FastAPI de inmediato.
echo      - Inicio automático garantizado.
echo.
echo  [2] INSTALAR SERVIDOR NATIVO CON PYTHON (Sin Docker)
echo      - Instala las librerías necesarias de Python.
echo      - Configura el Firewall de Windows para el puerto 8000.
echo.
echo  [3] CONFIGURAR INICIO AUTOMÁTICO AL ENCENDER WINDOWS
echo      - Hace que el servidor arranque solo en segundo plano al prender la PC.
echo.
echo  [4] INICIAR SERVIDOR AHORA (Modo manual en segundo plano)
echo.
echo  [5] Salir
echo.
echo ==============================================================================
set /p opcion="Elige una opción (1-5): "

if "%opcion%"=="1" goto :docker_setup
if "%opcion%"=="2" goto :python_setup
if "%opcion%"=="3" goto :startup_setup
if "%opcion%"=="4" goto :start_now
if "%opcion%"=="5" goto :salir

echo Opción no válida.
pause
exit /b

:docker_setup
cls
echo [1/3] Verificando Docker Desktop...
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ❌ No se detectó Docker en este equipo.
    echo    Por favor descarga e instala Docker Desktop desde:
    echo    https://www.docker.com/products/docker-desktop/
    echo    O elige la opción 2 para instalar con Python nativo.
    echo.
    pause
    exit /b
)

echo [2/3] Levantando contenedores de base de datos y API VmPOS...
cd /d "%~dp0"
docker compose up -d
if %errorlevel% equ 0 (
    echo.
    echo ✅ ¡Servidor VmPOS y PostgreSQL levantados exitosamente con Docker!
    echo    Puerto de escucha: 8000
    echo    Las demás cajas ya pueden conectarse a la IP de esta máquina.
) else (
    echo.
    echo ⚠️ Hubo un detalle levantando Docker. Verifica que Docker Desktop esté abierto.
)
echo.
pause
exit /b

:python_setup
cls
echo [1/3] Verificando Python...
set "PY_CMD=python"
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=py -3"
    ) else (
        echo.
        echo ❌ No se detectó Python instalado en Windows.
        echo    Por favor descarga e instala Python (versión 3.10 o superior)
        echo    marcando la casilla 'Add python.exe to PATH':
        echo    https://www.python.org/downloads/
        echo.
        pause
        exit /b
    )
)

echo ✅ Python detectado.
echo.
echo [2/3] Instalando dependencias del servidor FastAPI y base de datos...
cd /d "%~dp0"
%PY_CMD% -m pip install --upgrade pip
%PY_CMD% -m pip install -r server\requirements.txt

echo.
echo [3/3] Abriendo puerto 8000 en el Firewall de Windows...
netsh advfirewall firewall show rule name="VmPOS Server 8000" >nul 2>&1
if %errorlevel% neq 0 (
    netsh advfirewall firewall add rule name="VmPOS Server 8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
    echo ✅ Regla de Firewall creada para el puerto 8000.
) else (
    echo ✅ Regla de Firewall ya existía.
)

echo.
echo ==============================================================================
echo  ✅ Instalación de dependencias completada.
echo  Recuerda tener instalado PostgreSQL o configurada la base de datos en .env
echo ==============================================================================
echo.
pause
exit /b

:startup_setup
cls
echo Configurando inicio automático con Windows...
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_VBS=%~dp0iniciar_servidor_silencioso.vbs"

if not exist "%TARGET_VBS%" (
    echo ❌ No se encontró el archivo iniciar_servidor_silencioso.vbs en %~dp0
    pause
    exit /b
)

set "SHORTCUT=%STARTUP_FOLDER%\VmPOS_Servidor_Auto.lnk"
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%TARGET_VBS%'; $s.WorkingDirectory = '%~dp0'; $s.Save()"

if exist "%SHORTCUT%" (
    echo.
    echo ✅ ¡Acceso directo de inicio automático creado con éxito!
    echo    Ruta: %SHORTCUT%
    echo.
    echo A partir de ahora, cada vez que enciendas la computadora del Administrador,
    echo el servidor VmPOS arrancará automáticamente en segundo plano en el puerto 8000.
) else (
    echo ⚠️ No se pudo crear el acceso directo automáticamente.
    echo Puedes copiar manualmente iniciar_servidor_silencioso.vbs a la carpeta:
    echo %STARTUP_FOLDER%
)
echo.
pause
exit /b

:start_now
cls
echo Iniciando servidor en segundo plano...
cd /d "%~dp0"
start "" wscript.exe "iniciar_servidor_silencioso.vbs"
echo.
echo ✅ Servidor lanzado en segundo plano sin consola negra.
echo Comprueba el estado abriendo VmPOS en 'Configuración de Red y Servidor'.
echo.
pause
exit /b

:salir
exit /b

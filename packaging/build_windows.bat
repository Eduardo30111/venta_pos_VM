@echo off
REM ==============================================================================
REM Script: packaging/build_windows.bat
REM Compila VmPOS en un ejecutable de Windows y genera el instalador Setup (.exe)
REM ==============================================================================
chcp 65001 >nul
echo ==================================================================
echo 🚀 INICIANDO EMPAQUETADO DE VmPOS PARA WINDOWS
echo ==================================================================

cd /d "%~dp0\.."

echo 1. Instalando dependencias necesarias...
pip install --upgrade pip
pip install pyinstaller httpx reportlab matplotlib pandas openpyxl pillow pydantic pydantic-settings python-escpos python-barcode

echo 2. Limpiando compilaciones anteriores...
if exist build rd /s /q build
if exist dist rd /s /q dist

echo 3. Compilando aplicacion con PyInstaller...
pyinstaller --noconfirm --clean --windowed ^
    --name="VmPOS" ^
    --icon="assets\Salome.ico" ^
    --add-data="assets;assets" ^
    --add-data="config;config" ^
    --add-data="database;database" ^
    --add-data="interface;interface" ^
    --add-data="client;client" ^
    --add-data="network_config.json;." ^
    --hidden-import="reportlab" ^
    --hidden-import="reportlab.lib" ^
    --hidden-import="reportlab.platypus" ^
    --hidden-import="reportlab.pdfgen" ^
    --hidden-import="matplotlib" ^
    --hidden-import="matplotlib.backends.backend_tkagg" ^
    --hidden-import="pandas" ^
    --hidden-import="openpyxl" ^
    --hidden-import="PIL" ^
    --hidden-import="PIL.Image" ^
    --hidden-import="PIL.ImageTk" ^
    --hidden-import="sqlite3" ^
    --hidden-import="escpos" ^
    --hidden-import="win32print" ^
    --hidden-import="win32api" ^
    --hidden-import="httpx" ^
    --hidden-import="pydantic" ^
    --hidden-import="pydantic_settings" ^
    --hidden-import="barcode" ^
    --hidden-import="barcode.codex" ^
    --hidden-import="barcode.ean" ^
    --hidden-import="barcode.writer" ^
    interface\inicio_sesion.py

if errorlevel 1 (
    echo ❌ Error durante la compilacion de PyInstaller.
    pause
    exit /b 1
)

echo ✅ Compilacion exitosa. Carpeta generada en dist\VmPOS\
echo Generando archivo distribuible dist\VmPOS_Windows.zip...
powershell -Command "Compress-Archive -Path 'dist\VmPOS' -DestinationPath 'dist\VmPOS_Windows.zip' -Force" 2>nul
echo ✅ Archivo ZIP generado en dist\VmPOS_Windows.zip

echo 4. Verificando si Inno Setup esta instalado para generar el instalador Setup.exe...
set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC_PATH%" (
    set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if exist "%ISCC_PATH%" (
    echo Generando Instalador Setup con Inno Setup...
    "%ISCC_PATH%" packaging\installer_windows.iss
    echo ✅ Instalador generado en dist\VmPOS_Setup_v4.0.exe
) else (
    echo ℹ️ Inno Setup no esta instalado en la ruta por defecto.
    echo Puedes descargar Inno Setup gratuito desde https://jrsoftware.org/isdl.php
    echo O simplemente distribuir la carpeta dist\VmPOS\ comprimida en un archivo .ZIP.
)

echo ==================================================================
echo 🎉 ¡PROCESO DE WINDOWS FINALIZADO!
echo ==================================================================
pause

#!/usr/bin/env bash
# ==============================================================================
# Script: packaging/build_macos.sh
# Compila VmPOS en un paquete de aplicación macOS (.app) y genera el instalador .dmg
# ==============================================================================
set -e

if [ -d "/Library/Developer/CommandLineTools" ]; then
    export DEVELOPER_DIR="/Library/Developer/CommandLineTools"
fi

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=================================================================="
echo "🚀 INICIANDO EMPAQUETADO DE VmPOS PARA macOS"
echo "=================================================================="

# 1. Asegurar entorno virtual y dependencias compatibles con macOS (Tk >= 9.0)
if [ -x "/Users/eduardosanchez/miniconda3/bin/python3" ]; then
    PYTHON_BIN="/Users/eduardosanchez/miniconda3/bin/python3"
elif [ -x "$HOME/miniconda3/bin/python3" ]; then
    PYTHON_BIN="$HOME/miniconda3/bin/python3"
elif [ -x "/opt/homebrew/bin/python3" ]; then
    PYTHON_BIN="/opt/homebrew/bin/python3"
elif [ -x "/usr/local/bin/python3" ]; then
    PYTHON_BIN="/usr/local/bin/python3"
elif [ -f "./venv/bin/python" ]; then
    PYTHON_BIN="./venv/bin/python"
else
    PYTHON_BIN="python3"
fi

echo "Usando intérprete Python: $PYTHON_BIN"
$PYTHON_BIN -c "import tkinter, sys; print(f'Intérprete: Python {sys.version.split()[0]} | TkVersion: {tkinter.TkVersion} (Tcl: {tkinter.TclVersion})')"

export PYINSTALLER_CONFIG_DIR="$PROJECT_ROOT/build/pyinstaller_cache"
export MPLCONFIGDIR="$PROJECT_ROOT/build/matplotlib_cache"
mkdir -p "$PYINSTALLER_CONFIG_DIR" "$MPLCONFIGDIR"

echo "Verificando dependencias de compilación..."
$PYTHON_BIN -m pip install --quiet pyinstaller pillow reportlab matplotlib pandas openpyxl httpx pydantic pydantic_settings python-barcode babel python-escpos pyusb fastapi uvicorn "sqlalchemy[asyncio]" greenlet aiosqlite asyncpg "python-jose[cryptography]" "passlib[bcrypt]" "bcrypt==3.2.2" python-multipart

# 2. Generar archivo .icns si no existe
ICNS_PATH="$PROJECT_ROOT/assets/Salome.icns"
PNG_ICON="$PROJECT_ROOT/assets/Icono_salome.png"

if [ ! -f "$ICNS_PATH" ] && [ -f "$PNG_ICON" ]; then
    echo "Generando icono macOS (.icns)..."
    ICONSET_DIR="$PROJECT_ROOT/build/VmPOS.iconset"
    rm -rf "$ICONSET_DIR"
    mkdir -p "$ICONSET_DIR"

    sips -z 16 16     "$PNG_ICON" --out "$ICONSET_DIR/icon_16x16.png" > /dev/null 2>&1 || true
    sips -z 32 32     "$PNG_ICON" --out "$ICONSET_DIR/icon_16x16@2x.png" > /dev/null 2>&1 || true
    sips -z 32 32     "$PNG_ICON" --out "$ICONSET_DIR/icon_32x32.png" > /dev/null 2>&1 || true
    sips -z 64 64     "$PNG_ICON" --out "$ICONSET_DIR/icon_32x32@2x.png" > /dev/null 2>&1 || true
    sips -z 128 128   "$PNG_ICON" --out "$ICONSET_DIR/icon_128x128.png" > /dev/null 2>&1 || true
    sips -z 256 256   "$PNG_ICON" --out "$ICONSET_DIR/icon_128x128@2x.png" > /dev/null 2>&1 || true
    sips -z 256 256   "$PNG_ICON" --out "$ICONSET_DIR/icon_256x256.png" > /dev/null 2>&1 || true
    sips -z 512 512   "$PNG_ICON" --out "$ICONSET_DIR/icon_256x256@2x.png" > /dev/null 2>&1 || true
    sips -z 512 512   "$PNG_ICON" --out "$ICONSET_DIR/icon_512x512.png" > /dev/null 2>&1 || true
    sips -z 1024 1024 "$PNG_ICON" --out "$ICONSET_DIR/icon_512x512@2x.png" > /dev/null 2>&1 || true

    if command -v iconutil > /dev/null 2>&1; then
        iconutil -c icns "$ICONSET_DIR" -o "$ICNS_PATH" || true
    fi
    rm -rf "$ICONSET_DIR"
fi

# 3. Limpiar compilaciones previas
echo "Limpiando carpetas build/ y dist/..."
rm -rf build dist

# 4. Compilar con PyInstaller
echo "Compilando VmPOS.app con PyInstaller..."

ICON_FLAG=""
if [ -f "$ICNS_PATH" ]; then
    ICON_FLAG="--icon=$ICNS_PATH"
fi

NETWORK_DATA_FLAG=""
if [ -f "network_config.json" ]; then
    NETWORK_DATA_FLAG="--add-data=network_config.json:."
fi

$PYTHON_BIN -m PyInstaller \
    --name="VmPOS" \
    --windowed \
    --noconfirm \
    $ICON_FLAG \
    --add-data="assets:assets" \
    --add-data="config:config" \
    --add-data="database:database" \
    --add-data="interface:interface" \
    --add-data="client:client" \
    --add-data="server:server" \
    $NETWORK_DATA_FLAG \
    --collect-all="escpos" \
    --collect-all="greenlet" \
    --collect-all="bcrypt" \
    --collect-all="aiosqlite" \
    --collect-submodules="server" \
    --collect-submodules="uvicorn" \
    --collect-submodules="fastapi" \
    --collect-submodules="starlette" \
    --collect-submodules="anyio" \
    --collect-submodules="sqlalchemy" \
    --collect-submodules="jose" \
    --collect-submodules="passlib" \
    --hidden-import="fastapi" \
    --hidden-import="uvicorn" \
    --hidden-import="greenlet" \
    --hidden-import="greenlet._greenlet" \
    --hidden-import="sqlalchemy" \
    --hidden-import="sqlalchemy.ext.asyncio" \
    --hidden-import="sqlalchemy.dialects.sqlite.aiosqlite" \
    --hidden-import="sqlalchemy.dialects.postgresql.asyncpg" \
    --hidden-import="aiosqlite" \
    --hidden-import="asyncpg" \
    --hidden-import="jose" \
    --hidden-import="passlib.handlers.bcrypt" \
    --hidden-import="bcrypt" \
    --hidden-import="multipart" \
    --hidden-import="reportlab" \
    --hidden-import="reportlab.lib" \
    --hidden-import="reportlab.platypus" \
    --hidden-import="reportlab.pdfgen" \
    --hidden-import="matplotlib" \
    --hidden-import="matplotlib.backends.backend_tkagg" \
    --hidden-import="pandas" \
    --hidden-import="openpyxl" \
    --hidden-import="PIL" \
    --hidden-import="PIL.Image" \
    --hidden-import="PIL.ImageTk" \
    --hidden-import="sqlite3" \
    --hidden-import="escpos" \
    --hidden-import="usb" \
    --hidden-import="httpx" \
    --hidden-import="pydantic" \
    --hidden-import="pydantic_settings" \
    --hidden-import="barcode" \
    --hidden-import="barcode.codex" \
    --hidden-import="barcode.ean" \
    --hidden-import="barcode.writer" \
    --hidden-import="babel" \
    --hidden-import="babel.numbers" \
    interface/inicio_sesion.py

# Ajustar Info.plist para alta resolución Retina y forzar apariencia Aqua (evita texto blanco invisible en Dark Mode)
if [ -f "dist/VmPOS.app/Contents/Info.plist" ] && command -v plutil > /dev/null 2>&1; then
    plutil -replace NSHighResolutionCapable -bool true "dist/VmPOS.app/Contents/Info.plist" 2>/dev/null || true
    plutil -replace NSRequiresAquaSystemAppearance -bool true "dist/VmPOS.app/Contents/Info.plist" 2>/dev/null || true
fi

echo "✅ Aplicación VmPOS.app generada en dist/VmPOS.app"

echo "Generando paquete distribuible comprimido (.zip)..."
ditto -c -k --sequesterRsrc --keepParent "dist/VmPOS.app" "dist/VmPOS_macOS.zip"
echo "✅ Archivo ZIP generado en: dist/VmPOS_macOS.zip"

# Generar imagen instaladora DMG (arrastrar y soltar a /Applications)
echo "Generando instalador de disco DMG..."
DMG_STAGE="$PROJECT_ROOT/build/vmpos_dmg_stage"
STAGE_ISO="$PROJECT_ROOT/build/vmpos_stage.iso"
DMG_OUTPUT="$PROJECT_ROOT/dist/VmPOS_macOS_Instalador.dmg"

rm -rf "$DMG_STAGE" "$STAGE_ISO" "$DMG_OUTPUT"
mkdir -p "$DMG_STAGE"
cp -R "dist/VmPOS.app" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"

if hdiutil makehybrid -hfs -joliet -iso -default-volume-name "Instalador VmPOS" -o "$STAGE_ISO" "$DMG_STAGE" > /dev/null 2>&1; then
    if hdiutil convert "$STAGE_ISO" -format UDZO -imagekey zlib-level=9 -o "$DMG_OUTPUT" > /dev/null 2>&1; then
        echo "✅ Instalador DMG generado con éxito en: dist/VmPOS_macOS_Instalador.dmg"
    else
        echo "ℹ️ No se pudo convertir ISO a DMG, usando método estándar."
    fi
fi
rm -f "$STAGE_ISO"
rm -rf "$DMG_STAGE"

echo "=================================================================="
echo "🎉 ¡EMPAQUETADO PARA macOS COMPLETADO CON ÉXITO!"
echo "📍 Aplicación: dist/VmPOS.app"
echo "📍 Instalador DMG: $DMG_OUTPUT"
echo "=================================================================="

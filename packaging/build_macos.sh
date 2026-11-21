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

# 1. Asegurar entorno virtual y dependencias compatibles con macOS (Tk >= 8.6 obligatorio)
if [ -n "$PYTHON" ] && command -v "$PYTHON" > /dev/null 2>&1; then
    PYTHON_BIN="$PYTHON"
elif [ -n "$VIRTUAL_ENV" ] && [ -x "$VIRTUAL_ENV/bin/python3" ]; then
    PYTHON_BIN="$VIRTUAL_ENV/bin/python3"
elif command -v python3 > /dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    PYTHON_BIN="python3"
fi

echo "Usando intérprete Python: $PYTHON_BIN"

if ! "$PYTHON_BIN" -c "import tkinter; import _tkinter" 2>/dev/null; then
    echo "❌ ERROR: El intérprete $PYTHON_BIN no tiene soporte para Tkinter (_tkinter missing)."
    echo "En macOS con Homebrew, ejecute: brew install python-tk"
    exit 1
fi

"$PYTHON_BIN" -c "import tkinter, sys; print(f'Intérprete: Python {sys.version.split()[0]} | TkVersion: {tkinter.TkVersion} (Tcl: {tkinter.TclVersion})')"

TK_VER=$("$PYTHON_BIN" -c "import tkinter; print(tkinter.TkVersion)" 2>/dev/null || echo "0.0")
TK_MAJOR=$(echo "$TK_VER" | cut -d. -f1)
TK_MINOR=$(echo "$TK_VER" | cut -d. -f2)

if [ "$TK_MAJOR" -lt 8 ] || ([ "$TK_MAJOR" -eq 8 ] && [ "$TK_MINOR" -lt 6 ]); then
    echo "❌ ERROR: Intérprete Python tiene Tk $TK_VER. Se requiere Tk >= 8.6 para compatibilidad con macOS."
    exit 1
fi
echo "✅ Tkinter verificado correctamente: Tk $TK_VER"

echo "Verificando dependencias de compilación..."
if ! $PYTHON_BIN -c "import PyInstaller, PIL, reportlab, matplotlib, pandas, openpyxl, httpx, pydantic, pydantic_settings, barcode, escpos, fastapi, uvicorn, sqlalchemy, greenlet, asyncpg, jose, bcrypt, multipart" 2>/dev/null; then
    $PYTHON_BIN -m pip install --quiet pyinstaller pillow reportlab matplotlib pandas openpyxl httpx pydantic pydantic_settings python-barcode python-escpos pyusb fastapi uvicorn "sqlalchemy[asyncio]" greenlet aiosqlite asyncpg "python-jose[cryptography]" bcrypt python-multipart
fi

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

# 3. Limpiar compilaciones previas ANTES de crear cachés y staging limpio
echo "Limpiando compilaciones previas de macOS..."
rm -rf build
rm -rf dist/VmPOS.app dist/VmPOS dist/VmPOS_macOS.zip dist/VmPOS_macOS_Instalador.dmg

export PYINSTALLER_CONFIG_DIR="$PROJECT_ROOT/build/pyinstaller_cache"
export MPLCONFIGDIR="$PROJECT_ROOT/build/matplotlib_cache"
STAGE_CONFIG="$PROJECT_ROOT/build/stage_config"
STAGE_DATABASE="$PROJECT_ROOT/build/stage_database"
mkdir -p "$PYINSTALLER_CONFIG_DIR" "$MPLCONFIGDIR" "$STAGE_CONFIG" "$STAGE_DATABASE"

# Staging seguro de configuración (NUNCA incluir jwt_secret.key, token.json, business_config.json ni .db reales)
for cfg_tpl in printer_config.json theme_config.json barcode_label_config.json business_config.example.json; do
    if [ -f "config/$cfg_tpl" ]; then
        cp "config/$cfg_tpl" "$STAGE_CONFIG/"
    fi
done
touch "$STAGE_DATABASE/.keep"

# 4. Compilar con PyInstaller
echo "Compilando VmPOS.app con PyInstaller..."

ICON_FLAG=""
if [ -f "$ICNS_PATH" ]; then
    ICON_FLAG="--icon=$ICNS_PATH"
fi

$PYTHON_BIN -m PyInstaller \
    --name="VmPOS" \
    --windowed \
    --noconfirm \
    $ICON_FLAG \
    --add-data="assets:assets" \
    --add-data="$STAGE_CONFIG:config" \
    --add-data="$STAGE_DATABASE:database" \
    --add-data="interface:interface" \
    --add-data="client:client" \
    --add-data="server:server" \
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
    --hidden-import="interface.pantalla_carga" \
    --hidden-import="pantalla_carga" \
    --hidden-import="interface.backup_manager" \
    --hidden-import="interface.sync_manager" \
    interface/inicio_sesion.py

# Limpiar cualquier logo/secreto/DB accidental dentro del bundle antes de empaquetar
find "dist/VmPOS.app" -type f \( -name "*.db" -o -name "*.db-wal" -o -name "*.db-shm" -o -name "jwt_secret.key" -o -name "token.json" -o -name "business_config.json" \) -delete 2>/dev/null || true
rm -rf "dist/VmPOS.app/Contents/Resources/assets/logos" "dist/VmPOS.app/Contents/Frameworks/assets/logos" 2>/dev/null || true

LEAKED=$(find "dist/VmPOS.app" -type f \( -name "*.db" -o -name "jwt_secret.key" -o -name "token.json" -o -name "business_config.json" \) 2>/dev/null || true)
if [ -n "$LEAKED" ]; then
    echo "❌ ERROR DE SEGURIDAD: Se detectaron archivos sensibles dentro de dist/VmPOS.app:"
    echo "$LEAKED"
    exit 1
fi

# Ajustar Info.plist para alta resolución Retina y forzar apariencia Aqua (evita texto blanco invisible en Dark Mode)
if [ -f "dist/VmPOS.app/Contents/Info.plist" ] && command -v plutil > /dev/null 2>&1; then
    plutil -replace NSHighResolutionCapable -bool true "dist/VmPOS.app/Contents/Info.plist" 2>/dev/null || true
    plutil -replace NSRequiresAquaSystemAppearance -bool true "dist/VmPOS.app/Contents/Info.plist" 2>/dev/null || true
fi

echo "✅ Aplicación VmPOS.app generada y auditada sin secretos en dist/VmPOS.app"

echo "Generando paquete distribuible comprimido (.zip)..."
ditto -c -k --sequesterRsrc --keepParent "dist/VmPOS.app" "dist/VmPOS_macOS.zip"
if [ ! -s "dist/VmPOS_macOS.zip" ]; then
    echo "❌ ERROR: No se generó un archivo dist/VmPOS_macOS.zip válido."
    exit 1
fi
echo "✅ Archivo ZIP generado en: dist/VmPOS_macOS.zip"

# Generar imagen instaladora DMG (arrastrar y soltar a /Applications) — FAIL FAST obligatorio
echo "Generando instalador de disco DMG..."
DMG_STAGE="$PROJECT_ROOT/build/vmpos_dmg_stage"
STAGE_ISO="$PROJECT_ROOT/build/vmpos_stage.iso"
DMG_OUTPUT="$PROJECT_ROOT/dist/VmPOS_macOS_Instalador.dmg"

rm -rf "$DMG_STAGE" "$STAGE_ISO" "$DMG_OUTPUT"
mkdir -p "$DMG_STAGE"
cp -R "dist/VmPOS.app" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"

DMG_CREATED=0
if hdiutil makehybrid -hfs -joliet -iso -default-volume-name "Instalador VmPOS" -o "$STAGE_ISO" "$DMG_STAGE"; then
    if hdiutil convert "$STAGE_ISO" -format UDZO -imagekey zlib-level=9 -o "$DMG_OUTPUT"; then
        DMG_CREATED=1
    fi
fi

if [ "$DMG_CREATED" -ne 1 ] || [ ! -s "$DMG_OUTPUT" ]; then
    echo "Intentando generación DMG mediante hdiutil create nativo..."
    rm -f "$DMG_OUTPUT"
    hdiutil create -volname "Instalador VmPOS" -srcfolder "$DMG_STAGE" -ov -format UDZO "$DMG_OUTPUT"
fi

if [ ! -s "$DMG_OUTPUT" ]; then
    echo "❌ ERROR CRÍTICO: No se generó el instalador DMG ($DMG_OUTPUT)."
    rm -f "$STAGE_ISO"
    rm -rf "$DMG_STAGE"
    exit 1
fi

echo "Verificando integridad del DMG con hdiutil verify..."
if ! hdiutil verify "$DMG_OUTPUT"; then
    echo "❌ ERROR CRÍTICO: El instalador DMG falló la verificación de integridad (hdiutil verify)."
    rm -f "$STAGE_ISO" "$DMG_OUTPUT"
    rm -rf "$DMG_STAGE"
    exit 1
fi
echo "✅ Instalador DMG verificado con éxito en: $DMG_OUTPUT"

rm -f "$STAGE_ISO" "$PROJECT_ROOT/VmPOS.spec"
rm -rf "$DMG_STAGE" "$STAGE_CONFIG" "$STAGE_DATABASE"

if [ -d "dist/VmPOS.app" ]; then
    echo "Intentando actualizar /Applications/VmPOS.app..."
    (rm -rf "/Applications/VmPOS.app" && cp -R "dist/VmPOS.app" "/Applications/VmPOS.app") 2>/dev/null || echo "Aviso: Para actualizar /Applications/VmPOS.app se puede copiar manualmente dist/VmPOS.app o montar el DMG."
fi

echo "=================================================================="
echo "🎉 ¡EMPAQUETADO PARA macOS COMPLETADO CON ÉXITO!"
echo "📍 Aplicación: dist/VmPOS.app"
echo "📍 Instalador DMG: $DMG_OUTPUT"
echo "=================================================================="

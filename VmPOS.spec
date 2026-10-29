# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['interface/inicio_sesion.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('config', 'config'), ('database', 'database'), ('interface', 'interface'), ('client', 'client'), ('network_config.json', '.')],
    hiddenimports=['reportlab', 'reportlab.lib', 'reportlab.platypus', 'reportlab.pdfgen', 'matplotlib', 'matplotlib.backends.backend_tkagg', 'pandas', 'openpyxl', 'PIL', 'PIL.Image', 'PIL.ImageTk', 'sqlite3', 'escpos', 'usb', 'httpx', 'pydantic', 'pydantic_settings', 'barcode', 'barcode.codex', 'barcode.ean', 'barcode.writer'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VmPOS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['/Users/eduardosanchez/venta_pos_VM-main/assets/Salome.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VmPOS',
)
app = BUNDLE(
    coll,
    name='VmPOS.app',
    icon='/Users/eduardosanchez/venta_pos_VM-main/assets/Salome.icns',
    bundle_identifier=None,
)

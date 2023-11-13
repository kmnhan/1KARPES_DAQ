# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\webcam.py'],
    pathex=[],
    binaries=[],
    datas=[('src/webcam.ui', '.'), ('src/images/webcam.ico', './images'), ('src/qt_extensions/*', './qt_extensions/')],
    hiddenimports=['PyQt6'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['IPython'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Webcam Viewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\images\\webcam.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='webcam',
)

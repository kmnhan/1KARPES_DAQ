# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\pyloncam.py'],
    pathex=[],
    binaries=[],
    datas=[('src/framegrab.ui', '.'), ('src/images/pyloncam.ico', './images'), ('src/qt_extensions/*', './qt_extensions/')],
    hiddenimports=['PyQt6', 'matplotlib'],
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
    name='Pylon Camera Viewer',
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
    icon=['src\\images\\pyloncam.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='pyloncam',
)

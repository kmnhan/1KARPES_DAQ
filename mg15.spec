# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\mg15\\main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ("src/mg15/plotting.ui", "."),
        ("src/mg15/pressures.ui", "."),
        ("src/mg15/mg15.py", "."),
        ("src/mg15/icon.ico", "."),
    ],
    hiddenimports=['PyQt6', 'pyqtgraph', 'pymodbus'],
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
    name='MG15',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\mg15\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='mg15',
)

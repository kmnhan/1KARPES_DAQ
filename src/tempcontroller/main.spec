# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\tempcontroller\\main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ("src/tempcontroller/connection.py", "."),
        ("src/tempcontroller/widgets.py", "."),
        ("src/tempcontroller/command.ui", "."),
        ("src/tempcontroller/heater.ui", "."),
        ("src/tempcontroller/heatswitch.ui", "."),
        ("src/tempcontroller/main.ui", "."),
        ("src/tempcontroller/plotting.ui", "."),
        # ("src/tempcontroller/icon.ico", "."),
        ("src/qt_extensions/__init__.py", "./qt_extensions"),
        ("src/qt_extensions/legendtable.py", "./qt_extensions"),
        ("src/qt_extensions/plotting.py", "./qt_extensions"),
    ],
    hiddenimports=['PyQt6', 'pyqtgraph'],
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
    name='Temperature Contoller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
#     icon=['src\\mg15\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='tempcontrol',
)

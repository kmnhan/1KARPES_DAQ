# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("connection.py", "."),
        ("widgets.py", "."),
        ("command.ui", "."),
        ("heater.ui", "."),
        ("heatswitch.ui", "."),
        ("main.ui", "."),
        ("plotting.ui", "."),
        ("icon.ico", "."),
        ("qt_extensions/__init__.py", "./qt_extensions"),
        ("qt_extensions/legendtable.py", "./qt_extensions"),
        ("qt_extensions/plotting.py", "./qt_extensions"),
    ],
    hiddenimports=["PyQt6", "pyqtgraph"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Temperature Contoller",
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
    icon=["icon.ico"],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="tempcontrol",
)

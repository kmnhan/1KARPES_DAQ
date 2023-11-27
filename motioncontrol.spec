# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\motioncontrol\\main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ("src/motioncontrol/channel.ui", "."),
        ("src/motioncontrol/controller_single.ui", "."),
        ("src/motioncontrol/controller.ui", "."),
        ("src/motioncontrol/icon.ico", "."),
        ("src/motioncontrol/maniserver.py", "."),
        ("src/motioncontrol/moee.py", "."),
        ("src/motioncontrol/motionwidgets.py", "."),
    ],
    hiddenimports=['PyQt6', 'pyqtgraph', 'qtawesome'],
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
    name='Motion Control',
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
    icon=['src\\motioncontrol\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='motioncontrol',
)

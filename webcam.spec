# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["src/webcam/main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("src/webcam/webcam.ui", "."),
        ("src/webcam/icon.ico", "."),
    ],
    hiddenimports=["PyQt6"],
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
    name="Webcam Viewer",
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
    icon=["src/webcam/icon.ico"],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="webcam",
)

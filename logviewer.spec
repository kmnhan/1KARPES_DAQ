# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["src/logviewer.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("src/qt_extensions/*", "./qt_extensions/"),
        ("src/logviewer.ui", "."),
        ("src/logreader.py", "."),
        ("src/images/logviewer.ico", "./images"),
    ],
    hiddenimports=["PyQt6", "pandas", "seaborn"],
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
    a.binaries,
    a.datas,
    [],
    name="Log Viewer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["src\\images\\logviewer.ico"],
)

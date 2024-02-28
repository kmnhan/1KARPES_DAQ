# -*- mode: python ; coding: utf-8 -*-
import sys
if sys.platform == "darwin":
    icon_path = "src/images/logviewer.icns"
else:
    icon_path = "src/images/logviewer.ico"

a = Analysis(
    ["src/logviewer.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("src/logviewer.ui", "."),
        ("src/logreader.py", "."),
        (icon_path, "./images"),
        ("src/qt_extensions/__init__.py", "./qt_extensions/"),
        ("src/qt_extensions/legendtable.py", "./qt_extensions/"),
        ("src/qt_extensions/plotting.py", "./qt_extensions/"),
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
    name="Log Viewer",
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
    icon=[icon_path],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="logviewer",
)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="LogViewer.app",
        icon=icon_path,
        bundle_identifier=None,
    )


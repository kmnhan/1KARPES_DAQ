# -*- mode: python ; coding: utf-8 -*-

import pypylon
import pathlib
from PyInstaller.utils.hooks import copy_metadata

pypylon_dir = pathlib.Path(pypylon.__file__).parent
pylon_binaries = [(str(f), "./pypylon") for f in pypylon_dir.glob("*.dll")]
pylon_binaries += [(str(f), "./pypylon") for f in pypylon_dir.glob("*.pyd")]


datas = [
    ("src/pyloncam/pyloncam.ui", "."),
    ("src/pyloncam/cameramonitor_config.ui", "."),
    ("src/pyloncam/icon.ico", "."),
    ("src/pyloncam/icon_white.ico", "."),
    ("src/qt_extensions/*", "./qt_extensions/"),
]
datas += copy_metadata("numpy")
# For some reason, xarray requires numpy metadata on import

a = Analysis(
    ["src/pyloncam/main.py"],
    pathex=[],
    binaries=pylon_binaries,
    datas=datas,
    hiddenimports=[
        "PyQt6",
        "h5netcdf",
        "xarray",
        "numpy",
        "matplotlib",
        "matplotlib.colors",
    ],
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
    name="Pylon Camera Viewer",
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
    icon=["src/pyloncam/icon_white.ico"],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="pyloncam",
)

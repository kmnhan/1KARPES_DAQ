# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [("src/f70h/icon.ico", ".")]
datas += collect_data_files("f70h")


a = Analysis(
    ["src/f70h/__main__.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["PyQt6", "pyvisa", "pyvisa_py", "serial"],
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
    name="F70H Monitor",
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
    icon=["src/f70h/icon.ico"],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="f70h",
)

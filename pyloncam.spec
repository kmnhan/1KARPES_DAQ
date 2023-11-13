# -*- mode: python ; coding: utf-8 -*-

import pypylon
import pathlib
pypylon_dir = pathlib.Path(pypylon.__file__).parent
pylon_binaries = [(str(dll), '.') for dll in pypylon_dir.glob('*.dll')]
pylon_binaries += [(str(dll), '.') for dll in pypylon_dir.glob('*.pyd')]


a = Analysis(
    ['src\\pyloncam.py'],
    pathex=[],
    binaries=pylon_binaries,
    datas=[('src/framegrab.ui', '.'), ('src/images/pyloncam.ico', './images'), ('src/qt_extensions/*', './qt_extensions/')],
    hiddenimports=['PyQt6', 'matplotlib', 'pypylon', 'pypylon.pylon', 'pypylon.genicam', 'pypylon._pylon', 'pypylon._genicam'],
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
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name='pyloncam',
)

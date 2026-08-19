# -*- mode: python ; coding: utf-8 -*-


import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

icon_path = 'assets/icon.ico' if os.path.exists('assets/icon.ico') else 'assets/icon.png'

packages_to_collect = [
    'romann',
    'pykakasi',
    'sudachipy',
    'sudachidict_full',
    'sudachidict_core',
    'pyrekordbox',
    'mutagen',
]

datas = [('assets', 'assets')]
hiddenimports = []

for pkg in packages_to_collect:
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='rkbdb2xml-gui-console',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.exists(icon_path) else None,
)

# -*- mode: python ; coding: utf-8 -*-


import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

icon_path = 'assets/icon.ico' if os.path.exists('assets/icon.ico') else 'assets/icon.png'

# Packages whose data files and/or submodules are loaded dynamically at runtime.
# sudachidict_full is intentionally omitted: romann/sudachipy use the core
# dictionary by default, and the full dictionary adds ~340 MB to the bundle.
packages_to_collect = [
    'romann',
    'pykakasi',
    'sudachipy',
    'sudachidict_core',
    'pyrekordbox',
    'rekordbox_pdb',
    'mutagen',
]

# CLI-only submodules are not needed at runtime. Filter them out to reduce
# the number of modules PyInstaller has to analyze and bundle.
submodule_excludes = {
    'pykakasi': {'pykakasi.cli', 'pykakasi.scripts'},
    'sudachipy': {'sudachipy.command_line'},
    'mutagen': {'mutagen._tools'},
}


def collect_submodules_filtered(pkg, excludes=None):
    """Collect submodules while dropping known CLI/utility-only modules."""
    if excludes is None:
        excludes = set()
    all_submodules = collect_submodules(pkg)
    return [m for m in all_submodules if m not in excludes and not any(m.startswith(e + '.') for e in excludes)]


datas = [('assets', 'assets')]
hiddenimports = ['PySide6.QtMultimedia']

for pkg in packages_to_collect:
    # Always include the top-level package; collect_submodules may miss it
    # when PyInstaller treats the distribution as a plain module.
    hiddenimports.append(pkg)

    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass

    try:
        hiddenimports += collect_submodules_filtered(pkg, submodule_excludes.get(pkg, set()))
    except Exception:
        pass

# If SudachiDict-full happens to be installed in the build environment, this
# keeps its Python package out of the frozen app. The dictionary data files
# are handled by the sudachipy hook, so the safe fix is not to install
# sudachidict_full in the build environment.
excludes = ['sudachidict_full']

a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# The sudachipy hook pulls in all installed sudachidict_* packages. The app
# only ever uses the core dictionary, so drop full-dictionary data files even
# if sudachidict_full is installed in the build environment.
a.datas = [entry for entry in a.datas if 'sudachidict_full' not in entry[0]]

pyz = PYZ(a.pure)

# UPX compresses binaries but can significantly slow the build (and sometimes
# causes issues with Qt DLLs). Disable it by default; set RKBDB2XML_UPX=1 to
# re-enable when bundle size is more important than build time.
use_upx = os.environ.get('RKBDB2XML_UPX', '').lower() in ('1', 'true', 'yes', 'on')

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='rkbdb2xml-gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=use_upx,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.exists(icon_path) else None,
)

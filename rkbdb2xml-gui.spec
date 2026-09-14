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

# Exclude modules and packages that are not needed at runtime to speed up
# analysis and bundle compression.
excludes = [
    'sudachidict_full',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtQuick3D',
    'PySide6.QtVirtualKeyboard',
    'PySide6.QtPdf',
    'PySide6.QtPdfWidgets',
    'PySide6.QtWebEngine',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebSockets',
    'PySide6.QtSql',
    'PySide6.QtTest',
    'PySide6.QtDesigner',
    'PySide6.QtXml',
    'PySide6.QtHelp',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtPositioning',
    'PySide6.QtLocation',
    'PySide6.QtSpatialAudio',
    'PySide6.QtNfc',
    'PySide6.QtBluetooth',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DRender',
    'tkinter',
    'unittest',
]

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

# Filter out unused Qt binaries and dictionary data files to reduce bundle size and build time.
unused_qt_keywords = ('qml', 'quick', 'virtualkeyboard', 'pdf', 'webengine', 'designer')
a.datas = [
    entry for entry in a.datas
    if 'sudachidict_full' not in entry[0]
    and not any(kw in entry[0].lower() for kw in unused_qt_keywords)
]
a.binaries = [
    entry for entry in a.binaries
    if not any(kw in entry[0].lower() for kw in unused_qt_keywords)
]

pyz = PYZ(a.pure)

# UPX compresses binaries but can significantly slow the build (and sometimes
# causes issues with Qt DLLs). Disable it by default; set RKBDB2XML_UPX=1 to
# re-enable when bundle size is more important than build time.
use_upx = os.environ.get('RKBDB2XML_UPX', '').lower() in ('1', 'true', 'yes', 'on')

# Mode: onefile (single .exe, default) vs onedir (directory, much faster build).
# Set BUILD_MODE=onedir, RKBDB2XML_BUILD_MODE=onedir, or create .build_mode file.
build_mode = ""
if os.path.exists('.build_mode'):
    try:
        with open('.build_mode', 'r', encoding='utf-8') as f:
            build_mode = f.read().strip().lower()
    except Exception:
        pass
if not build_mode:
    build_mode = os.environ.get('RKBDB2XML_BUILD_MODE', os.environ.get('BUILD_MODE', 'onefile')).lower()
is_onedir = build_mode in ('onedir', 'dir')

if is_onedir:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='rkbdb2xml-gui',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=use_upx,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon_path if os.path.exists(icon_path) else None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=use_upx,
        upx_exclude=[],
        name='rkbdb2xml-gui',
    )
else:
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

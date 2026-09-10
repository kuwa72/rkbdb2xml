#!/usr/bin/env bash
# Local Windows build from WSL + copy to the well-known prd path.
# Usage: scripts/build_windows_local.sh [dest-path]
#   default dest: /mnt/c/Users/<user>/prd/rkbdb2xml/rkbdb2xml-gui-windows-amd64.exe
#   env WINPY: Windows python.exe (default: Store Python 3.13)
#   env BUILD_CLEAN: set to 1 to run PyInstaller with --clean (slower but fully fresh)
#
# Requires: WSL (/mnt/c visible), Windows Python.
# Creates a dedicated Windows-side venv (%LOCALAPPDATA%\\rkbdb2xml-venv) and
# reuses it across builds. Dependencies are only re-installed when the pinned
# requirements in this script change.
set -euo pipefail

cd "$(dirname "$0")/.."

DEST=""
WINPY="${WINPY:-/mnt/c/Users/ykuwa/AppData/Local/Microsoft/WindowsApps/python3.13.exe}"
if [ ! -x "${WINPY}" ]; then
    WINPY="$(dirname "${WINPY}")/python.exe"
fi

# Default dest: %USERPROFILE%\prd\rkbdb2xml\rkbdb2xml-gui-windows-amd64.exe
# (overridable via argv[1]). Resolved through the Windows env, not hardcoded.
default_dest() {
    local profile=""
    if [ -x "${WINPY}" ]; then
        profile="$("${WINPY}" -c "import os; print(os.environ.get('USERPROFILE', ''))" 2>/dev/null | tr -d '\r')"
    fi
    if [ -z "${profile}" ] && command -v cmd.exe >/dev/null 2>&1; then
        profile="$(cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r')"
    fi
    if [ -z "${profile}" ]; then
        echo "ERROR: cannot determine Windows USERPROFILE. Pass dest path explicitly." >&2
        exit 1
    fi
    printf '%s/prd/rkbdb2xml/rkbdb2xml-gui-windows-amd64.exe' "$(wslpath "${profile}")"
}

DEST="${1:-$(default_dest)}"

[ -d /mnt/c ] || { echo "ERROR: /mnt/c not found. Run this script from WSL." >&2; exit 1; }
[ -x "${WINPY}" ] || { echo "ERROR: Windows Python not found (${WINPY}). Set WINPY." >&2; exit 1; }

# Determine the Windows-side venv location (%LOCALAPPDATA%\rkbdb2xml-venv).
LOCALAPPDATA="$("${WINPY}" -c "import os; print(os.environ.get('LOCALAPPDATA', ''))" 2>/dev/null | tr -d '\r')"
if [ -z "${LOCALAPPDATA}" ]; then
    echo "ERROR: cannot determine Windows LOCALAPPDATA." >&2
    exit 1
fi
WIN_VENV_DIR="${LOCALAPPDATA}\\rkbdb2xml-venv"

# Resolve the actual venv prefix. Microsoft Store Python may create the venv
# under a redirected path (Packages/.../LocalCache), so sys.prefix is needed.
resolve_venv_prefix() {
    local pywin="${1}"
    "${pywin}" -c "import sys; print(sys.prefix)" 2>/dev/null | tr -d '\r'
}

# Use the WSL-mount path to invoke the venv Python; Windows-style paths like
# C:\... are not valid command names from inside WSL.
VENV_PY_WSL="$(wslpath -u "$(printf '%s\\Scripts\\python.exe' "${WIN_VENV_DIR}")" 2>/dev/null)"
if [ -z "${VENV_PY_WSL}" ]; then
    echo "ERROR: wslpath failed for ${WIN_VENV_DIR}\\Scripts\\python.exe" >&2
    exit 1
fi

if ! VENV_PREFIX_WIN="$(resolve_venv_prefix "${VENV_PY_WSL}")"; then
    VENV_PREFIX_WIN=""
fi

if [ -z "${VENV_PREFIX_WIN}" ]; then
    echo "=== Creating Windows venv ==="
    "${WINPY}" -m venv "${WIN_VENV_DIR}"
    # Resolve any junction/symlink to the actual Store-Python redirected path.
    if [ -e "${VENV_PY_WSL}" ]; then
        VENV_PY_WSL_RESOLVED="$(readlink -f "${VENV_PY_WSL}" 2>/dev/null || true)"
        if [ -n "${VENV_PY_WSL_RESOLVED}" ] && [ -f "${VENV_PY_WSL_RESOLVED}" ]; then
            VENV_PY_WSL="${VENV_PY_WSL_RESOLVED}"
        fi
    fi
    if ! VENV_PREFIX_WIN="$(resolve_venv_prefix "${VENV_PY_WSL}")"; then
        VENV_PREFIX_WIN=""
    fi
fi

if [ -z "${VENV_PREFIX_WIN}" ]; then
    echo "ERROR: failed to create or resolve Windows venv (${WIN_VENV_DIR})" >&2
    exit 1
fi

# Refresh executable path and WSL paths from the resolved prefix/executable.
if ! VENV_PY_WIN="$("${VENV_PY_WSL}" -c "import sys; print(sys.executable)" 2>/dev/null | tr -d '\r')"; then
    VENV_PY_WIN=""
fi
if [ -z "${VENV_PY_WIN}" ]; then
    echo "ERROR: could not resolve venv python.exe" >&2
    exit 1
fi
VENV_WSL="$(wslpath -u "${VENV_PREFIX_WIN}" 2>/dev/null)"
if [ -z "${VENV_WSL}" ]; then
    echo "ERROR: wslpath failed for ${VENV_PREFIX_WIN}" >&2
    exit 1
fi
VENV_PY_WSL="$(wslpath -u "${VENV_PY_WIN}" 2>/dev/null)"
VENV_REQ_WIN="$(printf '%s\\requirements.txt' "${VENV_PREFIX_WIN}")"
VENV_REQ_WSL="${VENV_WSL}/requirements.txt"
VENV_MARKER_WSL="${VENV_WSL}/.requirements.sha256"

echo "=== Windows venv resolved to: ${VENV_PREFIX_WIN} ==="

# Write the pinned Windows build requirements into the venv.
mkdir -p "${VENV_WSL}"
cat > "${VENV_REQ_WSL}" <<'EOF'
pyinstaller
PySide6==6.9.0
pyrekordbox==0.4.3
mutagen==1.47.0
psutil==7.0.0
romann==0.3.0
SudachiDict-core==20250129
rekordbox-pdb @ git+https://github.com/fragmede/rekordbox-pdb.git@ee3bac2f22ca11a5ce61eea35f8cb951c246eaef
EOF

# Compute hash of the requirements file to decide whether pip install is needed.
REQ_HASH="$(sha256sum "${VENV_REQ_WSL}" | cut -d' ' -f1)"
if [ ! -f "${VENV_MARKER_WSL}" ] || [ "$(cat "${VENV_MARKER_WSL}")" != "${REQ_HASH}" ]; then
    echo "=== Installing/updating runtime deps in Windows venv ==="
    "${VENV_PY_WIN}" -m pip install --upgrade pip
    "${VENV_PY_WIN}" -m pip install -r "${VENV_REQ_WIN}"
    echo "${REQ_HASH}" > "${VENV_MARKER_WSL}"
else
    echo "=== Windows venv deps are up to date (hash ${REQ_HASH:0:16}...) ==="
fi

# Decide whether to use --clean. Omitting it lets PyInstaller reuse build/ cache,
# which is much faster for incremental builds.
CLEAN_FLAG=""
if [ "${BUILD_CLEAN:-0}" = "1" ]; then
    CLEAN_FLAG="--clean"
fi

echo "=== Building Windows exe with PyInstaller ==="
"${VENV_PY_WIN}" -m PyInstaller ${CLEAN_FLAG} --noconfirm rkbdb2xml-gui.spec

echo "=== Verifying dist/rkbdb2xml-gui.exe ==="
python3 - dist/rkbdb2xml-gui.exe <<'PY'
import sys

path = sys.argv[1]
with open(path, "rb") as f:
    data = f.read()
assert data[:2] == b"MZ", "not a PE file"
assert data.rfind(b"MEI\x0c\x0b\x0a\x0b\x0e") != -1, "PyInstaller archive missing (truncated build?)"
print(f"  OK: {len(data)} bytes, PE + PyInstaller archive present")
PY

echo "=== Copying to ${DEST} ==="
mkdir -p "$(dirname "${DEST}")"
cp dist/rkbdb2xml-gui.exe "${DEST}"
ls -la "${DEST}"
echo "=== Done ==="

#!/usr/bin/env bash
# Local Windows build from WSL + copy to the well-known prd path.
# Usage: scripts/build_windows_local.sh [dest-path]
#   default dest: /mnt/c/Users/ykuwa/prd/rkbdb2xml/rkbdb2xml-gui-windows-amd64.exe
#   env WINPY: Windows python.exe (default: Store Python 3.13)
#
# Requires: WSL (/mnt/c visible), Windows Python with PyInstaller.
# Missing runtime deps (mutagen/psutil/romann/SudachiDict-full) are pip-installed
# into the Windows Python to match CI (.github/workflows/release.yml).
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
"${WINPY}" -c "import PyInstaller" 2>/dev/null \
    || { echo "ERROR: PyInstaller missing in Windows Python (${WINPY})." >&2; exit 1; }

echo "=== Ensuring runtime deps in Windows Python ==="
# Pin to requirements.txt versions (a stale pyrekordbox 0.4.0 on Windows crashes
# reading app.asar with a UnicodeDecodeError - 0.4.3 uses errors="replace").
"${WINPY}" -m pip install \
    "pyrekordbox==0.4.3" \
    "mutagen==1.47.0" \
    "psutil==7.0.0" \
    "romann==0.3.0" \
    "SudachiDict-full==20250129"

echo "=== Building Windows exe with PyInstaller ==="
"${WINPY}" -m PyInstaller --clean --noconfirm rkbdb2xml-gui.spec

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

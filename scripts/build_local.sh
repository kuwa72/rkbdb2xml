#!/usr/bin/env bash
set -e

echo "=== Setting up build environment ==="
PYTHON_BIN="python3"
if command -v python3.12 &>/dev/null; then
    PYTHON_BIN="python3.12"
elif [ -x "/usr/bin/python3.12" ]; then
    PYTHON_BIN="/usr/bin/python3.12"
fi

if [ -d ".venv" ]; then
    # Check if .venv python version is 3.12
    VENV_VER=$(.venv/bin/python --version 2>&1 || true)
    if [[ "$VENV_VER" != *"3.12"* ]]; then
        echo "Re-creating .venv with $PYTHON_BIN (was $VENV_VER)..."
        rm -rf .venv
    fi
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment with $PYTHON_BIN in .venv..."
    $PYTHON_BIN -m venv .venv
fi


source .venv/bin/activate

echo "=== Installing dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
pip install pyinstaller

echo "=== Building executable with PyInstaller ==="
pyinstaller --clean rkbdb2xml-gui.spec

echo "=== Build completed! ==="
echo "Binary created at:"
ls -lh dist/rkbdb2xml-gui*

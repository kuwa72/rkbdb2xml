#!/usr/bin/env bash
set -e

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "=== Checking python syntax ==="
python3 -m py_compile rkbdb2xml/*.py run_gui.py

echo "=== Running tests ==="
if command -v pytest &>/dev/null; then
    pytest tests/ -v
elif python3 -m pytest --version &>/dev/null; then
    python3 -m pytest tests/ -v
else
    echo "pytest not found in environment, running basic import tests..."
    python3 -c "import rkbdb2xml; print('rkbdb2xml version:', rkbdb2xml.__version__)"
fi

echo "=== All checks passed ==="


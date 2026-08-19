#!/usr/bin/env bash
set -e

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "=== Running pytest ==="
pytest tests/ -v


echo "=== Checking python syntax for gui.py ==="
python -m py_compile rkbdb2xml/gui.py run_gui.py

echo "=== All checks passed ==="

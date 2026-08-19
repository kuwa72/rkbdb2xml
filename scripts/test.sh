#!/usr/bin/env bash
set -e

echo "=== Running pytest ==="
pytest tests/ -v

echo "=== Checking python syntax for gui.py ==="
python -m py_compile rkbdb2xml/gui.py run_gui.py

echo "=== All checks passed ==="

#!/usr/bin/env bash
set -e

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
pip install pytest pytest-cov

if gh auth status >/dev/null 2>&1; then
    ./scripts/setup_labels.sh
else
    echo "Skipping label setup (gh not authenticated)"
fi

echo "Environment ready!"

#!/usr/bin/env bash
set -e

VERSION="v0.4.0"

echo "=== Staging changes ==="
git add .gitignore README.md pyproject.toml rkbdb2xml/ tests/ .github/ assets/ rkbdb2xml-gui*.spec run_gui.py scripts/


echo "=== Committing changes ==="
git commit -m "feat: Release ${VERSION} - Polish GUI UX, add app icons, and automated multi-platform build" || true

echo "=== Creating tag ${VERSION} ==="
git tag -a "${VERSION}" -m "Release ${VERSION} - User-friendly GUI & Automated Releases"

echo "=== Pushing to origin (branch & tags) ==="
git push origin main
git push origin "${VERSION}"

echo "=== Release ${VERSION} pushed successfully! ==="

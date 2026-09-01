#!/usr/bin/env bash
# Usage: scripts/release.sh <version> [commit message]
#   e.g. scripts/release.sh 0.5.5 "fix: defer audio playback until media is loaded"
#
# Bumps pyproject.toml and rkbdb2xml/__init__.py, commits, tags and pushes.
# Pushing the tag triggers .github/workflows/release.yml (multi-platform build).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
    echo "Usage: scripts/release.sh <version> [commit message]" >&2
    echo "Current version: $(grep -m1 '^version' pyproject.toml)" >&2
    exit 1
fi

VERSION="${1#v}"
TAG="v${VERSION}"
MESSAGE="${2:-"Release ${TAG}"}"

if ! [[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "ERROR: version must look like 0.5.5 (got '${VERSION}')" >&2
    exit 1
fi

if git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null; then
    echo "ERROR: tag ${TAG} already exists" >&2
    exit 1
fi

echo "=== Bumping version to ${VERSION} ==="
python3 - "${VERSION}" <<'PY'
import re
import sys

version = sys.argv[1]
for path, pattern in (
    ("pyproject.toml", r'^version = "[^"]+"'),
    ("rkbdb2xml/__init__.py", r'^__version__ = "[^"]+"'),
):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    replacement = pattern.split('"')[0].lstrip("^") + f'"{version}"'
    new_text, n = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if n != 1:
        raise SystemExit(f"ERROR: could not bump version in {path}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"  {path} -> {version}")
PY

echo "=== Running tests ==="
scripts/test.sh || echo "!!! tests reported failures (see above) !!!"

echo "=== Staging changes ==="
git add .gitignore README.md pyproject.toml rkbdb2xml/ tests/ .github/ assets/ rkbdb2xml-gui*.spec run_gui.py scripts/

echo "=== Committing changes ==="
git commit -m "${MESSAGE}" || true

echo "=== Creating tag ${TAG} ==="
git tag -a "${TAG}" -m "${MESSAGE}"

echo "=== Pushing to origin (branch & tag) ==="
git push origin main
git push origin "${TAG}"

echo "=== Release ${TAG} pushed successfully! ==="
echo "Build progress: https://github.com/kuwa72/rkbdb2xml/actions"

"""Shared pytest configuration.

``tests/data/rekordbox_test.db`` を実際に開くテストは、pyrekordbox が
Rekordbox 本体から鍵を取得できる環境（Windows/macOS + Rekordbox
インストール済み）でしか動かない。Linux CI ではファイルが存在しても
オープンに失敗するため、事前に一度だけ開いてみて、失敗したら
db6 依存モジュールをまとめて skip する。

対象はモジュール単位で挙げる。テスト内で自力 skip している
``test_file_copy_and_cascade`` 等は対象外。
"""

import os
from pathlib import Path

import pytest

_TEST_DB = os.path.join(
    os.path.dirname(__file__), "data", "rekordbox_test.db"
)


def load_dotenv(path: Path) -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into ``os.environ``.

    Used to pick up the repo-local ``.env`` (gitignored) holding
    ``RB6_DB_KEY`` for local encrypted-DB E2E runs. Existing
    environment variables are never overridden, so shell exports and
    CI secrets take precedence. Missing files are a no-op.
    """
    try:
        text = Path(path).read_text()
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


# リポジトリ直下の .env（gitignore 済み）からローカル用キーを読む
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# RekordboxXMLExporter(db_path=TEST_DB_PATH) を直接使うモジュール
_DB6_MODULES = {
    "test_bpm_conversion",
    "test_orderby_bpm",
    "test_romanization",
    "test_xml_output_compare",
}


def _db6_available() -> bool:
    try:
        from pyrekordbox.db6 import Rekordbox6Database

        db = Rekordbox6Database(_TEST_DB)
        db.close()
        return True
    except Exception:
        return False


def pytest_collection_modifyitems(items):
    if _db6_available():
        return
    skip = pytest.mark.skip(
        reason="pyrekordbox db6 unavailable (requires rekordbox install)"
    )
    for item in items:
        if item.module.__name__.split(".")[-1] in _DB6_MODULES:
            item.add_marker(skip)

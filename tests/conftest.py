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

import pytest

_TEST_DB = os.path.join(
    os.path.dirname(__file__), "data", "rekordbox_test.db"
)

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

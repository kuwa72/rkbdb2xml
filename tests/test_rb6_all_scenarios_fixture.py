"""Rekordbox 6.8.0 全シナリオ fixture の構造検証。"""

from pathlib import Path

from rekordbox_pdb import Database


DATA_DIR = Path(__file__).parent / "data"
FIXTURE_ROOT = DATA_DIR / "usb_fixtures" / "rkb680_all_scenarios"


def test_rb680_all_scenarios_fixture_is_complete() -> None:
    pdb_path = FIXTURE_ROOT / "PIONEER" / "rekordbox" / "export.pdb"
    database = Database.from_file(pdb_path)

    assert len(database.tracks) == 620
    assert len(database.playlist_tree) == 113
    assert len(database.playlist_entries) == 621
    assert sum(
        path.is_file()
        for path in (FIXTURE_ROOT / "Contents").rglob("*")
    ) == 620
    assert sum(
        path.is_file()
        for path in (FIXTURE_ROOT / "PIONEER" / "USBANLZ").rglob("*")
    ) == 1860

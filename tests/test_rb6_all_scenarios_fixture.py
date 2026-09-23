"""Rekordbox 6.8.0 全シナリオ fixture の構造検証。"""

import os
from pathlib import Path

import pytest
from rekordbox_pdb import Database

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter


DATA_DIR = Path(__file__).parent / "data"
FIXTURE_ROOT = DATA_DIR / "usb_fixtures" / "rkb680_all_scenarios"
DB_PATH = DATA_DIR / "rb680_database" / "master.db"


def _playlist_paths(database: Database) -> dict[int, str]:
    nodes = {
        node.id: (node.parent_id, node.name)
        for node in database.playlist_tree
    }
    paths = {}
    for node in database.playlist_tree:
        parts = [node.name]
        parent_id = node.parent_id
        while parent_id in nodes:
            parts.append(nodes[parent_id][1])
            parent_id = nodes[parent_id][0]
        paths[node.id] = "/".join(reversed(parts))
    return paths


def _entry_summaries(database: Database) -> dict[str, list[tuple[int, str, str]]]:
    paths = _playlist_paths(database)
    tracks = {track.id: track for track in database.tracks}
    summaries: dict[str, list[tuple[int, str, str]]] = {}
    for entry in database.playlist_entries:
        track = tracks.get(entry.track_id)
        leaf_name = paths.get(entry.playlist_id, "?").rsplit("/", 1)[-1]
        summaries.setdefault(leaf_name, []).append(
            (
                entry.entry_index,
                track.title if track else "",
                Path(track.filename).suffix.lower() if track else "",
            )
        )
    return summaries


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


def test_rb680_all_scenarios_db_generation_matches_reference_structure(
    tmp_path: Path,
) -> None:
    key = os.environ.get("RB6_DB_KEY")
    if not key:
        pytest.skip("set RB6_DB_KEY to run the encrypted RB6 database E2E")
    pytest.importorskip("pyrekordbox.db6")

    source_by_name = {
        path.name: path
        for path in (FIXTURE_ROOT / "Contents").rglob("*")
        if path.is_file()
    }
    exporter = RekordboxXMLExporter(
        str(DB_PATH),
        db_key=key,
        playlists=["SCENARIOS"],
        pdb_profile="rb6",
    )
    try:
        for content in exporter.db.get_content().all():
            source_name = Path(str(content.FolderPath)).name
            if source_name in source_by_name:
                content.FolderPath = str(source_by_name[source_name])
        usb_root = tmp_path / "usb"
        exporter.generate_device_export(str(usb_root))
    finally:
        exporter.close()

    generated = Database.from_file(
        usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    )
    reference = Database.from_file(
        FIXTURE_ROOT / "PIONEER" / "rekordbox" / "export.pdb"
    )

    assert len(generated.tracks) == len(reference.tracks) == 620
    assert len(generated.playlist_tree) == len(reference.playlist_tree) == 113
    assert len(generated.playlist_entries) == len(reference.playlist_entries) == 621
    assert set(_playlist_paths(generated).values()) == set(
        _playlist_paths(reference).values()
    )
    assert _entry_summaries(generated) == _entry_summaries(reference)
    assert sum(
        path.is_file() for path in (usb_root / "Contents").rglob("*")
    ) == 620

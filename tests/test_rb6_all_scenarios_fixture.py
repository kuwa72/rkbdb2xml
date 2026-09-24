"""Rekordbox 6.8.0 全シナリオ fixture の構造検証。"""

import os
import shutil
from collections import Counter
from pathlib import Path

import pytest
from rekordbox_pdb import Database

from rkbdb2xml.anlz import anlz_dir, existing_anlz_matches
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


def _tree_signature(database: Database) -> tuple:
    children: dict[int, list] = {}
    for node in database.playlist_tree:
        children.setdefault(node.parent_id, []).append(node)

    def visit(node):
        return (
            node.name,
            node.is_folder,
            node.sort_order,
            tuple(visit(child) for child in children.get(node.id, [])),
        )

    return tuple(visit(node) for node in children.get(0, []))


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


def _track_signatures(database: Database) -> Counter:
    def names(rows):
        return {row.id: row.name for row in rows}

    artists = names(database.artists)
    albums = names(database.albums)
    genres = names(database.genres)
    keys = names(database.keys)
    labels = names(database.labels)
    return Counter(
        (
            track.title,
            Path(track.filename).suffix.lower(),
            artists.get(track.artist_id),
            albums.get(track.album_id),
            genres.get(track.genre_id),
            keys.get(track.key_id),
            labels.get(track.label_id),
            track.duration,
            track.bitrate,
            track.sample_rate,
            track.sample_depth,
            track.file_size,
            track.tempo,
            track.rating,
            track.track_number,
            track.disc_number,
            track.year,
            track.comment,
        )
        for track in database.tracks
    )


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


def test_rb680_all_scenarios_anlz_layout_and_ppth() -> None:
    """キー不要で全620曲の Contents 相対パス・USBANLZ 配置・PPTH を検証する。

    ANLZ はハッシュ衝突時に実機が ``ANLZ0001`` 等の連番を振るため、
    照合の基準は ``ANLZ0000.DAT`` 固定ではなく DB の ``analyze_path``。
    """
    database = Database.from_file(
        FIXTURE_ROOT / "PIONEER" / "rekordbox" / "export.pdb"
    )
    contents = FIXTURE_ROOT / "Contents"
    on_disk = {
        "/Contents/" + path.relative_to(contents).as_posix()
        for path in contents.rglob("*")
        if path.is_file()
    }
    assert {track.file_path for track in database.tracks} == on_disk

    anlz_root = FIXTURE_ROOT / "PIONEER" / "USBANLZ"
    checked = 0
    for track in database.tracks:
        assert track.analyze_path, track.file_path
        anlz_file = FIXTURE_ROOT / track.analyze_path.lstrip("/")
        assert anlz_file.is_file(), track.analyze_path
        assert track.analyze_path.rsplit("/", 1)[0] == (
            f"/PIONEER/USBANLZ/{anlz_dir(track.file_path).as_posix()}"
        ), track.file_path
        assert existing_anlz_matches(anlz_file, track.file_path), (
            track.file_path
        )
        checked += 1
    assert checked == 620
    assert sum(
        path.is_file() for path in anlz_root.rglob("*")
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
    reference = Database.from_file(
        FIXTURE_ROOT / "PIONEER" / "rekordbox" / "export.pdb"
    )
    reference_analyze_paths = {
        track.filename: track.analyze_path
        for track in reference.tracks
        if track.analyze_path
    }
    exporter = RekordboxXMLExporter(
        str(DB_PATH),
        db_key=key,
        playlists=["SCENARIOS"],
        pdb_profile="rb6",
    )
    try:
        share_root = tmp_path / "share"
        shutil.copytree(
            FIXTURE_ROOT / "PIONEER" / "USBANLZ",
            share_root / "PIONEER" / "USBANLZ",
        )
        exporter.db._share_dir = share_root
        for content in exporter.db.get_content().all():
            source_name = Path(str(content.FolderPath)).name
            if source_name in source_by_name:
                content.FolderPath = str(source_by_name[source_name])
                content.AnalysisDataPath = reference_analyze_paths[source_name]
        usb_root = tmp_path / "usb"
        exporter.generate_device_export(str(usb_root))
    finally:
        exporter.close()

    generated = Database.from_file(
        usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    )
    assert len(generated.tracks) == len(reference.tracks) == 620
    assert _track_signatures(generated) == _track_signatures(reference)
    assert len(generated.playlist_tree) == len(reference.playlist_tree) == 113
    assert len(generated.playlist_entries) == len(reference.playlist_entries) == 621
    assert _tree_signature(generated) == _tree_signature(reference)
    assert _entry_summaries(generated) == _entry_summaries(reference)
    assert sum(
        path.is_file() for path in (usb_root / "Contents").rglob("*")
    ) == 620
    anlz_root = usb_root / "PIONEER" / "USBANLZ"
    assert sum(path.is_file() for path in anlz_root.rglob("*")) == 1860
    for track in generated.tracks:
        dat_path = anlz_root / anlz_dir(track.file_path) / "ANLZ0000.DAT"
        assert dat_path.is_file(), track.file_path
        assert existing_anlz_matches(dat_path, track.file_path), track.file_path

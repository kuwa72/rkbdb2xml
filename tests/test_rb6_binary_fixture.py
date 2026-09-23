"""Rekordbox 6.8.0 実出力とのバイナリ差分を固定するテスト。

このモジュールの参照値は、RB6.8.0 の `master.db` および USB 出力から
回収した fixture であり、RB5 fixture とは混ぜない。キー不要の最小 canary は
同梱 XML スナップショットから `pdb_profile="rb6"` で生成し、実 `master.db`
からの経路は `RB6_DB_KEY` を設定した E2E テストで検証する。
"""

import os
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict

import pytest
from rekordbox_pdb import Database

import rkbdb2xml.rkbdb2xml as rkbdb2xml_module
from rkbdb2xml.pdb_export import PdbExporter
from tests.test_fixture_comparison import (
    XmlContent,
    _AnlzDb,
    _build_node,
    _find_folder,
)

DATA_DIR = Path(__file__).parent / "data"
RB6_DB_DIR = DATA_DIR / "rb680_database"
RB6_INPUT_XML = DATA_DIR / "fixture_input" / "rekordbox.xml"
RB6_ROOT = DATA_DIR / "usb_fixtures" / "rkb680_sc01_one_ascii"
RB6_PDB = RB6_ROOT / "PIONEER" / "rekordbox" / "export.pdb"


def _page_header(data: bytes, page: int) -> Dict[str, int]:
    offset = page * 4096
    return {
        "page": struct.unpack_from("<I", data, offset + 4)[0],
        "type": struct.unpack_from("<I", data, offset + 8)[0],
        "next": struct.unpack_from("<I", data, offset + 12)[0],
        "sequence": struct.unpack_from("<I", data, offset + 16)[0],
        "tx20": struct.unpack_from("<H", data, offset + 0x20)[0],
        "tx22": struct.unpack_from("<H", data, offset + 0x22)[0],
    }


def _directory(data: bytes, table: int) -> tuple:
    return struct.unpack_from("<IIII", data, 0x1C + table * 16)


def _generate_rb6_export(tmp_path: Path) -> Path:
    reference_db = Database.from_file(RB6_PDB)
    xml_root = ET.parse(RB6_INPUT_XML).getroot()
    folder = _find_folder(xml_root, "SC01_one_ascii")
    assert folder is not None
    tree = _build_node(folder)
    if tree.is_folder and len(tree.children) == 1:
        tree = tree.children[0]

    tracks = {
        element.attrib["TrackID"]: XmlContent(element)
        for element in xml_root.find("COLLECTION")
    }
    expected_paths = {track.filename: track.file_path
                      for track in reference_db.tracks}
    reference_key = reference_db.keys[0].name if reference_db.keys else ""
    for content in tracks.values():
        if not content.KeyName:
            content.KeyName = reference_key
    usb_root = tmp_path / "usb"
    content_map: Dict[str, Any] = {}
    copy_map: Dict[str, Path] = {}
    for content_id, content in tracks.items():
        basename = Path(content.FolderPath).name
        destination = usb_root / expected_paths.get(
            basename, f"/Contents/{basename}"
        ).lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"audio")
        content_map[content_id] = content
        copy_map[content.FolderPath] = destination

    return PdbExporter(_AnlzDb(), pdb_profile="rb6").build(
        usb_root=usb_root,
        playlist_tree=[tree],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )


def test_explicit_rb6_key_is_passed_as_key(monkeypatch) -> None:
    captured = {}

    class FakeDatabase:
        def __init__(self, path, *args, **kwargs):
            captured["path"] = path
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(
        rkbdb2xml_module, "RekordboxDatabase", FakeDatabase
    )
    exporter = object.__new__(rkbdb2xml_module.RekordboxXMLExporter)
    exporter._connect_to_database("master.db", "secret-key")

    assert captured == {
        "path": "master.db",
        "args": (),
        "kwargs": {"key": "secret-key"},
    }


def test_rb6_db_and_reference_output_are_paired() -> None:
    assert (RB6_DB_DIR / "master.db").is_file()
    assert (RB6_DB_DIR / "datafile.edb").is_file()
    assert (RB6_DB_DIR / "masterPlaylists6.xml").is_file()
    assert RB6_PDB.is_file()
    assert (RB6_ROOT / "PIONEER" / "rekordbox" / "exportExt.pdb").is_file()


def test_rb6_db_input_reaches_device_export(tmp_path: Path) -> None:
    key = os.environ.get("RB6_DB_KEY")
    if not key:
        pytest.skip("set RB6_DB_KEY to run the encrypted RB6 database E2E")

    pytest.importorskip("pyrekordbox.db6")
    exporter = rkbdb2xml_module.RekordboxXMLExporter(
        str(RB6_DB_DIR / "master.db"),
        db_key=key,
        playlists=["SCENARIOS/SC01_one_ascii/SC01 one_ascii"],
        pdb_profile="rb6",
    )
    try:
        source = RB6_ROOT / "Contents" / "Artist" / "Album" / "trk_00001.mp3"
        local_audio = tmp_path / "audio" / "trk_00001.mp3"
        local_audio.parent.mkdir(parents=True)
        shutil.copyfile(source, local_audio)
        for content in exporter.db.get_content().all():
            if str(content.FolderPath).endswith("trk_00001.mp3"):
                content.FolderPath = str(local_audio)
        usb_root = tmp_path / "usb"
        exporter.generate_device_export(str(usb_root))
    finally:
        exporter.close()

    generated_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert generated_path.is_file()
    generated = Database.from_file(generated_path)
    reference = Database.from_file(RB6_PDB)

    assert len(generated.tracks) == len(reference.tracks) == 1
    generated_track = generated.tracks[0]
    reference_track = reference.tracks[0]
    assert generated_track.title == reference_track.title
    assert generated_track.bitmask == reference_track.bitmask
    assert generated_track.strings[2:4] == reference_track.strings[2:4]
    assert generated_track.duration == reference_track.duration
    assert generated_track.file_size == reference_track.file_size
    assert generated_track.tempo == reference_track.tempo
    assert generated_track.filename.endswith(".mp3")

    assert (
        len(generated.playlist_entries)
        == len(reference.playlist_entries)
        == 1
    )
    assert {
        node.name for node in generated.playlist_tree if not node.is_folder
    } == {
        node.name for node in reference.playlist_tree if not node.is_folder
    }


def test_rb6_track_row_profile_matches_reference(tmp_path: Path) -> None:
    generated_path = _generate_rb6_export(tmp_path)
    reference = Database.from_file(RB6_PDB).tracks[0]
    generated = Database.from_file(generated_path).tracks[0]

    assert generated.bitmask == reference.bitmask == 0x000C0700
    assert generated.strings[2:4] == reference.strings[2:4]
    assert generated.strings[6] == reference.strings[6] == "ON"
    assert generated.strings[7] == reference.strings[7] == "ON"
    assert generated.file_path == reference.file_path


def test_rb6_page_zero_header_matches_reference(tmp_path: Path) -> None:
    generated_path = _generate_rb6_export(tmp_path)
    reference = RB6_PDB.read_bytes()
    generated = generated_path.read_bytes()

    assert struct.unpack_from("<I", reference, 12)[0] == 53
    assert struct.unpack_from("<I", generated, 12)[0] == 53
    assert struct.unpack_from("<I", generated, 20)[0] == 13


def test_rb6_dynamic_page_headers_match_reference(tmp_path: Path) -> None:
    generated_path = _generate_rb6_export(tmp_path)
    generated = generated_path.read_bytes()
    expected = {
        2: (51, 11, 1, 0),
        4: (48, 8, 1, 0),
        6: (47, 7, 1, 0),
        8: (49, 9, 1, 0),
        16: (46, 6, 1, 0),
        18: (52, 12, 1, 0),
    }
    for page, values in expected.items():
        header = _page_header(generated, page)
        assert (header["next"], header["sequence"],
                header["tx20"], header["tx22"]) == values, page


def test_rb6_table_directory_matches_reference(tmp_path: Path) -> None:
    generated_path = _generate_rb6_export(tmp_path)
    reference = RB6_PDB.read_bytes()
    generated = generated_path.read_bytes()
    for table in (0, 1, 3, 8):
        assert (
            _directory(generated, table) == _directory(reference, table)
        ), table


def test_rb6_static_table_pages_match_reference(tmp_path: Path) -> None:
    generated_path = _generate_rb6_export(tmp_path)
    reference = RB6_PDB.read_bytes()
    generated = generated_path.read_bytes()
    for table in (6, 16, 17, 18, 19):
        first = 1 + 2 * table
        for page in (first, first + 1):
            assert generated[page * 4096:(page + 1) * 4096] == \
                reference[page * 4096:(page + 1) * 4096], (table, page)


def test_rb6_device_settings_match_reference(tmp_path: Path) -> None:
    generated_pdb = _generate_rb6_export(tmp_path)
    generated_pioneer = generated_pdb.parents[1]
    reference_pioneer = RB6_ROOT / "PIONEER"
    for name in (
        "DEVSETTING.DAT",
        "MYSETTING.DAT",
        "MYSETTING2.DAT",
        "DJMMYSETTING.DAT",
    ):
        assert (generated_pioneer / name).read_bytes() == \
            (reference_pioneer / name).read_bytes(), name


def test_rb6_binary_diff_baseline_is_limited_to_opaque_row_ids(
    tmp_path: Path,
) -> None:
    generated_path = _generate_rb6_export(tmp_path)
    reference = RB6_PDB.read_bytes()
    generated = generated_path.read_bytes()
    page_diffs = []
    for page in range(len(generated) // 4096):
        count = sum(
            a != b
            for a, b in zip(
                generated[page * 4096:(page + 1) * 4096],
                reference[page * 4096:(page + 1) * 4096],
            )
        )
        if count:
            page_diffs.append((page, count))

    # The remaining bytes are opaque Rekordbox row IDs/unique values which
    # the current editor does not expose. Keep this as a visible baseline;
    # page layout and semantic fields are asserted separately above.
    assert page_diffs == [(2, 11), (8, 1)]

"""Tests for CDJ-compatible DeviceSQL export."""

from pathlib import Path
from typing import Any, Dict

import pytest

from rekordbox_pdb import Database

from rkbdb2xml.pdb_export import (
    PdbExporter,
    DevicePdbNode,
    DevicePdbXml,
    create_empty_pdb,
)


class FakeDb:
    """Minimal database stub for ANLZ path lookup."""

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {}


class FakeContent:
    """Minimal DjmdContent-like object for unit tests."""

    def __init__(self, cid: str, title: str, folder_path: str,
                 ext: str = ".mp3") -> None:
        self.ID = cid
        self.Title = title
        self.FolderPath = folder_path
        self.ext = ext
        self.ArtistName = "Artist"
        self.AlbumName = "Album"
        self.GenreName = "House"
        self.KeyName = "Am"
        self.BPM = 12800
        self.Length = 240
        self.BitRate = 320
        self.SampleRate = 44100
        self.BitDepth = 16
        self.FileSize = 8_000_000
        self.TrackNo = 1
        self.DiscNo = 1
        self.ReleaseYear = 2025
        self.DateCreated = "2025-01-01"


@pytest.fixture
def usb_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a USB root with a copied dummy audio file."""
    usb_root = tmp_path / "usb"
    contents = usb_root / "Contents"
    contents.mkdir(parents=True)
    dest = contents / "abc123.mp3"
    dest.write_bytes(b"dummy audio")
    return usb_root, contents, dest


def test_create_empty_pdb_is_valid() -> None:
    data = create_empty_pdb()
    assert len(data) == 41 * 4096

    # A valid empty PDB can be loaded and populated by PdbEditor.
    from rekordbox_pdb.edit import PdbEditor

    ed = PdbEditor(data)
    tid = ed.add_track(title="T", file_path="/Contents/t.mp3")
    assert tid == 1


def test_device_pdb_xml_records_tree() -> None:
    xml = DevicePdbXml()
    folder = xml._root_node.add_playlist_folder("Folder")
    playlist = folder.add_playlist("Playlist")
    playlist.add_track("1")
    playlist.add_track("2")

    assert len(xml._root_node.children) == 1
    assert xml._root_node.children[0].is_folder
    assert len(xml._root_node.children[0].children) == 1
    assert xml._root_node.children[0].children[0].tracks == ["1", "2"]


def test_pdb_exporter_builds_export(usb_tree: tuple[Path, Path, Path]) -> None:
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}
    track_options: Dict[str, Dict[str, Any]] = {
        "1": {"roman": False, "bpm": True},
    }

    playlist = DevicePdbNode("My Playlist", is_folder=False)
    playlist.add_track("1")

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options=track_options,
    )

    assert pdb_path == usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert pdb_path.exists()

    db = Database.from_file(pdb_path)
    assert len(db.tracks) == 1
    track = db.tracks[0]
    assert track.title == "128 Test Track"  # BPM prefix applied
    assert track.file_path == "/Contents/abc123.mp3"
    artists = {a.id: a.name for a in db.artists}
    albums = {a.id: a.name for a in db.albums}
    assert artists[track.artist_id] == "Artist"
    assert albums[track.album_id] == "Album"

    assert len(db.playlist_tree) == 1
    assert db.playlist_tree[0].name == "My Playlist"
    assert len(db.playlist_entries) == 1
    assert db.playlist_entries[0].track_id == track.id


def test_pdb_exporter_honors_romanization(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    usb_root, _contents, dest = usb_tree
    content = FakeContent("2", "テスト", "/source/test.mp3")
    content_map: Dict[str, Any] = {"2": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}
    track_options: Dict[str, Dict[str, Any]] = {
        "2": {"roman": True, "bpm": False}
    }

    playlist = DevicePdbNode("Playlist", is_folder=False)
    playlist.add_track("2")

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options=track_options,
    )

    db = Database.from_file(pdb_path)
    assert len(db.tracks) == 1
    track = db.tracks[0]
    assert track.title.isascii()


def test_pdb_exporter_nested_folders(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    usb_root, _contents, dest = usb_tree
    content = FakeContent("3", "Nested", "/source/test.mp3")
    content_map: Dict[str, Any] = {"3": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    folder = DevicePdbNode("Root", is_folder=True)
    sub = folder.add_playlist_folder("Sub")
    pl = sub.add_playlist("Tracks")
    pl.add_track("3")

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[folder],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    nodes = {n.id: n for n in db.playlist_tree}
    assert len(nodes) == 3
    root = next(n for n in db.playlist_tree if n.name == "Root")
    sub_node = next(n for n in db.playlist_tree if n.name == "Sub")
    pl_node = next(n for n in db.playlist_tree if n.name == "Tracks")
    assert sub_node.parent_id == root.id
    assert pl_node.parent_id == sub_node.id


def test_pdb_exporter_skips_missing_copy(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    usb_root, _contents, _dest = usb_tree
    content = FakeContent("4", "Missing", "/source/missing.mp3")
    content_map: Dict[str, Any] = {"4": content}
    copy_map: Dict[str, Path] = {}

    playlist = DevicePdbNode("Pl", is_folder=False)
    playlist.add_track("4")

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    assert len(db.tracks) == 0
    assert len(db.playlist_entries) == 0

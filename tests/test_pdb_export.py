"""Tests for CDJ-compatible DeviceSQL export."""

import threading
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


class FakeDbWithAnlz(FakeDb):
    """Database stub that reports a DAT analysis file for every track."""

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {
            "DAT": Path("/anlz/ANLZ0000.DAT"),
            "EXT": Path("/anlz/ANLZ0000.EXT"),
            "2EX": None,
        }


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


def test_pdb_exporter_sets_analyze_path_when_anlz_exists(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """ANLZ を持つトラックは analyze_path に USBANLZ の実パスが入る。

    実機の export.pdb では ``/PIONEER/USBANLZ/P<ppp>/<hash>/ANLZ0000.DAT``
    が書かれており、プレイヤーはこのフィールドで解析データを引く。
    空のままだと BPM/グリッド/波形が出ない（退行防止）。
    """
    from rkbdb2xml.anlz import anlz_dir

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    playlist = _playlist_with("1")

    exporter = PdbExporter(FakeDbWithAnlz())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    track = db.tracks[0]
    expected = (
        f"/PIONEER/USBANLZ/"
        f"{anlz_dir(track.file_path).as_posix()}/ANLZ0000.DAT"
    )
    assert track.analyze_path == expected


def test_pdb_exporter_empty_analyze_path_without_anlz(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """ANLZ がないトラックは analyze_path が空のまま。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    assert db.tracks[0].analyze_path == ""


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
    with pytest.raises(RuntimeError) as exc_info:
        exporter.build(
            usb_root=usb_root,
            playlist_tree=[playlist],
            content_map=content_map,
            copy_map=copy_map,
            track_options={},
        )
    assert "USB Contents へのコピーが見つかりません" in str(exc_info.value)


# ----- キャンセルと原子的書き込み（Issue #14） -----------------------------------------


def _playlist_with(
    content_id: str, name: str = "My Playlist"
) -> DevicePdbNode:
    playlist = DevicePdbNode(name, is_folder=False)
    playlist.add_track(content_id)
    return playlist


def test_pdb_exporter_pre_cancelled_writes_nothing(
    usb_tree: tuple[Path, Path, Path],
) -> None:
    """キャンセル済みなら export.pdb も一時ファイルも書かない。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    cancel_event = threading.Event()
    cancel_event.set()

    exporter = PdbExporter(FakeDb())
    result = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
        cancel_event=cancel_event,
    )

    assert result is None
    pdb_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert not pdb_path.exists()
    assert not pdb_path.with_name("export.pdb.tmp").exists()


def test_pdb_exporter_cancelled_mid_build_writes_nothing(
    usb_tree: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """構築途中のキャンセルでは、未完成 PDB を USB に残さない。"""
    from rekordbox_pdb.edit import PdbEditor

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    cancel_event = threading.Event()
    orig_create_playlist = PdbEditor.create_playlist

    def cancelling_create(*a, **kw):
        cancel_event.set()
        return orig_create_playlist(*a, **kw)

    monkeypatch.setattr(PdbEditor, "create_playlist", cancelling_create)

    exporter = PdbExporter(FakeDb())
    result = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
        cancel_event=cancel_event,
    )

    assert result is None
    pdb_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert not pdb_path.exists()
    assert not pdb_path.with_name("export.pdb.tmp").exists()


def test_pdb_exporter_writes_atomically_leaves_no_tmp(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """正常時: export.pdb だけが残り、一時ファイルは残らない。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    assert pdb_path == usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert pdb_path.exists()
    assert not pdb_path.with_name("export.pdb.tmp").exists()
    db = Database.from_file(pdb_path)  # 読める = 完全なファイル
    assert len(db.tracks) == 1


def test_pdb_exporter_failed_save_keeps_previous_pdb(
    usb_tree: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """書き込み失敗時: 一時ファイルを削除し、既存の export.pdb は無傷のまま。"""
    from rekordbox_pdb.edit import PdbEditor

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )
    old_bytes = pdb_path.read_bytes()

    def failing_save(self, path: Path) -> None:
        Path(path).write_bytes(b"garbage")  # 途中で壊れた tmp を残す
        raise OSError("disk full")

    monkeypatch.setattr(PdbEditor, "save", failing_save)

    with pytest.raises(OSError):
        exporter.build(
            usb_root=usb_root,
            playlist_tree=[_playlist_with("1")],
            content_map=content_map,
            copy_map=copy_map,
            track_options={},
        )

    assert pdb_path.read_bytes() == old_bytes, "旧 export.pdb は上書きされない"
    assert not pdb_path.with_name("export.pdb.tmp").exists()


def test_pdb_exporter_cancelled_during_anlz_keeps_complete_pdb(
    usb_tree: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ANLZ コピー中のキャンセル: export.pdb は完成済みのまま残る。"""
    import rkbdb2xml.pdb_export as pdb_mod

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    cancel_event = threading.Event()

    def set_cancel(*a, **kw):
        cancel_event.set()

    monkeypatch.setattr(pdb_mod.anlz, "copy_anlz_for_content", set_cancel)

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
        cancel_event=cancel_event,
    )

    assert pdb_path is not None
    db = Database.from_file(pdb_path)
    assert len(db.tracks) == 1  # PDB は書き換え済みで完全
    assert not pdb_path.with_name("export.pdb.tmp").exists()

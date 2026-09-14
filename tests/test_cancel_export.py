"""エクスポート途中キャンセル（Issue #14）のテスト。

``threading.Event`` を各エクスポート関数に渡すと、ファイルコピーのループが
次のトラックの手前で停止し、部分コピー済みの Contents はそのまま残る。
export.pdb は一時ファイル経由の原子的書き込みになるため、キャンセル時には
未完成の PDB が USB 上に現れない。
"""

import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest

import rkbdb2xml.rkbdb2xml as rkbdb2xml_mod
from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter


class FakeQuery:
    def __init__(self, items: List[Any]) -> None:
        self._items = items

    def all(self) -> List[Any]:
        return self._items

    def __iter__(self):
        return iter(self._items)


class FakeDb:
    def __init__(self, playlists: List[Any], contents: List[Any]) -> None:
        self._playlists = playlists
        self._contents = contents

    def get_playlist(self) -> FakeQuery:
        return FakeQuery(self._playlists)

    def get_content(self) -> FakeQuery:
        return FakeQuery(self._contents)

    def get_playlist_contents(self, playlist: Any) -> FakeQuery:
        track_ids = set(str(t) for t in getattr(playlist, "track_ids", []))
        return FakeQuery([c for c in self._contents if str(c.ID) in track_ids])

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {}

    def close(self) -> None:
        pass


class FakePlaylist:
    def __init__(self, pid: str, name: str, parent_id: str) -> None:
        self.ID = pid
        self.Name = name
        self.ParentID = parent_id
        self.is_folder = False
        self.is_playlist = True
        self.track_ids: List[str] = []


class FakeContent:
    def __init__(self, cid: str, title: str, folder_path: str) -> None:
        self.ID = cid
        self.Title = title
        self.FolderPath = folder_path
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


def make_exporter(db: FakeDb) -> RekordboxXMLExporter:
    exporter = object.__new__(RekordboxXMLExporter)
    exporter.db = db
    exporter._playlists = ["My Playlist"]
    exporter._selected_track_ids = {str(c.ID) for c in db._contents}
    exporter._playlist_options = {
        "My Playlist": {"roman": False, "bpm": False, "orderby": "default"},
    }
    exporter._track_options = {}
    exporter._copy_map = {}
    exporter._verbose = False
    exporter._roman_converter = None
    return exporter


def write_audio(tmp_path: Path, name: str, size: int) -> Path:
    src = tmp_path / name
    src.write_bytes(bytes([65 + size % 26]) * size)
    return src


# ----- _copy_files のキャンセル -------------------------------------------------


def test_copy_files_pre_cancelled_copies_nothing(tmp_path: Path) -> None:
    src_a = write_audio(tmp_path, "a.mp3", 1000)
    src_b = write_audio(tmp_path, "b.mp3", 3000)
    contents = [
        FakeContent("1", "A", str(src_a)),
        FakeContent("2", "B", str(src_b)),
    ]
    exporter = make_exporter(FakeDb([], contents))
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    cancel_event = threading.Event()
    cancel_event.set()
    calls: List[tuple] = []
    exporter._copy_files(
        export_dir,
        progress_cb=lambda *a: calls.append(a),
        cancel_event=cancel_event,
    )

    assert list(export_dir.iterdir()) == []
    assert calls == [], "事前キャンセル時は進捗コールバックも呼ばない"


def test_copy_files_cancelled_midway_stops_before_next_track(
    tmp_path: Path,
) -> None:
    """1 曲目完了の報告直後にキャンセルすると、2 曲目はコピーされない。

    キャンセル時点までに完了したファイルは残る（後始末はしない）。
    """
    src_a = write_audio(tmp_path, "a.mp3", 1000)
    src_b = write_audio(tmp_path, "b.mp3", 3000)
    src_c = write_audio(tmp_path, "c.mp3", 2000)
    contents = [
        FakeContent("1", "A", str(src_a)),
        FakeContent("2", "B", str(src_b)),
        FakeContent("3", "C", str(src_c)),
    ]
    exporter = make_exporter(FakeDb([], contents))
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    cancel_event = threading.Event()
    calls: List[tuple] = []

    def progress(done, total, done_bytes, total_bytes):
        calls.append((done, total, done_bytes, total_bytes))
        if done == 1:
            cancel_event.set()

    exporter._copy_files(
        export_dir,
        progress_cb=progress,
        cancel_event=cancel_event,
    )

    assert len(list(export_dir.iterdir())) == 1, "次のトラックのコピーを開始しない"
    assert calls == [(0, 3, 0, 6000), (1, 3, 1000, 6000)]


def test_copy_files_cancel_reports_remaining_count_in_verbose_log(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    src_a = write_audio(tmp_path, "a.mp3", 1000)
    src_b = write_audio(tmp_path, "b.mp3", 3000)
    contents = [
        FakeContent("1", "A", str(src_a)),
        FakeContent("2", "B", str(src_b)),
    ]
    exporter = make_exporter(FakeDb([], contents))
    exporter._verbose = True
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    cancel_event = threading.Event()

    def progress(done, total, done_bytes, total_bytes):
        if done == 1:
            cancel_event.set()

    exporter._copy_files(
        export_dir,
        progress_cb=progress,
        cancel_event=cancel_event,
    )

    captured = capsys.readouterr()
    assert "キャンセルされました" in captured.out
    assert "残り 1 件" in captured.out, "どこまで処理済みかをログで報告する"


# ----- generate_xml のキャンセル -------------------------------------------------


def test_xml_export_cancelled_mid_copy_keeps_original_locations(
    tmp_path: Path,
) -> None:
    """キャンセル時は XML の Location を書き換えない（元の参照のまま）。"""
    src_a = write_audio(tmp_path, "a.mp3", 1000)
    src_b = write_audio(tmp_path, "b.mp3", 2000)
    content_a = FakeContent("1", "A", str(src_a))
    content_b = FakeContent("2", "B", str(src_b))
    playlist = FakePlaylist("101", "My Playlist", "0")
    playlist.track_ids = ["1", "2"]
    exporter = make_exporter(FakeDb([playlist], [content_a, content_b]))
    export_dir = tmp_path / "sub"
    export_dir.mkdir()  # GUI は出力先フォルダを作成してから export を呼ぶ
    xml_path = export_dir / "rekordbox.xml"

    cancel_event = threading.Event()

    def progress(done, total, done_bytes, total_bytes):
        if done == 1:
            cancel_event.set()

    exporter.generate_xml(
        str(xml_path),
        progress_cb=progress,
        cancel_event=cancel_event,
    )

    assert xml_path.exists(), "XML 本体はキャンセル前に書き出されている"
    assert len(list(export_dir.iterdir())) == 2  # rekordbox.xml + コピー済み 1 件
    import xml.etree.ElementTree as ET

    tree = ET.parse(xml_path)
    locations = [
        track.attrib.get("Location") for track in tree.findall(".//TRACK")
    ]
    # コレクションの 2 曲は元の参照のまま（コピー先 export_dir を指さない）
    non_null = [loc for loc in locations if loc is not None]
    assert len(non_null) == 2
    assert all("sub" not in loc for loc in non_null)


def test_xml_export_pre_cancelled_writes_no_xml(tmp_path: Path) -> None:
    src = write_audio(tmp_path, "a.mp3", 1000)
    content = FakeContent("1", "A", str(src))
    playlist = FakePlaylist("101", "My Playlist", "0")
    playlist.track_ids = ["1"]
    exporter = make_exporter(FakeDb([playlist], [content]))
    export_dir = tmp_path / "sub"
    xml_path = export_dir / "rekordbox.xml"

    cancel_event = threading.Event()
    cancel_event.set()

    exporter.generate_xml(str(xml_path), cancel_event=cancel_event)

    assert not xml_path.exists()
    assert not export_dir.exists()


# ----- generate_device_export のキャンセル -----------------------------------------


def test_device_export_pre_cancelled_writes_nothing(tmp_path: Path) -> None:
    src = write_audio(tmp_path, "a.mp3", 1000)
    content = FakeContent("1", "A", str(src))
    playlist = FakePlaylist("101", "My Playlist", "0")
    playlist.track_ids = ["1"]
    exporter = make_exporter(FakeDb([playlist], [content]))
    usb_root = tmp_path / "usb"

    cancel_event = threading.Event()
    cancel_event.set()

    exporter.generate_device_export(str(usb_root), cancel_event=cancel_event)

    assert not (usb_root / "Contents").exists()
    assert not (usb_root / "PIONEER" / "rekordbox" / "export.pdb").exists()


def test_device_export_cancelled_mid_copy_skips_pdb(tmp_path: Path) -> None:
    """コピー途中のキャンセルでは export.pdb を書かず、部分 Contents は残る。"""
    src_a = write_audio(tmp_path, "a.mp3", 1000)
    src_b = write_audio(tmp_path, "b.mp3", 2000)
    content_a = FakeContent("1", "A", str(src_a))
    content_b = FakeContent("2", "B", str(src_b))
    playlist = FakePlaylist("101", "My Playlist", "0")
    playlist.track_ids = ["1", "2"]
    exporter = make_exporter(FakeDb([playlist], [content_a, content_b]))
    usb_root = tmp_path / "usb"
    usb_root.mkdir()

    cancel_event = threading.Event()

    def progress(done, total, done_bytes, total_bytes):
        if done == 1:
            cancel_event.set()

    exporter.generate_device_export(
        str(usb_root),
        progress_cb=progress,
        cancel_event=cancel_event,
    )

    pdb_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert not pdb_path.exists(), "未完成 PDB は書かない"
    copied = list((usb_root / "Contents").iterdir())
    assert len(copied) == 1, "キャンセル時点までの Contents は残す"


# ----- トップレベル関数の cancel_event 転送 -----------------------------------------


class FakeExporter:
    """generate_xml / generate_device_export の引数を記録するだけのスタブ。"""

    def __init__(self, *a: Any, **kw: Any) -> None:
        self.calls: List[tuple] = []

    def generate_xml(self, path, progress_cb=None, phase_cb=None,
                     cancel_event=None) -> None:
        self.calls.append(("xml", path, progress_cb, phase_cb, cancel_event))

    def generate_device_export(self, usb_root, progress_cb=None,
                               phase_cb=None, cancel_event=None) -> None:
        self.calls.append(("device", usb_root, progress_cb, phase_cb,
                           cancel_event))

    def close(self) -> None:
        pass


def test_top_level_functions_forward_cancel_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeExporter()
    monkeypatch.setattr(
        rkbdb2xml_mod, "RekordboxXMLExporter", lambda *a, **kw: fake
    )
    cancel_event = threading.Event()

    rkbdb2xml_mod.export_rekordbox_db_to_xml(
        None, "/tmp/out.xml", cancel_event=cancel_event
    )
    rkbdb2xml_mod.export_rekordbox_db_to_device(
        None, "/tmp/usb", cancel_event=cancel_event
    )

    assert fake.calls[0] == ("xml", "/tmp/out.xml", None, None, cancel_event)
    assert fake.calls[1] == ("device", "/tmp/usb", None, None, cancel_event)


def test_top_level_functions_work_without_cancel_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cancel_event 未指定（既定 None）でも既存呼び出し形式は壊れない。"""
    fake = FakeExporter()
    monkeypatch.setattr(
        rkbdb2xml_mod, "RekordboxXMLExporter", lambda *a, **kw: fake
    )

    rkbdb2xml_mod.export_rekordbox_db_to_xml(None, "/tmp/out.xml")

    assert fake.calls[0] == ("xml", "/tmp/out.xml", None, None, None)

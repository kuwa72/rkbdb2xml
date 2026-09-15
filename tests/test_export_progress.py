"""Progress callback (count/bytes) and ETA helper tests.

``_copy_files`` は選択トラックごとに ``progress_cb(done, total, done_bytes,
total_bytes)`` を呼ぶ。呼び出しが無い場合（既存の全呼び出し元）の挙動を
壊さないこと、バイト数が実ファイルサイズと一致すること、フェーズ通知が
XML / USB の順序どおりに来ることを検証する。GUI の ETA 計算はウィンドウ
ベースの直近平均速度で行うため、``EtaEstimator`` を単体でテストする。
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List

import pytest

import rkbdb2xml.rkbdb2xml as rkbdb2xml_mod
from rkbdb2xml.gui import EtaEstimator, format_eta
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


# ----- _copy_files の progress_cb -------------------------------------------------


def test_copy_files_reports_counts_and_bytes(tmp_path: Path) -> None:
    src_a = tmp_path / "a.mp3"
    src_a.write_bytes(b"A" * 1000)
    src_b = tmp_path / "b.mp3"
    src_b.write_bytes(b"B" * 3000)
    contents = [
        FakeContent("1", "A", str(src_a)),
        FakeContent("2", "B", str(src_b)),
    ]
    exporter = make_exporter(FakeDb([], contents))
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    calls: List[tuple] = []
    exporter._copy_files(export_dir, progress_cb=lambda *a: calls.append(a))

    total = 4000
    assert calls[0] == (0, 2, 0, total)
    assert calls[-1] == (2, 2, total, total)
    # 途中の呼び出しも単調増加し、done_bytes は処理済みファイルの合計と一致する
    for done, tot, done_bytes, tot_bytes in calls:
        assert tot == 2
        assert tot_bytes == total
        assert 0 <= done_bytes <= total
    assert [c[0] for c in calls] == sorted(c[0] for c in calls)
    assert calls[1] == (1, 2, 1000, total) or calls[1] == (1, 2, 3000, total)


def test_copy_files_without_callback_still_copies(tmp_path: Path) -> None:
    src = tmp_path / "a.mp3"
    src.write_bytes(b"data")
    content = FakeContent("1", "A", str(src))
    exporter = make_exporter(FakeDb([], [content]))
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    exporter._copy_files(export_dir)  # progress_cb=None の既存呼び出し形式

    assert list(export_dir.iterdir()), "ファイルがコピーされていない"
    assert len(exporter._copy_map) > 0


def test_copy_files_counts_already_copied_files_as_done(tmp_path: Path) -> None:
    src = tmp_path / "a.mp3"
    src.write_bytes(b"x" * 100)
    content = FakeContent("1", "A", str(src))
    exporter = make_exporter(FakeDb([], [content]))
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    exporter._copy_files(export_dir)
    calls: List[tuple] = []
    exporter._copy_files(export_dir, progress_cb=lambda *a: calls.append(a))

    # 2 回目はコピーをスキップする。件数は全件処理済みで報告するが、
    # バイト側はスキップ分を含めない（issue #24: ETA の水増し防止）。
    assert calls == [(0, 1, 0, 0), (1, 1, 0, 0)]


def test_copy_files_excludes_skipped_files_from_byte_progress(tmp_path: Path) -> None:
    """Issue #24: already-written files finish instantly, so their bytes
    must not enter total_bytes/done_bytes — otherwise the measured copy
    speed is inflated and the ETA reads far too short."""
    src_skip = tmp_path / "skip.mp3"
    src_skip.write_bytes(b"S" * 7000)
    src_new = tmp_path / "new.mp3"
    src_new.write_bytes(b"N" * 1000)
    contents = [
        FakeContent("1", "Skip", str(src_skip)),
        FakeContent("2", "New", str(src_new)),
    ]
    exporter = make_exporter(FakeDb([], contents))
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    # Pre-create src_skip's destination (md5-of-source-path filename).
    md5_hex = hashlib.md5(str(src_skip).encode("utf-8")).hexdigest()
    (export_dir / f"{md5_hex}.mp3").write_bytes(b"old")

    calls: List[tuple] = []
    exporter._copy_files(export_dir, progress_cb=lambda *a: calls.append(a))

    pending = 1000  # only the file that actually needs copying
    assert calls[0] == (0, 2, 0, pending)
    assert calls[-1] == (2, 2, pending, pending)
    for _done, _tot, done_bytes, tot_bytes in calls:
        assert tot_bytes == pending
        assert 0 <= done_bytes <= pending


# ----- generate_xml の進捗・フェーズ -------------------------------------------------


def test_xml_export_reports_progress_and_phases(tmp_path: Path) -> None:
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"dummy audio data")
    content = FakeContent("1", "Test Track", str(audio))
    playlist = FakePlaylist("101", "My Playlist", "0")
    playlist.track_ids = ["1"]
    exporter = make_exporter(FakeDb([playlist], [content]))

    calls: List[tuple] = []
    phases: List[str] = []
    exporter.generate_xml(
        str(tmp_path / "rekordbox.xml"),
        progress_cb=lambda *a: calls.append(a),
        phase_cb=phases.append,
    )

    assert phases == ["ファイルコピー中", "XML 書き込み中"]
    size = len(b"dummy audio data")
    assert calls[0] == (0, 1, 0, size)
    assert calls[-1] == (1, 1, size, size)


# ----- generate_device_export の進捗・フェーズ ---------------------------------------


def test_device_export_reports_progress_and_phases(tmp_path: Path) -> None:
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"dummy audio data")
    usb_root = tmp_path / "usb"
    usb_root.mkdir()
    content = FakeContent("1", "Test Track", str(audio))
    playlist = FakePlaylist("101", "My Playlist", "0")
    playlist.track_ids = ["1"]
    exporter = make_exporter(FakeDb([playlist], [content]))

    calls: List[tuple] = []
    phases: List[str] = []
    exporter.generate_device_export(
        str(usb_root),
        progress_cb=lambda *a: calls.append(a),
        phase_cb=phases.append,
    )

    assert phases == [
        "ファイルコピー中",
        "データベース書き込み中",
        "ANLZ 解析データコピー中",
    ]
    size = len(b"dummy audio data")
    assert calls[0] == (0, 1, 0, size)
    assert (1, 1, size, size) in calls  # ファイルコピー段階の進捗
    assert calls[-1] == (1, 1, 0, 0)  # ANLZ 段階の進捗（バイト数は不明なので 0）
    assert (usb_root / "PIONEER" / "rekordbox" / "export.pdb").exists()


# ----- トップレベル関数のコールバック転送 ---------------------------------------------


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


def test_top_level_functions_forward_callbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeExporter()
    monkeypatch.setattr(rkbdb2xml_mod, "RekordboxXMLExporter", lambda *a, **kw: fake)
    progress_cb = lambda *a: None  # noqa: E731 - 記録用スタブ
    phase_cb = lambda p: None  # noqa: E731 - 記録用スタブ

    rkbdb2xml_mod.export_rekordbox_db_to_xml(
        None, "/tmp/out.xml", progress_cb=progress_cb, phase_cb=phase_cb
    )
    rkbdb2xml_mod.export_rekordbox_db_to_device(
        None, "/tmp/usb", progress_cb=progress_cb, phase_cb=phase_cb
    )

    assert fake.calls[0] == ("xml", "/tmp/out.xml", progress_cb, phase_cb, None)
    assert fake.calls[1] == ("device", "/tmp/usb", progress_cb, phase_cb, None)


def test_top_level_functions_work_without_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """コールバック未指定（既定 None）でも既存呼び出し形式は壊れない。"""
    fake = FakeExporter()
    monkeypatch.setattr(rkbdb2xml_mod, "RekordboxXMLExporter", lambda *a, **kw: fake)

    rkbdb2xml_mod.export_rekordbox_db_to_xml(None, "/tmp/out.xml")

    assert fake.calls[0] == ("xml", "/tmp/out.xml", None, None, None)


# ----- ETA（直近平均速度ベース） ------------------------------------------------------


def test_eta_estimator_returns_none_until_two_samples() -> None:
    est = EtaEstimator()
    assert est.update(0, 1000, now=0.0) is None
    assert est.update(100, 1000, now=1.0) is not None


def test_eta_estimator_computes_remaining_time() -> None:
    est = EtaEstimator()
    est.update(0, 1000, now=0.0)
    est.update(500, 1000, now=10.0)  # 50 単位/秒
    eta = est.update(600, 1000, now=12.0)
    assert eta == pytest.approx(8.0)  # 残り 400 単位 ÷ 50/秒


def test_eta_estimator_uses_recent_window_only() -> None:
    est = EtaEstimator(window_seconds=5.0)
    est.update(0, 1000, now=0.0)
    est.update(900, 1000, now=1.0)  # 古いサンプル: 非常に速い
    # 直近の 2 サンプルだけで速度を測る（古い高速サンプルは窓から外れる）
    est.update(900, 1000, now=10.0)
    est.update(910, 1000, now=11.0)  # 10 単位/秒
    eta = est.update(920, 1000, now=12.0)
    assert eta == pytest.approx(8.0)  # 残り 80 単位 ÷ 10/秒


def test_eta_estimator_returns_zero_when_finished() -> None:
    est = EtaEstimator()
    est.update(0, 100, now=0.0)
    est.update(50, 100, now=1.0)
    assert est.update(100, 100, now=2.0) == 0.0


def test_eta_estimator_unknown_with_zero_total() -> None:
    est = EtaEstimator()
    est.update(0, 0, now=0.0)
    est.update(0, 0, now=1.0)
    assert est.update(0, 0, now=2.0) is None


def test_eta_estimator_reset_drops_samples() -> None:
    est = EtaEstimator()
    est.update(0, 100, now=0.0)
    est.update(10, 100, now=1.0)
    est.reset()
    assert est.update(10, 100, now=2.0) is None


def test_format_eta() -> None:
    assert format_eta(0) == "約0秒"
    assert format_eta(5) == "約5秒"
    assert format_eta(59.9) == "約59秒"
    assert format_eta(60) == "約1分"
    assert format_eta(180) == "約3分"
    assert format_eta(3600) == "約1時間0分"
    assert format_eta(7200 + 300) == "約2時間5分"

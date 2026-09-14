"""Tests for the background workers' completion contract.

Both workers drive their QThread through their own signals, so an exit path
that forgets to signal is not a cosmetic bug:

* ``SizeCalculatorWorker.finished`` is what calls ``QThread.quit()``. Returning
  without it leaves the thread -- and the Rekordbox database connection it
  holds -- running for the rest of the session, and the summary label stuck on
  "計算中...".
* ``ExportWorker`` must never let an exception escape back into Qt's signal
  dispatch, and must not report success when the export failed.
"""

import threading

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from rkbdb2xml import gui  # noqa: E402


class SignalRecorder:
    """Collects emissions without needing a QApplication."""

    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)

    def connect(self, _):  # pragma: no cover - unused by these tests
        pass


class FakePlaylist:
    def __init__(self, id_, name, parent_id="root", is_folder=False):
        self.ID = id_
        self.Name = name
        self.ParentID = parent_id
        self.is_folder = is_folder


class FakeRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeDatabase:
    """Enough of Rekordbox6Database for SizeCalculatorWorker to run."""

    def __init__(self, playlists, contents=(), on_contents=None):
        self._playlists = playlists
        self._contents = contents
        self._on_contents = on_contents

    def get_playlist(self):
        return FakeRows(self._playlists)

    def get_playlist_contents(self, playlist):
        if self._on_contents:
            self._on_contents(playlist)
        return FakeRows(self._contents)

    def get_content(self):
        return FakeRows(self._contents)


def make_size_worker(selected_paths=("List",)):
    worker = gui.SizeCalculatorWorker.__new__(gui.SizeCalculatorWorker)
    worker._selected_paths = list(selected_paths)
    worker._db_path = None
    worker._is_cancelled = False
    worker.finished = SignalRecorder()
    return worker


def make_export_worker():
    worker = gui.ExportWorker.__new__(gui.ExportWorker)
    worker._db_path = None
    worker._output_path = "/tmp/out.xml"
    worker._playlists = ["List"]
    worker._playlist_options = {}
    worker._cancel_event = threading.Event()
    worker.progress = SignalRecorder()
    worker.succeeded = SignalRecorder()
    worker.cancelled = SignalRecorder()
    worker.finished = SignalRecorder()
    worker.error = SignalRecorder()
    worker.progress_count = SignalRecorder()
    worker.phase_changed = SignalRecorder()
    return worker


# ----- SizeCalculatorWorker -------------------------------------------------


def test_nothing_selected_still_finishes():
    worker = make_size_worker(selected_paths=[])

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0, 0)]


def test_a_database_failure_still_finishes(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("no Rekordbox here")

    monkeypatch.setattr(gui, "RekordboxDatabase", boom)
    worker = make_size_worker()

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0, 0)]


def test_a_cancelled_worker_still_finishes(monkeypatch):
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: FakeDatabase([]))
    worker = make_size_worker()
    worker.cancel()

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0, 0)]


def test_cancelling_midway_through_still_finishes(monkeypatch):
    """The path that used to leak: cancelled inside the collection loop.

    It returned without emitting, so QThread.quit() was never called and the
    thread kept its Rekordbox connection open for the rest of the session.
    """
    worker = make_size_worker(selected_paths=["List", "List2"])
    fetches = []

    def cancel_on_first_fetch(playlist):
        fetches.append(playlist)
        worker.cancel()

    db = FakeDatabase(
        [FakePlaylist("1", "List"), FakePlaylist("2", "List2")],
        on_contents=cancel_on_first_fetch,
    )
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: db)

    worker.run()

    assert len(fetches) == 1, "the test must reach the collection loop to be meaningful"
    assert worker.finished.calls == [(0, 0, 0, 0, 0, 0)]


def test_a_normal_calculation_reports_the_totals(monkeypatch, tmp_path):
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"x" * 5_000_000)

    class FakeContent:
        ID = "c1"
        FolderPath = str(audio)
        FileSize = 5_000_000
        Length = 240
        BitRate = 320

    db = FakeDatabase([FakePlaylist("1", "List")], contents=[FakeContent()])
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: db)
    worker = make_size_worker(selected_paths=["List"])

    worker.run()

    assert len(worker.finished.calls) == 1
    playlists, tracks, total_bytes, exact, estimated, excluded = worker.finished.calls[0]
    assert (playlists, tracks) == (1, 1)
    assert total_bytes == 5_000_000
    assert (exact, estimated, excluded) == (1, 0, 0)


def test_a_track_without_a_file_is_excluded(monkeypatch):
    """ファイルが無い曲はエクスポートされないので、曲数・サイズに含めない。

    FolderPath が空でも FileSize が無くても、実在ファイルが無ければ対象外。
    """

    class FakeContent:
        ID = "c2"
        FolderPath = None
        FileSize = None
        Length = 240
        BitRate = 320

    db = FakeDatabase([FakePlaylist("1", "List")], contents=[FakeContent()])
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: db)
    worker = make_size_worker(selected_paths=["List"])

    worker.run()

    assert len(worker.finished.calls) == 1
    playlists, tracks, total_bytes, exact, estimated, excluded = worker.finished.calls[0]
    assert (playlists, tracks) == (1, 0)
    assert total_bytes == 0
    assert (exact, estimated, excluded) == (0, 0, 1)


def test_a_track_with_no_size_signal_is_excluded(monkeypatch):
    """サイズ情報が一切無くても、ファイルが無いなら推定せず対象外。"""

    class FakeContent:
        ID = "c3"
        FolderPath = None
        FileSize = None
        Length = None
        BitRate = None

    db = FakeDatabase([FakePlaylist("1", "List")], contents=[FakeContent()])
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: db)
    worker = make_size_worker(selected_paths=["List"])

    worker.run()

    assert len(worker.finished.calls) == 1
    playlists, tracks, total_bytes, exact, estimated, excluded = worker.finished.calls[0]
    assert (playlists, tracks) == (1, 0)
    assert total_bytes == 0
    assert (exact, estimated, excluded) == (0, 0, 1)


def test_size_worker_signal_keeps_large_total_bytes_intact():
    """total_bytes > 2 GiB は Qt の 32bit int 変換で壊れてはいけない。

    Regression: ``Signal(int, ...)`` は Windows では int32 にサイレントに
    ラップされ、実サイズ（数十 GB）が負値・小さな値として表示される不具合
    があった。バイト値は object 型で送る。
    """
    app = QCoreApplication.instance() or QCoreApplication([])
    worker = gui.SizeCalculatorWorker(["List"])
    got = []

    def slot(*args):
        got.append(args)

    worker.finished.connect(slot)
    worker.finished.emit(1, 2, 57_206_522_426, 2, 0, 0)

    assert got and got[0][2] == 57_206_522_426


def test_export_worker_progress_signal_keeps_large_byte_counts_intact():
    """progress_count の done_bytes/total_bytes も同様に 32bit 変換を通さない。"""
    app = QCoreApplication.instance() or QCoreApplication([])
    worker = gui.ExportWorker(None, "/tmp/out.xml", ["List"])
    got = []

    def slot(*args):
        got.append(args)

    worker.progress_count.connect(slot)
    worker.progress_count.emit(0, 10, 57_206_522_426, 57_206_522_426)

    assert got and got[0][2] == 57_206_522_426 and got[0][3] == 57_206_522_426


def test_a_folder_is_not_queried_for_contents(monkeypatch):
    """get_playlist_contents() raises on folders, so they must be filtered out."""
    asked = []
    db = FakeDatabase(
        [FakePlaylist("1", "Folder", is_folder=True)],
        on_contents=lambda pl: asked.append(pl),
    )
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: db)
    worker = make_size_worker(selected_paths=["Folder"])

    worker.run()

    assert asked == []
    assert worker.finished.calls == [(0, 0, 0, 0, 0, 0)]


def test_a_non_exception_failure_still_finishes(monkeypatch):
    def boom(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(gui, "RekordboxDatabase", boom)
    worker = make_size_worker()

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0, 0)]


# ----- ExportWorker ---------------------------------------------------------


def test_a_successful_export_reports_success_then_finishes(monkeypatch):
    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", lambda *a, **kw: None)
    worker = make_export_worker()

    worker.run()

    assert worker.succeeded.calls == [()]
    assert worker.error.calls == []
    assert worker.finished.calls == [()]


def test_a_failing_export_reports_the_error_and_never_claims_success(monkeypatch):
    def boom(*a, **kw):
        raise ValueError("database is locked")

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", boom)
    worker = make_export_worker()

    worker.run()  # must not raise: an escaping exception freezes the window

    assert worker.succeeded.calls == []
    assert worker.error.calls == [("ValueError: database is locked",)]
    assert worker.finished.calls == [()]


def test_a_failing_export_logs_the_traceback(monkeypatch):
    def boom(*a, **kw):
        raise ValueError("database is locked")

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", boom)
    worker = make_export_worker()

    worker.run()

    logged = "\n".join(args[0] for args in worker.progress.calls)
    assert "ValueError" in logged and "boom" in logged


def test_stdout_is_restored_after_a_failing_export(monkeypatch):
    """The redirect is process-global; leaking it would break the whole app."""

    def boom(*a, **kw):
        raise ValueError("nope")

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", boom)
    worker = make_export_worker()
    before = gui.sys.stdout

    worker.run()

    assert gui.sys.stdout is before


def test_exporter_output_is_forwarded_to_the_log(monkeypatch):
    def chatty(*a, **kw):
        print("Saving XML to out.xml")
        print("楽曲ファイル処理完了")

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", chatty)
    worker = make_export_worker()

    worker.run()

    logged = [args[0] for args in worker.progress.calls]
    assert "Saving XML to out.xml" in logged
    assert "楽曲ファイル処理完了" in logged
    assert worker.succeeded.calls == [()]


def test_export_worker_forwards_progress_counts_and_phases(monkeypatch):
    def chatty(*a, **kw):
        progress_cb = kw.get("progress_cb")
        phase_cb = kw.get("phase_cb")
        progress_cb(0, 10, 0, 1_000_000)
        phase_cb("ファイルコピー中")
        progress_cb(5, 10, 500_000, 1_000_000)

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", chatty)
    worker = make_export_worker()

    worker.run()

    assert worker.progress_count.calls == [
        (0, 10, 0, 1_000_000),
        (5, 10, 500_000, 1_000_000),
    ]
    assert worker.phase_changed.calls == [("ファイルコピー中",)]
    assert worker.succeeded.calls == [()]


def test_device_export_worker_forwards_progress_counts_and_phases(monkeypatch):
    def chatty(*a, **kw):
        progress_cb = kw.get("progress_cb")
        phase_cb = kw.get("phase_cb")
        progress_cb(1, 1, 42, 42)
        phase_cb("データベース書き込み中")

    monkeypatch.setattr(gui, "export_rekordbox_db_to_device", chatty)
    worker = make_export_worker()
    worker._device_export = True

    worker.run()

    assert worker.progress_count.calls == [(1, 1, 42, 42)]
    assert worker.phase_changed.calls == [("データベース書き込み中",)]


def test_export_worker_reports_zero_progress_even_when_exporter_is_silent(monkeypatch):
    """エクスポータがコールバックを一切呼ばなくてもクラッシュしないこと。"""

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", lambda *a, **kw: None)
    worker = make_export_worker()

    worker.run()

    assert worker.progress_count.calls == []
    assert worker.phase_changed.calls == []
    assert worker.succeeded.calls == [()]


# ----- ExportWorker のキャンセル契約 ------------------------------------------------


def test_a_pre_cancelled_export_reports_cancelled_and_finishes(monkeypatch):
    """キャンセルは succeeded でも error でもない 3 つ目の結果として報告する。

    ``finished`` が必ず発行されること（＝ QThread.quit() が呼ばれ、スレッドが
    後始末される）も同時に保証する。
    """
    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", lambda *a, **kw: None)
    worker = make_export_worker()
    worker.cancel()

    worker.run()

    assert worker.succeeded.calls == []
    assert worker.error.calls == []
    assert worker.cancelled.calls == [()]
    assert worker.finished.calls == [()]


def test_an_export_cancelled_midway_reports_cancelled(monkeypatch):
    """エクスポート実行中に cancel() された場合も同じ契約。"""

    def cancel_midway(*a, **kw):
        cancel_event = kw.get("cancel_event")
        assert cancel_event is not None, "cancel_event がエクスポータに渡る"
        cancel_event.set()

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", cancel_midway)
    worker = make_export_worker()

    worker.run()

    assert worker.cancelled.calls == [()]
    assert worker.succeeded.calls == []
    assert worker.error.calls == []
    assert worker.finished.calls == [()]


def test_cancel_event_is_forwarded_to_the_exporter(monkeypatch):
    received = {}

    def record(*a, **kw):
        received["cancel_event"] = kw.get("cancel_event")

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", record)
    worker = make_export_worker()

    worker.run()

    assert received["cancel_event"] is worker._cancel_event


def test_cancel_does_not_set_error_on_a_failing_export(monkeypatch):
    """キャンセル済みでも、実際に例外が起これば error が優先される。"""

    def boom(*a, **kw):
        raise ValueError("database is locked")

    monkeypatch.setattr(gui, "export_rekordbox_db_to_xml", boom)
    worker = make_export_worker()
    worker.cancel()

    worker.run()

    assert worker.error.calls == [("ValueError: database is locked",)]
    assert worker.cancelled.calls == []
    assert worker.finished.calls == [()]

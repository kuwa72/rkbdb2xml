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

import pytest

pytest.importorskip("PySide6.QtCore")

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
    worker.progress = SignalRecorder()
    worker.succeeded = SignalRecorder()
    worker.finished = SignalRecorder()
    worker.error = SignalRecorder()
    return worker


# ----- SizeCalculatorWorker -------------------------------------------------


def test_nothing_selected_still_finishes():
    worker = make_size_worker(selected_paths=[])

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0)]


def test_a_database_failure_still_finishes(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("no Rekordbox here")

    monkeypatch.setattr(gui, "RekordboxDatabase", boom)
    worker = make_size_worker()

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0)]


def test_a_cancelled_worker_still_finishes(monkeypatch):
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: FakeDatabase([]))
    worker = make_size_worker()
    worker.cancel()

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0)]


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
    assert worker.finished.calls == [(0, 0, 0, 0, 0)]


def test_a_normal_calculation_reports_the_totals(monkeypatch):
    class FakeContent:
        ID = "c1"
        FolderPath = None
        FileSize = 5_000_000
        Length = 240
        BitRate = 320

    db = FakeDatabase([FakePlaylist("1", "List")], contents=[FakeContent()])
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: db)
    worker = make_size_worker(selected_paths=["List"])

    worker.run()

    assert len(worker.finished.calls) == 1
    playlists, tracks, total_bytes, exact, estimated = worker.finished.calls[0]
    assert (playlists, tracks) == (1, 1)
    assert total_bytes == 5_000_000
    assert (exact, estimated) == (1, 0)


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
    assert worker.finished.calls == [(0, 0, 0, 0, 0)]


def test_a_non_exception_failure_still_finishes(monkeypatch):
    def boom(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(gui, "RekordboxDatabase", boom)
    worker = make_size_worker()

    worker.run()

    assert worker.finished.calls == [(0, 0, 0, 0, 0)]


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

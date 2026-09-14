"""The size-calculator thread must not lose its reference while running.

Checkbox toggles debounce into ``_start_async_size_calculation()``. When the
previous calculation is still running, the GUI thread ``quit()``s and
``wait()``s on it -- and while the GUI thread is blocked, the old thread's
``finished`` signal is emitted. The queued ``_on_calc_thread_finished`` is
therefore delivered only *after* a replacement thread has been stored in
``self._calc_thread``. Clearing the attribute unconditionally drops the last
Python reference to the still-running thread, and PySide destroying the C++
``QThread`` then aborts the process
("QThread: Destroyed while thread is still running").

These tests use real QThreads: the race lives in signal delivery order, so a
fake would not exercise it. The gated fake database keeps each worker alive
long enough that the second ``_start`` always hits the quit()+wait() path.
"""

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtGui import QCloseEvent, QStandardItem, QStandardItemModel  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTreeView,
)

from rkbdb2xml import gui  # noqa: E402


WORKER_BUSY_SECONDS = 0.4


class GatedRows:
    """.all() blocks briefly so the owning worker stays 'running'."""

    def __init__(self, rows):
        self._rows = rows

    def all(self):
        time.sleep(WORKER_BUSY_SECONDS)
        return list(self._rows)


class FakePlaylist:
    ID = "1"
    Name = "List"
    ParentID = "root"
    is_folder = False


class FakeContent:
    ID = "c1"
    FolderPath = "/nonexistent/track.mp3"
    FileSize = None
    Length = None
    BitRate = None


class GatedDatabase:
    def get_playlist(self):
        return GatedRows([FakePlaylist()])

    def get_playlist_contents(self, playlist):
        return GatedRows([FakeContent()])

    def get_content(self):
        return GatedRows([FakeContent()])

    def close(self):
        pass


def pump_events():
    """Deliver queued signal invocations posted to the GUI thread."""
    QCoreApplication.sendPostedEvents()
    QCoreApplication.processEvents()


@pytest.fixture()
def window(monkeypatch):
    """Partially constructed MainWindow with the real thread management."""
    monkeypatch.setattr(gui, "RekordboxDatabase", lambda *a, **kw: GatedDatabase())
    QApplication.instance() or QApplication([])

    win = gui.MainWindow.__new__(gui.MainWindow)
    QMainWindow.__init__(win)
    win._calc_thread = None
    win._calc_worker = None
    win._export_thread = None
    win._export_worker = None
    win._summary_label = QLabel()
    win._capacity_label = QLabel()
    win._output_edit = QLineEdit()
    win._usb_drive_combo = QComboBox()
    win._device_combo = QComboBox()
    win._model = QStandardItemModel()
    win._tree = QTreeView()
    win._tree.setModel(win._model)

    item = QStandardItem("List")
    item.setCheckable(True)
    item.setCheckState(Qt.Checked)
    item.setData("List", gui.ROLE_PATH)
    item.setData(False, gui.ROLE_IS_FOLDER)
    win._model.appendRow(item)

    yield win

    thread = win._calc_thread
    if thread is not None:
        try:
            if win._calc_worker is not None:
                win._calc_worker.cancel()
            if thread.isRunning():
                thread.quit()
            thread.wait(2000)
        except RuntimeError:
            pass


def test_superseded_threads_finished_does_not_drop_the_new_thread(window):
    """Issue #20: rapid checkbox toggles crash the app.

    The second ``_start`` waits for T1 while T1's ``finished`` sits in the
    event queue; once delivered it must not clear the references that now
    point at the still-running T2.
    """
    window._start_async_size_calculation()  # T1 starts and blocks in the fake DB
    window._start_async_size_calculation()  # quit()+wait() on T1, then T2 starts

    t2 = window._calc_thread
    w2 = window._calc_worker
    assert t2 is not None and t2.isRunning()

    # Keep our own references so the assertion below fails cleanly instead
    # of aborting the whole suite when the bug drops the window's copies.
    try:
        pump_events()  # T1's stale finished is delivered here

        assert window._calc_thread is t2, (
            "stale finished dropped the running thread's reference "
            "(real app aborts here: 'QThread: Destroyed while running')"
        )
        assert window._calc_worker is w2
    finally:
        w2.cancel()
        t2.quit()
        t2.wait(2000)


def test_finished_thread_releases_its_references(window):
    """The guard must not break the normal path: a finished thread's own
    ``finished`` still clears the attributes."""
    window._start_async_size_calculation()

    thread = window._calc_thread
    assert thread is not None
    # worker.finished -> thread.quit is queued to the GUI thread, so the
    # event loop must be pumped while waiting for the thread to stop.
    for _ in range(50):
        pump_events()
        if thread.wait(200):
            break
    assert not thread.isRunning(), "gated worker should finish promptly"

    pump_events()  # deliver thread.finished -> _on_calc_thread_finished

    assert window._calc_thread is None
    assert window._calc_worker is None


def test_a_superseded_workers_result_does_not_overwrite_the_label(window):
    """A cancelled worker still emits finished(0,...); it must not clear
    the summary that a newer calculation is about to fill."""
    window._start_async_size_calculation()
    window._start_async_size_calculation()

    t2 = window._calc_thread
    w2 = window._calc_worker
    try:
        pump_events()  # delivers the stale finished(0,0,...) emission

        # The cancelled worker reported 0 playlists; the label must not show it.
        assert "計算中" in window._summary_label.text() or "0 プレイリスト" not in (
            window._summary_label.text()
        )
    finally:
        w2.cancel()
        t2.quit()
        t2.wait(2000)


def test_close_event_stops_the_calculation_thread(window, monkeypatch, tmp_path):
    """Closing the window while a calculation runs must not leave a
    reference-less QThread behind (same abort as above, on exit)."""
    monkeypatch.setattr(gui, "SETTINGS_FILE", tmp_path / "settings.json")
    window._start_async_size_calculation()
    thread = window._calc_thread
    assert thread is not None and thread.isRunning()

    window.closeEvent(QCloseEvent())

    assert not thread.isRunning()
    assert window._calc_thread is None
    assert window._calc_worker is None

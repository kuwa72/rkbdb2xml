"""Tests for playlist tree check-state propagation."""

import pytest

pytest.importorskip("PySide6.QtGui")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QStandardItem, QStandardItemModel  # noqa: E402

from rkbdb2xml import gui  # noqa: E402
from rkbdb2xml.gui import ROLE_IS_FOLDER  # noqa: E402


def make_folder_with_children(*states):
    folder = QStandardItem("Folder")
    folder.setCheckable(True)
    for index, state in enumerate(states):
        child = QStandardItem(f"Playlist {index}")
        child.setCheckable(True)
        child.setCheckState(state)
        folder.appendRow(child)
    return folder


def test_folder_shows_partial_check_when_hidden_child_is_selected():
    window = gui.MainWindow.__new__(gui.MainWindow)
    folder = make_folder_with_children(Qt.Unchecked, Qt.Checked)

    window._update_parent_check_state(folder)

    assert folder.checkState() == Qt.PartiallyChecked


def test_folder_shows_checked_when_all_children_are_selected():
    window = gui.MainWindow.__new__(gui.MainWindow)
    folder = make_folder_with_children(Qt.Checked, Qt.Checked)

    window._update_parent_check_state(folder)

    assert folder.checkState() == Qt.Checked


def make_connected_window():
    """Window harness with a live model: setCheckState emits itemChanged.

    This drives the real ``_on_item_changed`` cascade (issue #2 path),
    unlike the detached-item tests above. pytest enables faulthandler, so a
    SEGV here prints a native traceback instead of hanging the suite.
    """
    window = gui.MainWindow.__new__(gui.MainWindow)
    window._is_updating_checks = False
    window._trigger_calls = 0
    window._trigger_size_calculation = lambda: setattr(  # noqa: E731
        window, "_trigger_calls", window._trigger_calls + 1
    )
    window._on_option_changed_refresh_preview = lambda: None  # noqa: E731
    model = QStandardItemModel()
    model.itemChanged.connect(window._on_item_changed)
    window._model = model
    return window, model


def add_row(parent, name, is_folder, checked=True):
    item = QStandardItem(name)
    item.setCheckable(True)
    item.setData(is_folder, ROLE_IS_FOLDER)
    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
    parent.appendRow(item)
    return item


def test_uncheck_child_marks_folder_partial():
    window, model = make_connected_window()
    folder = add_row(model, "Folder", True)
    add_row(folder, "A", False)
    child_b = add_row(folder, "B", False)

    child_b.setCheckState(Qt.Unchecked)

    assert folder.checkState() == Qt.PartiallyChecked
    assert window._trigger_calls == 1


def test_uncheck_folder_clears_descendants():
    window, model = make_connected_window()
    folder = add_row(model, "Folder", True)
    add_row(folder, "A", False)
    add_row(folder, "B", False)

    folder.setCheckState(Qt.Unchecked)

    assert folder.child(0).checkState() == Qt.Unchecked
    assert folder.child(1).checkState() == Qt.Unchecked
    assert window._trigger_calls == 1


def test_uncheck_top_level_leaf_is_safe():
    window, model = make_connected_window()
    leaf = add_row(model, "Top", False)

    leaf.setCheckState(Qt.Unchecked)

    assert leaf.checkState() == Qt.Unchecked
    assert window._trigger_calls == 1


def test_nested_uncheck_propagates_to_grandparent():
    window, model = make_connected_window()
    folder = add_row(model, "Folder", True)
    sub = add_row(folder, "Sub", True)
    leaf = add_row(sub, "A", False)
    add_row(sub, "B", False)

    leaf.setCheckState(Qt.Unchecked)

    assert sub.checkState() == Qt.PartiallyChecked
    assert folder.checkState() == Qt.PartiallyChecked


def test_rapid_toggle_leaves_consistent_state():
    window, model = make_connected_window()
    folder = add_row(model, "Folder", True)
    leaf = add_row(folder, "A", False)
    add_row(folder, "B", False)

    for _ in range(20):
        leaf.setCheckState(Qt.Unchecked)
        leaf.setCheckState(Qt.Checked)

    assert leaf.checkState() == Qt.Checked
    assert folder.checkState() == Qt.Checked


class FakeCalcThread:
    """QThread stand-in that would crash if destroyed while 'running'."""

    def __init__(self, running=True):
        self._running = running
        self.quit_called = False
        self.wait_calls = []

    def isRunning(self):
        return self._running

    def quit(self):
        self.quit_called = True
        self._running = False

    def wait(self, ms=None):
        self.wait_calls.append(ms)
        return not self._running


def test_start_async_waits_for_previous_thread(monkeypatch):
    """Regression: destroying a running QThread aborts the process.

    The old code did ``quit(); wait(100)`` then dropped the reference, so a
    thread that didn't finish within 100 ms was destroyed while running
    (QThread: Destroyed while thread is still running). The fix waits for the
    previous thread to actually stop before reassigning _calc_thread.
    """
    window, model = make_connected_window()
    window._calc_worker = None
    window._calc_thread = FakeCalcThread(running=True)
    prev_thread = window._calc_thread
    window._collect_selected = lambda *a, **kw: []
    window._on_size_calculated = lambda *a, **kw: None

    window._start_async_size_calculation()

    assert prev_thread.quit_called
    # The fix must wait without a timeout so it never destroys a live thread.
    assert prev_thread.wait_calls == [None]
    assert window._calc_thread is None

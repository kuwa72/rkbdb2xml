"""Tests for playlist tree check-state propagation."""

import pytest

pytest.importorskip("PySide6.QtGui")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QStandardItem, QStandardItemModel  # noqa: E402

from rkbdb2xml import gui  # noqa: E402
from rkbdb2xml.gui import ROLE_IS_FOLDER, ROLE_PATH  # noqa: E402


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
    parent_path = parent.data(ROLE_PATH) if isinstance(parent, QStandardItem) else ""
    path = f"{parent_path}/{name}" if parent_path else name
    item.setData(path, ROLE_PATH)
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


def test_collect_selected_skips_partially_checked_folders():
    """Partially checked folders must not drag in unchecked siblings (issue #6)."""
    window, model = make_connected_window()
    folder = add_row(model, "Folder", True)
    child_a = add_row(folder, "A", False, checked=False)
    add_row(folder, "B", False, checked=False)
    child_a.setCheckState(Qt.Checked)
    # The model cascade leaves the folder partially checked.
    assert folder.checkState() == Qt.PartiallyChecked

    selected = []
    window._collect_selected(model.invisibleRootItem(), selected)

    assert selected == ["Folder/A"]
    assert "Folder" not in selected
    assert "Folder/B" not in selected


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


# ----- Startup folder-state aggregation (issue #22) -------------------------


def test_startup_aggregation_marks_all_ancestors_partial():
    """A checked item two levels down must mark every ancestor.

    The startup restore used to aggregate only top-level folders, and
    ``_update_parent_check_state`` only recurses *upwards* — so a mid-level
    folder kept its restored Unchecked state and the partial marker never
    reached the folders above it.
    """
    window, model = make_connected_window()
    top = add_row(model, "Top", True, checked=False)
    mid = add_row(top, "Mid", True, checked=False)
    add_row(mid, "Leaf", False)
    add_row(mid, "LeafUnchecked", False, checked=False)

    window._refresh_folder_checks()

    assert mid.checkState() == Qt.PartiallyChecked
    assert top.checkState() == Qt.PartiallyChecked


def test_startup_aggregation_handles_mixed_folder_and_leaf_children():
    """A folder containing a partially-checked folder plus an unchecked leaf
    must become partial, not unchecked."""
    window, model = make_connected_window()
    top = add_row(model, "Top", True, checked=False)
    mid = add_row(top, "Mid", True, checked=False)
    add_row(mid, "Deep", False)
    add_row(top, "Shallow", False, checked=False)

    window._refresh_folder_checks()

    assert mid.checkState() == Qt.Checked
    assert top.checkState() == Qt.PartiallyChecked


def test_startup_aggregation_marks_fully_checked_folder_checked():
    window, model = make_connected_window()
    top = add_row(model, "Top", True, checked=False)
    add_row(top, "A", False)
    add_row(top, "B", False)

    window._refresh_folder_checks()

    assert top.checkState() == Qt.Checked


def test_startup_aggregation_leaves_unchecked_tree_unchecked():
    window, model = make_connected_window()
    top = add_row(model, "Top", True, checked=False)
    mid = add_row(top, "Mid", True, checked=False)
    add_row(mid, "Leaf", False, checked=False)

    window._refresh_folder_checks()

    assert mid.checkState() == Qt.Unchecked
    assert top.checkState() == Qt.Unchecked

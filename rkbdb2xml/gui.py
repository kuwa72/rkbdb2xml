"""
PySide6 GUI for rkbdb2xml.

Provides a tree-based playlist viewer with per-playlist export options,
output folder selection, and background export execution.
"""

import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QObject,
    QThread,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase

from .rkbdb2xml import export_rekordbox_db_to_xml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SETTINGS_FILE = Path.home() / ".rkbdb2xml_gui_settings.json"

# Column indices for the tree model
COL_CHECK = 0   # Checkbox + Name
COL_ROMAN = 1   # Romanize option
COL_BPM = 2     # BPM-in-title option
COL_SORT = 3    # Sort order option

# Custom data roles stored on items
ROLE_PATH = Qt.UserRole + 1       # hierarchical path string
ROLE_IS_FOLDER = Qt.UserRole + 2  # bool
ROLE_PL_ID = Qt.UserRole + 3     # playlist ID


# ---------------------------------------------------------------------------
# Export worker
# ---------------------------------------------------------------------------
class ExportWorker(QObject):
    """Runs export_rekordbox_db_to_xml in a background thread."""

    progress = Signal(str)   # log messages
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        db_path: Optional[str],
        output_path: str,
        playlists: Optional[List[str]],
        playlist_options: Optional[Dict[str, dict]] = None,
    ):
        super().__init__()
        self._db_path = db_path
        self._output_path = output_path
        self._playlists = playlists
        self._playlist_options = playlist_options or {}

    @Slot()
    def run(self) -> None:
        import io
        import sys

        try:
            self.progress.emit(f"エクスポート開始: {self._output_path}")

            # Redirect stdout to capture verbose output and avoid
            # cp932 encoding errors on Windows.
            old_stdout = sys.stdout
            capture = io.StringIO()
            sys.stdout = capture

            try:
                export_rekordbox_db_to_xml(
                    self._db_path,
                    self._output_path,
                    db_key=None,
                    verbose=True,
                    roman=False,
                    bpm=False,
                    orderby="default",
                    playlists=self._playlists,
                    playlist_options=self._playlist_options,
                )
            finally:
                sys.stdout = old_stdout

            # Emit captured output (last 50 lines to avoid flooding)
            output = capture.getvalue()
            if output:
                lines = output.strip().splitlines()
                for line in lines[-50:]:
                    self.progress.emit(line)

            self.progress.emit("エクスポート完了!")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


# ---------------------------------------------------------------------------
# Sort-order delegate helper
# ---------------------------------------------------------------------------
SORT_OPTIONS = ["デフォルト", "BPM昇順"]
SORT_MAP = {"デフォルト": "default", "BPM昇順": "bpm"}
SORT_MAP_REV = {v: k for k, v in SORT_MAP.items()}


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("rkbdb2xml")
        self.setMinimumSize(800, 600)
        self.resize(1000, 700)

        self._export_thread: Optional[QThread] = None

        self._build_ui()
        self._load_playlists()

    # ----- UI construction -----

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # --- Output folder row ---
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("出力先フォルダ:"))
        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("エクスポート先のフォルダを選択...")
        out_row.addWidget(self._output_edit, 1)
        browse_btn = QPushButton("参照...")
        browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        # --- Tree view ---
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["プレイリスト", "Roman", "BPM", "ソート順"])

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setAlternatingRowColors(True)
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(COL_CHECK, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(COL_ROMAN, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(COL_BPM, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(COL_SORT, QHeaderView.ResizeToContents)

        # Connect item-changed for checkbox cascading
        self._model.itemChanged.connect(self._on_item_changed)

        layout.addWidget(self._tree, 1)

        # --- Export button row ---
        export_row = QHBoxLayout()
        self._export_btn = QPushButton("エクスポート開始")
        self._export_btn.setMinimumHeight(36)
        self._export_btn.clicked.connect(self._on_export)
        export_row.addWidget(self._export_btn)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setVisible(False)
        export_row.addWidget(self._progress)
        layout.addLayout(export_row)

        # --- Log area ---
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(150)
        self._log.setPlaceholderText("ログ出力...")
        layout.addWidget(self._log)

    # ----- Playlist loading -----

    def _load_playlists(self) -> None:
        """Load playlists from Rekordbox DB and build the tree model."""
        self._log_message("Rekordbox データベースを読み込み中...")
        try:
            db = RekordboxDatabase()
            pls = db.get_playlist().all()
        except Exception as e:
            self._log_message(f"DB読み込みエラー: {e}")
            return

        id_map = {pl.ID: pl for pl in pls}
        parent_map: Dict[Any, list] = {}
        for pl in pls:
            parent_map.setdefault(pl.ParentID, []).append(pl)
        for children in parent_map.values():
            children.sort(key=lambda x: x.Name)

        # Find root parents (IDs not in id_map)
        root_parents = [pid for pid in parent_map if pid not in id_map]

        # Load saved settings before building tree
        saved = self._load_settings()

        # Block signals during model build to avoid cascading checks
        self._model.blockSignals(True)

        def build_tree(parent_item: QStandardItem, pid: Any, parent_path: str) -> None:
            for pl in parent_map.get(pid, []):
                path_str = f"{parent_path}/{pl.Name}" if parent_path else pl.Name
                is_folder = pl.is_folder

                # Column 0: Checkbox + name
                name_item = QStandardItem(pl.Name)
                name_item.setEditable(False)
                name_item.setCheckable(True)
                name_item.setData(path_str, ROLE_PATH)
                name_item.setData(is_folder, ROLE_IS_FOLDER)
                name_item.setData(pl.ID, ROLE_PL_ID)

                # Restore check state from saved settings
                saved_selected = saved.get("selected_playlists", [])
                if path_str in saved_selected:
                    name_item.setCheckState(Qt.Checked)
                else:
                    name_item.setCheckState(Qt.Unchecked)

                if is_folder:
                    # Folder: option columns are empty/disabled
                    roman_item = QStandardItem("")
                    roman_item.setEnabled(False)
                    roman_item.setEditable(False)
                    bpm_item = QStandardItem("")
                    bpm_item.setEnabled(False)
                    bpm_item.setEditable(False)
                    sort_item = QStandardItem("")
                    sort_item.setEnabled(False)
                    sort_item.setEditable(False)
                else:
                    # Playlist: option columns with checkboxes / combo
                    # Restore per-playlist options
                    pl_opts = saved.get("playlist_options", {}).get(path_str, {})

                    roman_item = QStandardItem()
                    roman_item.setCheckable(True)
                    roman_item.setCheckState(
                        Qt.Checked if pl_opts.get("roman", True) else Qt.Unchecked
                    )
                    roman_item.setEditable(False)

                    bpm_item = QStandardItem()
                    bpm_item.setCheckable(True)
                    bpm_item.setCheckState(
                        Qt.Checked if pl_opts.get("bpm", True) else Qt.Unchecked
                    )
                    bpm_item.setEditable(False)

                    sort_val = pl_opts.get("orderby", "bpm")
                    sort_label = SORT_MAP_REV.get(sort_val, "BPM昇順")
                    sort_item = QStandardItem(sort_label)
                    sort_item.setEditable(False)

                parent_item.appendRow([name_item, roman_item, bpm_item, sort_item])

                if is_folder:
                    build_tree(name_item, pl.ID, path_str)

        root = self._model.invisibleRootItem()
        for rp in root_parents:
            build_tree(root, rp, "")

        self._model.blockSignals(False)

        self._tree.expandAll()

        # Set sort combo delegates after tree is built
        self._setup_sort_combos(root)

        # Restore output path
        self._output_edit.setText(saved.get("output_path", ""))

        count = self._count_playlists(root)
        self._log_message(f"{count} 個のプレイリストを読み込みました")

    def _setup_sort_combos(self, parent: QStandardItem) -> None:
        """Set QComboBox widgets on sort-order column for playlist rows."""
        for row in range(parent.rowCount()):
            name_item = parent.child(row, COL_CHECK)
            if not name_item:
                continue
            is_folder = name_item.data(ROLE_IS_FOLDER)
            sort_item = parent.child(row, COL_SORT)
            if not is_folder and sort_item:
                idx = self._model.indexFromItem(sort_item)
                combo = QComboBox()
                combo.addItems(SORT_OPTIONS)
                # Set current value from model text
                current_text = sort_item.text()
                combo_idx = combo.findText(current_text)
                if combo_idx >= 0:
                    combo.setCurrentIndex(combo_idx)
                self._tree.setIndexWidget(idx, combo)
            # Recurse for children
            if name_item.hasChildren():
                self._setup_sort_combos(name_item)

    def _count_playlists(self, parent: QStandardItem) -> int:
        count = 0
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if item:
                is_folder = item.data(ROLE_IS_FOLDER)
                if not is_folder:
                    count += 1
                if item.hasChildren():
                    count += self._count_playlists(item)
        return count

    # ----- Checkbox cascading -----

    def _on_item_changed(self, item: QStandardItem) -> None:
        """When a folder checkbox changes, cascade to children."""
        if item.column() != COL_CHECK:
            return
        is_folder = item.data(ROLE_IS_FOLDER)
        if not is_folder:
            return
        # Block signals to prevent recursive triggers
        self._model.blockSignals(True)
        self._set_children_check(item, item.checkState())
        self._model.blockSignals(False)

    def _set_children_check(self, parent: QStandardItem, state: Qt.CheckState) -> None:
        for row in range(parent.rowCount()):
            child = parent.child(row, COL_CHECK)
            if child:
                child.setCheckState(state)
                if child.hasChildren():
                    self._set_children_check(child, state)

    # ----- Output folder -----

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if folder:
            self._output_edit.setText(folder)

    # ----- Export -----

    def _on_export(self) -> None:
        output_path = self._output_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "エラー", "出力先フォルダを指定してください。")
            return

        output_dir = Path(output_path)
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(self, "エラー", f"フォルダ作成に失敗: {e}")
                return

        xml_path = str(output_dir / "rekordbox.xml")

        # Collect selected playlists
        selected_paths: List[str] = []
        root = self._model.invisibleRootItem()
        self._collect_selected(root, selected_paths)

        if not selected_paths:
            QMessageBox.warning(self, "エラー", "エクスポートするプレイリストを選択してください。")
            return

        # Collect per-playlist options dict
        pl_options: Dict[str, dict] = {}
        self._collect_all_options(root, pl_options)

        # Save settings before export
        self._save_settings()

        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._log_message(f"エクスポート対象: {len(selected_paths)} プレイリスト")

        # Create worker with per-playlist options
        worker = ExportWorker(
            db_path=None,
            output_path=xml_path,
            playlists=selected_paths,
            playlist_options=pl_options,
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._log_message)
        worker.error.connect(self._on_export_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_export_done)

        self._export_thread = thread
        self._export_worker = worker
        thread.start()

    def _collect_selected(self, parent: QStandardItem, result: List[str]) -> None:
        """Collect path strings of checked items (folders and playlists).

        When a folder is checked, its path is included and children are
        skipped because the core export logic automatically includes all
        descendants of a selected folder — matching CLI behaviour.
        """
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if not item:
                continue
            if item.checkState() != Qt.Checked:
                # Still recurse into unchecked folders; a child may be checked
                if item.hasChildren():
                    self._collect_selected(item, result)
                continue
            path_str = item.data(ROLE_PATH)
            is_folder = item.data(ROLE_IS_FOLDER)
            if is_folder:
                # Pass folder path — core logic includes all descendants
                if path_str:
                    result.append(path_str)
                # No need to recurse; descendants are covered by the folder
            else:
                if path_str:
                    result.append(path_str)

    def _collect_options(self, parent: QStandardItem) -> List[dict]:
        """Collect per-playlist options for checked playlists."""
        results: List[dict] = []
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if not item:
                continue
            is_folder = item.data(ROLE_IS_FOLDER)
            if item.checkState() == Qt.Checked and not is_folder:
                roman_item = parent.child(row, COL_ROMAN)
                bpm_item = parent.child(row, COL_BPM)
                sort_item = parent.child(row, COL_SORT)

                roman = roman_item.checkState() == Qt.Checked if roman_item else True
                bpm = bpm_item.checkState() == Qt.Checked if bpm_item else True

                # Read combo widget value
                orderby = "bpm"
                if sort_item:
                    idx = self._model.indexFromItem(sort_item)
                    widget = self._tree.indexWidget(idx)
                    if isinstance(widget, QComboBox):
                        orderby = SORT_MAP.get(widget.currentText(), "bpm")

                results.append({"roman": roman, "bpm": bpm, "orderby": orderby})
            if item.hasChildren():
                results.extend(self._collect_options(item))
        return results

    @Slot(str)
    def _on_export_error(self, msg: str) -> None:
        self._log_message(f"エラー: {msg}")
        QMessageBox.critical(self, "エクスポートエラー", msg)

    @Slot()
    def _on_export_done(self) -> None:
        self._export_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._export_thread = None

    # ----- Logging -----

    def _log_message(self, message: str) -> None:
        self._log.appendPlainText(message)

    # ----- Settings persistence -----

    def _load_settings(self) -> dict:
        """Load saved settings from JSON file."""
        if not SETTINGS_FILE.exists():
            return {}
        try:
            with SETTINGS_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self) -> None:
        """Save current settings to JSON file."""
        root = self._model.invisibleRootItem()

        # Collect selected playlist paths
        selected: List[str] = []
        self._collect_checked_paths(root, selected)

        # Collect per-playlist options
        options: Dict[str, dict] = {}
        self._collect_all_options(root, options)

        data = {
            "output_path": self._output_edit.text().strip(),
            "selected_playlists": selected,
            "playlist_options": options,
        }
        try:
            with SETTINGS_FILE.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _collect_checked_paths(self, parent: QStandardItem, result: List[str]) -> None:
        """Collect path strings of all checked items (folders + playlists)."""
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if not item:
                continue
            if item.checkState() == Qt.Checked:
                path_str = item.data(ROLE_PATH)
                if path_str:
                    result.append(path_str)
            if item.hasChildren():
                self._collect_checked_paths(item, result)

    def _collect_all_options(self, parent: QStandardItem, result: Dict[str, dict]) -> None:
        """Collect options for all playlist (non-folder) items."""
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if not item:
                continue
            is_folder = item.data(ROLE_IS_FOLDER)
            if not is_folder:
                path_str = item.data(ROLE_PATH)
                roman_item = parent.child(row, COL_ROMAN)
                bpm_item = parent.child(row, COL_BPM)
                sort_item = parent.child(row, COL_SORT)

                roman = roman_item.checkState() == Qt.Checked if roman_item else True
                bpm = bpm_item.checkState() == Qt.Checked if bpm_item else True

                orderby = "bpm"
                if sort_item:
                    idx = self._model.indexFromItem(sort_item)
                    widget = self._tree.indexWidget(idx)
                    if isinstance(widget, QComboBox):
                        orderby = SORT_MAP.get(widget.currentText(), "bpm")

                if path_str:
                    result[path_str] = {
                        "roman": roman,
                        "bpm": bpm,
                        "orderby": orderby,
                    }
            if item.hasChildren():
                self._collect_all_options(item, result)

    def closeEvent(self, event) -> None:
        """Save settings when window is closed."""
        self._save_settings()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

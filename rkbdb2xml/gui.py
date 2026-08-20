"""
PySide6 GUI for rkbdb2xml.

Provides a tree-based playlist viewer with per-playlist export options,
output folder selection, and background export execution.
"""

import json
import os
import platform
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
from PySide6.QtCore import (
    QModelIndex,
    QObject,
    QThread,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QDesktopServices,
    QFont,
    QIcon,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableView,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False


from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase

from .rkbdb2xml import export_rekordbox_db_to_xml

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------
SETTINGS_FILE = Path.home() / ".rkbdb2xml_gui_settings.json"


def get_default_output_dir() -> Path:
    """Return a user-friendly default export directory (Desktop or Home)."""
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return desktop / "Rekordbox_Export"
    return Path.home() / "Rekordbox_Export"


def get_app_icon() -> QIcon:
    """Find and return application icon."""
    # Look in assets directory
    base_dir = Path(__file__).resolve().parent.parent
    assets_dir = base_dir / "assets"
    
    # Try ICO or PNG
    for icon_name in ("icon.ico", "icon.png", "icon_256x256.png", "icon_64x64.png"):
        icon_path = assets_dir / icon_name
        if icon_path.exists():
            return QIcon(str(icon_path))
    return QIcon()


# Column indices for the tree model
COL_CHECK = 0  # Checkbox + Name
COL_ROMAN = 1  # Romanize option
COL_BPM = 2  # BPM-in-title option
COL_SORT = 3  # Sort order option

# Custom data roles stored on items
ROLE_PATH = Qt.UserRole + 1  # hierarchical path string
ROLE_IS_FOLDER = Qt.UserRole + 2  # bool
ROLE_PL_ID = Qt.UserRole + 3  # playlist ID
ROLE_FILE_PATH = Qt.UserRole + 4  # local audio file path string
ROLE_TRACK_TITLE = Qt.UserRole + 5  # track title string



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

        finally:
            self.finished.emit()



# ---------------------------------------------------------------------------
# Format helper
# ---------------------------------------------------------------------------
def format_bytes(bytes_val: int) -> str:
    """Format bytes into a human-readable string (B, KB, MB, GB)."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


def format_time(ms: int) -> str:
    """Format milliseconds into mm:ss format."""
    total_sec = max(0, int(ms) // 1000)
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes:02d}:{seconds:02d}"



# ---------------------------------------------------------------------------
# Size calculator worker (Async)
# ---------------------------------------------------------------------------
class SizeCalculatorWorker(QObject):
    """Calculates total track count and size for selected playlists asynchronously."""
    # (playlist_count, unique_track_count, total_bytes, exact_count, estimated_count)
    finished = Signal(int, int, int, int, int)

    def __init__(self, selected_paths: List[str], db_path: Optional[str] = None) -> None:
        super().__init__()
        self._selected_paths = selected_paths
        self._db_path = db_path
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    @Slot()
    def run(self) -> None:
        if not self._selected_paths or self._is_cancelled:
            self.finished.emit(0, 0, 0, 0, 0)
            return

        try:
            db = RekordboxDatabase(self._db_path)
            all_pls = db.get_playlist().all()

            # Map hierarchical paths to playlist objects
            id_map: Dict[Any, Any] = {}
            for pl in all_pls:
                id_map[pl.ID] = pl
                id_map[str(pl.ID)] = pl
                if str(pl.ID).isdigit():
                    id_map[int(pl.ID)] = pl

            parent_map: Dict[Any, list] = {}
            for pl in all_pls:
                parent_map.setdefault(pl.ParentID, []).append(pl)
            root_parents = [pid for pid in parent_map if pid not in id_map]

            path_map: Dict[str, Any] = {}

            def traverse(pid: Any, current_path: str) -> None:
                for pl in parent_map.get(pid, []):
                    p_str = f"{current_path}/{pl.Name}" if current_path else pl.Name
                    path_map[p_str] = pl
                    traverse(pl.ID, p_str)

            for rp in root_parents:
                traverse(rp, "")

            # Identify target playlists (resolve folders to children playlists)
            target_pls = []
            for spath in self._selected_paths:
                if spath in path_map:
                    pl = path_map[spath]
                    if not pl.is_folder and pl not in target_pls:
                        target_pls.append(pl)

            if not target_pls or self._is_cancelled:
                self.finished.emit(0, 0, 0, 0, 0)
                return

            # Collect unique track IDs
            unique_track_ids = set()
            for pl in target_pls:
                if self._is_cancelled:
                    return
                entries = db.get_playlist_contents(pl).all()
                for entry in entries:
                    cid = getattr(entry, "ContentID", None) or getattr(entry, "ID", None)
                    if cid is not None:
                        unique_track_ids.add(str(cid))

            # Query track sizes
            from .rkbdb2xml import RekordboxXMLExporter
            resolver = RekordboxXMLExporter.__new__(RekordboxXMLExporter)
            all_contents = db.get_content().all()
            content_map: Dict[str, Any] = {}
            for c in all_contents:
                content_map[str(c.ID)] = c

            total_bytes = 0
            exact_count = 0
            estimated_count = 0

            for cid in unique_track_ids:
                if self._is_cancelled:
                    return
                content = content_map.get(cid)
                if not content:
                    estimated_count += 1
                    total_bytes += 10 * 1024 * 1024
                    continue

                track_size = 0
                is_exact = False

                # 1. Check local file on disk
                loc = getattr(content, "FolderPath", None)
                if loc:
                    p = resolver._resolve_file_path(loc)
                    if p and p.exists() and p.is_file():
                        try:
                            s = p.stat().st_size
                            if s > 0:
                                track_size = s
                                is_exact = True
                        except Exception:
                            pass

                # 2. Check DB FileSize attribute
                if not is_exact:
                    fsize = getattr(content, "FileSize", None)
                    if fsize is not None:
                        try:
                            fs_int = int(fsize)
                            if 100_000 <= fs_int <= 5_000_000_000:
                                track_size = fs_int
                                is_exact = True
                        except (ValueError, TypeError):
                            pass

                # 3. Heuristic estimation from Length and BitRate / File extension
                if not is_exact:
                    estimated_count += 1
                    duration = getattr(content, "Length", None)
                    bitrate = getattr(content, "BitRate", None)

                    try:
                        dur_sec = float(duration) if (duration and float(duration) > 0) else 240.0
                    except (ValueError, TypeError):
                        dur_sec = 240.0

                    ext = ""
                    if loc:
                        ext = Path(str(loc)).suffix.lower()

                    if ext in (".wav", ".aif", ".aiff"):
                        track_size = int(dur_sec * 176_400)
                    elif ext in (".flac", ".alac"):
                        track_size = int(dur_sec * 100_000)
                    elif bitrate:
                        try:
                            br_kbps = float(bitrate) if float(bitrate) > 0 else 320.0
                            track_size = int(dur_sec * (br_kbps * 1000 / 8))
                        except (ValueError, TypeError):
                            track_size = int(dur_sec * 40_000)
                    else:
                        track_size = int(dur_sec * 40_000)

                    track_size = max(1_000_000, track_size)
                else:
                    exact_count += 1

                total_bytes += max(0, track_size)

            total_bytes = max(0, total_bytes)

            if not self._is_cancelled:
                self.finished.emit(
                    len(target_pls), len(unique_track_ids), total_bytes, exact_count, estimated_count
                )

        except Exception:
            if not self._is_cancelled:
                self.finished.emit(0, 0, 0, 0, 0)



# ---------------------------------------------------------------------------
# Sort-order delegate helper
# ---------------------------------------------------------------------------
SORT_OPTIONS = ["元の順序", "BPM昇順"]
SORT_MAP = {"元の順序": "default", "BPM昇順": "bpm"}
SORT_MAP_REV = {v: k for k, v in SORT_MAP.items()}



# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("rkbdb2xml - Rekordbox XML エクスポーター")
        self.setMinimumSize(850, 650)
        self.resize(1050, 720)
        self.setWindowIcon(get_app_icon())

        self._export_thread: Optional[QThread] = None
        self._is_updating_checks = False
        self._current_preview_item: Optional[QStandardItem] = None

        self._calc_thread: Optional[QThread] = None
        self._calc_worker: Optional[SizeCalculatorWorker] = None
        self._calc_timer = QTimer(self)
        self._calc_timer.setSingleShot(True)
        self._calc_timer.timeout.connect(self._start_async_size_calculation)

        # Media player for previewing audio
        self._player: Optional[Any] = None
        self._audio_output: Optional[Any] = None
        self._is_seeking = False
        self._current_playing_file = ""

        if HAS_MULTIMEDIA:
            try:
                self._player = QMediaPlayer(self)
                self._audio_output = QAudioOutput(self)
                self._player.setAudioOutput(self._audio_output)
                self._audio_output.setVolume(0.7)
                self._player.positionChanged.connect(self._on_player_position_changed)
                self._player.durationChanged.connect(self._on_player_duration_changed)
                self._player.playbackStateChanged.connect(self._on_player_state_changed)
            except Exception as e:
                print("[WARN] QMediaPlayer init failed:", e)
                self._player = None

        self._build_ui()


        self._check_rekordbox_status()
        self._load_playlists()

    # ----- UI construction -----

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # --- Rekordbox warning banner (hidden by default) ---
        self._rb_warn_frame = QFrame()
        self._rb_warn_frame.setStyleSheet(
            "QFrame { background-color: #fff3cd; color: #856404; "
            "border: 1px solid #ffeeba; border-radius: 4px; padding: 6px; }"
        )
        warn_layout = QHBoxLayout(self._rb_warn_frame)
        warn_layout.setContentsMargins(8, 4, 8, 4)
        self._rb_warn_label = QLabel(
            "⚠️ 注意: Rekordbox が起動しています。データベースを正確に読み込むため、Rekordbox を終了することを推奨します。"
        )
        self._rb_warn_label.setStyleSheet("font-weight: bold; color: #856404;")
        warn_layout.addWidget(self._rb_warn_label)
        self._rb_warn_frame.setVisible(False)
        layout.addWidget(self._rb_warn_frame)

        # --- Output folder row ---
        out_row = QHBoxLayout()
        out_label = QLabel("出力先フォルダ:")
        out_label.setStyleSheet("font-weight: bold;")
        out_row.addWidget(out_label)

        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("エクスポート先のフォルダを選択...")
        self._output_edit.setToolTip("XMLファイルおよび複製された楽曲ファイルが保存されるフォルダです")
        out_row.addWidget(self._output_edit, 1)

        browse_btn = QPushButton("📁 参照...")
        browse_btn.setToolTip("エクスポート先のフォルダを選択します")
        browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_btn)

        open_folder_btn = QPushButton("📂 開く")
        open_folder_btn.setToolTip("現在の出力先フォルダをファイルマネージャーで開きます")
        open_folder_btn.clicked.connect(self._open_current_output_dir)
        out_row.addWidget(open_folder_btn)

        layout.addLayout(out_row)

        # --- Toolbar row (Quick actions) ---
        toolbar_row = QHBoxLayout()
        toolbar_row.setSpacing(8)

        reload_btn = QPushButton("🔄 プレイリスト再読み込み")
        reload_btn.setToolTip("Rekordbox から最新のプレイリストを再取得します")
        reload_btn.clicked.connect(self._on_reload_playlists)
        toolbar_row.addWidget(reload_btn)

        select_all_btn = QPushButton("☑️ すべて選択")
        select_all_btn.setToolTip("すべてのプレイリストをエクスポート対象として選択します")
        select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        toolbar_row.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("⬜ すべて解除")
        deselect_all_btn.setToolTip("すべてのプレイリストの選択を解除します")
        deselect_all_btn.clicked.connect(lambda: self._set_all_checked(False))
        toolbar_row.addWidget(deselect_all_btn)

        # Batch options menu
        batch_btn = QPushButton("⚙️ 一括設定 ▾")
        batch_btn.setToolTip("選択中のすべてのプレイリストのオプションを一括変更します")
        batch_menu = QMenu(self)

        act_roman_on = batch_menu.addAction("全プレイリストの「ローマ字変換」をON")
        act_roman_on.triggered.connect(lambda: self._batch_set_option(COL_ROMAN, Qt.Checked))

        act_roman_off = batch_menu.addAction("全プレイリストの「ローマ字変換」をOFF")
        act_roman_off.triggered.connect(lambda: self._batch_set_option(COL_ROMAN, Qt.Unchecked))

        batch_menu.addSeparator()

        act_bpm_on = batch_menu.addAction("全プレイリストの「BPM付与」をON")
        act_bpm_on.triggered.connect(lambda: self._batch_set_option(COL_BPM, Qt.Checked))

        act_bpm_off = batch_menu.addAction("全プレイリストの「BPM付与」をOFF")
        act_bpm_off.triggered.connect(lambda: self._batch_set_option(COL_BPM, Qt.Unchecked))

        batch_menu.addSeparator()

        act_sort_bpm = batch_menu.addAction("全プレイリストの並び順を「BPM昇順」に設定")
        act_sort_bpm.triggered.connect(lambda: self._batch_set_sort("BPM昇順"))

        act_sort_default = batch_menu.addAction("全プレイリストの並び順を「元の順序」に設定")
        act_sort_default.triggered.connect(lambda: self._batch_set_sort("元の順序"))

        batch_btn.setMenu(batch_menu)
        toolbar_row.addWidget(batch_btn)

        toolbar_row.addStretch(1)
        layout.addLayout(toolbar_row)

        # --- Main Splitter (Left: Playlist Tree, Right: Track Preview) ---
        self._splitter = QSplitter(Qt.Horizontal)

        # Left panel: Playlist tree
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(4)
        tree_title = QLabel("📂 プレイリスト一覧 (チェックでエクスポート対象選択)")
        tree_title.setStyleSheet("font-weight: bold; color: #495057;")
        tree_layout.addWidget(tree_title)

        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["プレイリスト", "ローマ字", "BPM付加", "曲の並び順"])

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

        # Tooltips on headers
        self._tree.header().setToolTip(
            "プレイリスト: エクスポートする対象を選択\n"
            "ローマ字: 日本語の曲名・アーティスト名・アルバム名を半角ローマ字に変換\n"
            "BPM付加: 曲名先頭にテンポ数値を付与 (例: '128 曲名')\n"
            "曲の並び順: プレイリスト内の曲順を指定"
        )

        # Connect item-changed for checkbox cascading
        self._model.itemChanged.connect(self._on_item_changed)

        tree_layout.addWidget(self._tree, 1)
        self._splitter.addWidget(tree_container)

        # Right panel: Track preview table
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)

        self._preview_header = QLabel("🎵 選択中プレイリストの曲プレビュー (変換前 → 変換後イメージ)")
        self._preview_header.setStyleSheet("font-weight: bold; color: #1a73e8;")
        preview_layout.addWidget(self._preview_header)

        self._preview_model = QStandardItemModel()
        self._preview_model.setHorizontalHeaderLabels([
            "#", "元の曲名", "変換後タイトル (出力タグ/XML)", "アーティスト", "BPM", "ファイル状態"
        ])

        self._preview_table = QTableView()
        self._preview_table.setModel(self._preview_model)
        self._preview_table.setAlternatingRowColors(True)
        self._preview_table.setSelectionBehavior(QTableView.SelectRows)
        self._preview_table.setSelectionMode(QTableView.SingleSelection)
        self._preview_table.setEditTriggers(QTableView.NoEditTriggers)
        self._preview_table.horizontalHeader().setStretchLastSection(False)
        self._preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self._preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self._preview_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._preview_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        # Double click to play
        self._preview_table.doubleClicked.connect(self._on_preview_table_double_clicked)
        preview_layout.addWidget(self._preview_table, 1)

        # --- Mini Audio Player Panel ---
        player_frame = QFrame()
        player_frame.setStyleSheet(
            "QFrame { background-color: #f1f3f4; border: 1px solid #dadce0; "
            "border-radius: 6px; padding: 4px; }"
        )
        player_layout = QVBoxLayout(player_frame)
        player_layout.setContentsMargins(8, 4, 8, 4)
        player_layout.setSpacing(4)

        # Player top row: Controls & current track
        player_top = QHBoxLayout()
        self._play_btn = QPushButton("▶️ 再生")
        self._play_btn.setToolTip("選択中の曲を再生/一時停止 (曲をダブルクリックでも再生できます)")
        self._play_btn.setStyleSheet("font-weight: bold; padding: 3px 12px;")
        self._play_btn.clicked.connect(self._toggle_playback)
        player_top.addWidget(self._play_btn)

        self._stop_btn = QPushButton("⏹️ 停止")
        self._stop_btn.setStyleSheet("padding: 3px 10px;")
        self._stop_btn.clicked.connect(self._stop_playback)
        player_top.addWidget(self._stop_btn)

        self._player_track_label = QLabel("🎧 試聴: 曲をダブルクリックまたは選択して「▶️ 再生」")
        self._player_track_label.setStyleSheet("font-weight: bold; color: #3c4043; padding-left: 6px;")
        player_top.addWidget(self._player_track_label, 1)

        player_layout.addLayout(player_top)

        # Player bottom row: Seekbar, Time, Volume
        player_bot = QHBoxLayout()
        self._time_curr_label = QLabel("00:00")
        self._time_curr_label.setStyleSheet("font-size: 11px; color: #5f6368;")
        player_bot.addWidget(self._time_curr_label)

        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setValue(0)
        self._seek_slider.sliderMoved.connect(self._on_seek_slider_moved)
        self._seek_slider.sliderPressed.connect(self._on_seek_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_seek_slider_released)
        player_bot.addWidget(self._seek_slider, 1)

        self._time_total_label = QLabel("00:00")
        self._time_total_label.setStyleSheet("font-size: 11px; color: #5f6368;")
        player_bot.addWidget(self._time_total_label)

        vol_icon = QLabel("🔊")
        player_bot.addWidget(vol_icon)

        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(70)
        self._vol_slider.setMaximumWidth(80)
        self._vol_slider.setToolTip("音量調節")
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        player_bot.addWidget(self._vol_slider)

        player_layout.addLayout(player_bot)
        preview_layout.addWidget(player_frame)

        self._splitter.addWidget(preview_container)
        self._splitter.setSizes([450, 550])


        layout.addWidget(self._splitter, 1)

        # --- Export summary & capacity meter ---
        summary_frame = QFrame()
        summary_frame.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border: 1px solid #dee2e6; "
            "border-radius: 6px; padding: 6px 12px; }"
        )
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(6, 4, 6, 4)
        summary_layout.setSpacing(12)

        self._summary_label = QLabel("📊 エクスポート対象: 0 プレイリスト (0 曲 / 0 MB)")
        self._summary_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #212529;")
        summary_layout.addWidget(self._summary_label)

        self._capacity_label = QLabel("・ 16GB USBメモリ目安: 0.0% 使用 (残り 14.8 GB)")
        self._capacity_label.setStyleSheet("font-size: 12px; color: #2e7d32; font-weight: bold;")
        summary_layout.addWidget(self._capacity_label)

        summary_layout.addStretch(1)
        layout.addWidget(summary_frame)

        # --- Export button row ---
        export_row = QHBoxLayout()
        self._export_btn = QPushButton("🚀 エクスポート開始")
        self._export_btn.setMinimumHeight(40)
        self._export_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 6px 20px; }"
        )
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
        self._log.setMaximumHeight(130)
        self._log.setPlaceholderText("実行ログがここに表示されます...")
        layout.addWidget(self._log)

    # ----- Safety & Status checks -----

    def _check_rekordbox_status(self) -> None:
        """Check if Rekordbox process is currently running and update warning banner."""
        is_running = False
        try:
            for proc in psutil.process_iter(["name"]):
                name = proc.info.get("name")
                if name and "rekordbox" in name.lower():
                    is_running = True
                    break
        except Exception:
            pass
        self._rb_warn_frame.setVisible(is_running)

    # ----- Playlist loading -----

    def _on_reload_playlists(self) -> None:
        """Reload button handler."""
        self._check_rekordbox_status()
        self._load_playlists()

    def _load_playlists(self) -> None:
        """Load playlists from Rekordbox DB and build the tree model."""
        self._log_message("Rekordbox データベースを読み込み中...")
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["プレイリスト", "ローマ字変換", "BPM付加", "曲の並び順"])

        try:
            db = RekordboxDatabase()
            pls = db.get_playlist().all()
        except Exception as e:
            msg = (
                f"Rekordbox データベースの読み込みに失敗しました。\n\n"
                f"【詳細】: {e}\n\n"
                f"※ Rekordbox が起動中の場合は終了してから再試行してください。"
            )
            self._log_message(f"DB読み込みエラー: {e}")
            QMessageBox.warning(self, "データベース読み込みエラー", msg)
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
                    pl_opts = saved.get("playlist_options", {}).get(path_str, {})

                    roman_item = QStandardItem()
                    roman_item.setCheckable(True)
                    roman_item.setCheckState(
                        Qt.Checked if pl_opts.get("roman", True) else Qt.Unchecked
                    )
                    roman_item.setEditable(False)
                    roman_item.setToolTip("日本語の曲名・アーティスト名・アルバム名を半角ローマ字に変換します")

                    bpm_item = QStandardItem()
                    bpm_item.setCheckable(True)
                    bpm_item.setCheckState(
                        Qt.Checked if pl_opts.get("bpm", True) else Qt.Unchecked
                    )
                    bpm_item.setEditable(False)
                    bpm_item.setToolTip("曲名の先頭にテンポ（BPM数値）を付加します (例: 128 TrackName)")

                    sort_val = pl_opts.get("orderby", "bpm")
                    sort_label = SORT_MAP_REV.get(sort_val, "BPM昇順")
                    sort_item = QStandardItem(sort_label)
                    sort_item.setEditable(False)
                    sort_item.setToolTip("プレイリスト内の曲順を指定します")

                parent_item.appendRow([name_item, roman_item, bpm_item, sort_item])

                if is_folder:
                    build_tree(name_item, pl.ID, path_str)

        root = self._model.invisibleRootItem()
        for rp in root_parents:
            build_tree(root, rp, "")

        self._model.blockSignals(False)

        self._tree.collapseAll()

        # Set sort combo delegates after tree is built
        self._setup_sort_combos(root)

        # Restore output path (or use user-friendly default)
        saved_output = saved.get("output_path", "").strip()
        if saved_output:
            self._output_edit.setText(saved_output)
        else:
            self._output_edit.setText(str(get_default_output_dir()))

        count = self._count_playlists(root)
        self._log_message(f"{count} 個のプレイリストを読み込みました")

        # Connect tree selection to track preview
        self._tree.selectionModel().currentChanged.connect(self._on_tree_selection_changed)

        # Select first available playlist for preview if available
        for row in range(root.rowCount()):
            item = root.child(row, COL_CHECK)
            if item and not item.data(ROLE_IS_FOLDER):
                idx = self._model.indexFromItem(item)
                self._tree.selectionModel().setCurrentIndex(
                    idx, self._tree.selectionModel().SelectionFlag.ClearAndSelect
                )
                break

        # Calculate initial selection size
        self._trigger_size_calculation()


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
                current_text = sort_item.text()
                combo_idx = combo.findText(current_text)
                if combo_idx >= 0:
                    combo.setCurrentIndex(combo_idx)
                # Re-render preview when sort order changed
                combo.currentIndexChanged.connect(self._on_option_changed_refresh_preview)
                self._tree.setIndexWidget(idx, combo)
            if name_item.hasChildren():
                self._setup_sort_combos(name_item)

    def _on_option_changed_refresh_preview(self) -> None:
        """Refresh track preview when an option (roman, bpm, sort) changes."""
        if self._current_preview_item:
            self._update_track_preview(self._current_preview_item)

    def _on_tree_selection_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        """Update track preview when a playlist or folder is selected."""
        if not current.isValid():
            return
        name_idx = current.siblingAtColumn(COL_CHECK)
        item = self._model.itemFromIndex(name_idx)
        if item:
            self._update_track_preview(item)

    def _update_track_preview(self, item: QStandardItem) -> None:
        """Fetch tracks for selected playlist and populate preview table."""
        self._current_preview_item = item
        if not item:
            return

        is_folder = item.data(ROLE_IS_FOLDER)
        pl_id = item.data(ROLE_PL_ID)
        path_str = item.data(ROLE_PATH) or item.text()

        self._preview_model.removeRows(0, self._preview_model.rowCount())

        if is_folder:
            self._preview_header.setText(
                f"📁 フォルダ: {path_str} (※ プレイリストを選択すると曲プレビューが表示されます)"
            )
            return

        # Read current option settings from the tree row
        parent = item.parent() or self._model.invisibleRootItem()
        row = item.row()
        roman_item = parent.child(row, COL_ROMAN)
        bpm_item = parent.child(row, COL_BPM)
        sort_item = parent.child(row, COL_SORT)

        use_roman = (
            roman_item.checkState() == Qt.Checked
            if (roman_item and roman_item.isCheckable())
            else True
        )
        use_bpm = (
            bpm_item.checkState() == Qt.Checked
            if (bpm_item and bpm_item.isCheckable())
            else True
        )

        sort_text = "BPM昇順"
        if sort_item:
            idx = self._model.indexFromItem(sort_item)
            widget = self._tree.indexWidget(idx)
            if isinstance(widget, QComboBox):
                sort_text = widget.currentText()
            elif sort_item.text():
                sort_text = sort_item.text()
        orderby = SORT_MAP.get(sort_text, "bpm")

        # Query tracks from Rekordbox DB
        try:
            db = RekordboxDatabase()
            pl_obj = None
            for p in db.get_playlist().all():
                if p.ID == pl_id:
                    pl_obj = p
                    break
            if not pl_obj:
                self._preview_header.setText(f"🎵 プレイリスト: {path_str} (0 曲)")
                return

            entries = db.get_playlist_contents(pl_obj).all()
            if orderby == "bpm":
                def safe_bpm(entry):
                    b = getattr(entry, "BPM", None)
                    return b if b else 0
                entries = sorted(entries, key=safe_bpm)

            self._preview_header.setText(
                f"🎵 プレイリスト: {path_str} (全 {len(entries)} 曲)  "
                f"[ローマ字: {'ON' if use_roman else 'OFF'}, BPM付加: {'ON' if use_bpm else 'OFF'}, 順序: {sort_text}]"
            )

            from rkbdb2xml.rkbdb2xml import RomanConverter, RekordboxXMLExporter
            roman_conv = RomanConverter() if use_roman else None
            path_resolver = RekordboxXMLExporter.__new__(RekordboxXMLExporter)

            for i, entry in enumerate(entries, 1):
                raw_title = getattr(entry, "Title", "") or ""
                raw_artist = (
                    getattr(entry, "ArtistName", "")
                    or getattr(entry, "Artist", "")
                    or ""
                )
                raw_bpm = getattr(entry, "BPM", None)
                loc = getattr(entry, "FolderPath", None)

                conv_title = raw_title
                conv_artist = raw_artist
                if use_roman and roman_conv:
                    if not conv_title.isascii():
                        try:
                            conv_title = roman_conv.to_roman(conv_title)
                        except Exception:
                            pass
                    if not conv_artist.isascii():
                        try:
                            conv_artist = roman_conv.to_roman(conv_artist)
                        except Exception:
                            pass

                bpm_val = None
                if raw_bpm:
                    try:
                        bpm_val = float(raw_bpm) / 100.0
                    except Exception:
                        pass

                if use_bpm and bpm_val:
                    conv_title = f"{int(bpm_val)} {conv_title}"

                # Check file existence and resolve path
                file_status = "❌ なし"
                resolved_path_str = ""
                if loc:
                    try:
                        p = path_resolver._resolve_file_path(loc)
                        if p and p.exists() and p.is_file():
                            file_status = "⭕ 存在"
                            resolved_path_str = str(p)
                    except Exception:
                        pass

                num_item = QStandardItem(str(i))
                num_item.setData(resolved_path_str, ROLE_FILE_PATH)
                display_track_name = f"{conv_title} - {conv_artist}" if conv_artist else conv_title
                num_item.setData(display_track_name, ROLE_TRACK_TITLE)

                orig_title_item = QStandardItem(raw_title)
                conv_title_item = QStandardItem(conv_title)
                artist_item = QStandardItem(conv_artist)
                bpm_item_table = QStandardItem(f"{bpm_val:.1f}" if bpm_val else "-")
                file_item = QStandardItem(file_status)

                for it in (num_item, orig_title_item, conv_title_item, artist_item, bpm_item_table, file_item):
                    it.setEditable(False)

                conv_title_item.setToolTip(f"出力ファイル内タグ & XML名: {conv_title}")
                if loc:
                    file_item.setToolTip(f"元ファイルパス: {loc}")

                self._preview_model.appendRow([
                    num_item, orig_title_item, conv_title_item, artist_item, bpm_item_table, file_item
                ])



        except Exception as e:
            self._preview_header.setText(f"🎵 プレイリスト: {path_str} (読み込みエラー: {e})")

    # ----- Audio Player Controls -----

    def _on_preview_table_double_clicked(self, index: QModelIndex) -> None:
        """Play track when double clicking row in preview table."""
        if not index.isValid():
            return
        row = index.row()
        num_item = self._preview_model.item(row, 0)
        if not num_item:
            return
        file_path = num_item.data(ROLE_FILE_PATH)
        title = num_item.data(ROLE_TRACK_TITLE)
        if file_path:
            self._play_audio_file(file_path, title)
        else:
            self._player_track_label.setText("⚠️ ローカルに実ファイルが見つからないため試聴できません")
            self._player_track_label.setStyleSheet("font-weight: bold; color: #dc2626;")

    def _toggle_playback(self) -> None:
        """Toggle play/pause for selected track in preview table."""
        if not HAS_MULTIMEDIA or not self._player:
            QMessageBox.information(self, "プレイヤー未対応", "この環境ではマルチメディア再生がサポートされていません。")
            return

        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()
            return
        elif self._player.playbackState() == QMediaPlayer.PausedState:
            self._player.play()
            return

        # If stopped, play currently selected row in preview table
        sel = self._preview_table.selectionModel().currentIndex()
        if sel.isValid():
            self._on_preview_table_double_clicked(sel)
        else:
            # Try first row if available
            if self._preview_model.rowCount() > 0:
                idx = self._preview_model.index(0, 0)
                self._preview_table.selectionModel().setCurrentIndex(
                    idx, self._preview_table.selectionModel().SelectionFlag.ClearAndSelect
                )
                self._on_preview_table_double_clicked(idx)

    def _play_audio_file(self, file_path: str, title: str) -> None:
        """Load and start playing local audio file."""
        if not HAS_MULTIMEDIA or not self._player:
            return

        p = Path(file_path)
        if not p.exists() or not p.is_file():
            self._player_track_label.setText(f"⚠️ ファイルが見つかりません: {p.name}")
            self._player_track_label.setStyleSheet("font-weight: bold; color: #dc2626;")
            return

        self._current_playing_file = str(p)
        self._player.setSource(QUrl.fromLocalFile(str(p)))
        self._player.play()
        self._player_track_label.setText(f"🎵 再生中: {title}")
        self._player_track_label.setStyleSheet("font-weight: bold; color: #1a73e8;")

    def _stop_playback(self) -> None:
        """Stop playing audio."""
        if self._player:
            self._player.stop()
            self._seek_slider.setValue(0)
            self._time_curr_label.setText("00:00")
            self._player_track_label.setText("🎧 試聴: 停止中")
            self._player_track_label.setStyleSheet("font-weight: bold; color: #5f6368;")

    def _on_seek_slider_pressed(self) -> None:
        self._is_seeking = True

    def _on_seek_slider_released(self) -> None:
        if self._player:
            dur = self._player.duration()
            pos = int((self._seek_slider.value() / 1000.0) * dur)
            self._player.setPosition(pos)
        self._is_seeking = False

    def _on_seek_slider_moved(self, value: int) -> None:
        if self._player:
            dur = self._player.duration()
            curr_ms = int((value / 1000.0) * dur)
            self._time_curr_label.setText(format_time(curr_ms))

    def _on_volume_changed(self, value: int) -> None:
        if self._audio_output:
            self._audio_output.setVolume(value / 100.0)

    def _on_player_position_changed(self, position: int) -> None:
        if not self._is_seeking:
            dur = self._player.duration() if self._player else 0
            if dur > 0:
                val = int((position / dur) * 1000)
                self._seek_slider.setValue(val)
            self._time_curr_label.setText(format_time(position))

    def _on_player_duration_changed(self, duration: int) -> None:
        self._time_total_label.setText(format_time(duration))

    def _on_player_state_changed(self, state: Any) -> None:
        if state == QMediaPlayer.PlayingState:
            self._play_btn.setText("⏸️ 一時停止")
        else:
            self._play_btn.setText("▶️ 再生")


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

    # ----- Batch operations -----

    def _set_all_checked(self, checked: bool) -> None:
        """Check or uncheck all playlists and folders."""
        state = Qt.Checked if checked else Qt.Unchecked
        self._is_updating_checks = True
        try:
            root = self._model.invisibleRootItem()
            self._set_children_check(root, state)
        finally:
            self._is_updating_checks = False
        self._trigger_size_calculation()


    def _batch_set_option(self, col: int, state: Qt.CheckState) -> None:
        """Batch set checkbox state for an option column across all playlists."""
        root = self._model.invisibleRootItem()
        self._apply_option_state(root, col, state)
        self._on_option_changed_refresh_preview()

    def _apply_option_state(self, parent: QStandardItem, col: int, state: Qt.CheckState) -> None:
        for row in range(parent.rowCount()):
            name_item = parent.child(row, COL_CHECK)
            if not name_item:
                continue
            is_folder = name_item.data(ROLE_IS_FOLDER)
            if not is_folder:
                opt_item = parent.child(row, col)
                if opt_item and opt_item.isCheckable():
                    opt_item.setCheckState(state)
            if name_item.hasChildren():
                self._apply_option_state(name_item, col, state)

    def _batch_set_sort(self, sort_text: str) -> None:
        """Batch set sort order combo value for all playlists."""
        root = self._model.invisibleRootItem()
        self._apply_sort_text(root, sort_text)
        self._on_option_changed_refresh_preview()


    def _apply_sort_text(self, parent: QStandardItem, sort_text: str) -> None:
        for row in range(parent.rowCount()):
            name_item = parent.child(row, COL_CHECK)
            if not name_item:
                continue
            is_folder = name_item.data(ROLE_IS_FOLDER)
            if not is_folder:
                sort_item = parent.child(row, COL_SORT)
                if sort_item:
                    idx = self._model.indexFromItem(sort_item)
                    widget = self._tree.indexWidget(idx)
                    if isinstance(widget, QComboBox):
                        c_idx = widget.findText(sort_text)
                        if c_idx >= 0:
                            widget.setCurrentIndex(c_idx)
            if name_item.hasChildren():
                self._apply_sort_text(name_item, sort_text)

    # ----- Size & track count calculation (Async) -----

    def _trigger_size_calculation(self) -> None:
        """Trigger debounced asynchronous calculation of selected tracks and size."""
        self._summary_label.setText("📊 エクスポート対象: 計算中...")
        self._calc_timer.start(250)  # 250ms debounce

    def _start_async_size_calculation(self) -> None:
        """Start background worker to compute size of selected playlists."""
        if self._calc_worker:
            self._calc_worker.cancel()
        if self._calc_thread and self._calc_thread.isRunning():
            self._calc_thread.quit()
            self._calc_thread.wait(100)

        selected_paths: List[str] = []
        root = self._model.invisibleRootItem()
        self._collect_selected(root, selected_paths)

        if not selected_paths:
            self._on_size_calculated(0, 0, 0, 0, 0)
            return

        worker = SizeCalculatorWorker(selected_paths)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_size_calculated)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._calc_worker = worker
        self._calc_thread = thread
        thread.start()

    @Slot(int, int, int, int, int)
    def _on_size_calculated(
        self,
        playlist_count: int,
        track_count: int,
        total_bytes: int,
        exact_count: int,
        estimated_count: int,
    ) -> None:
        """Handle computed size and update summary label and capacity meter."""
        if playlist_count == 0 or track_count == 0 or total_bytes == 0:
            self._summary_label.setText("📊 選択中: 0 プレイリスト (0 曲 / 0 B)")
            self._capacity_label.setText("💾 16GB USBメモリ目安 (実効約14.8GB): 0 B / 14.8 GB (0.0% 使用)")
            self._capacity_label.setStyleSheet("font-size: 12px; color: #495057;")
            return

        size_str = format_bytes(total_bytes)

        breakdown = ""
        if estimated_count > 0:
            breakdown = f" (実ファイル: {exact_count}曲 / 推定: {estimated_count}曲)"

        self._summary_label.setText(
            f"📊 選択中: {playlist_count} プレイリスト ｜ 全 {track_count:,} 曲 ｜ 合計 約 {size_str}{breakdown}"
        )

        # Usable capacities: 16GB ≒ 14.8 GB, 32GB ≒ 29.5 GB, 64GB ≒ 59.0 GB
        USB_16GB = 14.8 * 1024 * 1024 * 1024
        USB_32GB = 29.5 * 1024 * 1024 * 1024
        USB_64GB = 59.0 * 1024 * 1024 * 1024

        ratio_16g = (total_bytes / USB_16GB) * 100.0

        if total_bytes <= USB_16GB:
            rem = USB_16GB - total_bytes
            rem_str = format_bytes(int(rem))
            self._capacity_label.setText(
                f"💾 16GB USBメモリ目安: {size_str} / 14.8 GB ({ratio_16g:.1f}% 使用 ｜ 残り {rem_str})  ⭕ 収まります"
            )
            self._capacity_label.setStyleSheet("font-size: 12px; color: #2e7d32; font-weight: bold;")
        elif total_bytes <= USB_32GB:
            over = total_bytes - USB_16GB
            over_str = format_bytes(int(over))
            rem_32 = USB_32GB - total_bytes
            rem_32_str = format_bytes(int(rem_32))
            self._capacity_label.setText(
                f"⚠️ 16GB容量オーバー: {size_str} / 14.8 GB ({ratio_16g:.1f}% ｜ +{over_str} 超過 ❌) ➔ 32GB USBメモリ推奨 (残 {rem_32_str})"
            )
            self._capacity_label.setStyleSheet("font-size: 12px; color: #d97706; font-weight: bold;")
        elif total_bytes <= USB_64GB:
            over = total_bytes - USB_16GB
            over_str = format_bytes(int(over))
            rem_64 = USB_64GB - total_bytes
            rem_64_str = format_bytes(int(rem_64))
            self._capacity_label.setText(
                f"⚠️ 16GB容量オーバー: {size_str} / 14.8 GB ({ratio_16g:.1f}% ｜ +{over_str} 超過 ❌) ➔ 64GB USBメモリ推奨 (残 {rem_64_str})"
            )
            self._capacity_label.setStyleSheet("font-size: 12px; color: #dc2626; font-weight: bold;")
        else:
            over = total_bytes - USB_16GB
            over_str = format_bytes(int(over))
            self._capacity_label.setText(
                f"⚠️ 16GB大幅オーバー: {size_str} / 14.8 GB ({ratio_16g:.1f}% ｜ +{over_str} 超過 ❌) ➔ 128GB以上の大容量メディア推奨"
            )
            self._capacity_label.setStyleSheet("font-size: 12px; color: #dc2626; font-weight: bold;")


    # ----- Checkbox cascading -----

    def _on_item_changed(self, item: QStandardItem) -> None:
        """When a folder or playlist checkbox changes, cascade to children and parents."""
        if getattr(self, "_is_updating_checks", False):
            return

        col = item.column()
        if col in (COL_ROMAN, COL_BPM):
            self._on_option_changed_refresh_preview()
            return

        if col != COL_CHECK:
            return

        self._is_updating_checks = True
        try:
            state = item.checkState()
            is_folder = item.data(ROLE_IS_FOLDER)

            # Cascade downwards to all children
            if is_folder and item.hasChildren():
                self._set_children_check(item, state)

            # Update parent folder state upwards
            parent = item.parent()
            if parent:
                self._update_parent_check_state(parent)
        finally:
            self._is_updating_checks = False

        self._trigger_size_calculation()



    def _set_children_check(self, parent: QStandardItem, state: Qt.CheckState) -> None:
        """Recursively set check state on all descendant items."""
        target_state = Qt.Checked if state == Qt.Checked else Qt.Unchecked
        for row in range(parent.rowCount()):
            child = parent.child(row, COL_CHECK)
            if child:
                child.setCheckState(target_state)
                if child.hasChildren():
                    self._set_children_check(child, target_state)

    def _update_parent_check_state(self, parent: QStandardItem) -> None:
        """Update parent item checkState based on its children states."""
        if not parent:
            return
        checked_count = 0
        total_count = 0
        has_partial = False

        for row in range(parent.rowCount()):
            child = parent.child(row, COL_CHECK)
            if child:
                total_count += 1
                c_state = child.checkState()
                if c_state == Qt.Checked:
                    checked_count += 1
                elif c_state == Qt.PartiallyChecked:
                    has_partial = True

        if total_count > 0:
            if checked_count == total_count:
                parent.setCheckState(Qt.Checked)
            elif checked_count == 0 and not has_partial:
                parent.setCheckState(Qt.Unchecked)
            else:
                parent.setCheckState(Qt.PartiallyChecked)

        # Recurse upwards to grandparents
        grand_parent = parent.parent()
        if grand_parent:
            self._update_parent_check_state(grand_parent)

    # ----- Output folder -----

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "出力先フォルダを選択")
        if folder:
            self._output_edit.setText(folder)

    def _open_current_output_dir(self) -> None:
        """Open the current output directory in the system file explorer."""
        path_str = self._output_edit.text().strip()
        if not path_str:
            QMessageBox.information(self, "通知", "出力先フォルダが設定されていません。")
            return
        p = Path(path_str)
        if not p.exists():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(self, "エラー", f"フォルダを作成できませんでした: {e}")
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    # ----- Export -----

    def _on_export(self) -> None:
        self._check_rekordbox_status()

        output_path = self._output_edit.text().strip()
        if not output_path:
            QMessageBox.warning(self, "確認", "出力先フォルダを指定してください。")
            return

        output_dir = Path(output_path)
        if not output_dir.exists():
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                QMessageBox.critical(
                    self, "フォルダ作成エラー", f"フォルダの作成に失敗しました:\n{e}"
                )
                return

        xml_path = str(output_dir / "rekordbox.xml")

        # Collect selected playlists
        selected_paths: List[str] = []
        root = self._model.invisibleRootItem()
        self._collect_selected(root, selected_paths)

        if not selected_paths:
            QMessageBox.warning(
                self,
                "プレイリスト未選択",
                "エクスポート対象のプレイリストが選択されていません。\n"
                "一覧からエクスポートしたいプレイリストにチェックを入れてください。",
            )
            return

        # Collect per-playlist options dict
        pl_options: Dict[str, dict] = {}
        self._collect_all_options(root, pl_options)

        # Save settings before export
        self._save_settings()

        self._export_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._current_export_dir = output_dir
        self._log_message(f"エクスポート対象: {len(selected_paths)} 件の項目")

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
        """Collect path strings of checked and partially checked items."""
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if not item:
                continue
            path_str = item.data(ROLE_PATH)
            state = item.checkState()

            if state in (Qt.Checked, Qt.PartiallyChecked):
                if path_str and path_str not in result:
                    result.append(path_str)
                if item.hasChildren():
                    self._collect_selected(item, result)
            else:
                if item.hasChildren():
                    self._collect_selected(item, result)


    @Slot(str)
    def _on_export_error(self, msg: str) -> None:
        self._log_message(f"エラー: {msg}")
        err_dialog = QMessageBox(self)
        err_dialog.setIcon(QMessageBox.Critical)
        err_dialog.setWindowTitle("エクスポートエラー")
        err_dialog.setText("エクスポート処理中にエラーが発生しました。")
        err_dialog.setInformativeText(
            f"{msg}\n\n"
            "【ヒント】\n"
            "・Rekordbox が起動している場合は終了してから再試行してください。\n"
            "・出力先フォルダの書き込み権限やディスク容量を確認してください。"
        )
        err_dialog.exec()

    @Slot()
    def _on_export_done(self) -> None:
        self._export_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._export_thread = None

        export_dir = getattr(self, "_current_export_dir", None)
        if export_dir and export_dir.exists():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle("エクスポート完了")
            box.setText("🎉 エクスポートが正常に完了しました！")
            box.setInformativeText(f"【出力先】\n{export_dir}")
            open_btn = box.addButton("📂 出力先フォルダを開く", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Ok)
            box.exec()

            if box.clickedButton() == open_btn:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(export_dir.resolve())))

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
    app.setWindowIcon(get_app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()



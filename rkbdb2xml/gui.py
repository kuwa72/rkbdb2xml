"""
PySide6 GUI for rkbdb2xml.

Provides a tree-based playlist viewer with per-playlist export options,
output folder selection, and background export execution.
"""

import io
import json
import platform
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    QCheckBox,
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



from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase

from . import __version__, player
from .player import PreviewPlayer
from .rkbdb2xml import (
    export_rekordbox_db_to_device,
    export_rekordbox_db_to_xml,
    playlist_tracks,
)

# ---------------------------------------------------------------------------
# Constants & Defaults
# ---------------------------------------------------------------------------
SETTINGS_FILE = Path.home() / ".rkbdb2xml_gui_settings.json"

# Diagnostic log for the mini player (written next to the settings file)
PLAYER_LOG_FILE = Path.home() / ".rkbdb2xml_player.log"


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
    """Runs export_rekordbox_db_to_* in a background thread.

    ``progress_count`` emits ``(done, total, done_bytes, total_bytes)`` during
    the file-copy phase; ``phase_changed`` emits the current phase name.
    ``cancel()`` requests a stop at the next track boundary; the export then
    reports ``cancelled`` (a third outcome, distinct from success/error).
    """

    progress = Signal(str)  # log messages
    # done/total are track counts; done_bytes/total_bytes can exceed 2 GiB and
    # must not go through Qt's 32-bit int conversion (it silently wraps on
    # Windows), so they are declared as object.
    progress_count = Signal(int, int, object, object)
    phase_changed = Signal(str)
    succeeded = Signal()  # export completed without error
    cancelled = Signal()  # export stopped by cancel(); no error occurred
    finished = Signal()  # always emitted, success, failure or cancel
    error = Signal(str)

    def __init__(
        self,
        db_path: Optional[str],
        output_path: str,
        playlists: Optional[List[str]],
        playlist_options: Optional[Dict[str, dict]] = None,
        device_export: bool = False,
    ):
        super().__init__()
        self._db_path = db_path
        self._output_path = output_path
        self._playlists = playlists
        self._playlist_options = playlist_options or {}
        self._device_export = device_export
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation; the exporter checks this periodically."""
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        """Run the export. Always reports either an error or completion.

        Nothing may escape this slot: an exception propagating back into Qt's
        signal dispatch leaves the thread half torn down, so the window never
        learns the export ended and simply stops responding.
        """
        capture = io.StringIO()
        try:
            self.progress.emit(f"エクスポート開始: {self._output_path}")

            # The exporter reports progress on stdout. sys.stdout is
            # process-global, so this also swallows anything the rest of the
            # app prints while the export runs -- and it keeps the exporter's
            # non-ASCII output away from the cp932 console on Windows.
            old_stdout = sys.stdout
            sys.stdout = capture
            try:
                if getattr(self, "_device_export", False):
                    export_rekordbox_db_to_device(
                        self._db_path,
                        self._output_path,
                        db_key=None,
                        verbose=True,
                        playlists=self._playlists,
                        playlist_options=self._playlist_options,
                        progress_cb=self._make_progress_cb(),
                        phase_cb=self._make_phase_cb(),
                        cancel_event=self._cancel_event,
                    )
                else:
                    export_rekordbox_db_to_xml(
                        self._db_path,
                        self._output_path,
                        db_key=None,
                        verbose=True,
                        playlists=self._playlists,
                        playlist_options=self._playlist_options,
                        progress_cb=self._make_progress_cb(),
                        phase_cb=self._make_phase_cb(),
                        cancel_event=self._cancel_event,
                    )
            finally:
                sys.stdout = old_stdout
        except Exception as e:
            self._emit_captured(capture)
            self.progress.emit(traceback.format_exc())
            self.error.emit(f"{type(e).__name__}: {e}")
        except BaseException as e:  # noqa: BLE001 - must not escape the slot
            self.error.emit(f"{type(e).__name__}: {e}")
        else:
            self._emit_captured(capture)
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit()
        finally:
            self.finished.emit()

    def _emit_captured(self, capture: "io.StringIO") -> None:
        """Forward the exporter's captured output (last 50 lines)."""
        try:
            output = capture.getvalue()
        except Exception:
            return
        if output:
            for line in output.strip().splitlines()[-50:]:
                self.progress.emit(line)

    def _make_progress_cb(self):
        """Return the exporter callback that forwards copy progress."""

        def _cb(done: int, total: int, done_bytes: int, total_bytes: int) -> None:
            self.progress_count.emit(done, total, done_bytes, total_bytes)

        return _cb

    def _make_phase_cb(self):
        """Return the exporter callback that forwards phase changes."""

        def _cb(phase: str) -> None:
            self.phase_changed.emit(phase)

        return _cb



def close_database(db: Any) -> None:
    """Close a Rekordbox database connection, ignoring failures.

    Every connection holds file handles on the SQLCipher database. The size
    calculation and the track preview each open one every time the selection
    changes, so leaving them open piles up connections for as long as the
    window is open.
    """
    if db is None:
        return
    try:
        db.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Format helper
# ---------------------------------------------------------------------------
def format_bytes(bytes_val: int) -> str:
    """Format bytes into a human-readable string (B, KB, MB, GB)."""
    val = max(0, int(bytes_val))
    if val < 1024:
        return f"{val} B"
    elif val < 1024 * 1024:
        return f"{val / 1024:.1f} KB"
    elif val < 1024 * 1024 * 1024:
        return f"{val / (1024 * 1024):.1f} MB"
    else:
        return f"{val / (1024 * 1024 * 1024):.2f} GB"



def format_time(ms: int) -> str:
    """Format milliseconds into mm:ss format."""
    total_sec = max(0, int(ms) // 1000)
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes:02d}:{seconds:02d}"


def format_eta(seconds: float) -> str:
    """Format remaining seconds as a human-readable ETA (e.g. ``約3分``)."""
    sec = max(0, int(seconds))
    if sec < 60:
        return f"約{sec}秒"
    minutes = sec // 60
    if minutes < 60:
        return f"約{minutes}分"
    return f"約{minutes // 60}時間{minutes % 60}分"


class EtaEstimator:
    """Estimate remaining time from (timestamp, done_units) samples.

    The speed is the average over the last ``window_seconds`` of samples only,
    so a temporary slowdown (or speed-up) does not distort the estimate for
    the whole run. Units are arbitrary (count or bytes); the caller decides.
    """

    def __init__(self, window_seconds: float = 8.0) -> None:
        self._window_seconds = window_seconds
        self._samples: List[Tuple[float, float]] = []

    def update(
        self, done: float, total: float, now: Optional[float] = None
    ) -> Optional[float]:
        """Record a sample and return the remaining seconds.

        Returns ``None`` until two samples within the window are available,
        and ``0.0`` once ``done`` reaches ``total``.
        """
        if total <= 0:
            return None
        if now is None:
            now = time.monotonic()
        self._samples.append((now, done))

        cutoff = now - self._window_seconds
        while len(self._samples) > 1 and self._samples[0][0] < cutoff:
            self._samples.pop(0)

        if len(self._samples) < 2:
            return None

        t0, d0 = self._samples[0]
        t1, d1 = self._samples[-1]
        elapsed = t1 - t0
        delta = d1 - d0
        if elapsed <= 0 or delta <= 0:
            return None
        speed = delta / elapsed
        remaining = total - done
        if remaining <= 0:
            return 0.0
        return remaining / speed

    def reset(self) -> None:
        self._samples.clear()


# ---------------------------------------------------------------------------
# Track size resolution
# ---------------------------------------------------------------------------
# How reliable a resolved track size is
SIZE_EXACT = "exact"  # stat() or DB FileSize
SIZE_ESTIMATED = "estimated"  # Length + BitRate / file type heuristic
SIZE_UNKNOWN = "unknown"  # no basis for a size
SIZE_MISSING = "missing"  # file does not exist; the track is not exportable

# Estimated bytes per second used when the DB has no file size: 16-bit
# 44.1 kHz stereo PCM, typical FLAC/ALAC compression, 320 kbps fallback.
_RATE_WAV = 176_400
_RATE_FLAC = 100_000
_RATE_DEFAULT = 40_000

# DjmdContent.FileType is pyrekordbox's FileType IntEnum (tables.py).
_FILE_TYPE_NAMES = {5: "FLAC", 11: "WAV", 12: "AIFF"}


def _content_kind(content) -> str:
    """Return an uppercased, human-readable file type of a DB row.

    ``DjmdContent.FileType`` is an int (pyrekordbox's ``FileType`` IntEnum);
    ``Kind`` is the human-readable name some exporters attach. Accept either.
    """
    ft = getattr(content, "FileType", None)
    if ft is not None:
        try:
            if int(ft) in _FILE_TYPE_NAMES:
                return _FILE_TYPE_NAMES[int(ft)]
        except (ValueError, TypeError):
            pass
    return str(
        getattr(content, "Kind", "") or getattr(content, "FileType", "") or ""
    ).upper()


def _content_ext(content) -> str:
    """Return the lowercased file extension (e.g. ".wav") from FolderPath."""
    loc = getattr(content, "FolderPath", None)
    if not loc:
        return ""
    name = str(loc).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def estimate_bytes_per_sec(content) -> int:
    """Estimate encoded bytes/second from BitRate, then file type.

    BitRate (kbps) is the most accurate signal and covers every codec; the
    file type (extension or DjmdContent.FileType) is the fallback. Never
    returns None.
    """
    bitrate = getattr(content, "BitRate", None)
    if bitrate is not None:
        try:
            br_kbps = float(bitrate)
            if br_kbps > 0:
                return int(br_kbps * 1000 / 8)
        except (ValueError, TypeError):
            pass

    kind = _content_kind(content)
    if kind in ("WAV", "AIFF", "AIF") or "WAV" in kind:
        return _RATE_WAV
    if "FLAC" in kind or "ALAC" in kind:
        return _RATE_FLAC

    ext = _content_ext(content)
    if ext in (".wav", ".aif", ".aiff"):
        return _RATE_WAV
    if ext in (".flac", ".alac"):
        return _RATE_FLAC

    return _RATE_DEFAULT


def track_duration_sec(content) -> Optional[float]:
    """Return the DB Length in seconds, or None when unusable.

    Rekordbox's XML TotalTime -- and the DB Length it is exported from -- is
    in seconds (pyrekordbox rbxml.py), so no unit conversion is needed.
    """
    length = getattr(content, "Length", None)
    if length is None:
        return None
    try:
        dur_sec = float(length)
    except (ValueError, TypeError):
        return None
    return dur_sec if dur_sec > 0 else None


def resolve_track_size(content, resolve_path=None) -> Tuple[int, str]:
    """Resolve a content row's byte size and how reliable it is.

    Returns ``(size_bytes, status)`` where ``status`` is one of ``SIZE_EXACT``
    (local file stat or DB FileSize), ``SIZE_ESTIMATED`` (Length + BitRate /
    file type heuristic), ``SIZE_UNKNOWN`` (no basis for a size; 0 bytes) or
    ``SIZE_MISSING`` (no file on disk; the track is not exportable, 0 bytes).

    ``resolve_path`` is an optional callable mapping a FolderPath string to a
    Path. When given, a track whose file cannot be resolved is reported as
    ``SIZE_MISSING`` and the DB fallbacks (FileSize / heuristic) are skipped:
    tracks with no file are never exported, so their sizes would only distort
    the capacity estimate. Without ``resolve_path`` the DB fallbacks are used
    (pure DB-row callers / unit tests).
    """
    loc = getattr(content, "FolderPath", None)
    if resolve_path is not None:
        try:
            p = resolve_path(loc) if loc else None
        except Exception:
            p = None
        if p is None or not p.exists() or not p.is_file():
            return 0, SIZE_MISSING
        try:
            s = p.stat().st_size
            if s > 0:
                return s, SIZE_EXACT
        except Exception:
            return 0, SIZE_MISSING

    fsize = getattr(content, "FileSize", None)
    if fsize is not None:
        try:
            fs_int = int(fsize)
            if fs_int < 0:
                # Rekordbox stores FileSize as a 32-bit signed integer;
                # restore the unsigned value (up to ~4.29 GB).
                fs_int = fs_int & 0xFFFFFFFF
            if 0 < fs_int <= 10_000_000_000:
                return fs_int, SIZE_EXACT
        except (ValueError, TypeError):
            pass

    dur_sec = track_duration_sec(content)
    if dur_sec is not None:
        return int(dur_sec * estimate_bytes_per_sec(content)), SIZE_ESTIMATED

    return 0, SIZE_UNKNOWN


# ---------------------------------------------------------------------------
# Size calculator worker (Async)
# ---------------------------------------------------------------------------
class SizeCalculatorWorker(QObject):
    """Calculates total track count and size for selected playlists asynchronously."""

    # (playlist_count, track_count, total_bytes, exact_count,
    #  estimated_count, excluded_count). track_count counts only exportable
    # tracks; excluded = files missing on disk, not exported, no size.
    # total_bytes can exceed 2 GiB, so it is declared as object: Qt's 32-bit
    # int conversion silently wraps on Windows (see ExportWorker.progress_count).
    finished = Signal(int, int, object, int, int, int)

    def __init__(self, selected_paths: List[str], db_path: Optional[str] = None) -> None:
        super().__init__()
        self._selected_paths = selected_paths
        self._db_path = db_path
        self._is_cancelled = False

    def cancel(self) -> None:
        self._is_cancelled = True

    @Slot()
    def run(self) -> None:
        """Compute the totals.

        ``finished`` must be emitted on every path: the QThread is quit by that
        signal, so returning without it leaves the thread -- and the Rekordbox
        database connection it holds -- alive for the rest of the session.
        """
        try:
            self._run()
        except Exception:
            self.finished.emit(0, 0, 0, 0, 0, 0)
        except BaseException:  # noqa: BLE001 - must not escape the slot
            self.finished.emit(0, 0, 0, 0, 0, 0)

    def _run(self) -> None:
        if not self._selected_paths or self._is_cancelled:
            self.finished.emit(0, 0, 0, 0, 0, 0)
            return

        db = None
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
                self.finished.emit(0, 0, 0, 0, 0, 0)
                return

            # Collect unique track IDs
            unique_track_ids = set()
            for pl in target_pls:
                if self._is_cancelled:
                    self.finished.emit(0, 0, 0, 0, 0, 0)
                    return
                for entry in playlist_tracks(db, pl):
                    unique_track_ids.add(str(entry.ID))

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
            excluded_count = 0
            included_count = 0

            for cid in unique_track_ids:
                if self._is_cancelled:
                    self.finished.emit(0, 0, 0, 0, 0, 0)
                    return
                content = content_map.get(cid)
                if not content:
                    excluded_count += 1
                    continue

                size, status = resolve_track_size(
                    content, resolve_path=resolver._resolve_file_path
                )
                if status in (SIZE_MISSING, SIZE_UNKNOWN):
                    # ファイルが存在しない曲はエクスポートされないため、
                    # 曲数・サイズのどちらにも含めない
                    excluded_count += 1
                    continue
                included_count += 1
                if status == SIZE_EXACT:
                    exact_count += 1
                else:
                    estimated_count += 1
                total_bytes += max(0, size)

            total_bytes = max(0, total_bytes)

            if self._is_cancelled:
                self.finished.emit(0, 0, 0, 0, 0, 0)
            else:
                self.finished.emit(
                    len(target_pls),
                    included_count,
                    total_bytes,
                    exact_count,
                    estimated_count,
                    excluded_count,
                )

        except Exception:
            self.finished.emit(0, 0, 0, 0, 0, 0)
        finally:
            close_database(db)



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
        self._export_worker: Optional[ExportWorker] = None
        # None / "success" / "error" / "cancelled" -- set per export
        self._export_result: Optional[str] = None
        self._is_updating_checks = False
        self._current_preview_item: Optional[QStandardItem] = None

        # Export progress state (count/bytes/ETA), reset per export
        self._eta_estimator = EtaEstimator()
        self._current_phase = ""

        self._calc_thread: Optional[QThread] = None
        self._calc_worker: Optional[SizeCalculatorWorker] = None
        self._calc_timer = QTimer(self)
        self._calc_timer.setSingleShot(True)
        self._calc_timer.timeout.connect(self._start_async_size_calculation)

        # Mini preview player (all playback state lives in PreviewPlayer)
        self._player = PreviewPlayer(self)
        self._is_seeking = False
        self._player.event.connect(self._on_player_event)
        self._player.positionChanged.connect(self._on_player_position_changed)
        self._player.durationChanged.connect(self._on_player_duration_changed)

        self._build_ui()
        self._populate_audio_devices(
            self._load_settings().get("audio_output_device", "")
        )

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

        # --- XML output folder row ---
        xml_row = QHBoxLayout()
        xml_label = QLabel("XML出力先フォルダ:")
        xml_label.setStyleSheet("font-weight: bold;")
        xml_row.addWidget(xml_label)

        self._output_edit = QLineEdit()
        self._output_edit.setPlaceholderText("エクスポート先のフォルダを選択...")
        self._output_edit.setToolTip("XMLファイルおよび複製された楽曲ファイルが保存されるフォルダです")
        xml_row.addWidget(self._output_edit, 1)

        browse_btn = QPushButton("参照...")
        browse_btn.setToolTip("エクスポート先のフォルダを選択します")
        browse_btn.clicked.connect(self._browse_output)
        xml_row.addWidget(browse_btn)

        open_folder_btn = QPushButton("開く")
        open_folder_btn.setToolTip("現在の出力先フォルダをファイルマネージャーで開きます")
        open_folder_btn.clicked.connect(self._open_current_output_dir)
        xml_row.addWidget(open_folder_btn)

        layout.addLayout(xml_row)

        # --- USB drive selection row ---
        usb_row = QHBoxLayout()
        usb_label = QLabel("USBメモリ:")
        usb_label.setStyleSheet("font-weight: bold;")
        usb_row.addWidget(usb_label)

        self._usb_drive_combo = QComboBox()
        self._usb_drive_combo.setMinimumWidth(240)
        self._usb_drive_combo.setToolTip(
            "CDJ-350/850/900/2000 シリーズ用のデバイスライブラリ（PIONEER/rekordbox/export.pdb）を "
            "直接書き出す USB メモリのドライブを選択します"
        )
        usb_row.addWidget(self._usb_drive_combo, 1)

        refresh_usb_btn = QPushButton("更新")
        refresh_usb_btn.setToolTip("接続されている USB メモリを再検出します")
        refresh_usb_btn.clicked.connect(self._refresh_usb_drives)
        usb_row.addWidget(refresh_usb_btn)

        browse_usb_btn = QPushButton("参照...")
        browse_usb_btn.setToolTip("USB メモリのドライブを手動で選択します")
        browse_usb_btn.clicked.connect(self._browse_usb_drive)
        usb_row.addWidget(browse_usb_btn)

        open_usb_btn = QPushButton("開く")
        open_usb_btn.setToolTip("選択中の USB メモリをファイルマネージャーで開きます")
        open_usb_btn.clicked.connect(self._open_current_usb_drive)
        usb_row.addWidget(open_usb_btn)

        layout.addLayout(usb_row)

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

        self._player_log_btn = QToolButton()
        self._player_log_btn.setText("🐞")
        self._player_log_btn.setToolTip("プレイヤー診断ログを表示（再生の不具合を報告するとき用）")
        self._player_log_btn.setAutoRaise(True)
        self._player_log_btn.clicked.connect(self._show_player_log)
        player_top.addWidget(self._player_log_btn)

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

        self._device_combo = QComboBox()
        self._device_combo.setToolTip("音声の出力先デバイス（音が出ないときはここを切り替えてください）")
        self._device_combo.setMaximumWidth(220)
        self._device_combo.setStyleSheet("font-size: 11px;")
        self._device_combo.currentIndexChanged.connect(self._on_audio_device_changed)
        player_bot.addWidget(QLabel("🔈"))
        player_bot.addWidget(self._device_combo)

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
        self._export_xml_btn = QPushButton("rekordbox.xml に出力")
        self._export_xml_btn.setMinimumHeight(40)
        self._export_xml_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 6px 20px; }"
        )
        self._export_xml_btn.clicked.connect(lambda: self._on_export("xml"))
        export_row.addWidget(self._export_xml_btn)

        self._export_usb_btn = QPushButton("USBメモリに出力")
        self._export_usb_btn.setMinimumHeight(40)
        self._export_usb_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: bold; padding: 6px 20px; }"
        )
        self._export_usb_btn.clicked.connect(lambda: self._on_export("device"))
        export_row.addWidget(self._export_usb_btn)

        export_row.addStretch(1)
        layout.addLayout(export_row)

        # --- Export progress row (hidden until an export starts) ---
        progress_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat("%v/%m 曲")
        self._progress.setVisible(False)
        progress_row.addWidget(self._progress, 3)

        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet("font-size: 12px; color: #495057;")
        self._progress_label.setVisible(False)
        progress_row.addWidget(self._progress_label, 5)

        self._export_cancel_btn = QPushButton("キャンセル")
        self._export_cancel_btn.setMinimumHeight(32)
        self._export_cancel_btn.setStyleSheet(
            "QPushButton { font-size: 13px; font-weight: bold;"
            " padding: 2px 18px; color: #b02a37;"
            " border: 1px solid #b02a37; border-radius: 4px;"
            " background: #fff5f5; }"
            "QPushButton:hover { background: #ffe3e3; }"
            "QPushButton:disabled { color: #adb5bd; border-color: #adb5bd;"
            " background: #f1f3f5; }"
        )
        self._export_cancel_btn.setVisible(False)
        self._export_cancel_btn.clicked.connect(self._on_export_cancel)
        progress_row.addWidget(self._export_cancel_btn)
        layout.addLayout(progress_row)

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

        db = None
        try:
            db = RekordboxDatabase()
            pls = db.get_playlist().all()
        except Exception as e:
            close_database(db)
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

        # The tree holds plain strings now, so the connection can go.
        close_database(db)

        self._model.blockSignals(False)

        # Refresh folder states after unblocking so the view receives data changes.
        self._refresh_folder_checks()

        self._tree.collapseAll()

        # Set sort combo delegates after tree is built
        self._setup_sort_combos(root)

        # Restore output path (or use user-friendly default)
        saved_output = saved.get("output_path", "").strip()
        if saved_output:
            self._output_edit.setText(saved_output)
        else:
            self._output_edit.setText(str(get_default_output_dir()))

        # Restore USB drive selection
        self._refresh_usb_drives()
        saved_usb = saved.get("usb_drive", "").strip()
        if saved_usb:
            idx = self._usb_drive_combo.findData(saved_usb)
            if idx < 0:
                display, total, free = self._drive_info(saved_usb)
                self._usb_drive_combo.insertItem(0, display, saved_usb)
                idx = 0
            self._usb_drive_combo.setCurrentIndex(idx)

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
        db = None
        try:
            db = RekordboxDatabase()
            pl_obj = db.get_playlist(ID=pl_id)
            if pl_obj is None:
                self._preview_header.setText(f"🎵 プレイリスト: {path_str} (0 曲)")
                return

            entries = playlist_tracks(db, pl_obj, orderby)

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
        finally:
            close_database(db)

    # ----- Audio preview player -----

    def _on_preview_table_double_clicked(self, index: QModelIndex) -> None:
        """Play the track that was double clicked."""
        if not index.isValid():
            return
        num_item = self._preview_model.item(index.row(), 0)
        if not num_item:
            return
        file_path = num_item.data(ROLE_FILE_PATH)
        title = num_item.data(ROLE_TRACK_TITLE)
        if file_path:
            self._player.play_file(file_path, title)
        else:
            self._set_player_message(
                "⚠️ ローカルに実ファイルが見つからないため試聴できません", "#dc2626"
            )

    def _toggle_playback(self) -> None:
        """Play/pause, or start the selected row when nothing is loaded."""
        if not self._player.available:
            QMessageBox.information(
                self, "プレイヤー未対応", "この環境ではマルチメディア再生がサポートされていません。"
            )
            return

        if not self._player.is_idle():
            self._player.toggle()
            return

        sel = self._preview_table.selectionModel().currentIndex()
        if sel.isValid():
            self._on_preview_table_double_clicked(sel)
        elif self._preview_model.rowCount() > 0:
            idx = self._preview_model.index(0, 0)
            self._preview_table.selectionModel().setCurrentIndex(
                idx, self._preview_table.selectionModel().SelectionFlag.ClearAndSelect
            )
            self._on_preview_table_double_clicked(idx)

    def _stop_playback(self) -> None:
        self._player.stop()

    def _on_player_event(self, kind: str, detail: str) -> None:
        """Render a player event into the track label and the play button."""
        if kind == player.LOADING:
            self._set_player_message(f"⏳ 読み込み中: {detail}", "#5f6368")
            self._seek_slider.setValue(0)
            self._time_curr_label.setText("00:00")
        elif kind == player.PLAYING:
            self._set_player_message(f"🎵 再生中: {detail}", "#1a73e8")
        elif kind == player.PAUSED:
            self._set_player_message(f"⏸️ 一時停止: {detail}", "#5f6368")
        elif kind == player.STOPPED:
            self._set_player_message("🎧 試聴: 停止中", "#5f6368")
            self._seek_slider.setValue(0)
            self._time_curr_label.setText("00:00")
        elif kind == player.ERROR:
            self._set_player_message(f"⚠️ {detail}", "#dc2626")
        self._play_btn.setText("⏸️ 一時停止" if self._player.is_playing() else "▶️ 再生")

    def _set_player_message(self, text: str, color: str) -> None:
        self._player_track_label.setText(text)
        self._player_track_label.setStyleSheet(f"font-weight: bold; color: {color};")

    def _populate_audio_devices(self, preferred: str = "") -> None:
        """Fill the output device selector; keep ``preferred`` if still present."""
        devices = self._player.output_devices()
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        current = preferred or self._player.current_device_name()
        for name, device in devices:
            self._device_combo.addItem(name, device)
        index = self._device_combo.findText(current) if current else -1
        if index >= 0:
            self._device_combo.setCurrentIndex(index)
        self._device_combo.blockSignals(False)
        self._device_combo.setEnabled(bool(devices))
        if index > 0 and preferred:
            # Restore the saved device (index 0 is Qt's default, already active).
            self._player.set_output_device(self._device_combo.itemData(index))

    def _on_audio_device_changed(self, index: int) -> None:
        device = self._device_combo.itemData(index)
        if device is None:
            return
        self._player.set_output_device(device)
        self._set_player_message(
            f"🔈 出力先: {self._device_combo.itemText(index)}", "#5f6368"
        )

    def _show_player_log(self) -> None:
        """Show the collected player events and save them to a file."""
        text = f"rkbdb2xml {__version__}\n{self._player.log_text()}"
        try:
            PLAYER_LOG_FILE.write_text(text, encoding="utf-8")
            saved = f"\n\n保存先: {PLAYER_LOG_FILE}"
        except Exception as e:
            saved = f"\n\n(ログの保存に失敗: {e})"

        box = QMessageBox(self)
        box.setWindowTitle("🐞 プレイヤー診断ログ")
        box.setText("再生の不具合を報告する際は、以下のログを添付してください。" + saved)
        box.setDetailedText(text)
        box.exec()

    def _on_seek_slider_pressed(self) -> None:
        self._is_seeking = True

    def _on_seek_slider_released(self) -> None:
        duration = self._player.duration()
        self._player.seek(int((self._seek_slider.value() / 1000.0) * duration))
        self._is_seeking = False

    def _on_seek_slider_moved(self, value: int) -> None:
        duration = self._player.duration()
        self._time_curr_label.setText(format_time(int((value / 1000.0) * duration)))

    def _on_volume_changed(self, value: int) -> None:
        self._player.set_volume(value / 100.0)

    def _on_player_position_changed(self, position: int) -> None:
        if self._is_seeking:
            return
        duration = self._player.duration()
        if duration > 0:
            self._seek_slider.setValue(int((position / duration) * 1000))
        self._time_curr_label.setText(format_time(position))

    def _on_player_duration_changed(self, duration: int) -> None:
        self._time_total_label.setText(format_time(duration))

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

    def _join_worker(self, worker_attr: str, thread_attr: str) -> None:
        """Cancel a worker and join its thread before dropping the references.

        Destroying a still-running QThread aborts the process
        ("QThread: Destroyed while thread is still running"), so the thread
        must actually stop before its last Python reference goes away. Both
        objects are deleteLater()'d when their thread finishes, so the Python
        wrappers can outlive the C++ objects; touching one then raises
        RuntimeError.
        """
        try:
            worker = getattr(self, worker_attr)
            if worker is not None:
                worker.cancel()
        except RuntimeError:
            pass
        setattr(self, worker_attr, None)
        try:
            thread = getattr(self, thread_attr)
            if thread is not None:
                if thread.isRunning():
                    thread.quit()
                thread.wait()
        except RuntimeError:
            pass
        setattr(self, thread_attr, None)

    def _start_async_size_calculation(self) -> None:
        """Start background worker to compute size of selected playlists."""
        self._join_worker("_calc_worker", "_calc_thread")

        selected_paths: List[str] = []
        root = self._model.invisibleRootItem()
        self._collect_selected(root, selected_paths)

        if not selected_paths:
            self._on_size_calculated(0, 0, 0, 0, 0, 0)
            return

        worker = SizeCalculatorWorker(selected_paths)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_size_calculated)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_calc_thread_finished)
        thread.finished.connect(thread.deleteLater)

        self._calc_worker = worker
        self._calc_thread = thread
        thread.start()

    @Slot()
    def _on_calc_thread_finished(self) -> None:
        """Forget the finished worker before Qt deletes it.

        This slot is delivered through the event queue and can arrive late:
        ``_start_async_size_calculation()`` waits for the old thread while
        the GUI thread is blocked, so the old thread's ``finished`` can be
        delivered *after* a replacement thread has already been stored.
        Clearing the attributes unconditionally would drop the last
        reference to a still-running thread and abort the process
        ("QThread: Destroyed while thread is still running"), so only the
        thread that actually emitted may clear them.
        """
        if self.sender() is self._calc_thread:
            self._calc_worker = None
            self._calc_thread = None

    @Slot(int, int, object, int, int, int)
    def _on_size_calculated(
        self,
        playlist_count: int,
        track_count: int,
        total_bytes: int,
        exact_count: int,
        estimated_count: int,
        excluded_count: int,
    ) -> None:
        """Handle computed size and update summary label and capacity meter."""
        # A cancelled worker still reports (0,0,...); a stale result must not
        # overwrite the summary while a newer calculation is in flight.
        if self._calc_worker is not None and self.sender() is not self._calc_worker:
            return
        if playlist_count == 0:
            self._summary_label.setText("📊 選択中: 0 プレイリスト (0 曲 / 0 B)")
            self._capacity_label.setText("💾 16GB USBメモリ目安 (実効約14.8GB): 0 B / 14.8 GB (0.0% 使用)")
            self._capacity_label.setStyleSheet("font-size: 12px; color: #495057;")
            return

        # ファイルが存在しない曲はエクスポート対象外。曲数・サイズに含めず、
        # 内訳に「対象外」として明示する。
        if track_count == 0:
            self._summary_label.setText(
                f"📊 選択中: {playlist_count} プレイリスト ｜ "
                f"対象外: {excluded_count:,} 曲 (ファイルなし) ｜ エクスポート可能な曲なし"
            )
            self._capacity_label.setText(
                "💾 エクスポート可能な曲がないため容量判定できません"
            )
            self._capacity_label.setStyleSheet(
                "font-size: 12px; color: #d97706; font-weight: bold;"
            )
            return

        size_str = format_bytes(total_bytes) if total_bytes > 0 else "不明"
        approx = "約 " if estimated_count > 0 else ""
        if excluded_count > 0:
            breakdown = (
                f" (実測: {exact_count}曲 / 推定: {estimated_count}曲 "
                f"/ 対象外: {excluded_count}曲)"
            )
        elif estimated_count > 0:
            breakdown = f" (実測: {exact_count}曲 / 推定: {estimated_count}曲)"
        else:
            breakdown = " (全曲実測)"

        self._summary_label.setText(
            f"📊 選択中: {playlist_count} プレイリスト ｜ 全 {track_count:,} 曲 ｜ 合計 {approx}{size_str}{breakdown}"
        )

        # Usable capacities: 16GB ≒ 14.8 GB, 32GB ≒ 29.5 GB, 64GB ≒ 59.0 GB
        USB_16GB = 14.8 * 1024 * 1024 * 1024
        USB_32GB = 29.5 * 1024 * 1024 * 1024
        USB_64GB = 59.0 * 1024 * 1024 * 1024

        if total_bytes == 0:
            self._capacity_label.setText(
                "💾 サイズ不明のため容量判定できません (対象外の曲を確認してください)"
            )
            self._capacity_label.setStyleSheet(
                "font-size: 12px; color: #d97706; font-weight: bold;"
            )
            return

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
        except Exception:
            _log_crash_exception("_on_item_changed")
            raise
        finally:
            self._is_updating_checks = False

        self._trigger_size_calculation()



    def _set_children_check(self, parent: QStandardItem, state: Qt.CheckState) -> None:
        """Recursively set check state on all descendant items."""
        target_state = Qt.Checked if state == Qt.Checked else Qt.Unchecked
        try:
            for row in range(parent.rowCount()):
                child = parent.child(row, COL_CHECK)
                if child:
                    child.setCheckState(target_state)
                    if child.hasChildren():
                        self._set_children_check(child, target_state)
        except Exception:
            _log_crash_exception("_set_children_check")
            raise

    def _update_parent_check_state(self, parent: QStandardItem) -> None:
        """Update parent item checkState based on its children states."""
        if not parent:
            return
        try:
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
        except Exception:
            _log_crash_exception("_update_parent_check_state")
            raise

    def _refresh_folder_checks(self) -> None:
        """Recompute every folder's check state from its leaves, bottom-up.

        Used after bulk-restoring check states at startup. Folders must be
        aggregated deepest-first: ``_update_parent_check_state`` only recurses
        *upwards*, so aggregating only the top level leaves mid-level folders
        Unchecked and a checked grandchild never marks its ancestors.
        """
        self._is_updating_checks = True
        try:
            self._aggregate_folder_checks(self._model.invisibleRootItem())
        finally:
            self._is_updating_checks = False

    def _aggregate_folder_checks(self, parent: QStandardItem) -> None:
        """Aggregate folder check states, children before their parents."""
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if item and item.hasChildren():
                self._aggregate_folder_checks(item)
                self._update_parent_check_state(item)

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

    def _detect_usb_drives(self) -> List[Tuple[str, str, int, int]]:
        """Return a list of candidate removable drives as (display, path, total, free)."""
        drives: List[Tuple[str, str, int, int]] = []
        paths: set = set()

        try:
            partitions = psutil.disk_partitions(all=False)
        except Exception:
            return drives

        # Linux: prefer lsblk removable flag and labels
        if sys.platform not in ("win32", "darwin"):
            try:
                result = subprocess.run(
                    ["lsblk", "-J", "-o", "NAME,MOUNTPOINT,LABEL,RM,SIZE"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0 and result.stdout:
                    data = json.loads(result.stdout)

                    def collect_lsblk(dev: dict) -> None:
                        for child in dev.get("children", []):
                            collect_lsblk(child)
                        rm = dev.get("rm")
                        if rm in (True, "1", 1) and dev.get("mountpoint"):
                            mp = dev["mountpoint"]
                            if mp not in paths:
                                paths.add(mp)
                                label = dev.get("label", "") or ""
                                display, total, free = self._drive_info(mp, label)
                                drives.append((display, mp, total, free))

                    for dev in data.get("blockdevices", []):
                        collect_lsblk(dev)
            except Exception:
                pass

        for part in partitions:
            mp = part.mountpoint
            if not mp or mp == "/" or mp in paths:
                continue
            if self._is_removable_mount(mp):
                paths.add(mp)
                display, total, free = self._drive_info(mp)
                drives.append((display, mp, total, free))

        return sorted(drives, key=lambda x: x[1])

    def _is_removable_mount(self, mp: str) -> bool:
        """Heuristic to identify external/removable drives by mountpoint."""
        if sys.platform == "win32":
            if len(mp) >= 2 and mp[1] == ":":
                return mp[0].upper() != "C"
            return False
        if sys.platform == "darwin":
            return mp.startswith("/Volumes/")
        return any(
            mp.startswith(prefix)
            for prefix in ("/media/", "/mnt/", "/run/media/")
        )

    def _drive_info(self, path: str, label: str = "") -> Tuple[str, int, int]:
        """Return (display_text, total_bytes, free_bytes) for a drive path."""
        total = 0
        free = 0
        try:
            usage = psutil.disk_usage(path)
            total = usage.total
            free = usage.free
        except Exception:
            pass

        if not label:
            label = self._get_volume_label(path)
        display = self._format_drive_text(path, label, total, free)
        return display, total, free

    def _format_drive_text(self, path: str, label: str, total: int, free: int) -> str:
        """Format a drive entry for the combo box."""
        parts = [path]
        if label:
            parts.append(f"({label})")
        if total > 0:
            parts.append(f"空き {format_bytes(free)} / {format_bytes(total)}")
        return " ".join(parts)

    def _get_volume_label(self, path: str) -> str:
        """Return the volume label for a drive path, if available."""
        if sys.platform == "win32":
            return self._windows_volume_label(path)
        if sys.platform == "darwin":
            return self._macos_volume_label(path)
        return self._linux_volume_label(path)

    @staticmethod
    def _windows_volume_label(path: str) -> str:
        try:
            import ctypes

            root = path
            if not root.endswith(("\\", "/")):
                root = root + "\\"
            buf = ctypes.create_unicode_buffer(256)
            ret = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root),
                buf,
                ctypes.c_uint32(256),
                None,
                None,
                None,
                None,
                0,
            )
            if ret:
                return buf.value
        except Exception:
            pass
        return ""

    @staticmethod
    def _macos_volume_label(path: str) -> str:
        try:
            import plistlib

            result = subprocess.run(
                ["diskutil", "info", "-plist", path],
                capture_output=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                plist = plistlib.loads(result.stdout)
                return str(plist.get("VolumeName", ""))
        except Exception:
            pass
        return ""

    @staticmethod
    def _linux_volume_label(path: str) -> str:
        try:
            result = subprocess.run(
                ["lsblk", "-J", "-o", "MOUNTPOINT,LABEL"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)

                def find_label(dev: dict) -> str:
                    if dev.get("mountpoint") == path:
                        return dev.get("label", "") or ""
                    for child in dev.get("children", []):
                        found = find_label(child)
                        if found:
                            return found
                    return ""

                for dev in data.get("blockdevices", []):
                    found = find_label(dev)
                    if found:
                        return found
        except Exception:
            pass
        return ""

    def _refresh_usb_drives(self) -> None:
        """Refresh the USB drive list and preserve the current selection."""
        current_path = self._usb_drive_combo.currentData()
        if not current_path:
            current_path = self._usb_drive_combo.currentText().strip()

        drives = self._detect_usb_drives()
        self._usb_drive_combo.clear()
        for display, path, total, free in drives:
            self._usb_drive_combo.addItem(display, path)

        if current_path:
            idx = self._usb_drive_combo.findData(current_path)
            if idx < 0:
                display, total, free = self._drive_info(current_path)
                self._usb_drive_combo.insertItem(0, display, current_path)
                idx = 0
            self._usb_drive_combo.setCurrentIndex(idx)

    def _browse_usb_drive(self) -> None:
        """Open a folder dialog to manually select a USB drive."""
        folder = QFileDialog.getExistingDirectory(self, "USB メモリを選択")
        if folder:
            self._refresh_usb_drives()
            idx = self._usb_drive_combo.findData(folder)
            if idx < 0:
                display, total, free = self._drive_info(folder)
                self._usb_drive_combo.insertItem(0, display, folder)
                idx = 0
            self._usb_drive_combo.setCurrentIndex(idx)

    def _open_current_usb_drive(self) -> None:
        """Open the selected USB drive in the system file explorer."""
        path_str = self._usb_drive_combo.currentData()
        if not path_str:
            path_str = self._usb_drive_combo.currentText().strip()
        if not path_str:
            QMessageBox.information(self, "通知", "USB メモリが選択されていません。")
            return
        p = Path(path_str)
        if not p.exists():
            QMessageBox.warning(self, "エラー", f"指定された USB メモリが見つかりません:\n{path_str}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.resolve())))

    # ----- Export -----

    def _on_export(self, mode: str) -> None:
        self._check_rekordbox_status()

        if mode == "xml":
            output_path = self._output_edit.text().strip()
            if not output_path:
                QMessageBox.warning(self, "確認", "XML 出力先フォルダを指定してください。")
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

            out_path = str(output_dir / "rekordbox.xml")
        elif mode == "device":
            usb_path = self._usb_drive_combo.currentData()
            if not usb_path:
                usb_path = self._usb_drive_combo.currentText().strip()
            if not usb_path:
                QMessageBox.warning(self, "確認", "USB メモリを選択してください。")
                return

            output_dir = Path(usb_path)
            if not output_dir.exists() or not output_dir.is_dir():
                QMessageBox.critical(
                    self, "エラー", f"指定された USB メモリが見つかりません:\n{usb_path}"
                )
                return

            out_path = usb_path
        else:
            return

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

        self._export_xml_btn.setEnabled(False)
        self._export_usb_btn.setEnabled(False)
        self._export_cancel_btn.setVisible(True)
        self._export_cancel_btn.setEnabled(True)

        # Reset progress display: determinate bar starts at 0, totals arrive
        # with the exporter's first progress callback.
        self._eta_estimator.reset()
        self._current_phase = ""
        self._export_result = None
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._progress_label.setText("準備中...")
        self._progress_label.setVisible(True)

        self._current_export_dir = output_dir
        self._log_message(f"エクスポート対象: {len(selected_paths)} 件の項目")

        # Create worker with per-playlist options
        worker = ExportWorker(
            db_path=None,
            output_path=out_path,
            playlists=selected_paths,
            playlist_options=pl_options,
            device_export=(mode == "device"),
        )
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._log_message)
        worker.progress_count.connect(self._on_export_progress)
        worker.phase_changed.connect(self._on_export_phase)
        worker.succeeded.connect(self._on_export_succeeded)
        worker.cancelled.connect(self._on_export_cancelled)
        worker.error.connect(self._on_export_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        # _on_export_done opens a modal dialog, which runs a nested event loop;
        # let it run before the thread object is scheduled for deletion.
        thread.finished.connect(self._on_export_done)
        thread.finished.connect(thread.deleteLater)

        self._export_thread = thread
        self._export_worker = worker
        thread.start()

    def _collect_selected(self, parent: QStandardItem, result: List[str]) -> None:
        """Collect path strings of checked items (partial folders are skipped)."""
        for row in range(parent.rowCount()):
            item = parent.child(row, COL_CHECK)
            if not item:
                continue
            path_str = item.data(ROLE_PATH)
            state = item.checkState()

            if state == Qt.Checked and path_str and path_str not in result:
                result.append(path_str)
            if item.hasChildren():
                self._collect_selected(item, result)


    @Slot()
    def _on_export_succeeded(self) -> None:
        self._export_result = "success"

    @Slot()
    def _on_export_cancel(self) -> None:
        """Request cancellation; the worker stops at the next track boundary."""
        worker = getattr(self, "_export_worker", None)
        if worker is None:
            return
        self._export_cancel_btn.setEnabled(False)
        self._progress_label.setText("キャンセル中...")
        try:
            worker.cancel()
        except RuntimeError:
            pass  # worker already deleted; export must have just finished

    @Slot()
    def _on_export_cancelled(self) -> None:
        self._export_result = "cancelled"
        self._log_message("エクスポートはキャンセルされました。")
        cancel_dialog = QMessageBox(self)
        cancel_dialog.setIcon(QMessageBox.Warning)
        cancel_dialog.setWindowTitle("エクスポートキャンセル")
        cancel_dialog.setText("エクスポートはキャンセルされました。")
        cancel_dialog.setInformativeText(
            "キャンセル時点までにコピーされたファイルは出力先に残ります。\n"
            "不完全な export.pdb は書き込まれていません。\n"
            "USB メモリを取り外す前に、書きかけのデータを確認してください。"
        )
        cancel_dialog.exec()

    @Slot(int, int, object, object)
    def _on_export_progress(
        self, done: int, total: int, done_bytes: int, total_bytes: int
    ) -> None:
        """Update the determinate bar and the count/bytes/ETA label."""
        if total > 0:
            self._progress.setRange(0, total)
            self._progress.setValue(done)

        if total_bytes > 0:
            eta = self._eta_estimator.update(done_bytes, total_bytes)
        else:
            eta = self._eta_estimator.update(done, total)

        text = f"{done}/{total} 曲"
        if total_bytes > 0:
            text += f" ・ {format_bytes(done_bytes)} / {format_bytes(total_bytes)}"
        if eta is not None:
            text += f" ・ 残り {format_eta(eta)}"
        if self._current_phase:
            text = f"{self._current_phase}: {text}"
        self._progress_label.setText(text)

    @Slot(str)
    def _on_export_phase(self, phase: str) -> None:
        self._current_phase = phase
        self._progress_label.setText(f"{phase}...")

    @Slot(str)
    def _on_export_error(self, msg: str) -> None:
        self._export_result = "error"
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
        self._export_xml_btn.setEnabled(True)
        self._export_usb_btn.setEnabled(True)
        self._export_cancel_btn.setVisible(False)
        self._export_cancel_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._progress_label.setVisible(False)
        self._current_phase = ""
        self._export_thread = None

        if self._export_result != "success":
            # _on_export_error / _on_export_cancelled already told the user
            return

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

        usb_path = self._usb_drive_combo.currentData()
        if not usb_path:
            usb_path = self._usb_drive_combo.currentText().strip()

        data = {
            "output_path": self._output_edit.text().strip(),
            "usb_drive": usb_path or "",
            "selected_playlists": selected,
            "playlist_options": options,
            "audio_output_device": self._device_combo.currentText(),
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
        """Stop the workers and save settings when window is closed.

        A QThread that loses its last Python reference while running aborts
        the process, so both background threads must be cancelled and
        joined before the window's attributes go away.
        """
        self._save_settings()
        self._join_worker("_calc_worker", "_calc_thread")
        self._join_worker("_export_worker", "_export_thread")
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
CRASH_LOG_FILE = Path.home() / ".rkbdb2xml_crash.log"


def _log_crash_exception(context: str) -> None:
    """Append the current exception (with context label) to the crash log."""
    try:
        with CRASH_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"=== EXCEPTION IN {context} ===\n")
            traceback.print_exc(file=f)
    except Exception:
        pass


def _install_crash_hooks() -> None:
    """Record *any* process exit path so silent crashes are not lost.

    A console=False PyInstaller build has no stderr, and a slot that swallows an
    exception can end the process without any WER report or crash dump. Both a
    native segfault (faulthandler) and an uncaught Python exception (excepthook)
    write a traceback here, so the *next* reproduction shows exactly what died.
    """
    try:
        import faulthandler

        with CRASH_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"\n=== rkbdb2xml {__version__} started {__import__('datetime').datetime.now()} ===\n")
        # faulthandler appends to the file on SIGSEGV/SIGABRT (native crashes).
        faulthandler.enable(file=CRASH_LOG_FILE.open("a", encoding="utf-8"))
    except Exception:
        pass

    def excepthook(exc_type, exc_value, exc_tb) -> None:
        try:
            with CRASH_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(f"=== UNCAUGHT EXCEPTION {exc_type.__name__} ===\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass
        # Still surface on stderr for a console run.
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def unraisablehook(unraisable) -> None:
        # Catches exceptions in QThread workers / destructors that bypass
        # sys.excepthook (e.g. SizeCalculatorWorker / ExportWorker threads).
        try:
            with CRASH_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(f"=== UNRAISABLE {unraisable.exc_type.__name__} ===\n")
                traceback.print_exception(
                    unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback, file=f
                )
        except Exception:
            pass

    sys.excepthook = excepthook
    sys.unraisablehook = unraisablehook


def main() -> None:
    _install_crash_hooks()
    app = QApplication(sys.argv)
    app.setWindowIcon(get_app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()



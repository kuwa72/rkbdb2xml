"""Mini preview player for the GUI.

A thin, explicit wrapper around QMediaPlayer. Everything the preview player
knows lives here; the GUI only wires widgets to signals.

Two properties of QMediaPlayer drive the whole design:

1. ``setSource()`` loads asynchronously. Calling ``play()`` right after it races
   with the loader, so playback is started when the media reports LoadedMedia.
2. ``stop()`` and ``setSource()`` emit ``mediaStatusChanged`` *synchronously*
   for the media being torn down, and ``play()`` called from inside such a slot
   can leave the pipeline running without ever starting the clock. So the
   pending request is invalidated *before* any teardown, and ``play()`` is
   always issued from a fresh event loop turn.

State is deliberately minimal: a single ``_Request`` (the track waiting to
start, or None) plus the path/title of what is loaded.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer

    HAS_MULTIMEDIA = True
except ImportError:  # pragma: no cover - depends on the PySide6 build
    HAS_MULTIMEDIA = False

# How long to wait for a source to load before reporting failure
LOAD_TIMEOUT_MS = 5000
# Ring buffer size for the diagnostics log
LOG_MAX_LINES = 300

# Event kinds emitted through PreviewPlayer.event
IDLE = "idle"
LOADING = "loading"
PLAYING = "playing"
PAUSED = "paused"
STOPPED = "stopped"
ERROR = "error"


@dataclass
class _Request:
    """A track waiting to be loaded and started."""

    path: str
    title: str
    generation: int


class PreviewPlayer(QObject):
    """Loads and plays single audio files for preview."""

    # (kind, detail) - detail is a track title for playback kinds, else a message
    event = Signal(str, str)
    positionChanged = Signal(int)
    durationChanged = Signal(int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._log: List[str] = []
        self._request: Optional[_Request] = None
        self._generation = 0
        self._loaded_path = ""
        self._loaded_title = ""

        self._player: Optional[Any] = None
        self._audio_output: Optional[Any] = None

        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.setInterval(LOAD_TIMEOUT_MS)
        self._load_timer.timeout.connect(self._on_load_timeout)

        if not HAS_MULTIMEDIA:
            self.log("QtMultimedia unavailable")
            return
        try:
            self._create_backend()
            self.log(f"init device='{self.current_device_name()}'")
            self.log(f"init outputs={[name for name, _ in self.output_devices()]}")
        except Exception as e:  # pragma: no cover - backend specific
            self.log(f"init failed: {e!r}")
            self._player = None

    def _create_backend(self) -> None:
        """Build the QMediaPlayer and its audio sink (overridden in tests)."""
        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._audio_output.setVolume(0.7)
        # Relayed through lambdas: QMediaPlayer emits qlonglong, which cannot be
        # connected signal-to-signal to a Signal(int).
        self._player.positionChanged.connect(lambda ms: self.positionChanged.emit(int(ms)))
        self._player.durationChanged.connect(lambda ms: self.durationChanged.emit(int(ms)))
        self._player.mediaStatusChanged.connect(self._on_status_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_error)

    # ----- capabilities -----

    @property
    def available(self) -> bool:
        return self._player is not None

    def output_devices(self) -> List[Tuple[str, Any]]:
        """(description, device) for every audio output Qt can see."""
        if not HAS_MULTIMEDIA:
            return []
        try:
            return [(d.description(), d) for d in QMediaDevices.audioOutputs()]
        except Exception as e:  # pragma: no cover - backend specific
            self.log(f"audioOutputs failed: {e!r}")
            return []

    def current_device_name(self) -> str:
        if not self._audio_output:
            return ""
        try:
            return self._audio_output.device().description()
        except Exception:  # pragma: no cover - backend specific
            return ""

    def set_output_device(self, device: Any) -> None:
        """Route playback to ``device``; playback continues on the new sink."""
        if not self._audio_output or device is None:
            return
        try:
            self._audio_output.setDevice(device)
            self.log(f"output device -> '{self.current_device_name()}'")
        except Exception as e:  # pragma: no cover - backend specific
            self.log(f"setDevice failed: {e!r}")

    # ----- transport -----

    def play_file(self, path: str, title: str) -> None:
        """Load ``path`` and start playing it once the media is ready."""
        if not self._player:
            self.event.emit(ERROR, "この環境では再生がサポートされていません")
            return

        p = Path(path)
        if not p.is_file():
            self.event.emit(ERROR, f"ファイルが見つかりません: {p.name}")
            return
        target = str(p.resolve())

        # Same track still loaded and not stopped: just rewind.
        if (
            self._request is None
            and target == self._loaded_path
            and self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState
        ):
            self._player.setPosition(0)
            self._player.play()
            self.event.emit(PLAYING, title)
            return

        self._load(target, title)

    def toggle(self) -> None:
        """Pause or resume. Does nothing while a track is still loading."""
        if not self._player or self._request is not None:
            return
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()

    def is_playing(self) -> bool:
        if not self._player:
            return False
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def is_idle(self) -> bool:
        """True when nothing is loading, playing or paused."""
        if not self._player:
            return True
        return (
            self._request is None
            and self._player.playbackState() == QMediaPlayer.PlaybackState.StoppedState
        )

    def stop(self) -> None:
        self._generation += 1  # cancel anything in flight
        self._request = None
        self._load_timer.stop()
        if self._player:
            self._player.stop()
        self.event.emit(STOPPED, "")

    def set_volume(self, volume: float) -> None:
        if self._audio_output:
            self._audio_output.setVolume(max(0.0, min(1.0, volume)))

    def seek(self, position_ms: int) -> None:
        if self._player:
            self._player.setPosition(position_ms)

    def duration(self) -> int:
        return self._player.duration() if self._player else 0

    def position(self) -> int:
        return self._player.position() if self._player else 0

    # ----- loading -----

    def _load(self, target: str, title: str) -> None:
        # Invalidate the previous request BEFORE any teardown: stop() emits
        # mediaStatusChanged synchronously for the media it stops, and that
        # event must not be mistaken for the new track being ready.
        self._generation += 1
        gen = self._generation
        self._request = None
        self._load_timer.stop()
        self.log(f"load#{gen} {Path(target).name}")

        self._player.stop()

        self._request = _Request(target, title, gen)
        self._loaded_path = target
        self._loaded_title = title
        # Set the source from a clean event loop turn, outside the teardown.
        QTimer.singleShot(0, lambda: self._apply_source(gen))

        self.event.emit(LOADING, title)
        self._load_timer.start()

    def _apply_source(self, gen: int) -> None:
        request = self._request
        if request is None or request.generation != gen:
            return
        try:
            self._player.setSource(QUrl.fromLocalFile(request.path))
        except Exception as e:  # pragma: no cover - backend specific
            self.log(f"setSource failed: {e!r}")
            self._request = None
            self._load_timer.stop()
            self.event.emit(ERROR, f"再生エラー: {e}")

    def _start(self, gen: int) -> None:
        request = self._request
        if request is None or request.generation != gen:
            return
        self._request = None
        self._load_timer.stop()
        self._player.play()
        self.event.emit(PLAYING, request.title)

    def _on_load_timeout(self) -> None:
        request = self._request
        if request is None or not self._player:
            return
        status = self._player.mediaStatus()
        self.log(f"load timeout status={_enum_name(status)}")
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._start(request.generation)  # loaded, we just never saw it
            return
        self._request = None
        self._player.stop()
        self.event.emit(ERROR, f"読み込みに失敗しました: {request.title}")

    # ----- player signals -----

    def _on_status_changed(self, status: Any) -> None:
        self.log(f"status={_enum_name(status)} pending={self._request is not None}")

        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            request = self._request
            if request is not None:
                # play() from inside this slot leaves the pipeline running
                # without starting the clock; issue it from the next turn.
                gen = request.generation
                QTimer.singleShot(0, lambda: self._start(gen))
            return

        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            request = self._request
            self._request = None
            self._load_timer.stop()
            title = request.title if request else self._loaded_title
            self.event.emit(ERROR, f"再生できない形式です: {title}")
            return

        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._request is not None:
                return  # flush event from the media being replaced
            self.stop()

    def _on_state_changed(self, state: Any) -> None:
        if self._request is not None:
            return  # a load is in flight; its own events describe the state
        if state == QMediaPlayer.PlaybackState.PausedState:
            self.event.emit(PAUSED, self._loaded_title)
        elif state == QMediaPlayer.PlaybackState.PlayingState:
            self.event.emit(PLAYING, self._loaded_title)

    def _on_error(self, error: Any, error_string: str) -> None:
        if not HAS_MULTIMEDIA or error == QMediaPlayer.Error.NoError:
            return
        self.log(f"error={_enum_name(error)} {error_string}")
        self.event.emit(ERROR, f"再生エラー: {error_string}")

    # ----- diagnostics -----

    def log(self, message: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]} {message}"
        self._log.append(line)
        if len(self._log) > LOG_MAX_LINES:
            del self._log[:-LOG_MAX_LINES]
        print("[player]", line)

    def log_text(self) -> str:
        header = (
            f"multimedia: {'有効' if HAS_MULTIMEDIA else '無効'}\n"
            f"出力デバイス: {self.current_device_name() or '-'}\n"
            f"現在の曲: {self._loaded_path or '-'}\n"
        )
        return header + "\n".join(self._log)


def _enum_name(value: Any) -> str:
    """Readable name for a Qt enum value."""
    return getattr(value, "name", None) or str(value)

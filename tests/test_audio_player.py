"""Tests for the mini preview player (rkbdb2xml.player.PreviewPlayer).

Both bugs this covers came from QMediaPlayer's asynchronous, re-entrant API:

* ``setSource()`` loads asynchronously, so ``play()`` right after it races with
  the loader and leaves a player that reports PlayingState without decoding.
* ``stop()`` emits ``mediaStatusChanged(LoadedMedia)`` *synchronously* for the
  media it stops, which must not be taken for the newly requested track.

FakeMediaPlayer reproduces both, so the tests fail if either guarantee is lost.
"""

import pytest

pytest.importorskip("PySide6.QtMultimedia")

from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402

from rkbdb2xml import player as player_mod  # noqa: E402
from rkbdb2xml.player import ERROR, LOADING, PLAYING, STOPPED, PreviewPlayer  # noqa: E402


class FakeMediaPlayer:
    """QMediaPlayer stand-in, including its synchronous status signals."""

    def __init__(self, owner):
        self._owner = owner
        self.calls = []
        self.sources = []
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.status = QMediaPlayer.MediaStatus.NoMedia
        self._position = 0

    def _emit(self, status):
        self.status = status
        self._owner._on_status_changed(status)

    def stop(self):
        self.calls.append("stop")
        was_active = self.state != QMediaPlayer.PlaybackState.StoppedState
        self.state = QMediaPlayer.PlaybackState.StoppedState
        if was_active and self.status != QMediaPlayer.MediaStatus.NoMedia:
            self._emit(QMediaPlayer.MediaStatus.LoadedMedia)

    def setSource(self, url):
        self.calls.append("setSource")
        self.sources.append(url.toLocalFile())
        self._emit(QMediaPlayer.MediaStatus.LoadingMedia)

    def finish_loading(self):
        self._emit(QMediaPlayer.MediaStatus.LoadedMedia)

    def play(self):
        self.calls.append("play")
        self.state = QMediaPlayer.PlaybackState.PlayingState

    def pause(self):
        self.calls.append("pause")
        self.state = QMediaPlayer.PlaybackState.PausedState

    def playbackState(self):
        return self.state

    def mediaStatus(self):
        return self.status

    def setAudioOutput(self, output):
        self.calls.append(f"setAudioOutput({'None' if output is None else 'sink'})")

    def setPosition(self, pos):
        self._position = pos

    def position(self):
        return self._position

    def duration(self):
        return 180000


class FakeAudioOutput:
    """Stands in for QAudioOutput; identity is what the re-arm relies on."""

    def volume(self):
        return 0.7

    def isMuted(self):
        return False


class FakeTimer:
    def __init__(self):
        self.running = False

    def setSingleShot(self, _):
        pass

    def setInterval(self, _):
        pass

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class FakeBackedPlayer(PreviewPlayer):
    """PreviewPlayer with the Qt backend and timers replaced by fakes."""

    def _create_backend(self):
        self._player = FakeMediaPlayer(self)
        self._audio_output = FakeAudioOutput()

    def _audio_diagnostics(self):
        return "device='fake'"

    def current_device_name(self):
        return "fake device"

    def output_devices(self):
        return [("fake device", object())]

    # Test-side driving helpers -------------------------------------------

    def run_deferred(self):
        while self.deferred:
            self.deferred.pop(0)()

    def start_track(self, path, title):
        self.play_file(path, title)
        self.run_deferred()

    def finish_loading(self):
        """Loader completes; play() is then scheduled for the next turn."""
        self._player.finish_loading()
        self.run_deferred()


@pytest.fixture()
def preview(monkeypatch):
    deferred = []
    delays = []

    def capture(ms, cb):
        delays.append(ms)
        deferred.append(cb)

    monkeypatch.setattr(player_mod.QTimer, "singleShot", staticmethod(capture))
    p = FakeBackedPlayer()
    p.deferred = deferred
    p.delays = delays
    p._load_timer = FakeTimer()
    p._probe_timer = FakeTimer()
    p._restarted = False
    p.events = []
    p.event.connect(lambda kind, detail: p.events.append((kind, detail)))
    return p


@pytest.fixture()
def track(tmp_path):
    p = tmp_path / "track.mp3"
    p.write_bytes(b"\x00" * 16)
    return str(p)


@pytest.fixture()
def two_tracks(tmp_path):
    a = tmp_path / "a.mp3"
    b = tmp_path / "b.mp3"
    for p in (a, b):
        p.write_bytes(b"\x00" * 16)
    return str(a), str(b)


def kinds(preview):
    return [kind for kind, _ in preview.events]


def test_play_waits_for_the_media_to_load(preview, track):
    preview.start_track(track, "Track A")

    assert "play" not in preview._player.calls, "play() must wait for LoadedMedia"
    assert kinds(preview) == [LOADING]
    assert preview._load_timer.running

    preview.finish_loading()

    assert preview._player.calls[-1] == "play"
    assert preview.events[-1] == (PLAYING, "Track A")
    assert not preview._load_timer.running


def test_switching_while_playing_starts_the_new_track(preview, two_tracks):
    """stop() re-emits LoadedMedia for the old track; it must not be consumed."""
    a, b = two_tracks
    preview.start_track(a, "A")
    preview.finish_loading()
    assert preview.is_playing()

    preview.start_track(b, "B")  # double-click another track while A plays

    assert preview.events[-1] == (LOADING, "B"), "the stale stop() event ate the request"

    preview.finish_loading()

    assert preview._player.sources[-1] == b
    assert preview.events[-1] == (PLAYING, "B")


def test_repeated_switching_always_starts(preview, two_tracks):
    a, b = two_tracks
    for i in range(6):
        path = a if i % 2 == 0 else b
        preview.start_track(path, f"T{i}")
        preview.finish_loading()
        assert preview.is_playing(), i
        assert preview._player.sources[-1] == path, i
        assert preview.events[-1] == (PLAYING, f"T{i}"), i


def test_superseded_load_never_sets_a_stale_source(preview, two_tracks):
    a, b = two_tracks
    preview.play_file(a, "A")
    preview.play_file(b, "B")  # before A's deferred setSource ran
    preview.run_deferred()

    assert preview._player.sources == [b]


def test_replaying_the_loaded_track_rewinds(preview, track):
    preview.start_track(track, "Track A")
    preview.finish_loading()
    preview._player._position = 5000
    calls_before = len(preview._player.calls)

    preview.start_track(track, "Track A")

    assert preview._player.position() == 0
    assert preview._player.calls[calls_before:] == ["play"], "no reload for a rewind"


def test_flush_end_of_media_does_not_cancel_a_pending_load(preview, track):
    preview.start_track(track, "Track A")

    preview._on_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

    assert preview.events[-1] == (LOADING, "Track A")

    preview.finish_loading()
    assert preview._player.calls[-1] == "play"


def test_end_of_media_stops_playback(preview, track):
    preview.start_track(track, "Track A")
    preview.finish_loading()

    preview._on_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

    assert preview.events[-1] == (STOPPED, "")
    assert preview.is_idle()


def test_load_timeout_reports_failure(preview, track):
    preview.start_track(track, "Track A")

    preview._on_load_timeout()  # still LoadingMedia

    assert preview.events[-1][0] == ERROR
    assert "読み込みに失敗" in preview.events[-1][1]
    assert preview.is_idle()


def test_load_timeout_starts_a_media_that_was_already_loaded(preview, track):
    """A LoadedMedia we somehow never saw must not strand the UI on "loading"."""
    preview.start_track(track, "Track A")
    preview._player.status = QMediaPlayer.MediaStatus.LoadedMedia

    preview._on_load_timeout()

    assert preview._player.calls[-1] == "play"
    assert preview.events[-1] == (PLAYING, "Track A")


def test_invalid_media_is_reported(preview, track):
    preview.start_track(track, "Track A")

    preview._on_status_changed(QMediaPlayer.MediaStatus.InvalidMedia)

    assert preview.events[-1][0] == ERROR
    assert "再生できない形式" in preview.events[-1][1]
    assert "play" not in preview._player.calls


def test_stop_cancels_a_pending_load(preview, track):
    preview.start_track(track, "Track A")
    preview.stop()

    assert preview.events[-1] == (STOPPED, "")
    assert not preview._load_timer.running

    preview.finish_loading()  # late event from the cancelled load
    assert "play" not in preview._player.calls


def test_toggle_pauses_and_resumes(preview, track):
    preview.start_track(track, "Track A")
    preview.finish_loading()

    preview.toggle()
    assert preview._player.calls[-1] == "pause"

    preview.toggle()
    assert preview._player.calls[-1] == "play"


def test_toggle_is_ignored_while_loading(preview, track):
    preview.start_track(track, "Track A")

    preview.toggle()

    assert "play" not in preview._player.calls
    assert "pause" not in preview._player.calls


def test_playback_starts_from_the_beginning(preview, track):
    """The one start known to work on Windows seeks before playing."""
    preview.start_track(track, "Track A")
    preview._player._position = 999
    preview.finish_loading()

    assert preview._player.position() == 0
    assert preview._player.calls[-1] == "play"


def test_replacing_a_playing_track_waits_for_the_stream_to_close(preview, two_tracks):
    """The failing case on Windows: the old stream had not finished closing.

    The new source used to be set one event loop turn (7ms in the logs) after
    stopping a playing track, and the clock then never started.
    """
    a, b = two_tracks
    preview.start_track(a, "A")
    preview.finish_loading()
    assert preview.is_playing()
    preview.delays.clear()

    preview.play_file(b, "B")

    assert preview.delays == [player_mod.TEARDOWN_GRACE_MS]


def test_starting_from_idle_does_not_wait(preview, track):
    preview.delays.clear()

    preview.play_file(track, "Track A")

    assert preview.delays == [0], "nothing was playing, so there is nothing to close"


def test_a_stalled_pipeline_is_restarted_once(preview, track):
    """Restarting is exactly what works by hand: seek to 0 and play again."""
    preview.start_track(track, "Track A")
    preview.finish_loading()
    assert preview._probe_timer.running

    preview._on_playback_probe()  # position is still 0

    assert preview._player.calls[-1] == "play"
    assert "restarting" in preview.log_text()
    assert "device='fake'" in preview.log_text()
    assert preview._probe_timer.running, "the restart is checked in turn"

    calls_before = list(preview._player.calls)
    preview._on_playback_probe()  # still stalled

    assert preview._player.calls == calls_before, "only one restart per track"


def test_the_restart_budget_is_per_track(preview, two_tracks):
    a, b = two_tracks
    preview.start_track(a, "A")
    preview.finish_loading()
    preview._on_playback_probe()
    assert preview._restarted

    preview.start_track(b, "B")
    preview.finish_loading()

    assert not preview._restarted, "a new track gets its own restart"


def test_a_paused_track_is_not_restarted(preview, track):
    preview.start_track(track, "Track A")
    preview.finish_loading()
    preview.toggle()  # paused at 0
    calls_before = list(preview._player.calls)

    preview._on_playback_probe()

    assert preview._player.calls == calls_before


def test_a_playing_track_is_left_alone(preview, track):
    preview.start_track(track, "Track A")
    preview.finish_loading()
    preview._player._position = 3000
    calls_before = list(preview._player.calls)

    preview._on_playback_probe()

    assert preview._player.calls == calls_before
    assert "pos=3000" in preview.log_text()
    assert "restarting" not in preview.log_text()


def test_missing_file_is_reported_without_touching_the_player(preview, tmp_path):
    preview.start_track(str(tmp_path / "nope.mp3"), "Gone")

    assert preview._player.calls == []
    assert preview.events[-1][0] == ERROR
    assert "見つかりません" in preview.events[-1][1]

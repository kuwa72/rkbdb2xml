"""Regression tests for the mini audio player's deferred playback.

QMediaPlayer.setSource() loads asynchronously. Calling play() immediately after
it races with the loader and leaves the player in PlayingState while nothing is
actually decoded, so playback must be deferred until LoadedMedia arrives.

stop() and setSource() in turn emit mediaStatusChanged *synchronously* for the
media being torn down, so the deferred-playback bookkeeping has to survive those
re-entrant events.
"""

import pytest

pytest.importorskip("PySide6.QtMultimedia")

from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402

from rkbdb2xml.gui import MainWindow  # noqa: E402


class FakePlayer:
    """Stands in for QMediaPlayer, including its synchronous status signals."""

    def __init__(self, harness):
        self._harness = harness
        self.calls = []
        self.sources = []
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self.status = QMediaPlayer.MediaStatus.NoMedia
        self._position = 0
        self._duration = 180000

    def _emit_status(self, status):
        self.status = status
        self._harness._on_player_media_status_changed(status)

    def stop(self):
        self.calls.append("stop")
        was_active = self.state != QMediaPlayer.PlaybackState.StoppedState
        self.state = QMediaPlayer.PlaybackState.StoppedState
        # Qt resets a playing/paused media back to LoadedMedia on stop(), and
        # the signal is delivered synchronously from inside stop().
        if was_active and self.status != QMediaPlayer.MediaStatus.NoMedia:
            self._emit_status(QMediaPlayer.MediaStatus.LoadedMedia)

    def setSource(self, url):
        self.calls.append("setSource")
        path = url.toLocalFile()
        self.sources.append(path)
        if not path:
            self._emit_status(QMediaPlayer.MediaStatus.NoMedia)
        else:
            self._emit_status(QMediaPlayer.MediaStatus.LoadingMedia)

    def finish_loading(self):
        """Simulate the loader thread completing."""
        self._emit_status(QMediaPlayer.MediaStatus.LoadedMedia)

    def play(self):
        self.calls.append("play")
        self.state = QMediaPlayer.PlaybackState.PlayingState

    def playbackState(self):
        return self.state

    def mediaStatus(self):
        return self.status

    def setPosition(self, pos):
        self._position = pos

    def position(self):
        return self._position

    def duration(self):
        return self._duration


class FakeLabel:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text

    def setStyleSheet(self, _):
        pass


class FakeSlider:
    def setValue(self, _):
        pass


class FakeTimer:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class Harness:
    """Minimal stand-in for MainWindow carrying only the player attributes."""

    _play_audio_file = MainWindow._play_audio_file
    _start_media_load = MainWindow._start_media_load
    _apply_pending_source = MainWindow._apply_pending_source
    _begin_playback = MainWindow._begin_playback
    _set_playing_label = MainWindow._set_playing_label
    _clear_pending_play = MainWindow._clear_pending_play
    _on_load_timeout = MainWindow._on_load_timeout
    _on_playback_check = MainWindow._on_playback_check
    _on_player_media_status_changed = MainWindow._on_player_media_status_changed
    _on_player_error_occurred = MainWindow._on_player_error_occurred
    _stop_playback = MainWindow._stop_playback
    _plog = MainWindow._plog

    def __init__(self, deferred):
        self._player = FakePlayer(self)
        self._player_track_label = FakeLabel()
        self._seek_slider = FakeSlider()
        self._time_curr_label = FakeLabel()
        self._load_timeout_timer = FakeTimer()
        self._playback_check_timer = FakeTimer()
        self._player_log = []
        self._current_playing_file = ""
        self._current_track_title = ""
        self._pending_play_file = ""
        self._pending_play_title = ""
        self._load_generation = 0
        self._load_attempt = 0
        self._deferred = deferred

    # _start_media_load defers the real setSource via QTimer.singleShot; the
    # tests drive that step explicitly instead of running an event loop.
    def run_deferred(self):
        while self._deferred:
            self._deferred.pop(0)()

    def play(self, path, title):
        self._play_audio_file(path, title)
        self.run_deferred()


@pytest.fixture()
def harness(monkeypatch):
    """Harness whose QTimer.singleShot callbacks are queued, not scheduled."""
    import rkbdb2xml.gui as gui

    deferred = []
    monkeypatch.setattr(
        gui.QTimer, "singleShot", staticmethod(lambda ms, cb: deferred.append(cb))
    )
    return Harness(deferred)


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


def test_play_is_deferred_until_media_is_loaded(harness, track):
    harness.play(track, "Track A")

    assert "play" not in harness._player.calls, "play() must wait for LoadedMedia"
    assert harness._pending_play_file == track
    assert harness._load_timeout_timer.running

    harness._player.finish_loading()

    assert harness._player.calls[-1] == "play"
    assert harness._pending_play_file == ""
    assert not harness._load_timeout_timer.running
    assert "再生中" in harness._player_track_label.text


def test_switching_while_a_track_is_playing_starts_the_new_track(harness, two_tracks):
    """stop() re-emits LoadedMedia for the old track; it must not eat the new one."""
    a, b = two_tracks
    harness.play(a, "A")
    harness._player.finish_loading()
    assert harness._player.state == QMediaPlayer.PlaybackState.PlayingState

    harness.play(b, "B")  # double-click another track while A is playing

    assert harness._pending_play_file == b, "the re-entrant stop() event ate the request"
    assert harness._load_timeout_timer.running
    assert "読み込み中" in harness._player_track_label.text

    harness._player.finish_loading()

    assert harness._player.sources[-1] == b
    assert harness._player.calls[-1] == "play"
    assert "B" in harness._player_track_label.text


def test_alternating_track_switches_all_start(harness, two_tracks):
    a, b = two_tracks
    for i in range(6):
        path = a if i % 2 == 0 else b
        harness.play(path, f"T{i}")
        harness._player.finish_loading()
        assert harness._player.state == QMediaPlayer.PlaybackState.PlayingState, i
        assert harness._player.sources[-1] == path, i
        assert "再生中" in harness._player_track_label.text, i


def test_superseded_load_does_not_set_a_stale_source(harness, two_tracks):
    a, b = two_tracks
    harness._play_audio_file(a, "A")
    harness._play_audio_file(b, "B")  # before A's deferred setSource ran
    harness.run_deferred()

    assert harness._player.sources[-1] == b
    assert a not in harness._player.sources


def test_stale_end_of_media_does_not_cancel_a_pending_load(harness, track):
    harness.play(track, "Track A")
    harness._player._position = harness._player._duration

    harness._on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

    assert harness._pending_play_file == track

    harness._player.finish_loading()
    assert harness._player.calls[-1] == "play"


def test_load_timeout_retries_once_then_reports_failure(harness, track):
    harness.play(track, "Track A")

    harness._on_load_timeout()  # still LoadingMedia
    harness.run_deferred()
    assert harness._pending_play_file == track
    assert harness._load_attempt == 1
    assert harness._load_timeout_timer.running

    harness._on_load_timeout()
    assert harness._pending_play_file == ""
    assert "読み込みに失敗" in harness._player_track_label.text


def test_load_timeout_plays_when_the_media_was_already_loaded(harness, track):
    """A LoadedMedia we somehow never saw must not strand the UI on "loading"."""
    harness.play(track, "Track A")
    harness._player.status = QMediaPlayer.MediaStatus.LoadedMedia

    harness._on_load_timeout()

    assert harness._player.calls[-1] == "play"
    assert "再生中" in harness._player_track_label.text


def test_playback_check_retries_a_stalled_pipeline(harness, track):
    harness.play(track, "Track A")
    harness._player.finish_loading()
    assert harness._playback_check_timer.running

    harness._on_playback_check()  # position is still 0
    harness.run_deferred()

    assert harness._load_attempt == 1
    assert harness._pending_play_file == track


def test_playback_check_is_quiet_while_playing_normally(harness, track):
    harness.play(track, "Track A")
    harness._player.finish_loading()
    harness._player._position = 3000

    harness._on_playback_check()

    assert harness._pending_play_file == ""
    assert "再生中" in harness._player_track_label.text


def test_invalid_media_reports_error(harness, track):
    harness.play(track, "Track A")

    harness._on_player_media_status_changed(QMediaPlayer.MediaStatus.InvalidMedia)

    assert harness._pending_play_file == ""
    assert "play" not in harness._player.calls
    assert "再生できない形式" in harness._player_track_label.text


def test_error_during_load_does_not_cancel_the_pending_track(harness, two_tracks):
    a, b = two_tracks
    harness.play(a, "A")
    harness.play(b, "B")
    # Aborting A's load reports an error while B is still loading; the two
    # cannot be told apart, so the pending load is left to the timeout.
    harness._on_player_error_occurred(QMediaPlayer.Error.ResourceError, "aborted")

    assert harness._pending_play_file == b

    harness._player.finish_loading()
    assert harness._player.calls[-1] == "play"


def test_stop_cancels_a_pending_load(harness, track):
    harness.play(track, "Track A")
    harness._stop_playback()

    assert harness._pending_play_file == ""
    assert not harness._load_timeout_timer.running

    harness._player.finish_loading()  # late event from the cancelled load
    assert "play" not in harness._player.calls
    assert "停止中" in harness._player_track_label.text


def test_missing_file_is_reported_without_touching_the_player(harness, tmp_path):
    harness.play(str(tmp_path / "nope.mp3"), "Gone")

    assert harness._player.calls == []
    assert "見つかりません" in harness._player_track_label.text

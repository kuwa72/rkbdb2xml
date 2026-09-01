"""Regression tests for the mini audio player's deferred playback.

QMediaPlayer.setSource() loads asynchronously. Calling play() immediately after
it races with the loader and leaves the player in PlayingState while nothing is
actually decoded, so playback must be deferred until LoadedMedia arrives.
"""

import pytest

pytest.importorskip("PySide6.QtMultimedia")

from PySide6.QtMultimedia import QMediaPlayer  # noqa: E402

from rkbdb2xml.gui import MainWindow  # noqa: E402


class FakePlayer:
    def __init__(self):
        self.calls = []
        self.sources = []
        self.state = QMediaPlayer.PlaybackState.StoppedState
        self._position = 0
        self._duration = 180000

    def stop(self):
        self.calls.append("stop")
        self.state = QMediaPlayer.PlaybackState.StoppedState

    def setSource(self, url):
        self.calls.append("setSource")
        self.sources.append(url.toLocalFile())

    def play(self):
        self.calls.append("play")
        self.state = QMediaPlayer.PlaybackState.PlayingState

    def playbackState(self):
        return self.state

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
    _set_playing_label = MainWindow._set_playing_label
    _clear_pending_play = MainWindow._clear_pending_play
    _on_load_timeout = MainWindow._on_load_timeout
    _on_player_media_status_changed = MainWindow._on_player_media_status_changed
    _on_player_error_occurred = MainWindow._on_player_error_occurred
    _stop_playback = MainWindow._stop_playback

    def __init__(self):
        self._player = FakePlayer()
        self._player_track_label = FakeLabel()
        self._seek_slider = FakeSlider()
        self._time_curr_label = FakeLabel()
        self._load_timeout_timer = FakeTimer()
        self._current_playing_file = ""
        self._current_track_title = ""
        self._pending_play_file = ""
        self._pending_play_title = ""
        self._pending_retry_done = False


@pytest.fixture()
def track(tmp_path):
    p = tmp_path / "track.mp3"
    p.write_bytes(b"\x00" * 16)
    return str(p)


def test_play_is_deferred_until_media_is_loaded(track):
    h = Harness()
    h._play_audio_file(track, "Track A")

    assert "play" not in h._player.calls, "play() must not be called before the media is loaded"
    assert h._pending_play_file == track
    assert h._load_timeout_timer.running

    h._on_player_media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)

    assert h._player.calls[-1] == "play"
    assert h._pending_play_file == ""
    assert not h._load_timeout_timer.running
    assert "再生中" in h._player_track_label.text


def test_rapid_track_switch_plays_the_last_requested_track(tmp_path):
    a = tmp_path / "a.mp3"
    b = tmp_path / "b.mp3"
    for p in (a, b):
        p.write_bytes(b"\x00" * 16)
    h = Harness()

    h._play_audio_file(str(a), "A")
    h._play_audio_file(str(b), "B")  # second double-click before A finished loading

    assert h._pending_play_file == str(b)
    h._on_player_media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)

    assert h._player.sources[-1] == str(b)
    assert h._player.calls.count("play") == 1
    assert "B" in h._player_track_label.text


def test_stale_end_of_media_does_not_cancel_a_pending_load(track):
    h = Harness()
    h._play_audio_file(track, "Track A")
    h._player._position = h._player._duration  # flush event from the previous media

    h._on_player_media_status_changed(QMediaPlayer.MediaStatus.EndOfMedia)

    assert h._pending_play_file == track, "a pending load must survive a flush EndOfMedia"

    h._on_player_media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)
    assert h._player.calls[-1] == "play"


def test_load_timeout_retries_once_then_reports_failure(track):
    h = Harness()
    h._play_audio_file(track, "Track A")

    h._on_load_timeout()
    assert h._pending_play_file == track
    assert h._player.sources[-1] == track
    assert h._load_timeout_timer.running

    h._on_load_timeout()
    assert h._pending_play_file == ""
    assert "読み込みに失敗" in h._player_track_label.text


def test_invalid_media_reports_error(track):
    h = Harness()
    h._play_audio_file(track, "Track A")

    h._on_player_media_status_changed(QMediaPlayer.MediaStatus.InvalidMedia)

    assert h._pending_play_file == ""
    assert "play" not in h._player.calls
    assert "再生できない形式" in h._player_track_label.text


def test_error_during_load_does_not_cancel_the_pending_track(tmp_path):
    a = tmp_path / "a.mp3"
    b = tmp_path / "b.mp3"
    for p in (a, b):
        p.write_bytes(b"\x00" * 16)
    h = Harness()

    h._play_audio_file(str(a), "A")
    h._play_audio_file(str(b), "B")
    # Aborting A's load reports an error while B is still loading; the two
    # cannot be told apart, so the pending load must be left to the timeout.
    h._on_player_error_occurred(QMediaPlayer.Error.ResourceError, "aborted")

    assert h._pending_play_file == str(b), "B's pending load must survive A's abort error"

    h._on_player_media_status_changed(QMediaPlayer.MediaStatus.LoadedMedia)
    assert h._player.calls[-1] == "play"


def test_missing_file_is_reported_without_touching_the_player(tmp_path):
    h = Harness()
    h._play_audio_file(str(tmp_path / "nope.mp3"), "Gone")

    assert h._player.calls == []
    assert "見つかりません" in h._player_track_label.text

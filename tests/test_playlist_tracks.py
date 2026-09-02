"""Tests for fetching a playlist's tracks.

``Rekordbox6Database.get_playlist_contents()`` always returns ``DjmdContent``
rows, whose ``ID`` is a string in Rekordbox 6. The code used to hedge against
that (``getattr(entry, "ContentID", None) or getattr(entry, "ID", None)``) and
then stored every ID in three types so later lookups could not miss. These
tests pin the single call path and the single ID type instead.

The full export needs a real Rekordbox database, so the DB is faked here; what
is under test is our own normalisation, not SQLAlchemy.
"""

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter, playlist_tracks


class FakeContent:
    """Stands in for a DjmdContent row."""

    def __init__(self, id_, bpm=None):
        self.ID = id_
        self.BPM = bpm


class FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeDatabase:
    def __init__(self, rows):
        self._rows = rows
        self.requested = []

    def get_playlist_contents(self, playlist):
        self.requested.append(playlist)
        return FakeQuery(self._rows)


class FakePlaylistNode:
    def __init__(self):
        self.tracks = []

    def add_track(self, track_id):
        self.tracks.append(track_id)


def make_exporter(**overrides):
    """An exporter with just enough state for _add_playlists_to_playlist."""
    exporter = RekordboxXMLExporter.__new__(RekordboxXMLExporter)
    exporter._playlist_path_map = {}
    exporter._playlist_options = {}
    exporter._orderby = "default"
    exporter._use_roman = False
    exporter._use_bpm = False
    exporter._selected_track_ids = set()
    exporter._track_options = {}
    for key, value in overrides.items():
        setattr(exporter, key, value)
    return exporter


class FakePlaylist:
    ID = "PL1"


def test_playlist_order_is_kept_by_default():
    db = FakeDatabase([FakeContent("3", 12000), FakeContent("1", 9000)])

    tracks = playlist_tracks(db, FakePlaylist())

    assert [t.ID for t in tracks] == ["3", "1"]


def test_bpm_ordering_sorts_ascending():
    db = FakeDatabase(
        [FakeContent("a", 14000), FakeContent("b", 9000), FakeContent("c", 12000)]
    )

    tracks = playlist_tracks(db, FakePlaylist(), orderby="bpm")

    assert [t.ID for t in tracks] == ["b", "c", "a"]


def test_tracks_without_bpm_sort_first():
    db = FakeDatabase([FakeContent("a", 12000), FakeContent("b", None)])

    tracks = playlist_tracks(db, FakePlaylist(), orderby="bpm")

    assert [t.ID for t in tracks] == ["b", "a"]


def test_an_unknown_orderby_keeps_playlist_order():
    db = FakeDatabase([FakeContent("a", 14000), FakeContent("b", 9000)])

    tracks = playlist_tracks(db, FakePlaylist(), orderby="whatever")

    assert [t.ID for t in tracks] == ["a", "b"]


def test_a_playlist_id_can_be_passed_straight_through():
    db = FakeDatabase([])

    playlist_tracks(db, "PL42")

    assert db.requested == ["PL42"], "the ID must reach get_playlist_contents as-is"


def test_selected_ids_are_recorded_as_strings():
    """Track IDs must be one type; the collection filter compares strings."""
    exporter = make_exporter()
    db = FakeDatabase([FakeContent("101"), FakeContent("102")])
    exporter.db = db
    node = FakePlaylistNode()

    exporter._add_playlists_to_playlist(node, FakePlaylist())

    assert node.tracks == ["101", "102"]
    assert exporter._selected_track_ids == {"101", "102"}
    assert set(exporter._track_options) == {"101", "102"}


def test_integer_ids_are_normalised_to_strings():
    exporter = make_exporter()
    exporter.db = FakeDatabase([FakeContent(101)])
    node = FakePlaylistNode()

    exporter._add_playlists_to_playlist(node, FakePlaylist())

    assert exporter._selected_track_ids == {"101"}
    assert node.tracks == ["101"]


def test_per_playlist_options_win_over_the_global_ones():
    exporter = make_exporter(
        _playlist_path_map={"PL1": "Folder/List"},
        _playlist_options={"Folder/List": {"roman": True, "bpm": True, "orderby": "bpm"}},
    )
    exporter.db = FakeDatabase([FakeContent("1", 14000), FakeContent("2", 9000)])
    node = FakePlaylistNode()

    exporter._add_playlists_to_playlist(node, FakePlaylist())

    assert node.tracks == ["2", "1"], "the per-playlist orderby must be applied"
    assert exporter._track_options["1"] == {"roman": True, "bpm": True}


def test_the_first_playlist_wins_for_a_track_in_several_playlists():
    exporter = make_exporter(
        _playlist_path_map={"PL1": "First"},
        _playlist_options={
            "First": {"roman": True, "bpm": False},
            "Second": {"roman": False, "bpm": True},
        },
    )
    exporter.db = FakeDatabase([FakeContent("7")])
    exporter._add_playlists_to_playlist(FakePlaylistNode(), FakePlaylist())

    exporter._playlist_path_map = {"PL1": "Second"}
    exporter._add_playlists_to_playlist(FakePlaylistNode(), FakePlaylist())

    assert exporter._track_options["7"] == {"roman": True, "bpm": False}

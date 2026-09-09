"""End-to-end tests for the device-library export path."""

from pathlib import Path
from typing import Any, Dict, List

from rekordbox_pdb import Database

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter


class FakeQuery:
    def __init__(self, items: List[Any]) -> None:
        self._items = items

    def all(self) -> List[Any]:
        return self._items


class FakeDb:
    def __init__(self, playlists: List[Any], contents: List[Any]) -> None:
        self._playlists = playlists
        self._contents = contents

    def get_playlist(self) -> FakeQuery:
        return FakeQuery(self._playlists)

    def get_content(self) -> FakeQuery:
        return FakeQuery(self._contents)

    def get_playlist_contents(self, playlist: Any) -> FakeQuery:
        track_ids = set(str(t) for t in getattr(playlist, "track_ids", []))
        return FakeQuery([c for c in self._contents if str(c.ID) in track_ids])

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {}

    def close(self) -> None:
        pass


class FakePlaylist:
    def __init__(self, pid: str, name: str, parent_id: str) -> None:
        self.ID = pid
        self.Name = name
        self.ParentID = parent_id
        self.is_folder = False
        self.is_playlist = True
        self.track_ids: List[str] = []


class FakeContent:
    def __init__(self, cid: str, title: str, folder_path: str) -> None:
        self.ID = cid
        self.Title = title
        self.FolderPath = folder_path
        self.ArtistName = "Artist"
        self.AlbumName = "Album"
        self.GenreName = "House"
        self.KeyName = "Am"
        self.BPM = 12800
        self.Length = 240
        self.BitRate = 320
        self.SampleRate = 44100
        self.BitDepth = 16
        self.FileSize = 8_000_000
        self.TrackNo = 1
        self.DiscNo = 1
        self.ReleaseYear = 2025
        self.DateCreated = "2025-01-01"


def test_device_export_creates_pdb_and_contents(tmp_path: Path) -> None:
    """RekordboxXMLExporter.generate_device_export builds a USB tree."""
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"dummy audio data")

    usb_root = tmp_path / "usb"
    usb_root.mkdir()

    content = FakeContent("1", "Test Track", str(audio))
    playlist = FakePlaylist("101", "My Playlist", "0")
    playlist.track_ids = ["1"]
    db = FakeDb([playlist], [content])

    exporter = object.__new__(RekordboxXMLExporter)
    exporter.db = db
    exporter._playlists = ["My Playlist"]
    exporter._playlist_options = {
        "My Playlist": {"roman": False, "bpm": False, "orderby": "default"},
    }
    exporter._track_options = {}
    exporter._copy_map = {}
    exporter._verbose = False
    exporter._roman_converter = None

    exporter.generate_device_export(str(usb_root))

    pdb_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    contents_dir = usb_root / "Contents"
    assert pdb_path.exists()
    assert contents_dir.exists()

    copied = list(contents_dir.iterdir())
    assert len(copied) == 1
    assert copied[0].suffix == ".mp3"

    db_pdb = Database.from_file(pdb_path)
    assert len(db_pdb.tracks) == 1
    track = db_pdb.tracks[0]
    assert track.title == content.Title
    assert track.file_path == f"/Contents/{copied[0].name}"
    assert len(db_pdb.playlist_tree) == 1
    assert db_pdb.playlist_tree[0].name == "My Playlist"
    assert len(db_pdb.playlist_entries) == 1

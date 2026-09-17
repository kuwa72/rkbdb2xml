"""CI 検証用のサンプル USB エクスポートを生成する。

実機検証ツール（crate-digger 等）に渡すための PIONEER/ ツリーを
``PdbExporter`` で作る。Rekordbox 本体・実データベースは不要。

Usage:
    python scripts/gen_sample_export.py <output_dir>
"""

import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rkbdb2xml.pdb_export import DevicePdbNode, PdbExporter  # noqa: E402


class _FakeDb:
    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {}


class _FakeContent:
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


def main() -> None:
    usb_root = Path(sys.argv[1])
    contents = usb_root / "Contents"
    contents.mkdir(parents=True)
    dest_a = contents / "track_a.mp3"
    dest_b = contents / "track_b.mp3"
    dest_a.write_bytes(b"audio a")
    dest_b.write_bytes(b"audio b")

    folder = DevicePdbNode("Root", is_folder=True)
    playlist = folder.add_playlist("Playlist")
    playlist.add_track("1")
    playlist.add_track("2")

    exporter = PdbExporter(_FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[folder],
        content_map={
            "1": _FakeContent("1", "Track One", "/src/a.mp3"),
            "2": _FakeContent("2", "Track Two", "/src/b.mp3"),
        },
        copy_map={"/src/a.mp3": dest_a, "/src/b.mp3": dest_b},
        track_options={},
    )
    print(pdb_path)


if __name__ == "__main__":
    main()

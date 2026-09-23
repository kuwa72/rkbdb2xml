"""``_copy_files`` の書き込みパターンに関するテスト。

USB フラッシュメモリでは in-place 上書きと細切れ書きが極端に遅いため:

- dest は書き込み用に 1 回だけ open されること（mutagen による ``rb+``
  再オープンがあってはならない）
- タグ変換はソース読み込み時（メモリ上）に済ませること
- 書き込み途中で失敗したら部分ファイルを残さないこと

を検証する。open の記録は builtins.open の差し替え（計測）で行い、
対象コードのロジック自体はフェイクで置き換えない。
"""

import builtins
import io
import wave
from pathlib import Path

from mutagen.id3 import ID3, TIT2
from mutagen.mp4 import MP4

from rkbdb2xml import rkbdb2xml
from rkbdb2xml.rkbdb2xml import (
    RekordboxXMLExporter,
    _disambiguate_anlz_destinations,
)
from rkbdb2xml.anlz import anlz_dir

M4A_FIXTURE = Path(__file__).parent / "data" / "test_audio.m4a"


class FakeContent:
    def __init__(self, cid: str, folder_path: str, bpm: int = 12800) -> None:
        self.ID = cid
        self.FolderPath = folder_path
        self.Title = "Test Track"
        self.ArtistName = "Test Artist"
        self.AlbumName = "Test Album"
        self.BPM = bpm


class FakeQuery:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items


class FakeDb:
    def __init__(self, contents):
        self._contents = contents

    def get_content(self):
        return FakeQuery(self._contents)


def make_mp3(path: Path, title: str = "orig") -> None:
    """既存タグ（小さいパディング）付きの合成 MP3 を作る。"""
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    bio = io.BytesIO()
    bio.write(frame * 2000)
    tags = ID3()
    tags["TIT2"] = TIT2(encoding=3, text=title)
    tags.save(fileobj=bio, padding=lambda info: 64)
    path.write_bytes(bio.getvalue())


def make_wav(path: Path, seconds: float = 0.1) -> None:
    import math
    import struct as _struct

    rate = 8000
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(
            b"".join(
                _struct.pack("<h", int(10000 * math.sin(2 * math.pi * 440 * i / rate)))
                for i in range(n)
            )
        )


def make_exporter(contents, tmp_path: Path) -> RekordboxXMLExporter:
    exporter = RekordboxXMLExporter.__new__(RekordboxXMLExporter)
    exporter.db = FakeDb(contents)
    exporter._playlists = None
    exporter._selected_track_ids = set()
    exporter._track_options = {}
    exporter._copy_map = {}
    exporter._verbose = False
    exporter._roman_converter = None
    return exporter


class OpenRecorder:
    """builtins.open を包んで open 呼び出し (path, mode) を記録する。"""

    def __init__(self):
        self.opens = []
        self._real = builtins.open

    def __enter__(self):
        builtins.open = self._wrap
        return self

    def __exit__(self, *exc):
        builtins.open = self._real

    def _wrap(self, file, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        self.opens.append((str(file), mode))
        return self._real(file, *args, **kwargs)


def dest_for(export_dir: Path, src: Path) -> Path:
    import hashlib

    md5 = hashlib.md5(str(src).encode("utf-8")).hexdigest()
    return export_dir / f"{md5}{src.suffix}"


def test_anlz_hash_collisions_get_distinct_destinations(tmp_path):
    first = "dbf4211b99d30bf16ffad8c56b83bcd3.mp3"
    second = "209b34afcad1f41e84a2d8e84dfc388f.mp3"
    jobs = [
        ("first", Path("first.mp3"), tmp_path / first, "loc1", "1", object()),
        ("second", Path("second.mp3"), tmp_path / second, "loc2", "2", object()),
    ]

    result = _disambiguate_anlz_destinations(jobs)
    directories = {
        anlz_dir(f"/Contents/{job[2].name}") for job in result
    }

    assert len(directories) == 2
    assert result[0][2].name == first
    assert result[1][2].name == f"209b34afcad1f41e84a2d8e84dfc388f-1.mp3"


# ----- dest への open は 1 回だけ・書き込みモードは 1 ストリーム -------------

def test_dest_is_opened_once_and_never_reopened_for_update(tmp_path):
    src = tmp_path / "src.mp3"
    make_mp3(src)
    content = FakeContent("1", str(src))
    exporter = make_exporter([content], tmp_path)
    export_dir = tmp_path / "Contents"
    export_dir.mkdir()

    with OpenRecorder() as rec:
        exporter._copy_files(export_dir)

    dest = dest_for(export_dir, src)
    dest_opens = [m for p, m in rec.opens if str(dest) == p]
    assert dest_opens == ["wb"]
    for _, mode in rec.opens:
        assert "+" not in mode, f"dest が更新モードで開かれた: {mode}"


def test_mp3_tags_are_rewritten(tmp_path):
    src = tmp_path / "src.mp3"
    make_mp3(src)
    content = FakeContent("1", str(src), bpm=12800)
    exporter = make_exporter([content], tmp_path)
    exporter._track_options = {"1": {"roman": False, "bpm": True}}
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    exporter._copy_files(export_dir)

    dest = dest_for(export_dir, src)
    tags = ID3(dest)
    assert tags["TIT2"].text == ["128 Test Track"]
    assert tags["TPE1"].text == ["Test Artist"]
    assert tags["TALB"].text == ["Test Album"]


def test_m4a_tags_are_rewritten(tmp_path):
    src = tmp_path / "src.m4a"
    src.write_bytes(M4A_FIXTURE.read_bytes())
    content = FakeContent("1", str(src))
    exporter = make_exporter([content], tmp_path)
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    exporter._copy_files(export_dir)

    dest = dest_for(export_dir, src)
    audio = MP4(dest)
    assert audio["\xa9nam"] == ["Test Track"]
    assert audio["\xa9ART"] == ["Test Artist"]
    assert audio["\xa9alb"] == ["Test Album"]


def test_wav_is_streamed_without_full_load(tmp_path):
    src = tmp_path / "src.wav"
    make_wav(src)
    content = FakeContent("1", str(src))
    exporter = make_exporter([content], tmp_path)
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    # タグ変換対象外の形式は全読込せずストリームコピーする
    assert exporter._prepare_tagged_bytes(src, ".wav", "t", "a", "al") is None

    exporter._copy_files(export_dir)

    dest = dest_for(export_dir, src)
    assert dest.read_bytes() == src.read_bytes()


def test_read_error_leaves_no_partial_file(tmp_path, monkeypatch):
    src = tmp_path / "src.wav"
    make_wav(src)
    content = FakeContent("1", str(src))
    exporter = make_exporter([content], tmp_path)
    export_dir = tmp_path / "out"
    export_dir.mkdir()
    monkeypatch.setattr(rkbdb2xml, "_COPY_CHUNK", 64)

    real_open = builtins.open

    class FlakySource(io.RawIOBase):
        """1 回目の読み込みまでは正常、その後読み込みエラーを起こすソース。"""

        def __init__(self, f):
            self._f = f
            self.reads = 0

        def readinto(self, b):
            if self.reads >= 1:
                raise OSError("simulated read error")
            self.reads += 1
            return self._f.readinto(b)

        def __getattr__(self, name):
            return getattr(self._f, name)

    def flaky_open(file, *args, **kwargs):
        f = real_open(file, *args, **kwargs)
        if str(file) == str(src):
            return FlakySource(f)
        return f

    monkeypatch.setattr(builtins, "open", flaky_open)

    exporter._copy_files(export_dir)

    dest = dest_for(export_dir, src)
    assert not dest.exists()


def test_tag_error_falls_back_to_original_bytes(tmp_path):
    src = tmp_path / "broken.m4a"
    src.write_bytes(b"this is not an mp4 file")
    content = FakeContent("1", str(src))
    exporter = make_exporter([content], tmp_path)
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    exporter._copy_files(export_dir)

    dest = dest_for(export_dir, src)
    assert dest.read_bytes() == b"this is not an mp4 file"


def test_existing_dest_is_not_rewritten(tmp_path):
    src = tmp_path / "src.mp3"
    make_mp3(src)
    content = FakeContent("1", str(src))
    exporter = make_exporter([content], tmp_path)
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    exporter._copy_files(export_dir)
    dest = dest_for(export_dir, src)
    dest.write_bytes(dest.read_bytes() + b"MARKER")

    exporter._copy_files(export_dir)

    assert dest.read_bytes().endswith(b"MARKER")


def test_files_are_processed_in_source_path_order(tmp_path):
    # DB の並び順と逆になるよう配置する
    dir_a = tmp_path / "aaa"
    dir_b = tmp_path / "bbb"
    dir_a.mkdir()
    dir_b.mkdir()
    src_a = dir_a / "track.mp3"
    src_b = dir_b / "track.mp3"
    make_mp3(src_a)
    make_mp3(src_b)
    contents = [FakeContent("1", str(src_b)), FakeContent("2", str(src_a))]
    exporter = make_exporter(contents, tmp_path)
    export_dir = tmp_path / "out"
    export_dir.mkdir()

    with OpenRecorder() as rec:
        exporter._copy_files(export_dir)

    src_opens = [p for p, m in rec.opens if m == "rb"]
    assert src_opens == sorted(src_opens)

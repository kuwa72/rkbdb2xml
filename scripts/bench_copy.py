#!/usr/bin/env python3
"""USB エクスポートのコピー性能を計測する。

合成コーパス（既存タグ付き mp3 / m4a / wav）を生成し、旧実装
（shutil.copy2 → USB 上のファイルを mutagen で書き換え）と新実装
（メモリ内タグ変換 → 1 ファイル 1 ストリーム書き）を比較する。

使い方:
    python scripts/bench_copy.py --impl old --target /mnt/usb_bench
    python scripts/bench_copy.py --impl new --target /mnt/usb_bench

--target には実際の USB メモリのマウントポイントを指定する（SSD や
RAM ディスクではフラッシュ特有の差が出ない）。計測は 2 回以上実行し、
2 回目以降の値を見ること（OS キャッシュの影響を除くため）。

出力する指標:
- wall / MB/s          : 壁時計時間
- dest opens           : dest を書き込み系モードで open した回数
                         （旧実装は copy 1 回 + mutagen の rb+ 再オープン）
- write calls / bytes  : dest への write 系システムコール回数とバイト数
                         （sendfile もカウント。ハードに依存しない指標）
- extents/file         : 出力ファイルの断片数（Linux のみ filefrag、理想は 1）
"""

import argparse
import builtins
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter  # noqa: E402

N_TRACKS = 12
MP3_BYTES = 10 * 1024 * 1024
WAV_BYTES = 20 * 1024 * 1024
LONG_TITLE = "128 Kaze wo Atsumete (Extended Club Mix) - " + "x" * 200


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


class FakeContent:
    def __init__(self, cid, folder_path):
        self.ID = str(cid)
        self.FolderPath = folder_path
        self.Title = "風をあつめて"
        self.ArtistName = "はっぴいえんど"
        self.AlbumName = "風街ろまん"
        self.BPM = 12800


class WriteCounter:
    """書き込みモードの open と、その file object への write を数える。"""

    def __init__(self):
        self.opens = 0
        self.writes = 0
        self.bytes = 0
        self._real_open = builtins.open
        self._real_sendfile = getattr(os, "sendfile", None)

    def __enter__(self):
        builtins.open = self._open
        if self._real_sendfile is not None:
            os.sendfile = self.sendfile
        return self

    def __exit__(self, *exc):
        builtins.open = self._real_open
        if self._real_sendfile is not None:
            os.sendfile = self._real_sendfile

    def _open(self, file, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        f = self._real_open(file, *args, **kwargs)
        if "r" in mode and "+" not in mode and "w" not in mode and "a" not in mode:
            return f
        self.opens += 1
        return _CountingFile(f, self)

    def sendfile(self, out, in_fd, offset, count):
        n = self._real_sendfile(out, in_fd, offset, count)
        self.writes += 1
        self.bytes += n
        return n


class _CountingFile:
    def __init__(self, f, counter):
        self._f = f
        self._c = counter

    def write(self, b):
        self._c.writes += 1
        self._c.bytes += len(b)
        return self._f.write(b)

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()


class Timer:
    def __init__(self):
        self.seconds = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.perf_counter() - self._t0


def make_corpus(src_dir: Path) -> list:
    from mutagen.id3 import ID3, TIT2

    src_dir.mkdir(parents=True, exist_ok=True)
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    paths = []
    for i in range(N_TRACKS):
        if i % 5 == 4:
            p = src_dir / f"track{i:02d}.wav"
            p.write_bytes(
                b"RIFF" + (WAV_BYTES - 8).to_bytes(4, "little")
                + b"WAVE" + b"\x00" * (WAV_BYTES - 12)
            )
        elif i % 5 == 3:
            p = src_dir / f"track{i:02d}.m4a"
            shutil.copyfile(Path(__file__).resolve().parent.parent / "tests" / "data" / "test_audio.m4a", p)
        else:
            p = src_dir / f"track{i:02d}.mp3"
            bio = io.BytesIO()
            bio.write(frame * (MP3_BYTES // len(frame)))
            tags = ID3()
            tags["TIT2"] = TIT2(encoding=3, text=f"original {i}")
            tags.save(fileobj=bio, padding=lambda info: 64)
            p.write_bytes(bio.getvalue())
        paths.append(p)
    return paths


def run_old_impl(src_paths, export_dir: Path) -> None:
    """issue 修正前の _copy_files のコピー部分を再現する。"""
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, ID3NoHeaderError
    from mutagen.mp4 import MP4

    for i, orig in enumerate(src_paths):
        md5 = hashlib.md5(str(orig).encode("utf-8")).hexdigest()
        dest = export_dir / f"{md5}{orig.suffix}"
        if not dest.exists():
            shutil.copy2(orig, dest)
        ext = dest.suffix.lower()
        try:
            if ext == ".mp3":
                try:
                    audio = ID3(dest)
                except ID3NoHeaderError:
                    audio = ID3()
                audio["TIT2"] = TIT2(encoding=3, text=LONG_TITLE)
                audio["TPE1"] = TPE1(encoding=3, text="Happy End")
                audio["TALB"] = TALB(encoding=3, text="Kazemachi Roman")
                audio.save(dest)
            elif ext in (".m4a", ".mp4"):
                audio = MP4(dest)
                if audio.tags is None:
                    audio.add_tags()
                audio.tags["\xa9nam"] = [LONG_TITLE]
                audio.tags["\xa9ART"] = ["Happy End"]
                audio.tags["\xa9alb"] = ["Kazemachi Roman"]
                audio.save()
        except Exception as e:
            print(f"[WARN] tag: {e}", file=sys.stderr)


def make_exporter(src_paths):
    contents = [FakeContent(i, str(p)) for i, p in enumerate(src_paths)]
    exporter = RekordboxXMLExporter.__new__(RekordboxXMLExporter)
    exporter.db = FakeDb(contents)
    exporter._playlists = None
    exporter._selected_track_ids = set()
    exporter._track_options = {}
    exporter._copy_map = {}
    exporter._verbose = False
    exporter._roman_converter = None
    return exporter


def count_extents(directory: Path):
    """filefrag で各ファイルの断片数を数える（Linux のみ、無ければ None）。"""
    if shutil.which("filefrag") is None:
        return None
    extents = []
    for p in sorted(directory.iterdir()):
        r = subprocess.run(
            ["filefrag", "-v", str(p)], capture_output=True, text=True
        )
        for line in r.stdout.splitlines():
            if "extents" in line:
                try:
                    extents.append(int(line.split("extents")[0].strip().split()[-1]))
                except (ValueError, IndexError):
                    pass
    return extents or None


def main() -> None:
    global N_TRACKS
    parser = argparse.ArgumentParser()
    parser.add_argument("--impl", choices=["old", "new"], required=True)
    parser.add_argument("--target", default=None, help="計測先ディレクトリ（USB のマウントポイント推奨）")
    parser.add_argument("--tracks", type=int, default=N_TRACKS)
    args = parser.parse_args()

    N_TRACKS = args.tracks

    cleanup = args.target is None
    root = Path(args.target) if args.target else Path(tempfile.mkdtemp(prefix="rkbdb2xml_bench_"))
    src_dir = root / "src"
    export_dir = root / "Contents"
    export_dir.mkdir(parents=True, exist_ok=True)

    src_paths = make_corpus(src_dir)
    total_mb = sum(p.stat().st_size for p in src_paths) / (1024 * 1024)

    with WriteCounter() as counter, Timer() as timer:
        if args.impl == "old":
            run_old_impl(src_paths, export_dir)
        else:
            exporter = make_exporter(src_paths)
            exporter._copy_files(export_dir)

    mb = total_mb
    print(f"impl={args.impl}  files={len(src_paths)}  data={mb:.1f}MB  target={args.target or 'tmp'}")
    print(f"  wall            : {timer.elapsed:.2f} s  ({mb / timer.elapsed:.1f} MB/s)")
    print(f"  dest opens      : {counter.opens}")
    print(f"  write calls     : {counter.writes}")
    print(f"  write bytes     : {counter.bytes / (1024 * 1024):.1f} MB")
    if not cleanup:
        extents = count_extents(export_dir)
        if extents:
            print(f"  extents/file    : avg {sum(extents) / len(extents):.2f}  max {max(extents)}")
        print(f"  (出力は {export_dir} に残っています)")
    else:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()

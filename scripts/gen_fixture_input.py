"""実 Rekordbox に読ませる fixture 入力（音声 + rekordbox XML）を生成する。

``PdbExporter`` の出力を実機形式と突き合わせるため、シナリオごとの
プレイリストを1枚の XML にまとめ、Rekordbox に「XML インポート →
プレイリスト単位で USB エクスポート」させて PIONEER/ ツリーを回収する。

Usage:
    .venv/bin/python scripts/gen_fixture_input.py /mnt/c/rkb-fixtures

出力:
    <out>/audio/...   タグ付き音声ファイル（ffmpeg + mutagen）
    <out>/rekordbox.xml  Rekordbox の Imported Library に指定する XML
    <out>/scenarios.json   シナリオ名 → プレイリスト名一覧（回収側が参照）
"""

import json
import shutil
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

FFMPEG = "ffmpeg"


@dataclass
class Track:
    title: str
    artist: str = "Artist"
    album: str = "Album"
    genre: str = "House"
    fmt: str = "mp3"  # mp3 / wav / flac / m4a / aiff
    comments: str = ""
    rating: int = 0  # 0..5 (XML には 0/51/../255 で書く)
    tonality: str = ""
    colour: str = ""
    bpm: str = "128.00"
    artwork: Optional[str] = None  # "jpg" / "png"
    duration: float = 1.0

    # 生成後に埋まる
    path: Optional[Path] = None
    size: int = 0
    track_id: int = 0


@dataclass
class Playlist:
    name: str
    tracks: List[Track] = field(default_factory=list)


@dataclass
class Folder:
    name: str
    children: list = field(default_factory=list)  # Folder | Playlist


# --- シナリオ定義 ---------------------------------------------------------

JP_ARTIST = "アーティスト名"


def _jp_tracks() -> List[Track]:
    return [
        Track("日本語タイトル", JP_ARTIST, "アルバム名", "テクノ"),
        Track("ひらがなとカタカナ", "歌い手", "アルバム", "J-POP"),
        Track("半角ｶﾀｶﾅﾀｲﾄﾙ", "ﾊﾝｶｸｱｰﾃｨｽﾄ", "ｱﾙﾊﾞﾑ", "ﾃｸﾉ"),
        Track("全角ＡＢＣ１２３", "Ａｒｔｉｓｔ", "Ａｌｂｕｍ", "Ｇｅｎｒｅ"),
        Track("混合 ASCII と日本語 Mix-Vol.1", "DJ 名前", "album", "genre"),
        Track("長音符ー波線〜特殊記号「」・", "読み", "盤", "音楽"),
    ]


def _long_string_tracks() -> List[Track]:
    return [
        Track("T" * n, "A" * n, "L" * min(n, 120)) for n in (40, 63, 64, 65, 100)
    ] + [
        Track("長" * (n // 2), "ア" * (n // 3)) for n in (127, 128, 200)
    ] + [
        Track("X" * 255), Track("Y" * 300),
    ]


def _special_char_tracks() -> List[Track]:
    return [
        Track("emoji 🎧🎵 track", "DJ 🎛", "album 💿"),
        Track("quotes \"' ` track", "it's", "l'album"),
        Track("amp & lt< gt> track", "A & B", "x < y > z"),
        Track("accents éèê ü ö ñ ç", "Björk", "Sigur Rós"),
        Track("кириллица Трек", "Артист", "Альбом"),
        Track("  leading and trailing  ", " artist ", " album "),
        Track("日本語とemojiの混合🎧曲", "アーティスト🎤", "アルバム📀"),
        Track("tab\tは無理でも改行なしで", "ok", "ok"),
    ]


def _many_tracks(n: int) -> List[Track]:
    return [
        Track(f"Bulk Track {i:04d}", f"Bulk Artist {i % 17:02d}",
              f"Bulk Album {i % 9:02d}", "House", bpm=f"{120 + i % 60}.00")
        for i in range(n)
    ]


def _nested_playlists() -> Folder:
    t = lambda s: Track(f"Nested {s}", "N Artist", "N Album")  # noqa: E731
    return Folder("L1", [
        Playlist("SC06 depth1", [t("d1a"), t("d1b")]),
        Folder("L2", [
            Playlist("SC06 depth2", [t("d2")]),
            Folder("L3", [
                Playlist("SC06 depth3", [t("d3a"), t("d3b")]),
                Folder("L4", [Playlist("SC06 depth4", [t("d4")])]),
            ]),
        ]),
    ])


def _many_playlists() -> List[Playlist]:
    return [
        Playlist(f"SC07 pl {i:02d}",
                 [Track(f"MP {i:02d}-{j}", f"MP Artist {i:02d}")
                  for j in range(2)])
        for i in range(80)
    ]


def _rating_tracks() -> List[Track]:
    keys = ["Am", "C", "G#m", "F#", "12A", "3B", "", "Em"]
    colours = ["", "0xFF0000", "0x00FF00", "0x0000FF", "0xFFFF00", "0xFF00FF"]
    return [
        Track(f"Rated {r}stars", "R Artist", "R Album",
              rating=r, tonality=keys[i % len(keys)],
              colour=colours[i % len(colours)])
        for i, r in enumerate([0, 1, 2, 3, 4, 5, 5, 3, 0, 2, 4, 1])
    ]


def _file_type_tracks() -> List[Track]:
    return [
        Track("Fmt MP3", fmt="mp3"),
        Track("Fmt WAV", fmt="wav"),
        Track("Fmt FLAC", fmt="flac"),
        Track("Fmt M4A", fmt="m4a"),
        Track("Fmt AIFF", fmt="aiff"),
        Track("Fmt MP3 2nd", fmt="mp3"),
    ]


def _bpm_tracks() -> List[Track]:
    return [
        Track("BPM zero", bpm="0.00"),
        Track("BPM slow", bpm="60.00"),
        Track("BPM half", bpm="128.50"),
        Track("BPM fast", bpm="200.99"),
        Track("BPM max", bpm="999.00"),
    ]


def _artwork_tracks() -> List[Track]:
    return [
        Track("Art MP3 jpg", fmt="mp3", artwork="jpg"),
        Track("Art FLAC png", fmt="flac", artwork="png"),
        Track("Art M4A png", fmt="m4a", artwork="png"),
        Track("Art none", fmt="mp3"),
    ]


def _misc() -> List[Playlist]:
    shared = Track("Shared Ref", "Shared", "Shared")
    return [
        Playlist("SC12 empty", []),
        Playlist("SC12 dup refs", [shared, shared, Track("Other", "O", "O")]),
        Playlist("SC12 no artist", [
            Track("No Artist Track", "", "", ""),
        ]),
    ]


def build_tree() -> Folder:
    return Folder("SCENARIOS", [
        Folder("SC01_one_ascii", [Playlist("SC01 one_ascii",
                                          [Track("Plain ASCII Title")])]),
        Folder("SC02_japanese", [Playlist("SC02 japanese", _jp_tracks())]),
        Folder("SC03_long_strings", [Playlist("SC03 long_strings",
                                             _long_string_tracks())]),
        Folder("SC04_special_chars", [Playlist("SC04 special_chars",
                                               _special_char_tracks())]),
        Folder("SC05_many_tracks", [Playlist("SC05 many_tracks",
                                             _many_tracks(400))]),
        Folder("SC06_nested_playlists", [_nested_playlists()]),
        Folder("SC07_many_playlists", _many_playlists()),
        Folder("SC08_ratings_keys_colors", [
            Playlist("SC08 ratings_keys_colors", _rating_tracks())]),
        Folder("SC09_file_types", [Playlist("SC09 file_types",
                                           _file_type_tracks())]),
        Folder("SC10_bpm", [Playlist("SC10 bpm", _bpm_tracks())]),
        Folder("SC11_artwork", [Playlist("SC11 artwork", _artwork_tracks())]),
        Folder("SC12_misc", _misc()),
    ])


# --- 音声生成 -------------------------------------------------------------

_FMT = {
    "mp3": (["-c:a", "libmp3lame", "-q:a", "9"], ".mp3"),
    "wav": (["-c:a", "pcm_s16le"], ".wav"),
    "flac": (["-c:a", "flac"], ".flac"),
    "m4a": (["-c:a", "aac", "-b:a", "96k"], ".m4a"),
    "aiff": (["-c:a", "pcm_s16be"], ".aiff"),
}


def _base_file(fmt: str, cache: Dict[str, Path], audio_dir: Path,
               duration: float = 1.0) -> Path:
    if fmt not in cache:
        codec, ext = _FMT[fmt]
        out = audio_dir / f"_base{ext}"
        subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi",
             "-i", f"sine=frequency=440:duration={duration}",
             *codec, str(out)],
            check=True, capture_output=True)
        cache[fmt] = out
    return cache[fmt]


def _tag(track: Track) -> None:
    fmt, path = track.fmt, track.path
    if fmt == "mp3":
        from mutagen.easyid3 import EasyID3
        from mutagen.id3 import ID3
        try:
            audio = EasyID3(str(path))
        except Exception:
            audio = EasyID3()
        for k, v in (("title", track.title), ("artist", track.artist),
                     ("album", track.album), ("genre", track.genre)):
            if v:
                audio[k] = v
        audio.save(str(path))
        if track.artwork:
            mime = "image/jpeg" if track.artwork == "jpg" else "image/png"
            pic = _artwork_bytes(track.artwork)
            tags = ID3(str(path))
            from mutagen.id3 import APIC
            tags.add(APIC(encoding=3, mime=mime, type=3, data=pic))
            tags.save(str(path))
    elif fmt == "flac":
        from mutagen.flac import FLAC, Picture
        audio = FLAC(str(path))
        audio["title"] = track.title
        if track.artist:
            audio["artist"] = track.artist
            audio["album"] = track.album
            audio["genre"] = track.genre
        if track.artwork:
            p = Picture()
            p.type = 3
            p.mime = ("image/jpeg" if track.artwork == "jpg"
                      else "image/png")
            p.data = _artwork_bytes(track.artwork)
            audio.add_picture(p)
        audio.save()
    elif fmt == "m4a":
        from mutagen.mp4 import MP4, MP4Cover
        audio = MP4(str(path))
        audio["\xa9nam"] = [track.title]
        if track.artist:
            audio["\xa9ART"] = [track.artist]
            audio["\xa9alb"] = [track.album]
            audio["\xa9gen"] = [track.genre]
        if track.artwork:
            fmtc = (MP4Cover.FORMAT_JPEG if track.artwork == "jpg"
                    else MP4Cover.FORMAT_PNG)
            audio["covr"] = [MP4Cover(_artwork_bytes(track.artwork),
                                      imageformat=fmtc)]
        audio.save()
    elif fmt == "wav":
        from mutagen.wave import WAVE
        audio = WAVE(str(path))
        from mutagen.id3 import TIT2, TPE1, TALB, TCON
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TIT2(encoding=3, text=track.title))
        if track.artist:
            audio.tags.add(TPE1(encoding=3, text=track.artist))
            audio.tags.add(TALB(encoding=3, text=track.album))
            audio.tags.add(TCON(encoding=3, text=track.genre))
        audio.save()
    elif fmt == "aiff":
        from mutagen.aiff import AIFF
        audio = AIFF(str(path))
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON
        if audio.tags is None:
            audio.add_tags()
        audio.tags = ID3()
        audio.tags.add(TIT2(encoding=3, text=track.title))
        if track.artist:
            audio.tags.add(TPE1(encoding=3, text=track.artist))
            audio.tags.add(TALB(encoding=3, text=track.album))
            audio.tags.add(TCON(encoding=3, text=track.genre))
        audio.save()


def _artwork_bytes(kind: str) -> bytes:
    tmp = Path(sys.argv[1]) / f"_art.{kind}"
    if not tmp.exists():
        codec = "mjpeg" if kind == "jpg" else "png"
        subprocess.run(
            [FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64",
             "-frames:v", "1", "-c:v", codec, str(tmp)],
            check=True, capture_output=True)
    return tmp.read_bytes()


def materialize(root: Folder, out: Path) -> None:
    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cache: Dict[str, Path] = {}
    counter = 0

    def walk(node) -> None:
        nonlocal counter
        for child in node.children:
            if isinstance(child, Playlist):
                for t in child.tracks:
                    if t.path is not None:
                        continue
                    counter += 1
                    base = _base_file(t.fmt, cache, audio_dir, t.duration)
                    t.path = audio_dir / f"trk_{counter:05d}{base.suffix}"
                    shutil.copyfile(base, t.path)
                    _tag(t)
                    t.size = t.path.stat().st_size
            else:
                walk(child)

    walk(root)


# --- XML 出力 --------------------------------------------------------------

def _loc(p: Path, win_root: str) -> str:
    # /mnt/c/rkb-fixtures/audio/x.mp3 -> file://localhost/C:/rkb-fixtures/...
    rel = p.relative_to(Path("/mnt") / win_root[0].lower())
    win = f"{win_root[0].upper()}:/" + "/".join(rel.parts)
    return "file://localhost/" + urllib.parse.quote(win)


def _node_xml(node, depth: int) -> str:
    ind = "  " * depth
    if isinstance(node, Playlist):
        lines = [f'{ind}<NODE Type="1" Name={quoteattr(node.name)} '
                 f'Entries="{len(node.tracks)}" KeyType="0">']
        seen: Dict[int, int] = {}
        for t in node.tracks:
            lines.append(f'{ind}  <TRACK Key="{t.track_id}"/>')
            seen[t.track_id] = 1
        lines.append(f"{ind}</NODE>")
        return "\n".join(lines)
    count = sum(1 for c in node.children if isinstance(c, Playlist))
    lines = [f'{ind}<NODE Type="0" Name={quoteattr(node.name)} '
             f'Count="{count}">']
    for c in node.children:
        lines.append(_node_xml(c, depth + 1))
    lines.append(f"{ind}</NODE>")
    return "\n".join(lines)


def write_xml(root: Folder, out: Path, win_root: str,
              audio_root: Path) -> Dict[str, List[str]]:
    tracks: List[Track] = []
    seen_ids = set()
    scenarios: Dict[str, List[str]] = {}

    def collect(node) -> None:
        for c in node.children:
            if isinstance(c, Playlist):
                for t in c.tracks:
                    if id(t) not in seen_ids:
                        seen_ids.add(id(t))
                        tracks.append(t)
            else:
                collect(c)

    collect(root)
    for i, t in enumerate(tracks, 1):
        t.track_id = i

    def scenario_map(node, key: str) -> None:
        for c in node.children:
            if isinstance(c, Playlist):
                scenarios[key].append(c.name)
            else:
                scenario_map(c, key)

    for c in root.children:
        scenarios[c.name] = []
        scenario_map(c, c.name)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<DJ_PLAYLISTS Version="1.0.0">',
        '  <PRODUCT Name="rekordbox" Version="5.8.7" Company="Pioneer DJ"/>',
        f'  <COLLECTION Entries="{len(tracks)}">',
    ]
    for t in tracks:
        attrs = {
            "TrackID": t.track_id, "Name": t.title, "Artist": t.artist,
            "Album": t.album, "Genre": t.genre,
            "Kind": {"mp3": "MP3 File", "wav": "WAV File",
                     "flac": "FLAC File", "m4a": "AAC File",
                     "aiff": "AIFF File"}[t.fmt],
            "Size": t.size, "TotalTime": int(t.duration),
            "AverageBpm": t.bpm,
            "DateAdded": "2026-09-17", "BitRate": 320,
            "SampleRate": 44100, "Comments": t.comments,
            "PlayCount": 0, "Rating": t.rating * 51 if t.rating else 0,
            "Location": _loc(t.path, win_root),
        }
        if t.tonality:
            attrs["Tonality"] = t.tonality
        if t.colour:
            attrs["Colour"] = t.colour
        attr_s = " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items())
        parts.append(f"    <TRACK {attr_s}/>")
    parts.append("  </COLLECTION>")
    parts.append("  <PLAYLISTS>")
    parts.append('    <NODE Type="0" Name="ROOT" Count="1">')
    parts.append(_node_xml(root, 3))
    parts.append("    </NODE>")
    parts.append("  </PLAYLISTS>")
    parts.append("</DJ_PLAYLISTS>")
    (out / "rekordbox.xml").write_text("\n".join(parts), encoding="utf-8")
    return scenarios


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    win_root = sys.argv[2] if len(sys.argv) > 2 else "C:\\rkb-fixtures"
    tree = build_tree()
    materialize(tree, out)
    scenarios = write_xml(tree, out, win_root, out / "audio")
    (out / "scenarios.json").write_text(
        json.dumps(scenarios, ensure_ascii=False, indent=2))
    n = sum(len(v) for v in scenarios.values())
    print(f"{len(scenarios)} scenarios, {n} playlists -> {out}")


if __name__ == "__main__":
    main()

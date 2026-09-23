"""usb_fixtures（実 Rekordbox 5.8.7 製 USB ツリー）との突合検証。

``tests/data/fixture_input/rekordbox.xml`` は各フィクスチャを生成した
とき実機 Rekordbox に読ませた入力（621 トラック・12 シナリオ）。
同じ入力を ``PdbExporter`` に流して得られる export.pdb と、
実フィクスチャの export.pdb をフィールド単位で突き合わせる。

既知の差分（Rekordbox 側の仕様）:

- RB5.8.7 は AIFF をエクスポートしない（sc09 の Fmt AIFF は
  フィクスチャに存在しない）
- tempo/duration/bitrate は Rekordbox が自前で解析した値を書く。
  本フィクスチャは未解析相当で tempo=0 だが、本ツールは XML の
  BPM/TotalTime を書く（情報量が多い方を選ぶ設計）
- ``analyze_date`` は Rekordbox の解析日。本ツールは date_added を
  使う（pyrekordbox に解析日カラムが無い）
- artwork_id は本ツール未対応（常に 0。sc11 でのみ実フィクスチャ側
  が非 0）
- ``index_shift`` / 0x14 のユニーク値は内部実装依存
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import pytest
from rekordbox_pdb import Database

from rkbdb2xml.pdb_export import DevicePdbNode, PdbExporter
from tests.test_export_validation import walk_pdb

DATA_DIR = Path(__file__).parent / "data"
FIXTURES_DIR = DATA_DIR / "usb_fixtures"
INPUT_XML = DATA_DIR / "fixture_input" / "rekordbox.xml"
SCENARIOS_JSON = FIXTURES_DIR / "scenarios.json"

# このテストは RB5.8.7 fixture との比較専用。RB6 fixture は
# test_rb6_binary_fixture.py 側で同じ入力・出力世代を固定して扱う。
SCENARIO_DIRS = sorted(
    p for p in FIXTURES_DIR.iterdir()
    if p.is_dir() and p.name.startswith("rkb587_")
    and p.name != "rkb587_empty"
)

# XML Colour(RGB) → colors テーブルの color_id。実フィクスチャの
# sc08 から読み取ったマッピング（RB がインポート時に RGB→index に
# 変換する。DjmdContent.ColorID 側は既に index なので、ここでは
# その index を再現しているだけ）
COLOUR_TO_ID = {
    "0xFF0000": 2,   # Red
    "0x00FF00": 5,   # Green
    "0x0000FF": 7,   # Blue
    "0xFFFF00": 4,   # Yellow
    # 0xFF00FF (magenta) は RB5.8.7 では color_id=0（未マッピング）
}

# 実フィクスチャ側に存在しないトラック（シナリオ dir → filename 集合）。
# RB5.8.7 がエクスポートしない AIFF のみ。
EXPECTED_MISSING = {
    "rkb587_sc09_file_types": {"trk_00608.aiff"},
    "rkb587_all_scenarios": {"trk_00608.aiff"},
}

# 実フィクスチャとの比較から外すフィールド。
# Rekordbox が自前解析で書く値（本ツールは XML 値を書く）・
# 未対応の artwork・内部実装依存値。
IGNORED_TRACK_FIELDS = {
    "tempo", "duration", "bitrate", "sample_rate",
    "artwork_id", "analyze_date", "index_shift",
}


class XmlContent:
    """rekordbox.xml の TRACK 属性を DjmdContent 相当の属性名に写像する。

    ``_track_metadata()`` が読む属性名に合わせる。欠けている属性は
    getattr のデフォルトに任せる。
    """

    def __init__(self, el: ET.Element) -> None:
        a = el.attrib
        self.ID = a["TrackID"]
        self.Title = a.get("Name", "")
        self.ArtistName = a.get("Artist", "")
        self.AlbumName = a.get("Album", "")
        self.GenreName = a.get("Genre", "")
        self.KeyName = a.get("Tonality", "")
        self.Commnt = a.get("Comments", "")
        self.BPM = int(float(a.get("AverageBpm", "0")) * 100)
        self.Length = int(a.get("TotalTime", "0"))
        self.BitRate = int(a.get("BitRate", "0"))
        self.SampleRate = int(a.get("SampleRate", "44100"))
        self.FileSize = int(a.get("Size", "0"))
        self.TrackNo = int(a.get("TrackNumber", "0"))
        self.DiscNo = int(a.get("DiscNumber", "0"))
        self.ReleaseYear = int(a.get("Year", "0"))
        self.DateAdded = a.get("DateAdded", "")
        self.PlayCount = int(a.get("PlayCount", "0"))
        # DjmdContent.Rating は XML と同じ 0-255 スケールと仮定。
        # 実フィクスチャ（0-5 星）との差が出れば変換バグとして検出される
        self.Rating = int(a.get("Rating", "0"))
        self.ColorID = COLOUR_TO_ID.get(a.get("Colour", ""), 0)
        loc = urlparse(a.get("Location", ""))
        self.FolderPath = unquote(loc.path).lstrip("/")


class _AnlzDb:
    """analyze_path を生成させるため、存在しない ANLZ パスを返す。

    コピーは src が存在しないため静かにスキップされるが、PDB の
    analyze_path フィールドにはハッシュ済みパスが入る。
    """

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {"DAT": Path("/nonexistent"), "EXT": None, "2EX": None}


def _load_xml() -> ET.Element:
    return ET.parse(INPUT_XML).getroot()


def _xml_tracks(root: ET.Element) -> Dict[str, XmlContent]:
    return {
        t.attrib["TrackID"]: XmlContent(t)
        for t in root.find("COLLECTION")
    }


def _find_folder(root: ET.Element, name: str) -> Optional[ET.Element]:
    for node in root.iter("NODE"):
        if node.attrib.get("Type") == "0" and node.attrib.get("Name") == name:
            return node
    return None


def _build_node(el: ET.Element) -> DevicePdbNode:
    """XML の NODE（Type 0=folder / 1=playlist）を DevicePdbNode に変換。"""
    node = DevicePdbNode(
        el.attrib["Name"], is_folder=el.attrib.get("Type") == "0")
    if node.is_folder:
        for child in el.findall("NODE"):
            node.children.append(_build_node(child))
    else:
        for trk in el.findall("TRACK"):
            node.tracks.append(trk.attrib["Key"])
    return node


def _track_snapshot(db: Database) -> Dict[str, dict]:
    """トラック行をファイル名で引けるスナップショットにする。

    参照フィールドは名前に解決しておく（id は割り当て順序で変わるため）。
    タイトルはシナリオ内で重複し得る（sc08 の Rated Xstars）ので
    キーは filename（trk_NNNNN.*）を使う。
    """
    artists = {a.id: a.name for a in db.artists}
    albums = {a.id: a.name for a in db.albums}
    genres = {g.id: g.name for g in db.genres}
    keys = {k.id: k.name for k in db.keys}
    labels = {l.id: l.name for l in db.labels}
    snap: Dict[str, dict] = {}
    for t in db.tracks:
        snap[t.filename] = {
            "title": t.title,
            "filename": t.filename,
            "file_path": t.file_path,
            "comment": t.comment,
            "mix_name": t.mix_name,
            "release_date": t.release_date,
            "date_added": t.date_added,
            "analyze_path": t.analyze_path,
            "analyze_date": t.analyze_date,
            "bitmask": t.bitmask,
            "index_shift": t.index_shift,
            "sample_rate": t.sample_rate,
            "sample_depth": t.sample_depth,
            "file_size": t.file_size,
            "tempo": t.tempo,
            "duration": t.duration,
            "bitrate": t.bitrate,
            "track_number": t.track_number,
            "disc_number": t.disc_number,
            "play_count": t.play_count,
            "year": t.year,
            "rating": t.rating,
            "color_id": t.color_id,
            "artwork_id": t.artwork_id,
            "artist": artists.get(t.artist_id),
            "album": albums.get(t.album_id),
            "genre": genres.get(t.genre_id),
            "key": keys.get(t.key_id),
            "label": labels.get(t.label_id),
            "str_flags": t.strings[2:4],
            "str_kuvo": t.strings[6],
            "str_autoload": t.strings[7],
        }
    return snap


def _playlist_snapshot(db: Database) -> List[tuple]:
    """(folder_path, playlist_name, [entry_titles]) の一覧を返す。"""
    nodes = {n.id: n for n in db.playlist_tree}
    by_id = {t.id: t.title for t in db.tracks}
    entries: Dict[int, List[str]] = {}
    for e in sorted(
            db.playlist_entries,
            key=lambda e: (e.playlist_id, e.entry_index)):
        entries.setdefault(e.playlist_id, []).append(
            by_id.get(e.track_id, "?"))

    def folder_path(n: Any) -> str:
        parts = []
        while n.parent_id and n.parent_id in nodes:
            n = nodes[n.parent_id]
            parts.append(n.name)
        return "/".join(reversed(parts))

    out = []
    for n in db.playlist_tree:
        if not n.is_folder:
            out.append((folder_path(n), n.name, entries.get(n.id, [])))
    return sorted(out)


def _generate(scenario_dir: Path, tmp_path: Path,
              expected: Database) -> Database:
    """シナリオの XML サブツリーを PdbExporter に流して生成 PDB を返す。

    copy_map の dest には実フィクスチャの file_path を使い、
    PDB の file_path フィールドが突合できるようにする
    （レイアウト規則自体の検証ではなく行書き込みの検証）。
    """
    root = _load_xml()
    tracks = _xml_tracks(root)
    folder_name = scenario_dir.name[len("rkb587_"):]
    # フィクスチャ dir は小文字、XML のフォルダ名は大文字
    # (sc01_one_ascii ↔ SC01_one_ascii)
    scenario_names = json.loads(SCENARIOS_JSON.read_text())
    folder_name = next(
        (k for k in scenario_names if k.lower() == folder_name),
        folder_name)
    if folder_name == "all_scenarios":
        # 一括エクスポートは SCENARIOS フォルダ全体が対象。
        # フィクスチャには XML 外の要素（無題リスト等）も混じるので
        # プレイリスト比較側で除外する
        folder_el = _find_folder(root, "SCENARIOS")
    else:
        folder_el = _find_folder(root, folder_name)
    assert folder_el is not None, f"{folder_name} not in rekordbox.xml"
    tree = _build_node(folder_el)

    expected_paths = {t.filename: t.file_path for t in expected.tracks}
    expected_by_title = {t.title: t.file_path for t in expected.tracks}
    usb_root = tmp_path / "usb"
    content_map: Dict[str, Any] = {}
    copy_map: Dict[str, Path] = {}
    for key, content in tracks.items():
        basename = Path(content.FolderPath).name
        dest_rel = (
            expected_paths.get(basename)
            # 実機は同名ファイルを -1 等に退避させるので、ファイル名が
            # ずれている場合はタイトルで対応付ける（all_scenarios の
            # trk_00001-1.mp3）
            or expected_by_title.get(content.Title)
            or f"/Contents/{basename}")
        dest = usb_root / dest_rel.lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"audio")
        content_map[key] = content
        copy_map[content.FolderPath] = dest

    pdb_path = PdbExporter(_AnlzDb()).build(
        usb_root=usb_root,
        playlist_tree=[tree],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )
    return Database.from_file(pdb_path)


# ----- フィクスチャ健全性 ---------------------------------------------------

ALL_FIXTURES = sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir())


@pytest.mark.parametrize("fixture_dir", ALL_FIXTURES,
                         ids=lambda p: p.name)
def test_fixture_pdb_parses(fixture_dir: Path) -> None:
    """全フィクスチャの export.pdb が両パーサーで走査できる。"""
    pdb = fixture_dir / "PIONEER" / "rekordbox" / "export.pdb"
    counts = walk_pdb(pdb)
    assert counts, fixture_dir.name
    Database.from_file(pdb)


# ----- 本ツール出力との突合 -------------------------------------------------


@pytest.mark.parametrize("scenario_dir", SCENARIO_DIRS,
                         ids=lambda p: p.name)
def test_generated_matches_fixture(scenario_dir: Path,
                                   tmp_path: Path) -> None:
    """同じ入力から生成した export.pdb が実フィクスチャと
    トラック行・プレイリスト構造で一致する。"""
    expected = Database.from_file(
        scenario_dir / "PIONEER" / "rekordbox" / "export.pdb")
    generated = _generate(scenario_dir, tmp_path, expected)

    exp_snap = _track_snapshot(expected)
    gen_snap = _track_snapshot(generated)

    missing_titles = EXPECTED_MISSING.get(scenario_dir.name, set())
    # 実フィクスチャに無いトラック（AIFF）は本ツール側だけに現れてよい
    extra = set(gen_snap) - set(exp_snap)
    assert extra <= missing_titles, f"unexpected extra tracks: {extra}"
    assert set(exp_snap) <= set(gen_snap), (
        f"missing tracks: {set(exp_snap) - set(gen_snap)}")

    diffs = []
    for fname in exp_snap:
        e, g = exp_snap[fname], gen_snap[fname]
        for field in e:
            if field in IGNORED_TRACK_FIELDS:
                continue
            ev, gv = e[field], g[field]
            if field == "analyze_path":
                # 同一ハッシュ dir に複数トラックが来た場合、実機は
                # ANLZ0001.DAT 等の連番を付ける。本ツールは常に
                # ANLZ0000 なのでディレクトリ部分のみ比較する
                ev = ev.rsplit("/", 1)[0] if ev else ev
                gv = gv.rsplit("/", 1)[0] if gv else gv
            if ev != gv:
                diffs.append(
                    f"{fname}.{field}: fixture={e[field]!r} "
                    f"generated={g[field]!r}")
    assert not diffs, "field mismatches:\n" + "\n".join(diffs[:20])

    # プレイリスト構造（フォルダ階層・名前・エントリ順のタイトル列）
    exp_pl = _playlist_snapshot(expected)
    gen_pl = _playlist_snapshot(generated)
    # 実フィクスチャに無いトラック（AIFF）はエントリからも除く
    exp_titles = {t["title"] for t in exp_snap.values()}
    gen_pl = [
        (path, name, [t for t in titles if t in exp_titles])
        for path, name, titles in gen_pl
    ]
    if scenario_dir.name == "rkb587_all_scenarios":
        # XML 外で取り込まれた要素を除く（README「突合時に期待される差分」）
        extras = {
            ("", "無題のリスト", ()),
            ("無題のフォルダ/無題のフォルダ/無題のフォルダ",
             "無題のリスト", ()),
            ("SC01_one_ascii", "SC01 one_ascii",
             ("Plain ASCII Title",)),
        }
        exp_pl = [
            p for p in exp_pl
            if (p[0], p[1], tuple(p[2])) not in extras
        ]
    assert gen_pl == exp_pl, (
        f"playlist mismatch:\nfixture={exp_pl}\ngenerated={gen_pl}")


@pytest.mark.parametrize("scenario_dir", SCENARIO_DIRS,
                         ids=lambda p: p.name)
def test_fixture_anlz_dir_matches_hash(scenario_dir: Path) -> None:
    """実フィクスチャ内の全トラックで、file_path → USBANLZ ディレクトリ
    名が anlz_path_hash の計算結果と一致する。"""
    from rkbdb2xml.anlz import anlz_dir

    fixture_root = scenario_dir
    db = Database.from_file(
        fixture_root / "PIONEER" / "rekordbox" / "export.pdb")
    anlz_root = fixture_root / "PIONEER" / "USBANLZ"
    for t in db.tracks:
        expected_dir = anlz_root / anlz_dir(t.file_path)
        assert expected_dir.is_dir(), (
            f"{t.title!r}: {expected_dir} not found "
            f"(file_path={t.file_path!r})")
        # analyze_path フィールドも同じハッシュ dir を指している
        # （同一 dir に複数トラックが来ると実機は ANLZ0001 等の
        # 連番を付けるので、ファイル名部分は見ない）
        assert t.analyze_path.rsplit("/", 1)[0] == (
            f"/PIONEER/USBANLZ/{anlz_dir(t.file_path).as_posix()}")


def test_empty_fixture_layout() -> None:
    """空フィクスチャは export.pdb のみで tracks=0。"""
    db = Database.from_file(
        FIXTURES_DIR / "rkb587_empty" / "PIONEER" / "rekordbox"
        / "export.pdb")
    assert len(db.tracks) == 0

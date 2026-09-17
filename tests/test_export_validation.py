"""実機なしの CI 検証: 生成 USB エクスポートを独立パーサーで読む。

rekordbox-pdb（書き込みに使っている実装）以外の独立した実装で
生成物が読めることを保証する。Kaitai Struct パーサーは
Deep-Symmetry/crate-digger の ``rekordbox_pdb.ksy`` /
``rekordbox_anlz.ksy``（EPL-2.0 OR MPL-2.0 OR LGPL-3.0-only、
同プロジェクトが実機上のエクスポートを日々パースしている実績の
ある文法）から ``scripts/gen_kaitai_parsers.mjs`` で生成したもの。

fixture の rkb5_*.pdb / rkb5_anlz.dat は Rekordbox 5.8.6 が
実際に書き出した USB エクスポート（空 / 1曲 / 複数プレイリスト）。
"""

import importlib.util
import struct
from io import BytesIO
from pathlib import Path
from typing import Any, Dict

import pytest
from rekordbox_pdb import Database

from rkbdb2xml.anlz import anlz_dir, rewrite_anlz_path
from rkbdb2xml.pdb_export import DevicePdbNode, PdbExporter

pytest.importorskip("kaitaistruct")

from kaitaistruct import KaitaiStream  # noqa: E402


def _load_kaitai_module(name: str) -> Any:
    """tests/kaitai/<name>.py を sys.path を汚染せずにロードする。

    生成モジュール名がインストール済みの ``rekordbox_pdb`` パッケージと
    衝突するため、importlib で直接ファイルから読み込む。
    """
    path = Path(__file__).parent / "kaitai" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"kaitai_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RekordboxPdb = _load_kaitai_module("rekordbox_pdb").RekordboxPdb
RekordboxAnlz = _load_kaitai_module("rekordbox_anlz").RekordboxAnlz

DATA_DIR = Path(__file__).parent / "data"

REAL_EXPORTS = [
    DATA_DIR / "rkb5_empty_export.pdb",
    DATA_DIR / "rkb5_one_track_export.pdb",
    DATA_DIR / "rkb5_multi_playlist_export.pdb",
    DATA_DIR / "rkb6_empty_export.pdb",
    DATA_DIR / "rkb_one_song_export.pdb",
]

# Rekordbox がライブラリ内容に関わらず常に書く静的テーブル
# (colors / columns / sort / history)。実機はこれらが空だと
# データベースを拒否する (Issue #32, #36)。
STATIC_TABLE_ROWS = {6: 8, 16: 27, 17: 22, 18: 17, 19: 1}

PAGE_SIZE = 4096


def walk_pdb(path: Path) -> Dict[int, int]:
    """Kaitai パーサーで全テーブルのページチェーンを辿り、
    {テーブル番号: 存在フラグの立った行数} を返す。

    ページヘッダの magic・チェーン・行オフセット・各行ボディの
    パースまで行うので、構造が壊れていれば例外になる。
    """
    data = path.read_bytes()
    io = KaitaiStream(BytesIO(data))
    pdb = RekordboxPdb(False, io)
    counts: Dict[int, int] = {}
    for table in pdb.tables:
        ref = table.first_page
        rows = 0
        seen = set()
        while ref.index != 0xFFFFFFFF and ref.index not in seen:
            seen.add(ref.index)
            page = ref.body
            if page.is_data_page:
                for group in page.row_groups or []:
                    for row in group.rows:
                        if row.present:
                            _ = row.body
                            rows += 1
            if ref.index == table.last_page.index:
                break
            ref = page.next_page
        if rows:
            counts[int(table.type)] = rows
    return counts


class FakeDb:
    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {}


class FakeDbWithAnlz(FakeDb):
    """全トラックに実 Rekordbox 5.8.6 製の ANLZ fixture を紐付ける。"""

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {
            "DAT": DATA_DIR / "rkb5_anlz.dat",
            "EXT": None,
            "2EX": None,
        }


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


def build_export(usb_root: Path, db: Any = None) -> Path:
    """2トラック・フォルダ+プレイリスト構成の USB ツリーを生成する。"""
    contents = usb_root / "Contents"
    contents.mkdir(parents=True)
    dest_a = contents / "track_a.mp3"
    dest_b = contents / "track_b.mp3"
    dest_a.write_bytes(b"audio a")
    dest_b.write_bytes(b"audio b")

    c1 = FakeContent("1", "Track One", "/src/a.mp3")
    c2 = FakeContent("2", "Track Two", "/src/b.mp3")
    folder = DevicePdbNode("Root", is_folder=True)
    playlist = folder.add_playlist("Playlist")
    playlist.add_track("1")
    playlist.add_track("2")

    exporter = PdbExporter(db or FakeDb())
    return exporter.build(
        usb_root=usb_root,
        playlist_tree=[folder],
        content_map={"1": c1, "2": c2},
        copy_map={"/src/a.mp3": dest_a, "/src/b.mp3": dest_b},
        track_options={},
    )


# ----- Layer 1+2: 構造不変条件と往復パース ----------------------------------


def test_generated_export_tree_layout(tmp_path: Path) -> None:
    """CDJ がマウント時に探すディレクトリ構成が揃っている。"""
    pdb_path = build_export(tmp_path / "usb")
    assert pdb_path.name == "export.pdb"
    assert pdb_path.parent == tmp_path / "usb" / "PIONEER" / "rekordbox"
    assert (tmp_path / "usb" / "Contents").is_dir()


def test_generated_pdb_parses_with_kaitai(tmp_path: Path) -> None:
    """生成 PDB を独立 Kaitai 文法で全行走査できる。"""
    counts = walk_pdb(build_export(tmp_path / "usb"))
    assert counts[0] == 2  # tracks
    for table, nrows in STATIC_TABLE_ROWS.items():
        assert counts.get(table) == nrows, f"static table {table}"


def test_generated_pdb_header_invariants(tmp_path: Path) -> None:
    """page0 の sequence が全ページをカバーし unk10 は実機値。"""
    data = build_export(tmp_path / "usb").read_bytes()
    assert struct.unpack_from("<I", data, 0x10)[0] == 5
    seq = struct.unpack_from("<I", data, 0x14)[0]
    for p in range(1, len(data) // PAGE_SIZE):
        page_seq = struct.unpack_from("<I", data, p * PAGE_SIZE + 0x10)[0]
        assert seq > page_seq, f"page {p}"
    # empty_candidate は一意かつ実ページを指さない
    cands = set()
    for i in range(20):
        _typ, ec, first, last = struct.unpack_from(
            "<IIII", data, 0x1C + i * 16
        )
        assert ec not in cands
        cands.add(ec)
        assert first <= last
        assert last * PAGE_SIZE < len(data)


def test_generated_pdb_matches_real_export_tables(tmp_path: Path) -> None:
    """実 Rekordbox エクスポートと同じ静的テーブル構成を持つ。"""
    real = walk_pdb(DATA_DIR / "rkb5_one_track_export.pdb")
    generated = walk_pdb(build_export(tmp_path / "usb"))
    for table in STATIC_TABLE_ROWS:
        assert table in generated, f"missing static table {table}"
        assert table in real
        # colors/columns 等の行数は Rekordbox バージョンで変わるので
        # 実エクスポート側は「存在する」ことだけを確認する
    # 生成側の静的行数は埋め込み blob (6.8.7 由来) と一致する
    for table, nrows in STATIC_TABLE_ROWS.items():
        assert generated[table] == nrows


def test_generated_pdb_parses_with_rekordbox_pdb(tmp_path: Path) -> None:
    """書き込みライブラリ自身でも往復読み込みできる。"""
    db = Database.from_file(build_export(tmp_path / "usb"))
    assert len(db.tracks) == 2
    assert len(db.playlist_tree) == 2  # folder + playlist
    assert len(db.playlist_entries) == 2


# ----- golden fixture: 実エクスポート自体もパースできる ----------------------


@pytest.mark.parametrize("pdb_file", REAL_EXPORTS)
def test_real_exports_parse_with_kaitai(pdb_file: Path) -> None:
    """健全性チェック: 実 Rekordbox 製 PDB が同じ文法で読める。"""
    counts = walk_pdb(pdb_file)
    for table in STATIC_TABLE_ROWS:
        assert table in counts, f"{pdb_file.name}: missing table {table}"


@pytest.mark.parametrize("pdb_file", REAL_EXPORTS)
def test_real_exports_parse_with_rekordbox_pdb(pdb_file: Path) -> None:
    Database.from_file(pdb_file)


# ----- ANLZ -----------------------------------------------------------------


def test_real_anlz_parses_with_kaitai_and_pyrekordbox() -> None:
    """実 Rekordbox 製 ANLZ が両パーサーで読める（パーサー健全性）。"""
    from pyrekordbox.anlz import AnlzFile

    dat = DATA_DIR / "rkb5_anlz.dat"
    anlz = RekordboxAnlz(KaitaiStream(BytesIO(dat.read_bytes())))
    assert len(anlz.sections) > 0
    af = AnlzFile.parse_file(str(dat))
    assert af.get("PPTH")


def test_copied_anlz_parses_and_has_usb_path(tmp_path: Path) -> None:
    """エクスポートで書き換えた ANLZ が独立パーサーで読め、
    PPTH が USB 上の楽曲パスを指す。"""
    from pyrekordbox.anlz import AnlzFile

    usb_root = tmp_path / "usb"
    pdb_path = build_export(usb_root, db=FakeDbWithAnlz())
    track = Database.from_file(pdb_path).tracks[0]

    anlz_rel = Path(track.analyze_path.lstrip("/"))
    anlz_file = usb_root / anlz_rel
    assert anlz_file.exists()
    assert (
        anlz_rel.parent
        == Path("PIONEER") / "USBANLZ" / anlz_dir(track.file_path)
    )

    af = AnlzFile.parse_file(str(anlz_file))
    assert af.get("PPTH") == track.file_path

    # Kaitai 側でもタグ連鎖が最後まで辿れる
    RekordboxAnlz(KaitaiStream(BytesIO(anlz_file.read_bytes())))


def test_rewrite_anlz_path_real_fixture(tmp_path: Path) -> None:
    """実 ANLZ fixture の PPTH 書き換え結果が pyrekordbox で読める。"""
    from pyrekordbox.anlz import AnlzFile

    dst = tmp_path / "out.DAT"
    new_path = "/Contents/rewritten_track.mp3"
    assert rewrite_anlz_path(DATA_DIR / "rkb5_anlz.dat", dst, new_path)
    assert AnlzFile.parse_file(str(dst)).get("PPTH") == new_path

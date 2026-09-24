"""Tests for CDJ-compatible DeviceSQL export."""

import struct
import threading
from pathlib import Path
from typing import Any, Dict

import pytest

from rekordbox_pdb import Database

from rkbdb2xml.pdb_export import (
    PdbExporter,
    DevicePdbNode,
    DevicePdbXml,
    create_empty_pdb,
)


class FakeDb:
    """Minimal database stub for ANLZ path lookup."""

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {}


class FakeDbWithAnlz(FakeDb):
    """Database stub that reports a DAT analysis file for every track."""

    def get_anlz_paths(self, content: Any) -> Dict[str, Any]:
        return {
            "DAT": Path("/anlz/ANLZ0000.DAT"),
            "EXT": Path("/anlz/ANLZ0000.EXT"),
            "2EX": None,
        }


class FakeContent:
    """Minimal DjmdContent-like object for unit tests."""

    def __init__(self, cid: str, title: str, folder_path: str,
                 ext: str = ".mp3") -> None:
        self.ID = cid
        self.Title = title
        self.FolderPath = folder_path
        self.ext = ext
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


@pytest.fixture
def usb_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a USB root with a copied dummy audio file."""
    usb_root = tmp_path / "usb"
    contents = usb_root / "Contents"
    contents.mkdir(parents=True)
    dest = contents / "abc123.mp3"
    dest.write_bytes(b"dummy audio")
    return usb_root, contents, dest


def test_create_empty_pdb_is_valid() -> None:
    data = create_empty_pdb()
    assert len(data) == 41 * 4096

    # A valid empty PDB can be loaded and populated by PdbEditor.
    from rekordbox_pdb.edit import PdbEditor

    ed = PdbEditor(data)
    tid = ed.add_track(title="T", file_path="/Contents/t.mp3")
    assert tid == 1


STATIC_TABLES = (6, 16, 17, 18, 19)


def _index_page_body(data: bytes, table_index: int) -> bytes:
    """Return the index-page body (offset 0x28..) of table `table_index`."""
    page_off = (1 + 2 * table_index) * 4096
    return data[page_off + 0x28 : page_off + 4096]


def _table_entry(data: bytes, table_index: int) -> tuple:
    """Return (type, empty_candidate, first_page, last_page)."""
    return struct.unpack_from("<IIII", data, 0x1C + table_index * 16)


def _page_num_rows(data: bytes, page_index: int) -> int:
    off = page_index * 4096
    return data[off + 0x18] + 0x100 * (data[off + 0x19] & 1)


def test_create_empty_pdb_index_page_layout() -> None:
    """Index ページ本体が実機フォーマットと一致する（Issue #27, #32）。

    実機の export.pdb では index ページの heap は
    ``[page_index, 0x03FFFFFF]`` の後に 0x03FFFFFF の magic、
    num_entries=0、first_empty=0x1fff、そして 1004 個の
    0x1FFFFFF8 空エントリが続く。欠けると Rekordbox が
    デバイス読み込み時に落ちる可能性がある。

    テーブル 6,16-19（colors/columns 等の静的テーブル）は実エクスポート
    では常にデータページを持つため、index ページの first data page は
    sentinel ではなく実ページを指す。
    """
    data = create_empty_pdb()
    for i in range(20):
        body = _index_page_body(data, i)
        # 0x28: page_index, 0x2c: first data page or sentinel
        assert struct.unpack_from("<I", body, 0)[0] == 1 + 2 * i
        if i in STATIC_TABLES:
            assert struct.unpack_from("<I", body, 4)[0] == 2 + 2 * i
        else:
            assert struct.unpack_from("<I", body, 4)[0] == 0x03FFFFFF
        # 0x30: magic, always present in real exports
        assert struct.unpack_from("<I", body, 8)[0] == 0x03FFFFFF
        # 0x34: zeros; 0x38: num_entries; 0x3a: first_empty=0x1fff
        assert struct.unpack_from("<I", body, 0x0C)[0] == 0
        # Rekordbox 5.8.7 実測: history (t19) の index ページのみ
        # エントリを1件持つ (0x143)。他は全て空。
        num_entries = 1 if i == 19 else 0
        assert struct.unpack_from("<H", body, 0x10)[0] == num_entries
        assert struct.unpack_from("<H", body, 0x12)[0] == 0x1FFF
        # 0x3c..: index entries, rest of page is zeros
        for e in (0, 500, 1003):
            expected = 0x143 if (i == 19 and e == 0) else 0x1FFFFFF8
            assert (
                struct.unpack_from("<I", body, 0x14 + e * 4)[0]
                == expected
            )
        tail = body[0x14 + 1004 * 4 :]
        assert tail == bytes(len(tail))


def test_create_empty_pdb_layout_matches_real_export() -> None:
    """テーブル配置が実エクスポートの規則と一致する（Issue #32）。

    実ファイルではテーブル i の index ページは 1+2i、
    データページスロットは 2+2i に配置される。静的テーブル
    （6,16-19）は最初からデータページを持つ。
    """
    data = create_empty_pdb()
    assert len(data) == 41 * 4096
    # Rekordbox 5.8.7 の全14エクスポートフィクスチャが書き出す値
    assert struct.unpack_from("<I", data, 0x10)[0] == 1
    for i in range(20):
        typ, empty_cand, first, last = _table_entry(data, i)
        assert typ == i
        assert first == 1 + 2 * i
        if i in STATIC_TABLES:
            assert last == 2 + 2 * i
        else:
            assert last == first
            assert empty_cand == 2 + 2 * i
        # index ページヘッダ: 実エクスポートでは sequence=1, flags=0x64
        off = first * 4096
        assert data[off + 0x1B] == 0x64
        assert struct.unpack_from("<I", data, off + 0x08)[0] == i


def test_create_empty_pdb_static_tables_populated() -> None:
    """静的テーブル（6,16-19）に実エクスポート相当の行がある（Issue #32, #36）。

    実エクスポートでは colors(6)・columns(16)・unknown(17,18)・
    history(19) はライブラリ内容に関わらず常に行を持ち、
    空だと実機がデータベースを拒否する。
    """
    data = create_empty_pdb()
    # t19 (history) の num_rows はエクスポート毎に増える削除済み
    # スロットを含む。埋め込み blob は最も履歴の浅い
    # rkb587_sc01_one_ascii 由来 (num_rows=2)。
    expected = {6: 8, 16: 27, 17: 21, 18: 17, 19: 2}
    for i, nrows in expected.items():
        _typ, _ec, _first, last = _table_entry(data, i)
        assert _page_num_rows(data, last) == nrows, f"table {i}"


def test_create_empty_pdb_static_rows_match_real_export() -> None:
    """静的テーブルの行内容が実エクスポートと一致する（Issue #32）。

    columns テーブルの行は Rekordbox が書き出す固定の
    ブラウズカラム定義（"GENRE" 等）であり、ライブラリに依存しない。
    colors テーブルも同様に固定の8色（"Pink" 等）を持つ。
    """
    data = create_empty_pdb()
    _typ, _ec, _first, last = _table_entry(data, 16)
    page = data[last * 4096 : (last + 1) * 4096]
    assert "GENRE".encode("utf-16-le") in page
    assert "ARTIST".encode("utf-16-le") in page

    _typ, _ec, _first, last = _table_entry(data, 6)
    page = data[last * 4096 : (last + 1) * 4096]
    assert b"Pink" in page
    assert b"Purple" in page


def test_create_empty_pdb_static_pages_match_fixture() -> None:
    """埋め込み静的ページが実エクスポート fixture と一致する（Issue #32, #36）。

    ``data/pdb_static.bin`` は Rekordbox 5.8.7 が書き出した
    ``tests/data/usb_fixtures/rkb587_sc01_one_ascii`` のテーブル
    6,16-19 のページ（index+data）をそのまま抜き出したもの。
    編集・再生成で実機形式からずれていないかを fixture と
    突き合わせる。
    """
    fixture_path = (
        Path(__file__).parent / "data" / "usb_fixtures"
        / "rkb587_sc01_one_ascii" / "PIONEER" / "rekordbox"
        / "export.pdb"
    )
    if not fixture_path.is_file():
        pytest.skip("legacy RB5 fixture removed")
    fixture = fixture_path.read_bytes()
    data = create_empty_pdb()
    for i in STATIC_TABLES:
        index_page = 1 + 2 * i
        for p in (index_page, index_page + 1):
            assert (
                data[p * 4096 : (p + 1) * 4096]
                == fixture[p * 4096 : (p + 1) * 4096]
            ), f"table {i} page {p}"


def test_export_pdb_header_sequence_covers_all_pages(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """page0 の sequence は全ページの sequence を超える（実機が検証）。

    実機は ``header.sequence >= max(全ページの sequence) + 1`` を
    要求し、満たさないと "rekordbox database not found" になる
    （Issue #32）。
    """
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    data = pdb_path.read_bytes()
    seq = struct.unpack_from("<I", data, 0x14)[0]
    for p in range(1, len(data) // 4096):
        page_seq = struct.unpack_from("<I", data, p * 4096 + 0x10)[0]
        assert seq > page_seq, f"page {p} seq={page_seq} >= header={seq}"


def test_export_pdb_static_tables_survive_build(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """ビルド後も静的テーブル（16-19）の行が残る（Issue #32）。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    data = pdb_path.read_bytes()
    for i in STATIC_TABLES:
        _typ, _ec, _first, last = _table_entry(data, i)
        assert _first != last, f"table {i} lost its data page"
        assert _page_num_rows(data, last) >= 1, f"table {i} is empty"


def test_device_pdb_xml_records_tree() -> None:
    xml = DevicePdbXml()
    folder = xml._root_node.add_playlist_folder("Folder")
    playlist = folder.add_playlist("Playlist")
    playlist.add_track("1")
    playlist.add_track("2")

    assert len(xml._root_node.children) == 1
    assert xml._root_node.children[0].is_folder
    assert len(xml._root_node.children[0].children) == 1
    assert xml._root_node.children[0].children[0].tracks == ["1", "2"]


def test_pdb_exporter_builds_export(usb_tree: tuple[Path, Path, Path]) -> None:
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}
    track_options: Dict[str, Dict[str, Any]] = {
        "1": {"roman": False, "bpm": True},
    }

    playlist = DevicePdbNode("My Playlist", is_folder=False)
    playlist.add_track("1")

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options=track_options,
    )

    assert pdb_path == usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert pdb_path.exists()

    db = Database.from_file(pdb_path)
    assert len(db.tracks) == 1
    track = db.tracks[0]
    assert track.title == "128 Test Track"  # BPM prefix applied
    assert track.file_path == "/Contents/abc123.mp3"
    artists = {a.id: a.name for a in db.artists}
    albums = {a.id: a.name for a in db.albums}
    assert artists[track.artist_id] == "Artist"
    assert albums[track.album_id] == "Album"

    assert len(db.playlist_tree) == 1
    assert db.playlist_tree[0].name == "My Playlist"
    assert len(db.playlist_entries) == 1
    assert db.playlist_entries[0].track_id == track.id


def test_pdb_exporter_honors_romanization(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    usb_root, _contents, dest = usb_tree
    content = FakeContent("2", "テスト", "/source/test.mp3")
    content_map: Dict[str, Any] = {"2": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}
    track_options: Dict[str, Dict[str, Any]] = {
        "2": {"roman": True, "bpm": False}
    }

    playlist = DevicePdbNode("Playlist", is_folder=False)
    playlist.add_track("2")

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options=track_options,
    )

    db = Database.from_file(pdb_path)
    assert len(db.tracks) == 1
    track = db.tracks[0]
    assert track.title.isascii()


def test_pdb_exporter_nested_folders(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    usb_root, _contents, dest = usb_tree
    content = FakeContent("3", "Nested", "/source/test.mp3")
    content_map: Dict[str, Any] = {"3": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    folder = DevicePdbNode("Root", is_folder=True)
    sub = folder.add_playlist_folder("Sub")
    pl = sub.add_playlist("Tracks")
    pl.add_track("3")

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[folder],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    nodes = {n.id: n for n in db.playlist_tree}
    assert len(nodes) == 3
    root = next(n for n in db.playlist_tree if n.name == "Root")
    sub_node = next(n for n in db.playlist_tree if n.name == "Sub")
    pl_node = next(n for n in db.playlist_tree if n.name == "Tracks")
    assert sub_node.parent_id == root.id
    assert pl_node.parent_id == sub_node.id


def test_pdb_exporter_sets_analyze_path_when_anlz_exists(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """ANLZ を持つトラックは analyze_path に USBANLZ の実パスが入る。

    実機の export.pdb では ``/PIONEER/USBANLZ/P<ppp>/<hash>/ANLZ0000.DAT``
    が書かれており、プレイヤーはこのフィールドで解析データを引く。
    空のままだと BPM/グリッド/波形が出ない（退行防止）。
    """
    from rkbdb2xml.anlz import anlz_dir

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    playlist = _playlist_with("1")

    exporter = PdbExporter(FakeDbWithAnlz())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    track = db.tracks[0]
    expected = (
        f"/PIONEER/USBANLZ/"
        f"{anlz_dir(track.file_path).as_posix()}/ANLZ0000.DAT"
    )
    assert track.analyze_path == expected


def test_pdb_exporter_empty_analyze_path_without_anlz(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """ANLZ がないトラックは analyze_path が空のまま。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    assert db.tracks[0].analyze_path == ""


def test_pdb_exporter_skips_missing_copy(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    usb_root, _contents, _dest = usb_tree
    content = FakeContent("4", "Missing", "/source/missing.mp3")
    content_map: Dict[str, Any] = {"4": content}
    copy_map: Dict[str, Path] = {}

    playlist = DevicePdbNode("Pl", is_folder=False)
    playlist.add_track("4")

    exporter = PdbExporter(FakeDb())
    with pytest.raises(RuntimeError) as exc_info:
        exporter.build(
            usb_root=usb_root,
            playlist_tree=[playlist],
            content_map=content_map,
            copy_map=copy_map,
            track_options={},
        )
    assert "USB Contents へのコピーが見つかりません" in str(exc_info.value)


def test_pdb_exporter_entry_index_contiguous_after_skip(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """コピー失敗トラックがあっても entry_index は連続する（Issue #27）。

    実機の export.pdb では、エクスポートに失敗したトラックは
    プレイリストから落とされ entry_index が詰め直される。
    欠番が残ると Rekordbox のデバイス読み込みが落ちる可能性がある。
    """
    usb_root, contents, dest = usb_tree
    dest2 = contents / "def456.mp3"
    dest2.write_bytes(b"dummy audio 2")
    c1 = FakeContent("1", "First", "/source/a.mp3")
    c2 = FakeContent("2", "Missing", "/source/missing.mp3")
    c3 = FakeContent("3", "Last", "/source/b.mp3")
    content_map: Dict[str, Any] = {"1": c1, "2": c2, "3": c3}
    copy_map: Dict[str, Path] = {
        "/source/a.mp3": dest,
        "/source/b.mp3": dest2,
    }

    playlist = DevicePdbNode("Pl", is_folder=False)
    for cid in ("1", "2", "3"):
        playlist.add_track(cid)

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[playlist],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    db = Database.from_file(pdb_path)
    entries = sorted(
        db.playlist_entries, key=lambda e: e.entry_index)
    assert len(entries) == 2
    assert [e.entry_index for e in entries] == [1, 2]
    titles = {t.id: t.title for t in db.tracks}
    assert [titles[e.track_id] for e in entries] == ["First", "Last"]


def test_pdb_exporter_index_page_layout_after_build(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """データページ割り当て後も index ページの magic が残る（Issue #27）。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    data = pdb_path.read_bytes()
    body = _index_page_body(data, 0)  # TRACKS テーブル
    assert struct.unpack_from("<I", body, 4)[0] != 0x03FFFFFF  # 先頭データページ
    assert struct.unpack_from("<I", body, 8)[0] == 0x03FFFFFF  # magic 保持
    assert struct.unpack_from("<H", body, 0x12)[0] == 0x1FFF   # first_empty


# ----- キャンセルと原子的書き込み（Issue #14） -----------------------------------------


def _playlist_with(
    content_id: str, name: str = "My Playlist"
) -> DevicePdbNode:
    playlist = DevicePdbNode(name, is_folder=False)
    playlist.add_track(content_id)
    return playlist


def test_pdb_exporter_pre_cancelled_writes_nothing(
    usb_tree: tuple[Path, Path, Path],
) -> None:
    """キャンセル済みなら export.pdb も一時ファイルも書かない。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    cancel_event = threading.Event()
    cancel_event.set()

    exporter = PdbExporter(FakeDb())
    result = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
        cancel_event=cancel_event,
    )

    assert result is None
    pdb_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert not pdb_path.exists()
    assert not pdb_path.with_name("export.pdb.tmp").exists()


def test_pdb_exporter_cancelled_mid_build_writes_nothing(
    usb_tree: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """構築途中のキャンセルでは、未完成 PDB を USB に残さない。"""
    from rekordbox_pdb.edit import PdbEditor

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    cancel_event = threading.Event()
    orig_create_playlist = PdbEditor.create_playlist

    def cancelling_create(*a, **kw):
        cancel_event.set()
        return orig_create_playlist(*a, **kw)

    monkeypatch.setattr(PdbEditor, "create_playlist", cancelling_create)

    exporter = PdbExporter(FakeDb())
    result = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
        cancel_event=cancel_event,
    )

    assert result is None
    pdb_path = usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert not pdb_path.exists()
    assert not pdb_path.with_name("export.pdb.tmp").exists()


def test_pdb_exporter_writes_atomically_leaves_no_tmp(
    usb_tree: tuple[Path, Path, Path]
) -> None:
    """正常時: export.pdb だけが残り、一時ファイルは残らない。"""
    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )

    assert pdb_path == usb_root / "PIONEER" / "rekordbox" / "export.pdb"
    assert pdb_path.exists()
    assert not pdb_path.with_name("export.pdb.tmp").exists()
    db = Database.from_file(pdb_path)  # 読める = 完全なファイル
    assert len(db.tracks) == 1


def test_pdb_exporter_failed_save_keeps_previous_pdb(
    usb_tree: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """書き込み失敗時: 一時ファイルを削除し、既存の export.pdb は無傷のまま。"""
    from rekordbox_pdb.edit import PdbEditor

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
    )
    old_bytes = pdb_path.read_bytes()

    def failing_save(self, path: Path) -> None:
        Path(path).write_bytes(b"garbage")  # 途中で壊れた tmp を残す
        raise OSError("disk full")

    monkeypatch.setattr(PdbEditor, "save", failing_save)

    with pytest.raises(OSError):
        exporter.build(
            usb_root=usb_root,
            playlist_tree=[_playlist_with("1")],
            content_map=content_map,
            copy_map=copy_map,
            track_options={},
        )

    assert pdb_path.read_bytes() == old_bytes, "旧 export.pdb は上書きされない"
    assert not pdb_path.with_name("export.pdb.tmp").exists()


def test_pdb_exporter_cancelled_during_anlz_keeps_complete_pdb(
    usb_tree: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ANLZ コピー中のキャンセル: export.pdb は完成済みのまま残る。"""
    import rkbdb2xml.pdb_export as pdb_mod

    usb_root, _contents, dest = usb_tree
    content = FakeContent("1", "Test Track", "/source/test.mp3")
    content_map: Dict[str, Any] = {"1": content}
    copy_map: Dict[str, Path] = {"/source/test.mp3": dest}

    cancel_event = threading.Event()

    def set_cancel(*a, **kw):
        cancel_event.set()

    monkeypatch.setattr(pdb_mod.anlz, "copy_anlz_for_content", set_cancel)

    exporter = PdbExporter(FakeDb())
    pdb_path = exporter.build(
        usb_root=usb_root,
        playlist_tree=[_playlist_with("1")],
        content_map=content_map,
        copy_map=copy_map,
        track_options={},
        cancel_event=cancel_event,
    )

    assert pdb_path is not None
    db = Database.from_file(pdb_path)
    assert len(db.tracks) == 1  # PDB は書き換え済みで完全
    assert not pdb_path.with_name("export.pdb.tmp").exists()

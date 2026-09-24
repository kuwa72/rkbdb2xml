"""Rekordbox 製 USB エクスポートと rkbdb2xml 製エクスポートを突合する。

2つの USB ルート (PIONEER/ + Contents/ を持つディレクトリ) を比較し、
構造・内容の差分を報告する。バイト一致が期待できるもの (設定ファイル) と
構造一致が期待できるもの (export.pdb の行・ツリー) を分けて検証する。

Usage:
    python scripts/compare_usb_exports.py <rekordbox_dir> <generated_dir>
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rekordbox_pdb import Database  # noqa: E402

from rkbdb2xml.anlz import anlz_dir, existing_anlz_matches  # noqa: E402

SETTINGS_FILES = (
    "DEVSETTING.DAT", "MYSETTING.DAT", "MYSETTING2.DAT",
    "DJMMYSETTING.DAT", "djprofile.nxs",
)

# Rekordbox が書くが rkbdb2xml が意図的に生成しないもの:
# - djprofile.nxs   : Kuvo DJ プロフィール (個人情報を含む)
# - exportExt.pdb   : Device Library Plus (CDJ-3000+ 向け)
# - Artwork/        : アートワーク画像 (CDJ-350/800 では未使用)
KNOWN_ABSENT = ("djprofile.nxs",)
KNOWN_ABSENT_REKORDBOX_DIR = ("exportExt.pdb",)

results = []

# known 差分の3分類（Issue #55）。FAIL には数えず [INFO] で分類を付ける。
KNOWN_CATEGORIES = {
    "input": "入力由来",
    "generation": "Rekordbox世代／履歴由来",
    "unimplemented": "rkbdb2xml未実装",
}


def report(ok: bool, label: str, detail: str = "",
           category: str | None = None) -> None:
    if category is not None and category not in KNOWN_CATEGORIES:
        raise ValueError(f"unknown known-diff category: {category!r}")
    if category and not ok:
        print(f"[INFO] {KNOWN_CATEGORIES[category]}: {label} -- {detail}")
        return
    results.append(ok)
    mark = "OK " if ok else "FAIL"
    line = f"[{mark}] {label}"
    if detail:
        line += f" -- {detail}"
    print(line)


def _name_map(coll):
    """id -> name 解決用 (artists/albums/genres/keys/labels)。"""
    out = {}
    for row in coll:
        rid = getattr(row, "id", None)
        name = getattr(row, "name", None)
        out[rid] = name
    return out


def track_sig(t, db):
    """バージョン間で安定なトラック属性のタプルを返す。"""
    artists = _name_map(db.artists)
    albums = _name_map(db.albums)
    genres = _name_map(db.genres)
    keys = _name_map(db.keys)
    labels = _name_map(db.labels)
    return (
        t.title,
        Path(t.filename).suffix.lower() if t.filename else "",
        artists.get(t.artist_id),
        albums.get(t.album_id),
        genres.get(t.genre_id),
        keys.get(t.key_id),
        labels.get(t.label_id),
        t.duration, t.bitrate, t.sample_rate, t.sample_depth,
        t.file_size, t.tempo, t.rating, t.track_number,
        t.disc_number, t.year, t.comment,
    )


def tree_sig(node, children_map):
    """(name, is_folder, sorted children sigs) の再帰シグネチャ。"""
    return (
        node.name,
        node.is_folder,
        tuple(sorted(
            tree_sig(c, children_map) for c in children_map.get(node.id, [])
        )),
    )


def _page_row_count(page: bytes) -> int:
    """Read the 11-bit ``num_rows`` field from a table page header.

    The page header stores 13 bits of ``num_row_offsets`` followed by 11
    bits of ``num_rows`` in little-endian bit order at offset 0x18 (the
    same layout the kaitai parser reads). Page 0 is the database header
    page and must not be passed here.
    """
    if len(page) < 0x1B:
        return 0
    word = int.from_bytes(page[0x18:0x1B], "little")
    return (word >> 13) & 0x7FF


def raw_pdb_diff(ref_pdb: Path, gen_pdb: Path) -> dict[str, int]:
    """Return page/byte/row counts for a raw ``export.pdb`` comparison."""
    ref = ref_pdb.read_bytes()
    gen = gen_pdb.read_bytes()
    page_size = 4096
    ref_pages = len(ref) // page_size
    gen_pages = len(gen) // page_size
    common_pages = min(ref_pages, gen_pages)
    differing_pages = 0
    differing_bytes = 0
    differing_header_pages = 0
    for page in range(common_pages):
        ref_page = ref[page * page_size:(page + 1) * page_size]
        gen_page = gen[page * page_size:(page + 1) * page_size]
        count = sum(a != b for a, b in zip(ref_page, gen_page))
        if count:
            differing_pages += 1
            differing_bytes += count
        if ref_page[:0x28] != gen_page[:0x28]:
            differing_header_pages += 1
    # page 0 is the database header, not a table page
    ref_rows = sum(
        _page_row_count(ref[p * page_size:(p + 1) * page_size])
        for p in range(1, ref_pages)
    )
    gen_rows = sum(
        _page_row_count(gen[p * page_size:(p + 1) * page_size])
        for p in range(1, gen_pages)
    )
    differing_row_pages = sum(
        _page_row_count(ref[p * page_size:(p + 1) * page_size])
        != _page_row_count(gen[p * page_size:(p + 1) * page_size])
        for p in range(1, common_pages)
    )
    return {
        "ref_bytes": len(ref),
        "gen_bytes": len(gen),
        "ref_pages": ref_pages,
        "gen_pages": gen_pages,
        "common_pages": common_pages,
        "differing_pages": differing_pages,
        "differing_header_pages": differing_header_pages,
        "differing_bytes": differing_bytes,
        "ref_rows": ref_rows,
        "gen_rows": gen_rows,
        "differing_row_pages": differing_row_pages,
    }


def check_paths(root: Path, db, tag: str) -> None:
    """Contents 相対パス・USBANLZ 配置・PPTH をまとめて検証する。

    1つの USB ルートについて次の4点を順に報告する（Issue #55）。

    1. ``Contents/`` の相対パス集合と DB の ``file_path`` 集合の一致
    2. ``analyze_path`` が指す ANLZ ファイルの実在
    3. ``analyze_path`` のディレクトリが ``anlz_dir(file_path)`` の
       ハッシュと一致すること
    4. ANLZ の ``PPTH`` が ``file_path`` と一致すること

    照合基準は ``ANLZ0000.DAT`` 固定ではなく DB の ``analyze_path``。
    実機 Rekordbox はハッシュ衝突時に ``ANLZ0001`` 等の連番を振るため。
    PPTH は pyrekordbox 無しでも読める ``existing_anlz_matches`` で
    見るので、CI でも検証が走る。
    """
    contents = root / "Contents"
    on_disk = set()
    if contents.exists():
        on_disk = {
            "/Contents/" + p.relative_to(contents).as_posix()
            for p in contents.rglob("*")
            if p.is_file()
        }
    declared = {t.file_path for t in db.tracks}
    report(
        on_disk == declared,
        f"{tag} Contents relative paths match DB file_path",
        f"missing={sorted(declared - on_disk)[:3]} "
        f"orphan={sorted(on_disk - declared)[:3]}",
    )

    missing = bad_dir = ppth_bad = 0
    examples = []
    for t in db.tracks:
        if not t.analyze_path:
            continue
        expected_dir = f"/PIONEER/USBANLZ/{anlz_dir(t.file_path).as_posix()}"
        if t.analyze_path.rsplit("/", 1)[0] != expected_dir:
            bad_dir += 1
        f = root / t.analyze_path.lstrip("/")
        if not f.is_file():
            missing += 1
            continue
        if not existing_anlz_matches(f, t.file_path):
            ppth_bad += 1
            examples.append(t.analyze_path)
    report(missing == 0, f"{tag} ANLZ files present",
           f"missing={missing}")
    report(bad_dir == 0, f"{tag} USBANLZ dir == hash(file_path)",
           f"bad={bad_dir}")
    report(ppth_bad == 0, f"{tag} ANLZ PPTH == track file_path",
           f"bad={ppth_bad} {examples[:3]}")


def compare_pdb(ref_root: Path, gen_root: Path) -> None:
    ref_pdb = ref_root / "PIONEER" / "rekordbox" / "export.pdb"
    gen_pdb = gen_root / "PIONEER" / "rekordbox" / "export.pdb"
    report(ref_pdb.exists(), "ref export.pdb exists", str(ref_pdb))
    report(gen_pdb.exists(), "gen export.pdb exists", str(gen_pdb))
    if not (ref_pdb.exists() and gen_pdb.exists()):
        return

    ref = Database.from_file(ref_pdb)
    gen = Database.from_file(gen_pdb)
    raw = raw_pdb_diff(ref_pdb, gen_pdb)
    print(
        "[INFO] raw PDB: "
        f"ref_pages={raw['ref_pages']} gen_pages={raw['gen_pages']} "
        f"diff_pages={raw['differing_pages']} "
        f"diff_header_pages={raw['differing_header_pages']} "
        f"diff_bytes={raw['differing_bytes']} "
        f"ref_rows={raw['ref_rows']} gen_rows={raw['gen_rows']} "
        f"diff_row_pages={raw['differing_row_pages']}"
    )

    # --- tracks ---------------------------------------------------------
    ref_sigs = Counter(track_sig(t, ref) for t in ref.tracks)
    gen_sigs = Counter(track_sig(t, gen) for t in gen.tracks)
    report(
        len(ref.tracks) == len(gen.tracks),
        "track count",
        f"ref={len(ref.tracks)} gen={len(gen.tracks)}",
    )
    missing = ref_sigs - gen_sigs
    extra = gen_sigs - ref_sigs
    report(
        not missing and not extra,
        "track attribute multiset",
        f"missing={sum(missing.values())} extra={sum(extra.values())}",
    )
    for sig, n in list(missing.items())[:5]:
        print(f"    missing x{n}: {sig[:2]}")
    for sig, n in list(extra.items())[:5]:
        print(f"    extra   x{n}: {sig[:2]}")

    # --- playlist tree --------------------------------------------------
    def children_map(db):
        m = {}
        for n in db.playlist_tree:
            m.setdefault(n.parent_id, []).append(n)
        return m

    ref_map, gen_map = children_map(ref), children_map(gen)
    ref_tree = sorted(
        tree_sig(n, ref_map) for n in ref_map.get(0, []))
    gen_tree = sorted(
        tree_sig(n, gen_map) for n in gen_map.get(0, []))
    # Rekordbox のプレイリスト単体エクスポートは祖先フォルダを含めず
    # フラットになる。リーフのプレイリスト名集合が一致するなら
    # それは設計上の既知差分。
    known_flat = False
    if ref_tree != gen_tree:
        ref_leaves = {n.name for n in ref.playlist_tree if not n.is_folder}
        gen_leaves = {n.name for n in gen.playlist_tree if not n.is_folder}
        known_flat = ref_leaves == gen_leaves
    report(
        ref_tree == gen_tree,
        "playlist tree structure",
        f"ref nodes={len(ref.playlist_tree)} gen nodes={len(gen.playlist_tree)}",
        # Rekordbox のプレイリスト単体エクスポートは祖先フォルダを書かず
        # フラットになる。リーフ集合が一致するなら設計上の既知差分。
        category="generation" if known_flat else None,
    )
    if ref_tree != gen_tree:
        print(f"    ref: {ref_tree}")
        print(f"    gen: {gen_tree}")

    # --- playlist entries -------------------------------------------------
    # playlist_id -> ordered track sig list で比較 (木構造が一致前提)
    def entry_map(db):
        id2track = {t.id: t for t in db.tracks}
        m = {}
        for e in sorted(db.playlist_entries, key=lambda e: e.entry_index):
            t = id2track.get(e.track_id)
            m.setdefault(e.playlist_id, []).append(
                (t.title, Path(t.filename).suffix.lower()) if t else None)
        return m

    def pl_path_map(db):
        """playlist node id -> 階層パス"""
        nodes = {n.id: n for n in db.playlist_tree}
        paths = {}
        for n in db.playlist_tree:
            parts = [n.name]
            pid = n.parent_id
            while pid in nodes:
                parts.append(nodes[pid].name)
                pid = nodes[pid].parent_id
            paths[n.id] = "/".join(reversed(parts))
        return paths

    ref_entries = entry_map(ref)
    gen_entries = entry_map(gen)
    ref_paths = pl_path_map(ref)
    gen_paths = pl_path_map(gen)
    ref_by_path = {ref_paths[pid]: v for pid, v in ref_entries.items()}
    gen_by_path = {gen_paths[pid]: v for pid, v in gen_entries.items()}
    # Rekordbox の単一プレイリストエクスポートは祖先フォルダを書かず
    # フラットになるが、rkbdb2xml は祖先を保持する。その場合は
    # パス末尾 (プレイリスト名) で突合する。
    if set(ref_by_path) != set(gen_by_path):
        ref_by_path = {p.rsplit("/", 1)[-1]: v
                       for p, v in ref_by_path.items()}
        gen_by_path = {p.rsplit("/", 1)[-1]: v
                       for p, v in gen_by_path.items()}
    all_pl = set(ref_by_path) | set(gen_by_path)
    bad = []
    for p in sorted(all_pl):
        if ref_by_path.get(p) != gen_by_path.get(p):
            bad.append(p)
    report(
        not bad,
        "playlist entries (ordered track lists)",
        f"playlists with diffs: {bad[:10]}",
    )
    for p in bad[:5]:
        r = ref_by_path.get(p)
        g = gen_by_path.get(p)
        print(f"    {p}:")
        print(f"      ref({len(r) if r else '-'}): {r[:8] if r else r}")
        print(f"      gen({len(g) if g else '-'}): {g[:8] if g else g}")

    # --- static / aux tables --------------------------------------------
    for attr in ("colors", "columns", "artwork", "labels",
                 "artists", "albums", "genres", "keys"):
        r = len(getattr(ref, attr, []))
        g = len(getattr(gen, attr, []))
        report(r == g, f"table {attr}", f"ref={r} gen={g}",
               # アートワーク行は未実装 (CDJ-350/800 は表示しない)
               category="unimplemented" if attr == "artwork" else None)

    # --- Contents / ANLZ の配置と PPTH ------------------------------------
    check_paths(ref_root, ref, "ref")
    check_paths(gen_root, gen, "gen")

    # USBANLZ file count
    def count_anlz(root):
        d = root / "PIONEER" / "USBANLZ"
        return sum(1 for _ in d.rglob("*") if _.is_file()) if d.exists() else 0
    report(count_anlz(ref_root) == count_anlz(gen_root),
           "USBANLZ file count",
           f"ref={count_anlz(ref_root)} gen={count_anlz(gen_root)}")


def compare_contents(ref_root: Path, gen_root: Path) -> None:
    def files(root):
        d = root / "Contents"
        if not d.exists():
            return []
        return [p for p in d.rglob("*") if p.is_file()]

    rf, gf = files(ref_root), files(gen_root)
    report(len(rf) == len(gf), "Contents file count",
           f"ref={len(rf)} gen={len(gf)}")
    ref_ext = Counter(p.suffix.lower() for p in rf)
    gen_ext = Counter(p.suffix.lower() for p in gf)
    report(ref_ext == gen_ext, "Contents extension distribution",
           f"ref={dict(ref_ext)} gen={dict(gen_ext)}")


def compare_settings(ref_root: Path, gen_root: Path) -> None:
    for name in SETTINGS_FILES:
        r = ref_root / "PIONEER" / name
        g = gen_root / "PIONEER" / name
        if not r.exists() and not g.exists():
            continue
        report(
            r.exists() and g.exists(),
            f"PIONEER/{name} presence",
            f"ref={r.exists()} gen={g.exists()}",
            # djprofile.nxs は個人情報を含むため意図的に生成しない
            category="unimplemented" if name in KNOWN_ABSENT else None,
        )
        if r.exists() and g.exists():
            report(
                r.read_bytes() == g.read_bytes(),
                f"PIONEER/{name} bytes",
                f"ref={r.stat().st_size}B gen={g.stat().st_size}B",
                # ユーザー設定値 + Rekordbox バージョン文字列を含むため
                # インストール毎にバイトが変わる。構造サイズのみ一致前提。
                category=(
                    "generation" if name != "DJMMYSETTING.DAT" else None
                ),
            )
    # Rekordbox が rekordbox/ 以下に書く付属ファイル
    for name in KNOWN_ABSENT_REKORDBOX_DIR:
        r = ref_root / "PIONEER" / "rekordbox" / name
        g = gen_root / "PIONEER" / "rekordbox" / name
        if r.exists() or g.exists():
            report(
                r.exists() and g.exists(),
                f"PIONEER/rekordbox/{name} presence",
                f"ref={r.exists()} gen={g.exists()}",
                # exportExt.pdb (Device Library Plus) は未実装
                category="unimplemented",
            )
    # Artwork ディレクトリ (画像行と同じく未実装)
    r = ref_root / "PIONEER" / "Artwork"
    g = gen_root / "PIONEER" / "Artwork"
    if r.exists() or g.exists():
        report(r.exists() and g.exists(), "PIONEER/Artwork presence",
               f"ref={r.exists()} gen={g.exists()}",
               category="unimplemented")


def main() -> None:
    ref_root = Path(sys.argv[1])
    gen_root = Path(sys.argv[2])
    print(f"ref: {ref_root}\ngen: {gen_root}\n")
    compare_settings(ref_root, gen_root)
    compare_contents(ref_root, gen_root)
    compare_pdb(ref_root, gen_root)
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()

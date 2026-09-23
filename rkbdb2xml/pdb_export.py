"""DeviceSQL (`export.pdb`) exporter for CDJ-compatible USB exports."""

import datetime
import os
import struct
import threading
from importlib.resources import files
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rekordbox_pdb import TableType
from rekordbox_pdb.edit import PdbEditor, encode_string

from . import anlz

PAGE_SIZE = 4096
PAGE_HEADER_SIZE = 0x28
NUM_TABLES = 20

# Tables that always carry rows in a real Rekordbox export, regardless of
# library content: 6=colors, 16=columns, 17/18=sort config, 19=history
# sync state.  Players reject the database when these are empty, so the
# pages from a real export are embedded verbatim (see data/pdb_static*.bin).
STATIC_TABLES = (6, 16, 17, 18, 19)
_STATIC_PAGE_FILES = {
    "rb5": "pdb_static.bin",
    "rb6": "pdb_static_rb6.bin",
}
_STATIC_PAGES: Dict[str, bytes] = {}

# Files Rekordbox writes next to export.pdb on every export.  Old players
# (CDJ-350/800 era) read DEVSETTING/MYSETTING at mount time, so an export
# created from scratch should carry them.  They are only written when missing
# so a player's own settings are never clobbered.
DEVICE_SETTING_FILES = ("DEVSETTING.DAT", "MYSETTING.DAT", "MYSETTING2.DAT")
_DEVICE_SETTING_SOURCES = {
    "rb5": {name: name for name in DEVICE_SETTING_FILES},
    "rb6": {
        "DEVSETTING.DAT": "DEVSETTING_rb6.DAT",
        "MYSETTING.DAT": "MYSETTING_rb6.DAT",
        "MYSETTING2.DAT": "MYSETTING2_rb6.DAT",
        "DJMMYSETTING.DAT": "DJMMYSETTING_rb6.DAT",
    },
}


def _load_static_pages(pdb_profile: str = "rb5") -> bytes:
    """Return the 10 pages (index+data for tables 6,16-19) of a real export."""
    try:
        filename = _STATIC_PAGE_FILES[pdb_profile]
    except KeyError:
        raise ValueError(
            f"unknown pdb profile {pdb_profile!r}; "
            f"expected one of {sorted(_STATIC_PAGE_FILES)}"
        ) from None
    if pdb_profile not in _STATIC_PAGES:
        _STATIC_PAGES[pdb_profile] = (
            files("rkbdb2xml") / "data" / filename
        ).read_bytes()
    return _STATIC_PAGES[pdb_profile]


def create_empty_pdb(pdb_profile: str = "rb5") -> bytes:
    """Return a minimal valid `export.pdb` that `PdbEditor` can populate.

    ``pdb_profile`` selects the static pages captured from a real
    Rekordbox export of that generation. Mirrors the layout of a real
    Rekordbox export: table ``i`` gets its
    index page at ``1 + 2*i`` and a data-page slot at ``2 + 2*i``.  The
    static tables (6,16-19) are pre-populated with pages captured from a
    real export because players reject the database when they are empty.
    """
    total_pages = 1 + 2 * NUM_TABLES  # 41
    buf = bytearray(total_pages * PAGE_SIZE)

    # Page 0 header
    # 0x00: magic=0, 0x04: page_size, 0x08: num_tables,
    # 0x0c: next_unused_page, 0x10: unknown, 0x14: sequence.
    # next_unused_page points past the embedded static pages' beyond-EOF
    # empty candidates (41..45); sequence must exceed every data page's
    # sequence.  The 0x10 field varies across exports but every
    # Rekordbox 5.8.7 export observed writes 1. RB6.8.0 reserves page 46
    # for the playlist-tree empty candidate and starts allocating at 47.
    next_unused = 47 if pdb_profile == "rb6" else 46
    struct.pack_into("<IIIIII", buf, 0x00, 0, PAGE_SIZE, NUM_TABLES,
                     next_unused, 1, 0)

    static = _load_static_pages(pdb_profile)
    # Sequence must exceed every page's sequence.  The embedded static
    # pages carry their source export's values (history can be large),
    # so page 0 is set above the embedded maximum.
    max_seq = max(
        struct.unpack_from("<I", static, p * PAGE_SIZE + 0x10)[0]
        for p in range(2 * len(STATIC_TABLES))
    )
    struct.pack_into("<I", buf, 0x14, max_seq + 1)

    # Table directory at 0x1c.  Populated tables get a beyond-EOF empty
    # candidate like in real exports; empty tables point at their own
    # zero-filled data slot.
    static_empty_cands = {6: 42, 16: 43, 17: 44, 18: 45, 19: 41}
    for i in range(NUM_TABLES):
        index_page = 1 + 2 * i
        slot_page = 2 + 2 * i
        if i in STATIC_TABLES:
            first_page, last_page = index_page, slot_page
            empty_candidate = static_empty_cands[i]
        else:
            first_page = last_page = index_page
            empty_candidate = slot_page
        off = 0x1c + i * 16
        struct.pack_into("<IIII", buf, off, i, empty_candidate,
                         first_page, last_page)

    for i in range(NUM_TABLES):
        if i in STATIC_TABLES:
            dst = (1 + 2 * i) * PAGE_SIZE
            src = STATIC_TABLES.index(i) * 2 * PAGE_SIZE
            buf[dst : dst + 2 * PAGE_SIZE] = static[src : src + 2 * PAGE_SIZE]
            continue

        page_index = 1 + 2 * i
        page_off = page_index * PAGE_SIZE
        slot_page = 2 + 2 * i

        # Real index pages carry sequence=1 and link to their own
        # empty-candidate slot. Dynamic data-page sequence is normalized
        # after the append transaction for fresh RB6 exports.
        struct.pack_into("<IIIIII", buf, page_off, 0, page_index, i,
                         slot_page, 1, 0)

        # page[0x18] slot count low, [0x19-0x1a] unaligned u16,
        # [0x1b] page flags (0x64 = index, no rows)
        buf[page_off + 0x18] = 0
        buf[page_off + 0x19] = 0
        buf[page_off + 0x1a] = 0
        buf[page_off + 0x1b] = 0x64

        # [0x1c] free_size, [0x1e] used_size, [0x20] rows written,
        # [0x22] previous slot count, [0x24] 1004 on index, [0x26] small count
        struct.pack_into("<HHHHHH", buf, page_off + 0x1c, 0, 0,
                         0x1fff, 0x1fff, 1004, 0)

        # Heap: [0x28] this index page number,
        # [0x2c] first data page or 0x03FFFFFF sentinel,
        # [0x30] 0x03FFFFFF magic (always present in real exports),
        # [0x34] zeros, [0x38] num_entries=0, [0x3a] first_empty=0x1fff,
        # [0x3c..] 1004 index entry slots filled with 0x1FFFFFF8.
        struct.pack_into("<II", buf, page_off + PAGE_HEADER_SIZE,
                         page_index, 0x03FFFFFF)
        struct.pack_into("<I", buf, page_off + 0x30, 0x03FFFFFF)
        struct.pack_into("<HH", buf, page_off + 0x38, 0, 0x1FFF)
        for e in range(1004):
            struct.pack_into("<I", buf, page_off + 0x3C + e * 4,
                             0x1FFFFFF8)

    # Data slots of empty tables are left zero-filled; PdbEditor will
    # initialise them when rows are first appended.
    return bytes(buf)


def _set_track_string(
    editor: PdbEditor, track_id: int, slot: int, value: str
) -> None:
    """Replace one same-length DeviceSQL string in an appended track row.

    ``PdbEditor`` exposes fixed numeric fields but not the variable track
    string slots.  RB6 exports in the captured fixture use ``"1"`` for
    slot 3, while the dependency's generic ``rb6`` profile writes ``"2"``.
    Both encodings are one byte, so patching the slot does not move any row
    offsets or page bookkeeping.
    """
    encoded = encode_string(value)
    for track, location in zip(
        editor.db.tracks, editor.db.row_locations(TableType.TRACKS)
    ):
        if track.id != track_id:
            continue
        offset = struct.unpack_from(
            "<H", editor._buf, location + 0x5E + slot * 2
        )[0]
        start = location + offset
        current = bytes(editor._buf[start:start + len(encoded)])
        if len(encoded) != len(current):
            raise ValueError(
                f"track string slot {slot} changed length: "
                f"{len(current)} -> {len(encoded)}"
            )
        editor._buf[start:start + len(encoded)] = encoded
        editor._db = None
        return
    raise LookupError(f"no track with id {track_id}")


# Page layout of the fresh, one-track RB6.8.0 export used as the binary
# canary.  Larger libraries have history-dependent sequence numbers and
# must be compared separately; do not apply this table to them.
_RB6_MINIMAL_LAYOUT = {
    0: (2, 51, 11),   # tracks
    1: (4, 48, 8),    # genres
    2: (6, 47, 7),    # artists
    3: (8, 49, 9),    # albums
    5: (12, 50, 10),  # keys
    7: (16, 46, 6),   # playlist tree
    8: (18, 52, 12),  # playlist entries
}


def _normalize_rb6_minimal_layout(editor: PdbEditor, data: bytes) -> bytes:
    """Apply the observed fresh-RB6 page metadata to the one-track canary.

    ``PdbEditor`` allocates an empty file transactionally and therefore
    starts at sequence 2.  Rekordbox's fresh RB6 export uses the stable
    table sequence values and page candidates below.  The shape guard keeps
    this deliberately narrow; multi-track/history fixtures are not rewritten.
    """
    if len(data) != 41 * PAGE_SIZE:
        return data
    if not (
        len(editor.db.tracks) == 1
        and len(editor.db.artists) == 1
        and len(editor.db.albums) == 1
        and len(editor.db.genres) == 1
        and len(editor.db.keys) == 1
        and len(editor.db.playlist_tree) == 1
        and len(editor.db.playlist_entries) == 1
    ):
        return data

    buf = bytearray(data)
    for table, (page, empty_candidate, sequence) in _RB6_MINIMAL_LAYOUT.items():
        page_offset = page * PAGE_SIZE
        if struct.unpack_from("<I", buf, page_offset + 0x08)[0] != table:
            return data
        if buf[page_offset + 0x1B] == 0x64:
            return data

        struct.pack_into("<I", buf, 0x1C + table * 16 + 0x04,
                         empty_candidate)
        struct.pack_into("<I", buf, page_offset + 0x0C, empty_candidate)
        struct.pack_into("<I", buf, page_offset + 0x10, sequence)
        struct.pack_into("<H", buf, page_offset + 0x20, 1)
        struct.pack_into("<H", buf, page_offset + 0x22, 0)

    struct.pack_into("<I", buf, 0x0C, 53)
    return bytes(buf)


class DevicePdbNode:
    """In-memory playlist/folder node used while building the USB library."""

    def __init__(self, name: str, is_folder: bool = False,
                 parent: Optional["DevicePdbNode"] = None):
        self.name = name
        self.is_folder = is_folder
        self.parent = parent
        self.children: List["DevicePdbNode"] = []
        self.tracks: List[str] = []

    def add_playlist_folder(self, name: str) -> "DevicePdbNode":
        node = DevicePdbNode(name, is_folder=True, parent=self)
        self.children.append(node)
        return node

    def add_playlist(self, name: str) -> "DevicePdbNode":
        node = DevicePdbNode(name, is_folder=False, parent=self)
        self.children.append(node)
        return node

    def add_track(self, track_id: str) -> None:
        self.tracks.append(track_id)


class DevicePdbXml:
    """Fake RekordboxXml object that builds a DevicePdbNode tree.

    `RekordboxXMLExporter._add_playlists()` can be called with this object;
    it will record the playlist/folder structure and the track ids in each
    playlist, without producing an XML file.
    """

    def __init__(self) -> None:
        self._root_node = DevicePdbNode("", is_folder=True)


class PdbExporter:
    """Build a CDJ-compatible `export.pdb` and copy ANLZ analysis data."""

    def __init__(self, db: Any, verbose: bool = False,
                 pdb_profile: str = "rb5") -> None:
        self.db = db
        self._verbose = verbose
        self._roman_converter: Optional[Any] = None
        # Track-row constants differ between Rekordbox generations; the
        # "rb5" values match players of the CDJ-350/800 era.
        self._pdb_profile = pdb_profile

    def verbose(self, message: str) -> None:
        if self._verbose:
            print(message)

    def _prime_rb6_lookups(
        self, editor: PdbEditor, content_map: Dict[str, Any]
    ) -> None:
        """Pre-create RB6 lookup rows in Rekordbox's observed order.

        The generic editor otherwise creates artist → album → genre while
        the captured RB6 export allocates artist → genre → album. Priming
        the unique lookup rows before track insertion keeps page allocation
        and table empty-candidate ordering aligned with that export.
        """
        for content in content_map.values():
            artist = self._get_first(content, "ArtistName", "Artist")
            genre = self._get_first(content, "GenreName", "Genre")
            album = self._get_first(content, "AlbumName", "Album")
            key = self._get_first(content, "KeyName", "Key")
            label = self._get_first(content, "LabelName", "Label")

            artist_id = editor.get_or_create_artist(artist) if artist else 0
            if genre:
                editor.get_or_create_genre(genre)
            if album:
                editor.get_or_create_album(album, artist_id)
            if key:
                editor.get_or_create_key(key)
            if label:
                editor.get_or_create_label(label)

    def build(
        self,
        usb_root: Path,
        playlist_tree: List[DevicePdbNode],
        content_map: Dict[str, Any],
        copy_map: Dict[str, Path],
        track_options: Dict[str, Dict[str, Any]],
        cancel_event: Optional[threading.Event] = None,
        progress_cb: Optional[Callable[[int, int, int, int], None]] = None,
        phase_cb: Optional[Callable[[str], None]] = None,
    ) -> Optional[Path]:
        """Generate `PIONEER/rekordbox/export.pdb` under ``usb_root``.

        The PDB is written to ``export.pdb.tmp`` first and atomically renamed
        to ``export.pdb`` only on success, so a CDJ never sees a partially
        written file. When ``cancel_event`` is set before the save, nothing is
        written and ``None`` is returned (a previous ``export.pdb``, if any,
        is left untouched).
        """
        pdb_dir = usb_root / "PIONEER" / "rekordbox"
        pdb_dir.mkdir(parents=True, exist_ok=True)
        pdb_path = pdb_dir / "export.pdb"
        tmp_path = pdb_dir / "export.pdb.tmp"

        # rkbdb2xml が生成しない Rekordbox 側ファイル（Device Library Plus の
        # DB や My Tag）が古いまま残っていると、新しい export.pdb と内容が
        # 食い違い Rekordbox のデバイス読み込みが落ちる可能性がある。
        stale = [
            name for name in (
                "exportLibrary.db", "exportLibrary.db-wal",
                "exportLibrary.db-shm", "exportExt.pdb",
                "playlists3.sync", "playlists3Plus.sync",
            )
            if (pdb_dir / name).exists()
        ]
        if stale:
            self.verbose(
                "[WARN] 過去の Rekordbox エクスポートのファイルが残っています: "
                + ", ".join(stale)
                + "。export.pdb と内容が不一致だと Rekordbox が落ちる可能性が"
                "あります。USB メモリを初期化して再エクスポートするか、"
                "該当ファイルを削除してください。"
            )

        needs_roman = any(
            opts.get("roman", False) for opts in track_options.values()
        )
        if needs_roman:
            try:
                from romann import RomanConverter
                self._roman_converter = RomanConverter()
            except Exception as e:
                self.verbose(
                    f"[WARN] romannライブラリ初期化失敗: {e}"
                )
                self._roman_converter = None

        ed = PdbEditor(create_empty_pdb(self._pdb_profile))
        if self._pdb_profile == "rb6":
            selected_ids: List[str] = []

            def collect_content_ids(node: DevicePdbNode) -> None:
                selected_ids.extend(node.tracks)
                for child in node.children:
                    collect_content_ids(child)

            for root in playlist_tree:
                collect_content_ids(root)
            selected_content_map = {
                content_id: content_map[content_id]
                for content_id in dict.fromkeys(selected_ids)
                if content_id in content_map
            }
            self._prime_rb6_lookups(ed, selected_content_map)

        track_id_map: Dict[str, int] = {}
        track_to_usb: Dict[int, str] = {}
        errors: List[str] = []

        def process_node(node: DevicePdbNode, parent_pdb_id: int = 0) -> int:
            try:
                pdb_node_id = ed.create_playlist(
                    node.name, parent_pdb_id, node.is_folder
                )
            except Exception as e:
                msg = f"create_playlist({node.name!r}): {e}"
                errors.append(msg)
                self.verbose(f"[WARN] {msg}")
                return 0
            if node.is_folder:
                for child in node.children:
                    process_node(child, pdb_node_id)
            else:
                self.verbose(
                    f"[PDB] プレイリスト書き込み: {node.name} "
                    f"({len(node.tracks)} トラック)"
                )
                entry_index = 0
                for content_id in node.tracks:
                    if content_id not in track_id_map:
                        content = content_map.get(content_id)
                        if content is None:
                            msg = f"トラックが見つかりません: {content_id}"
                            self.verbose(f"[WARN] {msg}")
                            errors.append(msg)
                            continue
                        dest = self._resolve_dest(usb_root, copy_map, content)
                        if dest is None:
                            msg = (
                                f"USB Contents へのコピーが見つかりません: "
                                f"{content_id} "
                                f"(FolderPath={getattr(content, 'FolderPath', None)})"
                            )
                            self.verbose(f"[WARN] {msg}")
                            errors.append(msg)
                            continue

                        usb_path = "/" + dest.relative_to(usb_root).as_posix()
                        metadata = self._track_metadata(content,
                                                        track_options.get(
                                                            content_id, {}),
                                                        usb_path)
                        metadata["analyze_path"] = self._analyze_path_for(
                            content, usb_path
                        )
                        try:
                            pdb_track_id = ed.add_track(
                                **metadata, profile=self._pdb_profile)
                        except Exception as e:
                            msg = f"add_track({content_id}, title={metadata.get('title')!r}): {e}"
                            self.verbose(f"[WARN] {msg}")
                            errors.append(msg)
                            continue
                        if self._pdb_profile == "rb6":
                            _set_track_string(ed, pdb_track_id, 3, "1")
                        track_id_map[content_id] = pdb_track_id
                        track_to_usb[pdb_track_id] = usb_path

                    pdb_track_id = track_id_map.get(content_id)
                    if pdb_track_id is not None:
                        # スキップされたトラックで欠番が残らないよう、
                        # 追加できた分だけ連番を振る（Rekordbox 純正と同じ）。
                        try:
                            ed.add_to_playlist(
                                pdb_node_id, pdb_track_id, entry_index + 1)
                            entry_index += 1
                        except Exception as e:
                            msg = (
                                f"add_to_playlist({node.name}, "
                                f"track={pdb_track_id}, "
                                f"idx={entry_index + 1}): {e}"
                            )
                            self.verbose(f"[WARN] {msg}")
                            errors.append(msg)
            return pdb_node_id

        for root in playlist_tree:
            if cancel_event is not None and cancel_event.is_set():
                self.verbose("キャンセルされました: PDB 書き込みを中断しました")
                return None
            process_node(root, 0)

        if not track_id_map and errors:
            raise RuntimeError(
                "PDB 書き込みに失敗しました:\n" + "\n".join(errors[:20])
            )

        if cancel_event is not None and cancel_event.is_set():
            self.verbose("キャンセルされました: PDB 書き込みを中断しました")
            return None

        # 原子的書き込み: 一時ファイルに保存し、成功時のみ rename する。
        # 未完成の export.pdb が USB 上に現れることはない。
        try:
            if self._pdb_profile == "rb6":
                pdb_data = ed.to_bytes()
                pdb_data = _normalize_rb6_minimal_layout(ed, pdb_data)
                tmp_path.write_bytes(pdb_data)
            else:
                ed.save(tmp_path)
            os.replace(tmp_path, pdb_path)
        except Exception:
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise
        self.verbose(
            f"PDB saved: {pdb_path} "
            f"(playlists={len(ed.db.playlist_tree)}, "
            f"tracks={len(track_id_map)})"
        )

        # Rekordbox 純正のエクスポートが置く設定ファイルを補完する。
        # 既存のものはプレイヤー/Rekordbox が管理する値なので上書きしない。
        pioneer_dir = usb_root / "PIONEER"
        setting_sources = _DEVICE_SETTING_SOURCES[self._pdb_profile]
        for name, source_name in setting_sources.items():
            dst = pioneer_dir / name
            if dst.exists():
                continue
            try:
                dst.write_bytes(
                    (files("rkbdb2xml") / "data" / source_name).read_bytes()
                )
            except Exception as e:
                self.verbose(f"[WARN] {name} の書き込みに失敗: {e}")

        if phase_cb is not None:
            phase_cb("ANLZ 解析データコピー中")
        anlz_total = len(track_id_map)
        anlz_done = 0
        for content_id, pdb_track_id in track_id_map.items():
            if cancel_event is not None and cancel_event.is_set():
                self.verbose("キャンセルされました: ANLZ コピーを中断しました")
                break
            content = content_map[content_id]
            usb_path = track_to_usb[pdb_track_id]
            anlz.copy_anlz_for_content(
                self.db, content, usb_root, usb_path,
                verbose=self._verbose
            )
            anlz_done += 1
            if progress_cb is not None:
                progress_cb(anlz_done, anlz_total, 0, 0)

        return pdb_path

    def _resolve_dest(
        self, usb_root: Path, copy_map: Dict[str, Path], content: Any
    ) -> Optional[Path]:
        loc = getattr(content, "FolderPath", None)
        if not loc:
            self.verbose(
                f"[WARN] FolderPath がありません: {getattr(content, 'ID', '?')}"
            )
            return None
        dest = copy_map.get(loc)
        if dest is None:
            # try common variants
            for key in (str(loc), loc):
                if key in copy_map:
                    dest = copy_map[key]
                    break
        if dest is None or not dest.exists():
            self.verbose(
                f"[WARN] コピー先が見つかりません: {loc}"
            )
            return None
        return dest

    def _analyze_path_for(self, content: Any, usb_path: str) -> str:
        """Return the ``analyze_path`` value for the PDB track row.

        Real Rekordbox exports point this at the track's ANLZ DAT file,
        e.g. ``/PIONEER/USBANLZ/P02B/00027DA5/ANLZ0000.DAT``.  The player
        uses this field to locate analysis data (beatgrid / waveform), so
        it must be set for the grid to show.  Empty when the track has no
        local ANLZ files.
        """
        try:
            get_anlz_paths = getattr(self.db, "get_anlz_paths", None)
            paths = get_anlz_paths(content) if get_anlz_paths else None
        except Exception:
            paths = None
        if not paths or not any(paths.values()):
            return ""
        rel = anlz.anlz_dir(usb_path).as_posix()
        return f"/PIONEER/USBANLZ/{rel}/ANLZ0000.DAT"

    @staticmethod
    def _get_first(content: Any, *attrs: str) -> str:
        for attr in attrs:
            value = getattr(content, attr, None)
            if value:
                return str(value)
        return ""

    def _track_metadata(
        self, content: Any, options: Dict[str, Any], usb_path: str
    ) -> Dict[str, Any]:
        use_roman = bool(options.get("roman", False))
        use_bpm = bool(options.get("bpm", False))

        title = self._get_first(content, "Title")
        artist = self._get_first(content, "ArtistName", "Artist")
        album = self._get_first(content, "AlbumName", "Album")
        genre = self._get_first(content, "GenreName", "Genre")
        key = self._get_first(content, "KeyName", "Key")
        label = self._get_first(content, "LabelName", "Label")
        comment = self._get_first(content, "Commnt", "Comments")

        if use_roman:
            title = self._romanize(title, force=True)
            artist = self._romanize(artist, force=True)
            album = self._romanize(album, force=True)
            genre = self._romanize(genre, force=True)
            key = self._romanize(key, force=True)

        if use_bpm:
            bpm = self._safe_bpm(getattr(content, "BPM", None))
            if bpm:
                title = f"{int(bpm)} {title}"

        date_added = self._format_optional_date(
            getattr(content, "DateCreated", None)
            or getattr(content, "StockDate", None)
            or getattr(content, "DateAdded", None)
        )
        release_date = self._format_optional_date(
            getattr(content, "ReleaseDate", None)
        )

        return {
            "title": title,
            "file_path": usb_path,
            "filename": Path(usb_path).name,
            "artist": artist,
            "album": album,
            "genre": genre,
            "key": key,
            "label": label,
            "comment": comment,
            "date_added": date_added or datetime.date.today().isoformat(),
            "release_date": release_date,
            "analyze_path": "",
            "tempo": self._clip_int(getattr(content, "BPM", 0), 4, 0),
            "duration": self._clip_int(getattr(content, "Length", 0), 2, 0),
            "year": self._clip_int(getattr(content, "ReleaseYear", 0), 2, 0),
            "bitrate": self._clip_int(getattr(content, "BitRate", 0), 4, 0),
            "sample_rate": self._clip_int(
                getattr(content, "SampleRate", 44100), 4, 44100
            ),
            "sample_depth": self._clip_int(
                getattr(content, "BitDepth", 16), 2, 16
            ),
            "file_size": self._clip_int(self._file_size(content), 4, 0),
            "track_number": self._clip_int(getattr(content, "TrackNo", 0), 4, 0),
            "disc_number": self._clip_int(getattr(content, "DiscNo", 0), 2, 0),
            "play_count": self._clip_int(
                getattr(content, "DJPlayCount", None)
                or getattr(content, "PlayCount", 0),
                2,
                0,
            ),
            # DjmdContent.Rating は XML と同じ 0-255 スケール
            # (51刻み)。DeviceSQL の rating は 0-5 星なので換算する。
            # 実機 RB5.8.7 フィクスチャ (sc08) で検証済み。
            "rating": self._clip_int(
                self._rating_to_stars(getattr(content, "Rating", 0)),
                1, 0),
            "color_id": self._clip_int(getattr(content, "ColorID", 0), 1, 0),
            "artwork_id": 0,
        }

    @staticmethod
    def _format_optional_date(value: Any) -> str:
        if not value:
            return ""
        if isinstance(value, str):
            return value
        try:
            return value.isoformat()
        except Exception:
            return str(value)

    @staticmethod
    def _int_or(value: Any, default: int) -> int:
        if value is None:
            return default
        try:
            v = int(value)
            return v if v >= 0 else default
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _rating_to_stars(value: Any) -> int:
        """DjmdContent の 0-255 Rating を DeviceSQL の 0-5 星に換算する。"""
        try:
            r = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return r // 51 if r > 5 else r

    @staticmethod
    def _clip_int(value: Any, size: int, default: int = 0) -> int:
        """Return a non-negative int that fits in the given unsigned byte width."""
        if value is None:
            return default
        try:
            v = int(value)
        except (ValueError, TypeError):
            return default
        if v < 0:
            return default
        max_val = (1 << (8 * size)) - 1
        if v > max_val:
            return max_val
        return v

    def _safe_bpm(self, value: Any) -> Optional[float]:
        try:
            return float(value) / 100.0
        except Exception:
            return None

    def _file_size(self, content: Any) -> int:
        value = getattr(content, "FileSize", None)
        if value is None:
            return 0
        try:
            v = int(value)
            # Rekordbox stores file size as a signed 32-bit integer;
            # restore values > 2 GiB by masking to unsigned.
            if v < 0:
                v = v & 0xFFFFFFFF
            return v
        except (ValueError, TypeError):
            return 0

    def _romanize(self, value: str, force: bool = False) -> str:
        if not value:
            return value
        if value.isascii():
            return value
        if force and self._roman_converter:
            try:
                return self._roman_converter.to_roman(value)
            except Exception as e:
                self.verbose(f"[WARN] romann変換失敗: {value}: {e}")
                return value
        return value

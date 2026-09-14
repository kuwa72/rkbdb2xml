"""DeviceSQL (`export.pdb`) exporter for CDJ-compatible USB exports."""

import datetime
import os
import struct
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rekordbox_pdb.edit import PdbEditor

from . import anlz

PAGE_SIZE = 4096
PAGE_HEADER_SIZE = 0x28
NUM_TABLES = 20


def create_empty_pdb() -> bytes:
    """Return a minimal valid empty `export.pdb` that `PdbEditor` can populate.

    The file contains a page-0 table directory and one index page per table,
    plus pre-reserved empty-candidate data pages.  This mirrors the layout
    observed in real Rekordbox exports and is sufficient for `PdbEditor` to
    allocate data pages and append rows.
    """
    num_index_pages = NUM_TABLES
    num_empty_pages = NUM_TABLES
    total_pages = 1 + num_index_pages + num_empty_pages  # 41
    buf = bytearray(total_pages * PAGE_SIZE)

    # Page 0 header
    # 0x00: magic=0, 0x04: page_size, 0x08: num_tables,
    # 0x0c: next_unused_page, 0x10: unknown=1, 0x14: sequence=1
    struct.pack_into("<IIIIII", buf, 0x00, 0, PAGE_SIZE, NUM_TABLES,
                     total_pages, 1, 0)
    struct.pack_into("<I", buf, 0x14, 1)

    # Table directory at 0x1c
    for i in range(NUM_TABLES):
        table_type = i
        first_page = 1 + i
        last_page = first_page
        empty_candidate = 1 + NUM_TABLES + i
        off = 0x1c + i * 16
        struct.pack_into("<IIII", buf, off, table_type, empty_candidate,
                         first_page, last_page)

    # Index pages for each table
    for i in range(NUM_TABLES):
        page_index = 1 + i
        page_off = page_index * PAGE_SIZE
        empty_candidate = 1 + NUM_TABLES + i

        struct.pack_into("<IIIIII", buf, page_off, 0, page_index, i,
                         empty_candidate, 0, 0)

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

        # Heap: [0x28] this index page number, [0x2c] 0x03FFFFFF sentinel
        struct.pack_into("<II", buf, page_off + PAGE_HEADER_SIZE,
                         page_index, 0x03FFFFFF)

    # empty-candidate pages (21..40) are left zero-filled; PdbEditor will
    # initialise them when rows are first appended.
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

    def __init__(self, db: Any, verbose: bool = False) -> None:
        self.db = db
        self._verbose = verbose
        self._roman_converter: Optional[Any] = None

    def verbose(self, message: str) -> None:
        if self._verbose:
            print(message)

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

        ed = PdbEditor(create_empty_pdb())

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
                for idx, content_id in enumerate(node.tracks, start=1):
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
                            pdb_track_id = ed.add_track(**metadata)
                        except Exception as e:
                            msg = f"add_track({content_id}, title={metadata.get('title')!r}): {e}"
                            self.verbose(f"[WARN] {msg}")
                            errors.append(msg)
                            continue
                        track_id_map[content_id] = pdb_track_id
                        track_to_usb[pdb_track_id] = usb_path

                    pdb_track_id = track_id_map.get(content_id)
                    if pdb_track_id is not None:
                        try:
                            ed.add_to_playlist(pdb_node_id, pdb_track_id, idx)
                        except Exception as e:
                            msg = (
                                f"add_to_playlist({node.name}, "
                                f"track={pdb_track_id}, idx={idx}): {e}"
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
            "rating": self._clip_int(getattr(content, "Rating", 0), 1, 0),
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

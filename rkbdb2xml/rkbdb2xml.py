"""
Main functionality for converting Rekordbox DB to XML.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple, Any
import urllib.parse
import urllib.request
import hashlib
import mutagen
from mutagen.id3 import ID3, TIT2, TPE1, TALB
from mutagen.mp4 import MP4

import pyrekordbox
from pyrekordbox.rbxml import RekordboxXml
from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase, DjmdPlaylist
from pyrekordbox.config import get_config, KeyExtractor, get_pioneer_install_dir
from lxml import etree
import psutil
import shutil

REKORDBOX_VERSION = "6.8.0"
DEFAULT_XML_FILENAME = "rekordbox.xml"

class RekordboxXMLExporter:
    """
    Export Rekordbox database to XML format similar to Rekordbox XML export.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        db_key: Optional[str] = None,
        use_verbose: bool = False,
        use_roman: bool = False,
        use_bpm: bool = False,
        orderby: str = "default",
        playlist_specs: Optional[List[str]] = None,
        playlist_options: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """
        Initialize the exporter with the path to the Rekordbox database.

        Args:
            playlist_options: Per-playlist options dict mapping playlist path
                to {"roman": bool, "bpm": bool, "orderby": str}.
                When provided, these override the global roman/bpm/orderby
                settings for matched playlists.
        """
        self._verbose = use_verbose
        self._use_roman = use_roman
        self._use_bpm = use_bpm
        self._orderby = orderby
        # Playlist selection specs parsed from CLI
        self._playlist_specs = playlist_specs
        # Per-playlist options (path -> {roman, bpm, orderby})
        self._playlist_options = playlist_options or {}
        # Per-track options resolved during playlist processing
        # track_id -> {roman, bpm}
        self._track_options: Dict[Any, Dict[str, Any]] = {}
        self._roman_converter = None
        needs_roman = use_roman or any(
            opts.get("roman", False) for opts in self._playlist_options.values()
        )
        if needs_roman:
            try:
                from romann import RomanConverter
                self._roman_converter = RomanConverter()
            except Exception as e:
                print("[WARN] romannライブラリの初期化に失敗しました。ローマ字変換は無効化されます。", e)
                self._roman_converter = None
        self._check_rekordbox_running()
        self._connect_to_database(db_path, db_key)

    def verbose(self, message: str) -> None:
        if self._verbose:
            print(message)

    def _connect_to_database(self, db_path: Optional[str], db_key: Optional[str]):
        """
        Connect to the Rekordbox database, handling key download if necessary.
        """
        try:
            self.db = RekordboxDatabase(db_path, db_key)
        except Exception:
            key = self._download_rekordbox_key()
            self.db = RekordboxDatabase(key=key)

    def _check_rekordbox_running(self):
        """
        Check if Rekordbox is currently running and warn the user if it is.
        """
        for proc in psutil.process_iter(["name"]):
            if "rekordbox" in proc.info["name"].lower():
                return True
        return False

    def _download_rekordbox_key(self) -> Optional[str]:
        """
        Download the Rekordbox database key using pyrekordbox internal API.
        Returns:
            The downloaded key if successful, None otherwise
        """
        config = get_config("rekordbox6")
        if config and "dp" in config and config["dp"]:
            return config["dp"]

        # キャッシュがなければKeyExtractorで取得
        pioneer_install_dir = get_pioneer_install_dir()
        extractor = KeyExtractor(str(pioneer_install_dir))
        return extractor.run()

    def generate_xml(self, path: str) -> None:
        """
        Generate XML file from the Rekordbox database.

        Args:
            path: Path where the XML file should be saved
        """
        xml = RekordboxXml()
        self._selected_track_ids = set()
        self._add_playlists(xml)
        self._add_tracks_to_collection(xml)
        self.verbose(f"Saving XML to {path}")
        xml.save(path)
        
        # Files are copied directly into the same export directory as the XML
        output_file = Path(path)
        export_dir = output_file.parent
        export_dir.mkdir(parents=True, exist_ok=True)
        
        self._copy_map: Dict[str, Path] = {}
        self.verbose(f"Copying files to {export_dir}")
        self._copy_files(export_dir)
        # Update XML Location attributes to point to copied files
        self._update_locations(path, export_dir)

    def _build_path_map(self, all_playlists) -> Dict[Any, str]:
        """Build hierarchical path map (ID -> 'Folder/Subfolder/Playlist') matching GUI."""
        id_map = {pl.ID: pl for pl in all_playlists}
        parent_map: Dict[Any, list] = {}
        for pl in all_playlists:
            parent_map.setdefault(pl.ParentID, []).append(pl)
        for children in parent_map.values():
            children.sort(key=lambda x: x.Name)

        root_parents = [pid for pid in parent_map if pid not in id_map]
        path_map: Dict[Any, str] = {}

        def traverse(pid: Any, current_path: str) -> None:
            for pl in parent_map.get(pid, []):
                p_str = f"{current_path}/{pl.Name}" if current_path else pl.Name
                path_map[pl.ID] = p_str
                traverse(pl.ID, p_str)

        for rp in root_parents:
            traverse(rp, "")
        return path_map

    def _add_playlists(self, xml) -> None:
        """
        Add playlists to the XML.

        Args:
            xml: The RekordboxXml instance
        """
        all_playlists = self.db.get_playlist().all()
        id_map_all = {pl.ID: pl for pl in all_playlists}
        self._playlist_path_map = self._build_path_map(all_playlists)

        # Filter playlists if specs provided (include descendants & ancestors)
        if self._playlist_specs:
            target_ids = set()
            for spec in self._playlist_specs:
                if spec.isdigit() and int(spec) in id_map_all:
                    target_ids.add(int(spec))
                else:
                    for pid, ppath in self._playlist_path_map.items():
                        if (
                            ppath == spec
                            or ppath.endswith(f"/{spec}")
                            or spec == ppath.split("/")[-1]
                        ):
                            target_ids.add(pid)

            # Build parent->children map
            parent_map_full: Dict[Any, List] = {}
            for pl in all_playlists:
                parent_map_full.setdefault(pl.ParentID, []).append(pl)

            include_ids = set()

            def collect_desc(pid):
                include_ids.add(pid)
                for child in parent_map_full.get(pid, []):
                    collect_desc(child.ID)

            for tid in target_ids:
                collect_desc(tid)

            # Include ancestor folders
            for pid in list(include_ids):
                curr = id_map_all.get(pid)
                while curr:
                    include_ids.add(curr.ID)
                    curr = id_map_all.get(curr.ParentID)

            all_playlists = [pl for pl in all_playlists if pl.ID in include_ids]

        # Group by parent ID for XML hierarchy generation
        parent_map: Dict[Any, List] = {}
        for pl in all_playlists:
            parent_map.setdefault(pl.ParentID, []).append(pl)
        for children in parent_map.values():
            children.sort(key=lambda x: x.Name)

        id_map = {pl.ID: pl for pl in all_playlists}
        root_parents = [pid for pid in parent_map if pid not in id_map]

        # Queue for breadth-first building: (parent_db_id, parent_xml_node)
        queue = [(rp, xml._root_node) for rp in root_parents]

        while queue:
            parent_id, parent_xml = queue.pop(0)
            children = parent_map.get(parent_id, [])
            for child in children:
                self.verbose(f"adding playlist: {child.Name} (parent: {parent_id})")
                if child.is_folder:
                    child_xml = parent_xml.add_playlist_folder(self._romanize(child.Name))
                    queue.append((child.ID, child_xml))
                elif child.is_playlist:
                    pl_xml = parent_xml.add_playlist(self._romanize(child.Name))
                    self._add_playlists_to_playlist(pl_xml, child)


    def _add_tracks_to_collection(self, xml) -> None:
        """Add all tracks to the XML collection."""
        tracks = self.db.get_content()

        # uniq tracks
        tracks = list({track.FolderPath: track for track in tracks}.values())

        # filter tracks
        # track.FolderPathが空かfile://localhost//Contentsで始まるトラックを除外
        tracks = [
            track
            for track in tracks
            if not (
                track.FolderPath is None
                or track.FolderPath == ""
                or track.FolderPath.startswith("file://localhost//Contents")
            )
        ]

        # If playlists specified, limit to selected tracks
        if getattr(self, '_playlist_specs', None):
            tracks = [track for track in tracks if track.ID in self._selected_track_ids]

        # Add each track to the collection
        for track in tracks:
            self.verbose(f"Processing track: {track}")
            self._add_track_to_xml(xml, track)

    def _romanize(self, value: str, force: Optional[bool] = None) -> str:
        """
        ローマ字変換
        ASCIIのみの場合は変換をスキップ

        Args:
            value: 変換対象文字列
            force: Trueなら強制変換、Falseなら変換しない、
                   Noneならグローバル設定(_use_roman)に従う
        """
        if not value:
            return value
        if value.isascii():
            return value
        should_romanize = force if force is not None else self._use_roman
        if should_romanize and self._roman_converter:
            try:
                return self._roman_converter.to_roman(value)
            except Exception as e:
                self.verbose(f"[WARN] romann変換失敗: {value}: {e}")
                return value
        return value

    def _safe_bpm(self, val) -> Optional[float]:
        """Convert raw BPM value to float BPM."""
        try:
            return float(val) / 100.0
        except Exception:
            return None

    def _add_track_to_xml(self, xml, track) -> bool:
        """
        Add a track to the XML collection.

        Args:
            xml: The RekordboxXml instance
            track: Track data from the database (DjmdContent object)
        """
        # Resolve per-track options (set during playlist processing)
        track_opts = self._track_options.get(track.ID, {})
        use_roman = track_opts.get("roman", self._use_roman)
        use_bpm = track_opts.get("bpm", self._use_bpm)

        # Prepare track attributes
        # まずAverageBpmをtrack_attrsに格納
        avg_bpm_val = self._safe_bpm(getattr(track, 'BPM', None))
        track_attrs = {}
        track_attrs["AverageBpm"] = "{:.2f}".format(avg_bpm_val) if avg_bpm_val is not None else ""

        # その後、他属性を処理
        for db_field, xml_attr in self._track_attribute_mapping().items():
            if xml_attr == "AverageBpm":
                continue  # すでに格納済み
            value = (getattr(track, db_field) or "") if hasattr(track, db_field) else ""
            # ローマ字変換
            if xml_attr == "Name":
                value = str(value) if value is not None else ""
                value = self._romanize(value, force=use_roman)
                # BPM有効時はタイトル先頭にBPM整数値を付与
                if use_bpm:
                    avg_bpm = track_attrs.get("AverageBpm")
                    try:
                        bpm_float = float(avg_bpm) if avg_bpm else 0.0
                        bpm_int = int(bpm_float) if bpm_float > 0 else None
                    except Exception:
                        bpm_int = None
                    if bpm_int is not None:
                        old_value = value
                        value = f"{bpm_int} {value}"
                        if self._verbose:
                            print(f"[BPM TITLE] {old_value} → {value} (AverageBpm={avg_bpm})")
            elif xml_attr in ("Artist", "Album"):
                value = str(value) if value is not None else ""
                value = self._romanize(value, force=use_roman)
            if value is not None:
                track_attrs[xml_attr] = value

        self.verbose(f"Adding track: {track}")
        # Add track element and attach TEMPO child
        track_elem = xml.add_track(track.FolderPath, **track_attrs)
        bpm_str = track_attrs.get("AverageBpm")
        if bpm_str:
            track_elem.add_tempo(Inizio="0.000", Bpm=bpm_str, Metro="4/4", Battito="1")
        return True

    def _track_attribute_mapping(self) -> Dict[str, str]:
        """
        Define mapping between database fields and XML attributes.

        Returns:
            Dictionary mapping database field names to XML attribute names
        """
        # Mapping based on PyRekordbox's actual API
        # We handle different possible field names in the database
        return {
            "ID": "TrackID",
            "Title": "Name",
            "Artist": "Artist",
            "ArtistName": "Artist",  # DjmdContent attribute
            "Composer": "Composer",
            "ComposerName": "Composer",  # DjmdContent attribute
            "Album": "Album",
            "AlbumName": "Album",  # DjmdContent attribute
            "Grouping": "Grouping",
            "Genre": "Genre",
            "GenreName": "Genre",  # DjmdContent attribute
            "FileType": "Kind",  # DjmdContent attribute
            "Kind": "Kind",
            "FileSize": "Size",  # DjmdContent attribute
            "Size": "Size",
            "Length": "TotalTime",  # DjmdContent attribute
            "DiscNo": "DiscNumber",  # DjmdContent attribute
            "TrackNo": "TrackNumber",  # DjmdContent attribute
            "ReleaseYear": "Year",  # DjmdContent attribute
            "Year": "Year",
            "BPM": "AverageBpm",  # DjmdContent attribute
            "AverageBpm": "AverageBpm",
            "DateCreated": "DateAdded",  # DjmdContent attribute
            "StockDate": "DateAdded",  # DjmdContent attribute
            "DateAdded": "DateAdded",
            "BitRate": "BitRate",
            "SampleRate": "SampleRate",
            "Commnt": "Comments",  # DjmdContent attribute
            "Comments": "Comments",
            "DJPlayCount": "PlayCount",  # DjmdContent attribute
            "PlayCount": "PlayCount",
            "Rating": "Rating",
            "Remixer": "Remixer",
            "RemixerName": "Remixer",  # DjmdContent attribute
            "KeyName": "Tonality",  # DjmdContent attribute
            "Tonality": "Tonality",
            "Label": "Label",
            "LabelName": "Label",  # DjmdContent attribute
            "Mix": "Mix",
        }

    def _resolve_file_path(self, loc: Optional[str]) -> Optional[Path]:
        """Resolve a Rekordbox FolderPath URI or local path string to a valid Path object."""
        if not loc:
            return None

        # 1. Try directly if valid and exists
        try:
            p = Path(loc)
            if p.exists():
                return p
        except Exception:
            pass

        # 2. Parse file:// URI or encoded path
        path_str = loc
        if "://" in loc or loc.startswith("file:"):
            parsed = urllib.parse.urlparse(loc)
            unquoted = urllib.parse.unquote(parsed.path)
            # Use standard url2pathname for OS-specific conversions
            converted = urllib.request.url2pathname(unquoted)
            if os.name == "nt":
                converted = converted.lstrip("/").lstrip("\\")
                if len(unquoted) >= 3 and unquoted[1] == ":" and unquoted[0] == "/":
                    converted = unquoted[1:]
            path_str = converted
        else:
            path_str = urllib.parse.unquote(loc)

        # 3. Try converted path
        try:
            p = Path(path_str)
            if p.exists():
                return p
        except Exception:
            pass

        # 4. Fallback for Windows leading slash
        if os.name == "nt" and (path_str.startswith("/") or path_str.startswith("\\")):
            try:
                p = Path(path_str.lstrip("/\\"))
                if p.exists():
                    return p
            except Exception:
                pass

        # Return Path even if not exists (for logging/matching)
        try:
            return Path(path_str)
        except Exception:
            return None

    def _add_playlists_to_playlist(self, playlist_node, playlist) -> None:
        """
        Add tracks to a playlist.

        Args:
            playlist_node: The playlist node to add tracks to
            playlist: The playlist to get tracks for
        """
        # Resolve per-playlist options
        pl_path = self._playlist_path_map.get(playlist.ID, "")
        pl_opts = self._playlist_options.get(pl_path, {})
        orderby = pl_opts.get("orderby", self._orderby)
        use_roman = pl_opts.get("roman", self._use_roman)
        use_bpm = pl_opts.get("bpm", self._use_bpm)

        # Get tracks in playlist
        playlist_entries = self.db.get_playlist_contents(playlist).all()

        # orderby=bpm オプション対応
        if orderby == 'bpm':
            def safe_bpm(entry):
                bpm = getattr(entry, 'BPM', None)
                if not bpm:
                    return 0
                return bpm
            playlist_entries = sorted(playlist_entries, key=safe_bpm)

        # Normalize playlist entries and record per-track options
        for entry in playlist_entries:
            # entry can be DjmdContent or DjmdSongPlaylist
            track_id = getattr(entry, 'ContentID', None) or getattr(entry, 'ID', None)
            if track_id is None:
                continue

            playlist_node.add_track(track_id)

            # Record track ID in all possible types for robust lookup
            self._selected_track_ids.add(track_id)
            self._selected_track_ids.add(str(track_id))
            try:
                self._selected_track_ids.add(int(track_id))
            except Exception:
                pass

            if getattr(entry, 'ID', None) is not None:
                self._selected_track_ids.add(entry.ID)
                self._selected_track_ids.add(str(entry.ID))

            # Store per-track options (first playlist's settings win)
            if track_id not in self._track_options:
                self._track_options[track_id] = {
                    "roman": use_roman,
                    "bpm": use_bpm,
                }

    def close(self) -> None:
        """Close the database connection when done."""
        try:
            self.db.close()
        except Exception:
            pass

    def _copy_files(self, export_dir: Path) -> None:
        """
        Copy selected track files to export directory, preserving audio metadata.
        """
        copied = 0
        skipped = 0
        failed = 0

        for content in self.db.get_content().all():
            cid = getattr(content, 'ID', None)
            # If specific playlists selected, filter by selected tracks
            if getattr(self, '_playlist_specs', None):
                if (
                    cid not in self._selected_track_ids
                    and str(cid) not in self._selected_track_ids
                ):
                    continue

            loc = getattr(content, 'FolderPath', None)
            if not loc:
                self.verbose(f"Track ID {cid}: FolderPath missing, skipping")
                skipped += 1
                continue

            orig = self._resolve_file_path(loc)
            if not orig or not orig.exists():
                print(f"[WARN] 楽曲ファイルが見つかりません: {loc} (解決パス: {orig})")
                failed += 1
                continue

            # MD5 hash as filename (preserving extension)
            path_for_hash = str(orig).encode("utf-8")
            md5_hex = hashlib.md5(path_for_hash).hexdigest()
            ext = orig.suffix or ".mp3"
            dest = export_dir / f"{md5_hex}{ext}"

            # Copy file if not already copied
            if not dest.exists():
                try:
                    shutil.copy2(orig, dest)
                    copied += 1
                except Exception as e:
                    print(f"[ERROR] コピー失敗: {orig} → {dest}: {e}")
                    failed += 1
                    continue
            else:
                copied += 1

            # Map multiple path variants for XML location updates
            self._copy_map[loc] = dest
            self._copy_map[str(orig)] = dest
            self._copy_map[orig.as_posix()] = dest
            if "://" in loc:
                self._copy_map[urllib.parse.unquote(loc)] = dest
                parsed = urllib.parse.urlparse(loc)
                self._copy_map[urllib.parse.unquote(parsed.path)] = dest

            # Resolve per-track options
            track_opts = self._track_options.get(cid, {})
            use_roman = track_opts.get("roman", self._use_roman)
            use_bpm = track_opts.get("bpm", self._use_bpm)

            # Rewrite metadata tags using mutagen
            title_val = getattr(content, 'Title', '') or ''
            artist_val = getattr(content, 'ArtistName', '') or getattr(content, 'Artist', '') or ''
            album_val = getattr(content, 'AlbumName', '') or getattr(content, 'Album', '') or ''

            if use_roman:
                title_val = self._romanize(title_val, force=True)
                artist_val = self._romanize(artist_val, force=True)
                album_val = self._romanize(album_val, force=True)

            if use_bpm:
                bpm_val = self._safe_bpm(getattr(content, 'BPM', None))
                if bpm_val:
                    title_val = f"{int(bpm_val)} {title_val}"

            ext_lower = dest.suffix.lower()
            try:
                if ext_lower == '.mp3':
                    try:
                        audio = ID3(dest)
                    except mutagen.id3.ID3NoHeaderError:
                        audio = ID3()
                    audio['TIT2'] = TIT2(encoding=3, text=title_val)
                    audio['TPE1'] = TPE1(encoding=3, text=artist_val)
                    audio['TALB'] = TALB(encoding=3, text=album_val)
                    audio.save(dest)
                elif ext_lower in ('.m4a', '.mp4'):
                    audio = MP4(dest)
                    if audio.tags is None:
                        audio.add_tags()
                    audio.tags['\xa9nam'] = [title_val]
                    audio.tags['\xa9ART'] = [artist_val]
                    audio.tags['\xa9alb'] = [album_val]
                    audio.save()
            except Exception as e:
                self.verbose(f"[WARN] タグ書き換えエラー ({dest.name}): {e}")

        print(f"楽曲ファイル処理完了: コピー={copied}件, 失敗={failed}件, スキップ={skipped}件")

    def _update_locations(self, xml_path: str, export_dir: Path) -> None:
        """
        Update Location attributes in XML to URIs of copied files.
        """
        from lxml import etree
        import urllib.parse as up
        import os

        tree = etree.parse(xml_path)
        for track in tree.findall(".//TRACK"):
            loc = track.attrib.get("Location")
            if not loc:
                continue

            # Look up in copy_map using various key representations
            dest = self._copy_map.get(loc)
            if not dest and "://" in loc:
                parsed = up.urlparse(loc)
                raw = up.unquote(parsed.path)
                dest = self._copy_map.get(raw)
                if not dest and os.name == "nt" and raw.startswith("/"):
                    dest = self._copy_map.get(raw.lstrip("/"))

            if not dest:
                # Try resolved path
                resolved = self._resolve_file_path(loc)
                if resolved:
                    dest = self._copy_map.get(str(resolved)) or self._copy_map.get(resolved.as_posix())

            if dest:
                uri = dest.resolve().as_uri()
                parsed_uri = up.urlparse(uri)
                if parsed_uri.scheme == "file" and not parsed_uri.netloc:
                    parsed_uri = parsed_uri._replace(netloc="localhost")
                    uri = up.urlunparse(parsed_uri)
                track.attrib["Location"] = uri

        tree.write(xml_path, encoding="UTF-8", xml_declaration=True)



def export_rekordbox_db_to_xml(
    db_path: Optional[str],
    output_path: str,
    db_key: Optional[str] = None,
    verbose: bool = False,
    roman: bool = False,
    bpm: bool = False,
    orderby: str = "default",
    playlists: Optional[List[str]] = None,
    playlist_options: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """
    Export a Rekordbox database to XML format.

    Args:
        db_path: Path to the Rekordbox database file, or None to auto-detect
        output_path: Path where the XML file should be saved
        verbose: Show detailed output during export
        db_key: Rekordbox database key (optional, for newer Rekordbox versions)
        playlist_options: Per-playlist options dict mapping playlist path
            to {"roman": bool, "bpm": bool, "orderby": str}.
    """
    exporter = RekordboxXMLExporter(
        db_path,
        db_key=db_key,
        use_verbose=verbose,
        use_roman=roman,
        use_bpm=bpm,
        orderby=orderby,
        playlist_specs=playlists,
        playlist_options=playlist_options,
    )
    try:
        exporter.generate_xml(output_path)
    finally:
        exporter.close()

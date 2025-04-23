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
    ):
        """
        Initialize the exporter with the path to the Rekordbox database.
        """
        self._verbose = use_verbose
        self._use_roman = use_roman
        self._use_bpm = use_bpm
        self._orderby = orderby
        # Playlist selection specs parsed from CLI
        self._playlist_specs = playlist_specs
        self._roman_converter = None
        if use_roman:
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
        # ファイルコピー用出力ディレクトリを作成し、元ファイルを複製
        export_dir = Path(path).with_suffix("")
        export_dir.mkdir(parents=True, exist_ok=True)
        # Initialize mapping for updating XML locations
        self._copy_map: Dict[str, Path] = {}
        self.verbose(f"Copying files to {export_dir}")
        self._copy_files(export_dir)
        # Update XML Location attributes to point to copied files
        self._update_locations(path, export_dir)

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

    def _romanize(self, value: str) -> str:
        """
        ローマ字変換（有効時のみ）
        ASCIIのみの場合は変換をスキップ
        """
        if not value:
            return value
        if value.isascii():
            return value
        if self._use_roman and self._roman_converter:
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
        # Prepare track attributes
        track_attrs = {}
        # 既存の属性ループ
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
                value = self._romanize(value)
                # --bpm有効時はタイトル先頭にBPM整数値を付与（AverageBpmを利用）
                if self._use_bpm:
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
                value = self._romanize(value)
            if value is not None:
                track_attrs[xml_attr] = value

        self.verbose(f"Adding track: {track}")
        # Add track to XML
        xml.add_track(track.FolderPath, **track_attrs)
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
            "TotalTime": "TotalTime",
            "DiscNo": "DiscNumber",  # DjmdContent attribute
            "DiscNumber": "DiscNumber",
            "TrackNo": "TrackNumber",  # DjmdContent attribute
            "TrackNumber": "TrackNumber",
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

    def _add_playlists(self, xml) -> None:
        """
        Add playlists to the XML.

        ツリー構造を分析してからXMLに出力する
        ID=0のプレイリストはルートフォルダ

        Args:
            xml: The RekordboxXml instance
        """

        all_playlists = self.db.get_playlist().all()
        # Filter playlists if specs provided (include descendants & ancestors)
        if self._playlist_specs:
            orig_playlists = all_playlists
            id_map = {pl.ID: pl for pl in orig_playlists}
            # Build full path for each playlist
            path_map: Dict[Any, str] = {}
            for pl in orig_playlists:
                parts = [pl.Name]
                pid = pl.ParentID
                while pid in id_map:
                    parent = id_map[pid]
                    parts.insert(0, parent.Name)
                    pid = parent.ParentID
                path_map[pl.ID] = "/".join(parts)
            # Determine initial target IDs from specs
            target_ids = set()
            matched_specs = set()
            for spec in self._playlist_specs:
                if spec.isdigit():
                    sid = int(spec)
                    if sid in id_map:
                        target_ids.add(sid)
                        matched_specs.add(spec)
                else:
                    for pid, ppath in path_map.items():
                        if ppath == spec:
                            target_ids.add(pid)
                            matched_specs.add(spec)
            # 無効な指定をエラーとする
            unmatched = [spec for spec in self._playlist_specs if spec not in matched_specs]
            if unmatched:
                raise ValueError(f"Invalid playlist spec(s): {', '.join(unmatched)}")
            # Build parent->children map
            parent_map: Dict[Any, List] = {}
            for pl in orig_playlists:
                parent_map.setdefault(pl.ParentID, []).append(pl)
            # Collect include IDs (descendants and ancestors)
            include_ids = set()
            def collect_desc(pid):
                include_ids.add(pid)
                for child in parent_map.get(pid, []):
                    collect_desc(child.ID)
            for tid in target_ids:
                collect_desc(tid)
            # Include ancestor folders
            for pid in list(include_ids):
                curr = id_map.get(pid)
                while curr:
                    include_ids.add(curr.ID)
                    curr = id_map.get(curr.ParentID)
            all_playlists = [pl for pl in orig_playlists if pl.ID in include_ids]

        db_root = DjmdPlaylist()
        db_root.ID = "root"
        db_root.Name = "root"
        root = xml._root_node

        # db/xml playlist pair list
        db_xml_playlist_tuple_cue = [(db_root, root)]

        # find child folders, add to child, and remove them from all_playlists
        while db_xml_playlist_tuple_cue:
            parent, parent_xml = db_xml_playlist_tuple_cue[-1]
            # 親IDが一致する子ノードをすべて抽出
            children = [pl for pl in all_playlists if pl.ParentID == parent.ID]
            if not children:
                db_xml_playlist_tuple_cue.pop()
                continue
            for child in children:
                self.verbose(f"adding playlist: {child} (parent: {parent.ID})")
                if child.is_folder:
                    child_xml = parent_xml.add_playlist_folder(self._romanize(child.Name))
                    db_xml_playlist_tuple_cue.append((child, child_xml))
                elif child.is_playlist:
                    pl_xml = parent_xml.add_playlist(self._romanize(child.Name))
                    self._add_playlists_to_playlist(pl_xml, child)
                all_playlists.remove(child)

    def _add_playlists_to_playlist(self, playlist_node, playlist) -> None:
        """
        Add tracks to a playlist.

        Args:
            playlist_node: The playlist node to add tracks to
            playlist: The playlist to get tracks for
        """
        # Get tracks in playlist
        playlist_entries = self.db.get_playlist_contents(playlist).all()

        # --orderby=bpm オプション対応
        if getattr(self, '_orderby', 'default') == 'bpm':
            def safe_bpm(entry):
                bpm = entry.BPM
                if not bpm:
                    return 0
                return bpm
            playlist_entries = sorted(playlist_entries, key=safe_bpm)

        # Normalize playlist entries
        for entry in playlist_entries:
            playlist_node.add_track(entry.ID)
            # Record track ID for collection filtering
            self._selected_track_ids.add(entry.ID)

    def close(self) -> None:
        """Close the database connection when done."""
        # In version 0.4.0+ closing might not be necessary,
        # but we'll call it if the method exists
        self.db.close()

    def _copy_files(self, export_dir: Path) -> None:
        """
        Copy selected track files to export directory, preserving home-relative paths.
        """
        # Flatten copy: use md5 of full path as filename and rewrite tags
        for content in self.db.get_content().all():
            if content.ID not in self._selected_track_ids:
                continue
            loc = getattr(content, 'FolderPath', None)
            if not loc:
                self.verbose("FolderPath missing, skipping")
                continue
            # Parse file:// URI or raw path
            if "://" in loc:
                parsed = urllib.parse.urlparse(loc)
                path_str = urllib.parse.unquote(parsed.path)
                if os.name == 'nt' and path_str.startswith('/'):
                    path_str = path_str.lstrip('/')
            else:
                path_str = loc
            orig = Path(path_str)
            if not orig.exists():
                self.verbose(f"Source file not found, skipping: {orig}")
                continue
            # MD5 hash as filename (no extension)
            md5_hex = hashlib.md5(path_str.encode("utf-8")).hexdigest()
            # 元ファイルの拡張子を保持
            ext = orig.suffix
            dest = export_dir / f"{md5_hex}{ext}"
            try:
                shutil.copy2(orig, dest)
            except Exception as e:
                self.verbose(f"Copy failed: {orig} → {dest}: {e}")
                continue
            # Record mapping from original path to copied file
            self._copy_map[path_str] = dest
            # Rewrite metadata tags using mutagen
            title_val = getattr(content, 'Title', '') or ''
            artist_val = getattr(content, 'ArtistName', '') or getattr(content, 'Artist', '') or ''
            album_val = getattr(content, 'AlbumName', '') or getattr(content, 'Album', '') or ''
            if self._use_roman:
                title_val = self._romanize(title_val)
                artist_val = self._romanize(artist_val)
                album_val = self._romanize(album_val)
            if self._use_bpm:
                bpm_val = self._safe_bpm(getattr(content, 'BPM', None))
                if bpm_val:
                    title_val = f"{int(bpm_val)} {title_val}"
            ext = dest.suffix.lower()
            if ext == '.mp3':
                try:
                    audio = ID3(dest)
                except mutagen.id3.ID3NoHeaderError:
                    audio = ID3()
                audio['TIT2'] = TIT2(encoding=3, text=title_val)
                audio['TPE1'] = TPE1(encoding=3, text=artist_val)
                audio['TALB'] = TALB(encoding=3, text=album_val)
                audio.save(dest)
            elif ext in ('.m4a', '.mp4'):
                audio = MP4(dest)
                tags = audio.tags or {}
                tags['\xa9nam'] = [title_val]
                tags['\xa9ART'] = [artist_val]
                tags['\xa9alb'] = [album_val]
                audio.tags = tags
                audio.save(dest)

    def _update_locations(self, xml_path: str, export_dir: Path) -> None:
        """
        Update Location attributes in XML to URIs of copied files.
        """
        from lxml import etree
        import urllib.parse as up
        import os
        # Parse XML file
        tree = etree.parse(xml_path)
        # Update each TRACK Location
        for track in tree.findall(".//TRACK"):
            loc = track.attrib.get("Location")
            if not loc:
                continue
            # Extract raw filesystem path
            if "://" in loc:
                parsed = up.urlparse(loc)
                raw = up.unquote(parsed.path)
                if os.name == "nt" and raw.startswith("/"):
                    raw = raw.lstrip("/")
            else:
                raw = loc
            dest = self._copy_map.get(raw)
            if dest:
                track.attrib["Location"] = dest.resolve().as_uri()
        # Write back updated XML
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
) -> None:
    """
    Export a Rekordbox database to XML format.

    Args:
        db_path: Path to the Rekordbox database file, or None to auto-detect
        output_path: Path where the XML file should be saved
        verbose: Show detailed output during export
        db_key: Rekordbox database key (optional, for newer Rekordbox versions)
    """
    exporter = RekordboxXMLExporter(
        db_path,
        db_key=db_key,
        use_verbose=verbose,
        use_roman=roman,
        use_bpm=bpm,
        orderby=orderby,
        playlist_specs=playlists,
    )
    try:
        exporter.generate_xml(output_path)
    finally:
        exporter.close()

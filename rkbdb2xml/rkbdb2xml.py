"""
Main functionality for converting Rekordbox DB to XML.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple, Any
import urllib.parse
import urllib.request

import pyrekordbox
from pyrekordbox.db6.database import PlaylistType
from pyrekordbox.rbxml import RekordboxXml
from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase, DjmdPlaylist
from pyrekordbox.config import get_config, KeyExtractor, get_pioneer_install_dir
from lxml import etree
import psutil

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
    ):
        """
        Initialize the exporter with the path to the Rekordbox database.
        """
        self._verbose = use_verbose
        self._use_roman = use_roman
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
        self._add_playlists(xml)
        self._add_tracks_to_collection(xml)
        self.verbose(f"Saving XML to {path}")
        xml.save(path)

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
        for db_field, xml_attr in self._track_attribute_mapping().items():
            switch = {
                "AverageBpm": "{:.2f}".format(track.BPM / 100.0),
            }
            value = switch.get(
                xml_attr,
                (getattr(track, db_field) or "") if hasattr(track, db_field) else "",
            )

            # ローマ字変換
            if xml_attr in ("Name", "Artist", "Album"):
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

        # Normalize playlist entries
        for entry in playlist_entries:
            playlist_node.add_track(entry.ID)

    def close(self) -> None:
        """Close the database connection when done."""
        # In version 0.4.0+ closing might not be necessary,
        # but we'll call it if the method exists
        self.db.close()


def export_rekordbox_db_to_xml(
    db_path: Optional[str],
    output_path: str,
    db_key: Optional[str] = None,
    verbose: bool = False,
    roman: bool = False,
) -> None:
    """
    Export a Rekordbox database to XML format.

    Args:
        db_path: Path to the Rekordbox database file, or None to auto-detect
        output_path: Path where the XML file should be saved
        verbose: Show detailed output during export
        db_key: Rekordbox database key (optional, for newer Rekordbox versions)
    """
    exporter = RekordboxXMLExporter(db_path, db_key=db_key, use_verbose=verbose, use_roman=roman)
    try:
        exporter.generate_xml(output_path)
    finally:
        exporter.close()

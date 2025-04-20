"""
Main functionality for converting Rekordbox DB to XML.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple, Any

import pyrekordbox
from pyrekordbox.rbxml import RekordboxXml
# Update import to use db6 module instead of db
from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase
from rich.console import Console
from rich.progress import Progress
from lxml import etree


class RekordboxXMLExporter:
    """
    Export Rekordbox database to XML format similar to Rekordbox XML export.
    """
    
    def __init__(self, db_path: Optional[str] = None, console: Optional[Console] = None, db_key: Optional[str] = None):
        """
        Initialize the exporter with the path to the Rekordbox database.
        
        Args:
            db_path: Path to the Rekordbox database file, or None to auto-detect
            console: Rich console for output (optional)
            db_key: Rekordbox database key (optional, for newer Rekordbox versions)
        """
        self.console = console or Console()
        self.db_path = db_path
        self.db_key = db_key
        
        try:
            self._connect_to_database()
            # Version 0.4.0+ of pyrekordbox automatically connects the database
            # No need to call connect() anymore
            self.rekordbox_version = self._get_rekordbox_version()
        except Exception as e:
            if self.console:
                self.console.log("[bold red]Error connecting to Rekordbox database[/bold red]")
            raise e
            
    def _connect_to_database(self):
        """
        Connect to the Rekordbox database, handling key download if necessary.
        """
        try:
            # Check if Rekordbox is running and warn the user
            self._check_rekordbox_running()
            
            # Try to connect with manually provided key if available
            if self.db_key:
                if self.console:
                    self.console.log("[blue]Using manually provided database key[/blue]")
                if self.db_path:
                    self.db = RekordboxDatabase(self.db_path, key=self.db_key)
                    if self.console:
                        self.console.log(f"Using specified database: {self.db_path}")
                else:
                    self.db = RekordboxDatabase(key=self.db_key)
                    if self.console:
                        self.console.log("Auto-detected Rekordbox database")
                return
            
            # Try to connect without a key
            if self.db_path:
                self.db = RekordboxDatabase(self.db_path)
                if self.console:
                    self.console.log(f"Using specified database: {self.db_path}")
            else:
                # Let pyrekordbox find the database automatically
                self.db = RekordboxDatabase()
                if self.console:
                    self.console.log("Auto-detected Rekordbox database")
        except Exception as e:
            error_str = str(e)
            # Check if the error is about missing key
            if "key" in error_str.lower() and "not found" in error_str.lower() or "could not unlock database" in error_str.lower():
                if self.console:
                    self.console.log("[yellow]Database key not found. Attempting to download key...[/yellow]")
                
                # Try to download the key using pyrekordbox CLI
                key = self._download_rekordbox_key()
                
                # If we got a key, try connecting again
                if key:
                    self.db_key = key
                    try:
                        if self.db_path:
                            self.db = RekordboxDatabase(self.db_path, key=key)
                        else:
                            self.db = RekordboxDatabase(key=key)
                        if self.console:
                            self.console.log("[green]Successfully connected to database with downloaded key[/green]")
                        return
                    except Exception as reconnect_error:
                        if self.console:
                            self.console.log(f"[red]Failed to connect with downloaded key: {str(reconnect_error)}[/red]")
                
                # If we get here, we couldn't connect with the downloaded key
                if "rekordbox>6.6.5" in error_str.lower() or "rekordbox > 6.6.5" in error_str.lower():
                    if self.console:
                        self.console.log("[yellow]You are using Rekordbox 6.6.5 or newer, which requires a manual key.[/yellow]")
                        self.console.log("[yellow]Please run 'python -m pyrekordbox download-key' manually and provide the key.[/yellow]")
                    
                raise Exception(f"Failed to connect to Rekordbox database: {str(e)}. For Rekordbox 6.6.5+, please provide a key manually.")
            else:
                # If it's not a key issue, re-raise the exception
                if self.console:
                    self.console.log(f"[red]Database connection error: {str(e)}[/red]")
                raise
                
    def _check_rekordbox_running(self):
        """
        Check if Rekordbox is currently running and warn the user if it is.
        """
        try:
            import psutil
            
            for proc in psutil.process_iter(['name']):
                if 'rekordbox' in proc.info['name'].lower():
                    if self.console:
                        self.console.log("[yellow]Warning: Rekordbox is currently running.[/yellow]")
                        self.console.log("[yellow]This may cause issues with database access. Consider closing Rekordbox first.[/yellow]")
                    return True
            return False
        except Exception:
            # Ignore errors in checking for Rekordbox process
            return False
                
    def _download_rekordbox_key(self) -> Optional[str]:
        """
        Download the Rekordbox database key using pyrekordbox internal API.
        Returns:
            The downloaded key if successful, None otherwise
        """
        try:
            if self.console:
                self.console.log("[yellow]Downloading Rekordbox database key (internal API)...[/yellow]")
            # pyrekordboxの設定からキャッシュ済みキー取得
            from pyrekordbox.config import get_config, KeyExtractor, get_pioneer_install_dir
            try:
                config = get_config('rekordbox6')
                if config and 'dp' in config and config['dp']:
                    return config['dp']
            except Exception as config_error:
                if self.console:
                    self.console.log(f"[yellow]Could not read key from config: {str(config_error)}[/yellow]")
            # キャッシュがなければKeyExtractorで取得
            try:
                pioneer_install_dir = get_pioneer_install_dir()
                extractor = KeyExtractor(str(pioneer_install_dir))
                key = extractor.run()
                if key:
                    return key
            except Exception as extract_error:
                if self.console:
                    self.console.log(f"[red]Key extraction failed: {extract_error}[/red]")
            return None
        except Exception as e:
            if self.console:
                self.console.log(f"[red]Error downloading key: {str(e)}[/red]")
            return None
    
    def _get_rekordbox_version(self) -> str:
        """Get the Rekordbox version from the database if possible."""
        try:
            # In pyrekordbox, you can get the version from the database's version property
            if hasattr(self.db, 'version'):
                return self.db.version
            elif hasattr(self.db, 'db_version'):
                return self.db.db_version
            # Try to get from master.db directly if it's a Rekordbox 6.x database
            elif hasattr(self.db, 'execute_query'):
                try:
                    rows = self.db.execute_query("SELECT value FROM djmdSetting WHERE name='applicationVersionStatus'")
                    if rows and len(rows) > 0:
                        return rows[0][0]
                except Exception:
                    pass
            return "6.8.0"  # Default version if can't be determined
        except Exception:
            return "6.8.0"
    
    def generate_xml(self, output_path: str, verbose: bool = False) -> None:
        """
        Generate XML file from the Rekordbox database.
        
        Args:
            output_path: Path where the XML file should be saved
            verbose: Show detailed output during export
        """
        with Progress(
            console=self.console,
            disable=not verbose,
            expand=True
        ) as progress:
            # Create the RekordboxXml instance
            export_task = progress.add_task("Generating XML...", total=4)
            xml = RekordboxXml(
                name="rekordbox", 
                version=self.rekordbox_version, 
                company="AlphaTheta"
            )
            
            # Add PRODUCT element
            if verbose:
                self.console.log("Adding PRODUCT information...")
            progress.update(export_task, advance=1)
            
            # Add tracks to COLLECTION
            if verbose:
                self.console.log("Adding COLLECTION (tracks)...")
            self._add_tracks_to_collection(xml, progress, verbose)
            progress.update(export_task, advance=1)
            
            # Add playlists
            if verbose:
                self.console.log("Adding PLAYLISTS...")
            self._add_playlists(xml, progress, verbose)
            progress.update(export_task, advance=1)
            
            # Write to file
            if verbose:
                self.console.log(f"Writing XML to {output_path}...")
            xml.save(output_path)
            progress.update(export_task, advance=1)
    
    def _add_tracks_to_collection(self, xml, progress, verbose: bool) -> None:
        """Add all tracks to the XML collection."""
        # In PyRekordbox 0.4.0+ the method to get tracks is search_content()
        tracks = []
        try:
            if hasattr(self.db, 'search_content'):
                # search_content now requires a text parameter, use empty string to get all tracks
                tracks = self.db.search_content("")
            elif hasattr(self.db, 'get_content'):
                tracks = self.db.get_content()
            elif hasattr(self.db, 'get_tracks'):
                tracks = self.db.get_tracks()
            else:
                if self.console:
                    self.console.log("[yellow]Warning: Unable to find method to get tracks[/yellow]")
            
            # Ensure tracks is a list
            if tracks is None:
                tracks = []
            
            # Try alternative methods if no tracks were found
            if len(tracks) == 0 and hasattr(self.db, 'get_all_content'):
                tracks = self.db.get_all_content()
            
            if len(tracks) == 0 and hasattr(self.db, 'get_all_tracks'):
                tracks = self.db.get_all_tracks()
        except Exception as e:
            if self.console:
                self.console.log(f"[yellow]Warning: Error getting tracks: {str(e)}[/yellow]")
        
        if verbose:
            self.console.log(f"Found {len(tracks)} tracks in database")
        
        # Sort tracks by Sequence attribute to match Rekordbox export order
        try:
            tracks = sorted(tracks, key=lambda t: getattr(t, "Sequence", t.get("Sequence", 0)))
        except Exception:
            pass
        
        # Create a track processing task if in verbose mode
        track_task = None
        if verbose:
            track_task = progress.add_task("Processing tracks...", total=len(tracks))
        
        # Keep track of successfully added tracks
        added_tracks = 0
        failed_tracks = 0
        
        # Add each track to the collection（LocationがNone/空文字のトラックはスキップ）
        for track in tracks:
            location = self._get_track_file_path(track)
            if location is None or location == '':
                # Location未設定のトラックはXML出力対象外
                continue
            success = self._add_track_to_xml(xml, track)
            if success:
                added_tracks += 1
            else:
                failed_tracks += 1
        
            if track_task:
                progress.update(track_task, advance=1)
        
        if verbose:
            self.console.log(f"Added {added_tracks} tracks to XML, {failed_tracks} tracks failed")
    
    def _get_track_file_path(self, track) -> str:
        """
        トラックオブジェクトからファイルの絶対パスまたはURLを生成する。
        
        """
        if hasattr(track, 'Location'):
            loc = getattr(track, 'Location', '')
            # If already a file URL, use as-is
            if isinstance(loc, str) and loc.startswith('file://'):
                return loc
            return self._format_file_location(loc)
        if hasattr(track, '__getitem__') and 'Location' in track:
            loc = track['Location']
            # If already a file URL, use as-is
            if isinstance(loc, str) and loc.startswith('file://'):
                return loc
            return self._format_file_location(loc)

        import os
        folder_path = getattr(track, 'FolderPath', '') if hasattr(track, 'FolderPath') else ''
        file_name = getattr(track, 'FileNameL', '') if hasattr(track, 'FileNameL') else ''
        # dict型互換
        if not folder_path and hasattr(track, '__getitem__') and 'FolderPath' in track:
            folder_path = track['FolderPath']
        if not file_name and hasattr(track, '__getitem__') and 'FileNameL' in track:
            file_name = track['FileNameL']
        if folder_path and file_name:
            # 末尾重複防止
            if folder_path.endswith(file_name):
                path = folder_path
            else:
                path = os.path.join(folder_path, file_name)
            return self._format_file_location(path)
        # Location属性があれば使う
        return ''

    def _add_track_to_xml(self, xml, track) -> bool:
        """
        Add a track to the XML collection.
        
        Args:
            xml: The RekordboxXml instance
            track: Track data from the database (DjmdContent object)
        """
        # Extract track properties - handle both dict-like and object-like access
        try:
            # Try to access as an object with attributes
            track_id = str(getattr(track, 'ID', ''))
            
            # ファイルパス生成を専用メソッドに委譲
            location = self._get_track_file_path(track)
                
            # Prepare track attributes
            track_attrs = {}
            # まずBPM値を明示的に処理し、AverageBpmにセット
            bpm_raw = None
            if hasattr(track, 'BPM'):
                bpm_raw = getattr(track, 'BPM')
            elif hasattr(track, '__getitem__') and 'BPM' in track:
                bpm_raw = track['BPM']
            if bpm_raw is not None:
                try:
                    bpm_value = float(bpm_raw) / 100.0
                    track_attrs['AverageBpm'] = "{:.2f}".format(bpm_value)
                except (ValueError, TypeError):
                    track_attrs['AverageBpm'] = str(bpm_raw)
            # 既存の属性ループ
            for db_field, xml_attr in self._track_attribute_mapping().items():
                # 'AverageBpm'は絶対に上書きしない
                if xml_attr == 'AverageBpm':
                    continue
                if hasattr(track, db_field):
                    value = getattr(track, db_field)
                    if value is not None:
                        # Handle special cases
                        if db_field in ['BPM', 'bpm', 'Bpm']:
                            value = str(value)
                        else:
                            value = str(value)
                        if db_field == 'Location' or (db_field == 'FolderPath' and file_name):
                            value = location
                            location = value
                        # ここでAverageBpmの上書きを絶対にしない
                        if xml_attr != 'AverageBpm':
                            track_attrs[xml_attr] = value
        except Exception as attr_error:
            # Fallback to dictionary access if attribute access fails
            try:
                # Try to get track_id and location using attribute access first
                if hasattr(track, 'ID'):
                    track_id = str(getattr(track, 'ID', ''))
                else:
                    # Try dictionary-like access if possible
                    if hasattr(track, '__getitem__') and 'ID' in track:
                        track_id = str(track['ID'])
                    else:
                        track_id = ''
                
                # Try to get folder path and file name for constructing location
                folder_path = ''
                file_name = ''
                
                # Try attribute access first
                if hasattr(track, 'FolderPath'):
                    folder_path = getattr(track, 'FolderPath', '')
                elif hasattr(track, '__getitem__') and 'FolderPath' in track:
                    folder_path = track['FolderPath']
                    
                if hasattr(track, 'FileNameL'):
                    file_name = getattr(track, 'FileNameL', '')
                elif hasattr(track, '__getitem__') and 'FileNameL' in track:
                    file_name = track['FileNameL']
                
                # Construct location from folder path and file name if both exist
                if folder_path and file_name:
                    # Check if folder_path already contains the file_name to avoid duplication
                    if folder_path.endswith(file_name):
                        location = folder_path
                    else:
                        # Use string concatenation instead of os.path.join to avoid scope issues
                        location = folder_path + '/' + file_name
                else:
                    # Fallback to direct Location attribute if available
                    if hasattr(track, 'Location'):
                        location = getattr(track, 'Location', '')
                    elif hasattr(track, '__getitem__') and 'Location' in track:
                        location = track['Location']
                    else:
                        location = ''
                
                # Prepare track attributes
                track_attrs = {}
                for db_field, xml_attr in self._track_attribute_mapping().items():
                    value = None
                    
                    # Try attribute access first
                    if hasattr(track, db_field):
                        value = getattr(track, db_field)
                    # Then try dictionary-like access
                    elif hasattr(track, '__getitem__') and db_field in track:
                        value = track[db_field]
                    
                    if value is not None:
                        # Handle special cases
                        if db_field in ['BPM', 'AverageBpm', 'bpm', 'average_bpm', 'Bpm']:
                            # BPM値はデータベースでは100倍で保存されているので、100で割って正しい値に変換
                            try:
                                bpm_value = float(value) / 100.0
                                value = "{:.2f}".format(bpm_value)
                            except (ValueError, TypeError):
                                # 変換に失敗した場合は元の値を使用
                                value = str(value)
                        else:
                            value = str(value)
                            
                        # Handle special case for file location
                        if db_field == 'Location':
                            value = self._format_file_location(value)
                            location = value  # Store formatted location for add_track method
                        track_attrs[xml_attr] = value
            except Exception as dict_error:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not process track: {str(dict_error)}[/yellow]")
                return False
                # Add track to XML
        try:
            # Use pyrekordbox.rbxml's add_track method
            track_id = track_attrs.get('TrackID', '')
            
            # Make sure all required attributes are present
            # Add missing attributes with default values if they're not in track_attrs
            for attr in ['Album', 'Artist', 'Composer', 'Genre', 'Grouping', 'Label', 'Mix', 'Remixer', 'Tonality']:
                if attr not in track_attrs:
                    track_attrs[attr] = ''
            
            # Ensure location is not empty to avoid duplicate track errors
            if not location or location == 'file://localhost/':
                # Generate a unique location based on track ID if the actual location is empty
                # Don't add file://localhost/ prefix as pyrekordbox will add it automatically
                location = f"unknown_location_{track_id}.mp3"
            
            # Remove Location from track_attrs if it exists, since we'll pass it as a separate parameter
            if 'Location' in track_attrs:
                del track_attrs['Location']
            
            # Add track to XML
            try:
                xml_track = xml.add_track(location, **track_attrs)
            except Exception as add_error:
                # If adding the track fails due to duplicate location, try with a modified location
                if "already contains a track with Location" in str(add_error):
                    # Modify the location to make it unique
                    unique_location = f"{location}?id={track_id}"
                    try:
                        xml_track = xml.add_track(unique_location, **track_attrs)
                    except Exception as retry_error:
                        if self.console:
                            self.console.log(f"[yellow]Warning: Could not add track {track_id} even with unique location: {str(retry_error)}[/yellow]")
                        return False
                else:
                    if self.console:
                        self.console.log(f"[yellow]Warning: Could not add track {track_id}: {str(add_error)}[/yellow]")
                    return False
            
            # Get the raw XML document to add markers directly
            # This is a workaround since we can't access the XML elements directly through the API
            try:
                # Try to access the XML document
                xml_doc = None
                
                # Try different ways to access the XML document
                if hasattr(xml, 'to_xml_string'):
                    # Save to a temporary file and parse it back
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as temp_file:
                        temp_path = temp_file.name
                    
                    # Save current state to temp file
                    xml.save(temp_path)
                    
                    # Parse the XML file
                    xml_doc = etree.parse(temp_path)
                    
                    # Find the track element by ID
                    track_elem = None
                    for elem in xml_doc.findall('.//TRACK'):
                        if elem.get('TrackID') == track_id:
                            track_elem = elem
                            break
                    
                    if track_elem is not None:
                        # Add BPM information as TEMPO marker
                        bpm = None
                        if hasattr(track, 'BPM'):
                            bpm = getattr(track, 'BPM')
                        elif 'BPM' in track_attrs:
                            bpm = track_attrs['BPM']
                        elif 'AverageBpm' in track_attrs:
                            bpm = track_attrs['AverageBpm']
                        
                        if bpm and float(bpm) > 0:
                            # Create a TEMPO element
                            tempo_elem = etree.SubElement(track_elem, "TEMPO")
                            tempo_elem.set("Inizio", "0.025")  # Standard start position
                            tempo_elem.set("Bpm", f"{float(bpm):.2f}")
                            tempo_elem.set("Metro", "4/4")  # Default time signature
                            tempo_elem.set("Battito", "1")  # Default beat
                        
                        # Add cue points as POSITION_MARK elements
                        if hasattr(track, 'Cues') and getattr(track, 'Cues'):
                            cues = getattr(track, 'Cues')
                            for i, cue in enumerate(cues):
                                # Create a POSITION_MARK element
                                pos_elem = etree.SubElement(track_elem, "POSITION_MARK")
                                pos_elem.set("Name", getattr(cue, 'Name', f"Cue {i+1}"))
                                pos_elem.set("Type", str(getattr(cue, 'Type', "0")))
                                pos_elem.set("Start", str(getattr(cue, 'Position', "0.0")))
                                pos_elem.set("Num", str(i))
                                # Add color if available
                                if hasattr(cue, 'Color'):
                                    pos_elem.set("Red", str(getattr(cue, 'Color', {}).get('Red', "0")))
                                    pos_elem.set("Green", str(getattr(cue, 'Color', {}).get('Green', "0")))
                                    pos_elem.set("Blue", str(getattr(cue, 'Color', {}).get('Blue', "0")))
                    
                    # Save the modified XML back
                    xml_doc.write(temp_path)
                    
                    # Load the modified XML back into the pyrekordbox object
                    # This is a hack, but it's the only way to modify the XML directly
                    xml = pyrekordbox.rbxml.RekordboxXml.parse_file(temp_path)
                    
                    # Clean up the temporary file
                    import os
                    os.unlink(temp_path)
            except Exception as xml_error:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not add markers for track {track_id}: {str(xml_error)}[/yellow]")
            except Exception as marker_error:
                # Don't fail the whole track if we can't add markers
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not add markers for track {track_id}: {str(marker_error)}[/yellow]")
                # Continue with the track even if markers failed
                pass
            
            # Track was successfully added
            return True
        except Exception as e:
            if self.console:
                self.console.log(f"[yellow]Warning: Could not add track {track_id}: {str(e)}[/yellow]")
            return False
    
    def _track_attribute_mapping(self) -> Dict[str, str]:
        """
        Define mapping between database fields and XML attributes.
        
        Returns:
            Dictionary mapping database field names to XML attribute names
        """
        # Mapping based on PyRekordbox's actual API
        # We handle different possible field names in the database
        main_mapping = {
            'ID': 'TrackID',
            'Title': 'Name',
            'Artist': 'Artist',
            'ArtistName': 'Artist',  # DjmdContent attribute
            'Composer': 'Composer',
            'ComposerName': 'Composer',  # DjmdContent attribute
            'Album': 'Album',
            'AlbumName': 'Album',  # DjmdContent attribute
            'Grouping': 'Grouping',
            'Genre': 'Genre',
            'GenreName': 'Genre',  # DjmdContent attribute
            'FileType': 'Kind',  # DjmdContent attribute
            'Kind': 'Kind',
            'FileSize': 'Size',  # DjmdContent attribute
            'Size': 'Size',
            'Length': 'TotalTime',  # DjmdContent attribute
            'TotalTime': 'TotalTime',
            'DiscNo': 'DiscNumber',  # DjmdContent attribute
            'DiscNumber': 'DiscNumber',
            'TrackNo': 'TrackNumber',  # DjmdContent attribute
            'TrackNumber': 'TrackNumber',
            'ReleaseYear': 'Year',  # DjmdContent attribute
            'Year': 'Year',
            'BPM': 'AverageBpm',  # DjmdContent attribute
            'AverageBpm': 'AverageBpm', 
            'DateCreated': 'DateAdded',  # DjmdContent attribute
            'StockDate': 'DateAdded',  # DjmdContent attribute
            'DateAdded': 'DateAdded',
            'BitRate': 'BitRate',
            'SampleRate': 'SampleRate',
            'Commnt': 'Comments',  # DjmdContent attribute
            'Comments': 'Comments',
            'DJPlayCount': 'PlayCount',  # DjmdContent attribute
            'PlayCount': 'PlayCount',
            'Rating': 'Rating',
            'Location': 'Location',
            'Remixer': 'Remixer',
            'RemixerName': 'Remixer',  # DjmdContent attribute
            'KeyName': 'Tonality',  # DjmdContent attribute
            'Tonality': 'Tonality',
            'Label': 'Label',
            'LabelName': 'Label',  # DjmdContent attribute
            'Mix': 'Mix'
        }
        
        # Alternative field names that might be used in pyrekordbox
        alternative_mappings = {
            # ID variations
            'id': 'TrackID',
            'Id': 'TrackID',
            'track_id': 'TrackID',
            'TrackId': 'TrackID',
            
            # Title variations
            'title': 'Name',
            'name': 'Name',
            'track_title': 'Name',
            
            # Artist variations
            'artist': 'Artist',
            'artist_name': 'Artist',
            
            # BPM variations
            'bpm': 'AverageBpm',
            'average_bpm': 'AverageBpm',
            'Bpm': 'AverageBpm',
            
            # Date variations
            'date_added': 'DateAdded',
            'added_date': 'DateAdded',
            'added_at': 'DateAdded',
            
            # Path/location variations
            'location': 'Location',
            'path': 'Location',
            'file_path': 'Location',
            'FilePath': 'Location',
            
            # File variations
            'file_size': 'Size',
            'filesize': 'Size',
            
            # Time variations
            'duration': 'TotalTime',
            'length': 'TotalTime',
            'time': 'TotalTime',
            
            # Misc variations
            'comment': 'Comments',
            'play_count': 'PlayCount',
            'key': 'Tonality',
            'musical_key': 'Tonality',
            'disc_no': 'DiscNumber',
            'track_no': 'TrackNumber'
        }
        
        # Merge dictionaries, with main_mapping taking precedence
        return {**alternative_mappings, **main_mapping}
    
    def _format_file_location(self, path: str) -> str:
        """
        Format file path as Rekordbox XML expects (always file:///... URL, cross-platform).
        Args:
            path: File path from the database
        Returns:
            Formatted file URL (file:///...)
        """
        import os
        import urllib.parse
        if not path:
            return ''
        # 絶対パス化
        abs_path = os.path.abspath(path)
        # Windowsパスをスラッシュ区切りに
        abs_path = abs_path.replace('\\', '/')
        # 先頭にドライブレターがある場合（例: C:/...）、file:///C:/...とする
        if os.name == 'nt':
            if not abs_path.startswith('/'):
                abs_path = '/' + abs_path
        url = 'file://' + abs_path
        return urllib.parse.quote(url, safe=':/')

    
    def _add_tempo_markers(self, track_elem: etree.Element, track: Dict) -> None:
        """
        Add TEMPO elements to a track.
        
        Args:
            track_elem: The TRACK element to add the tempo markers to
            track: Track data from the database
        """
        track_id = track.get('ID')
        
        # Try different API methods based on what's available in pyrekordbox
        tempo_markers = None
        
        # First try to get from beatgrid if available
        if hasattr(self.db, 'get_beatgrid'):
            try:
                beatgrid = self.db.get_beatgrid(track_id)
                if beatgrid:
                    tempo_markers = []
                    # Convert beatgrid data to tempo markers format
                    for i, beat in enumerate(beatgrid):
                        if i == 0 or beat.get('bpm') != beatgrid[i-1].get('bpm'):
                            tempo_markers.append({
                                'position': beat.get('time', 0.0),
                                'bpm': beat.get('bpm', 0.0),
                                'meter_numerator': 4,  # Default time signature
                                'meter_denominator': 4,
                                'beat_number': beat.get('beat_number', 1)
                            })
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get beatgrid for track {track_id}: {e}[/yellow]")
        
        # Fall back to get_track_tempo_markers if available
        if not tempo_markers and hasattr(self.db, 'get_track_tempo_markers'):
            try:
                tempo_markers = self.db.get_track_tempo_markers(track_id)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get tempo markers for track {track_id}: {e}[/yellow]")
        
        # Add tempo elements if we have markers
        if tempo_markers:
            for marker in tempo_markers:
                # Format BPM with 2 decimal places
                bpm_value = marker.get('bpm', 0.0)
                if isinstance(bpm_value, (int, float)):
                    bpm_formatted = f"{float(bpm_value):.2f}"
                else:
                    bpm_formatted = "0.00"
                
                # Get time signature
                numerator = marker.get('meter_numerator', 4)
                denominator = marker.get('meter_denominator', 4)
                
                # Add TEMPO element
                tempo = etree.SubElement(
                    track_elem, 
                    "TEMPO",
                    Inizio=str(marker.get('position', '0.0')),
                    Bpm=bpm_formatted,
                    Metro=f"{numerator}/{denominator}",
                    Battito=str(marker.get('beat_number', 1))
                )
    
    def _add_position_markers(self, track_elem: etree.Element, track: Dict) -> None:
        """
        Add POSITION_MARK elements to a track.
        
        Args:
            track_elem: The TRACK element to add the position markers to
            track: Track data from the database
        """
        track_id = track.get('ID')
        
        # Try different API methods based on what's available in pyrekordbox
        cue_points = None
        
        # First try to get memory/hot cues if available
        if hasattr(self.db, 'get_memory_cues'):
            try:
                memory_cues = self.db.get_memory_cues(track_id)
                if memory_cues:
                    cue_points = []
                    for cue in memory_cues:
                        # Convert to the expected format
                        cue_point = {
                            'name': cue.get('name', ''),
                            'type': cue.get('type', 0),
                            'position': cue.get('position', 0.0),
                            'hot_cue_number': -1,  # Default for memory cues
                        }
                        # Add color if available
                        if 'color_id' in cue:
                            color_id = cue.get('color_id')
                            # Map color_id to RGB values based on Rekordbox color system
                            # This is a simplified mapping and might need adjustment
                            colors = {
                                1: (255, 0, 0),      # Red
                                2: (0, 255, 0),      # Green
                                3: (0, 0, 255),      # Blue
                                4: (255, 255, 0),    # Yellow
                                5: (255, 0, 255),    # Magenta
                                6: (0, 255, 255),    # Cyan
                                7: (255, 165, 0),    # Orange
                                8: (128, 0, 128),    # Purple
                            }
                            if color_id in colors:
                                cue_point['red'], cue_point['green'], cue_point['blue'] = colors[color_id]
                        cue_points.append(cue_point)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get memory cues for track {track_id}: {e}[/yellow]")
        
        # Try to get hot cues if available
        if hasattr(self.db, 'get_hot_cues'):
            try:
                hot_cues = self.db.get_hot_cues(track_id)
                if hot_cues:
                    # Initialize cue_points if it's None
                    if cue_points is None:
                        cue_points = []
                    
                    for cue in hot_cues:
                        # Convert to the expected format
                        cue_point = {
                            'name': cue.get('name', ''),
                            'type': cue.get('type', 0),
                            'position': cue.get('position', 0.0),
                            'hot_cue_number': cue.get('hot_cue_number', -1),
                        }
                        # Add color if available
                        if 'color_id' in cue:
                            color_id = cue.get('color_id')
                            # Same color mapping as above
                            colors = {
                                1: (255, 0, 0),      # Red
                                2: (0, 255, 0),      # Green
                                3: (0, 0, 255),      # Blue
                                4: (255, 255, 0),    # Yellow
                                5: (255, 0, 255),    # Magenta
                                6: (0, 255, 255),    # Cyan
                                7: (255, 165, 0),    # Orange
                                8: (128, 0, 128),    # Purple
                            }
                            if color_id in colors:
                                cue_point['red'], cue_point['green'], cue_point['blue'] = colors[color_id]
                        cue_points.append(cue_point)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get hot cues for track {track_id}: {e}[/yellow]")
        
        # Fall back to get_track_cue_points if available
        if not cue_points and hasattr(self.db, 'get_track_cue_points'):
            try:
                cue_points = self.db.get_track_cue_points(track_id)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get cue points for track {track_id}: {e}[/yellow]")
        
        # Add position mark elements if we have cue points
        if cue_points:
            for cue in cue_points:
                attrs = {
                    'Name': str(cue.get('name', '')),
                    'Type': str(cue.get('type', '0')),
                    'Start': str(cue.get('position', '0.0')),
                    'Num': str(cue.get('hot_cue_number', '-1'))
                }
                
                # Add color information if available
                if 'red' in cue and 'green' in cue and 'blue' in cue:
                    attrs['Red'] = str(cue.get('red', '0'))
                    attrs['Green'] = str(cue.get('green', '0'))
                    attrs['Blue'] = str(cue.get('blue', '0'))
                
                etree.SubElement(track_elem, "POSITION_MARK", **attrs)
    
    def _add_playlists(self, xml, progress, verbose: bool) -> None:
        """
        Add playlists to the XML.
        
        Args:
            xml: The RekordboxXml instance
            progress: Progress instance for reporting
            verbose: Whether to show verbose output
        """
        
        # Try to get playlists from different methods
        playlist_folders = []
        regular_playlists = []
        
        # SQLクエリを使用してプレイリスト情報を取得
        try:
            from sqlalchemy import text
            
            if hasattr(self.db, 'engine'):
                with self.db.engine.connect() as conn:
                    # プレイリストフォルダを取得 (Attribute = 1 がフォルダ)
                    folder_query = text("SELECT ID, Seq, Name, ParentID FROM djmdPlaylist WHERE Attribute = 1 ORDER BY Seq")
                    folder_results = conn.execute(folder_query).fetchall()
                    
                    for folder in folder_results:
                        folder_dict = {
                            'Id': folder[0],
                            'Seq': folder[1],
                            'Name': folder[2],
                            'ParentId': folder[3]
                        }
                        playlist_folders.append(folder_dict)
                    
                    # 通常のプレイリストを取得 (Attribute = 0 が通常のプレイリスト)
                    playlist_query = text("SELECT ID, Seq, Name, ParentID FROM djmdPlaylist WHERE Attribute = 0 ORDER BY Seq")
                    playlist_results = conn.execute(playlist_query).fetchall()
                    
                    for playlist in playlist_results:
                        playlist_dict = {
                            'Id': playlist[0],
                            'Seq': playlist[1],
                            'Name': playlist[2],
                            'ParentId': playlist[3]
                        }
                        regular_playlists.append(playlist_dict)
                    
                    if self.console:
                        self.console.log(f"[green]Found {len(playlist_folders)} folders and {len(regular_playlists)} playlists using SQL query[/green]")
            else:
                # 従来のメソッドを試す（フォールバック）
                # Get playlist folders
                if hasattr(self.db, 'get_playlist_folders'):
                    playlist_folders = self.db.get_playlist_folders()
                elif hasattr(self.db, 'get_folders'):
                    playlist_folders = self.db.get_folders()
                elif hasattr(self.db, 'get_playlist'):
                    # In pyrekordbox 0.4.0, we can get all playlists and filter folders
                    all_playlists = self.db.get_playlist()
                    for playlist in all_playlists:
                        # Check if it's a folder (Type=0)
                        if hasattr(playlist, 'Type') and getattr(playlist, 'Type') == 0:
                            playlist_folders.append(playlist)
                
                # Get regular playlists
                if hasattr(self.db, 'get_playlists'):
                    regular_playlists = self.db.get_playlists()
                elif hasattr(self.db, 'get_playlist'):
                    # In pyrekordbox 0.4.0, we can get all playlists and filter non-folders
                    all_playlists = self.db.get_playlist()
                    for playlist in all_playlists:
                        # Check if it's not a folder (Type=1)
                        if hasattr(playlist, 'Type') and getattr(playlist, 'Type') == 1:
                            regular_playlists.append(playlist)
        except Exception as e:
            if self.console:
                self.console.log(f"[yellow]Warning: Failed to get playlists using SQL: {e}[/yellow]")
            
            # 従来のメソッドを試す（フォールバック）
            try:
                # Get playlist folders
                if hasattr(self.db, 'get_playlist_folders'):
                    playlist_folders = self.db.get_playlist_folders()
                elif hasattr(self.db, 'get_folders'):
                    playlist_folders = self.db.get_folders()
                elif hasattr(self.db, 'get_playlist'):
                    # In pyrekordbox 0.4.0, we can get all playlists and filter folders
                    all_playlists = self.db.get_playlist()
                    for playlist in all_playlists:
                        # Check if it's a folder (Type=0)
                        if hasattr(playlist, 'Type') and getattr(playlist, 'Type') == 0:
                            playlist_folders.append(playlist)
                
                # Get regular playlists
                if hasattr(self.db, 'get_playlists'):
                    regular_playlists = self.db.get_playlists()
                elif hasattr(self.db, 'get_playlist'):
                    # In pyrekordbox 0.4.0, we can get all playlists and filter non-folders
                    all_playlists = self.db.get_playlist()
                    for playlist in all_playlists:
                        # Check if it's not a folder (Type=1)
                        if hasattr(playlist, 'Type') and getattr(playlist, 'Type') == 1:
                            regular_playlists.append(playlist)
            except Exception as e2:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get playlists using fallback methods: {e2}[/yellow]")
        
        # Convert DjmdContent objects to dictionaries if needed
        normalized_folders = []
        for folder in playlist_folders:
            folder_dict = {}
            
            # Handle both dictionary and object access
            try:
                # Try object attribute access first
                if hasattr(folder, 'ID'):
                    folder_dict['Id'] = getattr(folder, 'ID')
                elif hasattr(folder, 'Id'):
                    folder_dict['Id'] = getattr(folder, 'Id')
                
                if hasattr(folder, 'ParentID'):
                    folder_dict['ParentId'] = getattr(folder, 'ParentID')
                elif hasattr(folder, 'ParentId'):
                    folder_dict['ParentId'] = getattr(folder, 'ParentId')
                
                if hasattr(folder, 'Name'):
                    folder_dict['Name'] = getattr(folder, 'Name')
                
                # If we couldn't get the required fields, try dictionary access
                if 'Id' not in folder_dict:
                    # Try dictionary access for various field names
                    for id_field in ['Id', 'id', 'ID', 'folder_id']:
                        if hasattr(folder, '__getitem__') and id_field in folder:
                            folder_dict['Id'] = folder[id_field]
                            break
                
                if 'ParentId' not in folder_dict:
                    for parent_field in ['ParentId', 'parent_id', 'parentId', 'parent']:
                        if hasattr(folder, '__getitem__') and parent_field in folder:
                            folder_dict['ParentId'] = folder[parent_field]
                            break
                
                if 'Name' not in folder_dict:
                    if hasattr(folder, '__getitem__') and 'Name' in folder:
                        folder_dict['Name'] = folder['Name']
                    elif hasattr(folder, '__getitem__') and 'name' in folder:
                        folder_dict['Name'] = folder['name']
                
                # Default values if still missing
                if 'Id' not in folder_dict:
                    continue  # Skip folders without ID
                
                if 'ParentId' not in folder_dict:
                    folder_dict['ParentId'] = 0
                
                if 'Name' not in folder_dict:
                    folder_dict['Name'] = 'Unnamed Folder'
                
                normalized_folders.append(folder_dict)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not process folder: {str(e)}[/yellow]")
        
        # Normalize playlist objects
        normalized_playlists = []
        for playlist in regular_playlists:
            playlist_dict = {}
            
            # Handle both dictionary and object access
            try:
                # Try object attribute access first
                if hasattr(playlist, 'ID'):
                    playlist_dict['Id'] = getattr(playlist, 'ID')
                elif hasattr(playlist, 'Id'):
                    playlist_dict['Id'] = getattr(playlist, 'Id')
                
                if hasattr(playlist, 'ParentID'):
                    playlist_dict['ParentId'] = getattr(playlist, 'ParentID')
                elif hasattr(playlist, 'ParentId'):
                    playlist_dict['ParentId'] = getattr(playlist, 'ParentId')
                
                if hasattr(playlist, 'Name'):
                    playlist_dict['Name'] = getattr(playlist, 'Name')
                
                # If we couldn't get the required fields, try dictionary access
                if 'Id' not in playlist_dict:
                    # Try dictionary access for various field names
                    for id_field in ['Id', 'id', 'ID', 'playlist_id']:
                        if hasattr(playlist, '__getitem__') and id_field in playlist:
                            playlist_dict['Id'] = playlist[id_field]
                            break
                
                if 'ParentId' not in playlist_dict:
                    for parent_field in ['ParentId', 'parent_id', 'parentId', 'parent']:
                        if hasattr(playlist, '__getitem__') and parent_field in playlist:
                            playlist_dict['ParentId'] = playlist[parent_field]
                            break
                
                if 'Name' not in playlist_dict:
                    if hasattr(playlist, '__getitem__') and 'Name' in playlist:
                        playlist_dict['Name'] = playlist['Name']
                    elif hasattr(playlist, '__getitem__') and 'name' in playlist:
                        playlist_dict['Name'] = playlist['name']
                
                # Default values if still missing
                if 'Id' not in playlist_dict:
                    continue  # Skip playlists without ID
                
                if 'ParentId' not in playlist_dict:
                    playlist_dict['ParentId'] = 0
                
                if 'Name' not in playlist_dict:
                    playlist_dict['Name'] = 'Unnamed Playlist'
                
                normalized_playlists.append(playlist_dict)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not process playlist: {str(e)}[/yellow]")
        
        if verbose:
            self.console.log(f"Found {len(normalized_playlists)} playlists and {len(normalized_folders)} folders")
            playlist_task = progress.add_task("Processing playlists...", total=len(normalized_playlists) + len(normalized_folders))
        else:
            playlist_task = None
        
        # Process folders and playlists using pyrekordbox.rbxml API
        folder_map = {0: xml.root_playlist_folder}  # Map folder IDs to Node objects, 0 is ROOT
        
        # First add all folders
        for folder in sorted(normalized_folders, key=lambda f: f.get('ParentId', 0)):
            try:
                folder_id = folder.get('Id')
                parent_id = folder.get('ParentId', 0)
                folder_name = folder.get('Name', 'Unnamed Folder')
                
                # Get parent node
                parent_node = folder_map.get(parent_id)
                if parent_node is None:
                    # If parent not found, add to root
                    parent_node = xml.root_playlist_folder
                
                # Add folder
                folder_node = parent_node.add_playlist_folder(folder_name)
                folder_map[folder_id] = folder_node
                
                if verbose and playlist_task:
                    progress.update(playlist_task, advance=1)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not add folder {folder.get('Name')}: {str(e)}[/yellow]")
        
        # Add playlists
        for playlist in normalized_playlists:
            try:
                playlist_id = playlist.get('Id')
                parent_id = playlist.get('ParentId', 0)
                playlist_name = playlist.get('Name', 'Unnamed Playlist')
                
                # Get parent node
                parent_node = folder_map.get(parent_id)
                if parent_node is None:
                    # If parent not found, add to root
                    parent_node = xml.root_playlist_folder
                
                # Add playlist
                playlist_node = parent_node.add_playlist(playlist_name)
                
                # Add tracks to playlist
                self._add_tracks_to_playlist(xml, playlist_node, playlist_id)
                
                if verbose and playlist_task:
                    progress.update(playlist_task, advance=1)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not add playlist {playlist.get('Name')}: {str(e)}[/yellow]")
    
    def _add_tracks_to_playlist(self, xml, playlist_node, playlist_id) -> None:
        """
        Add tracks to a playlist.
        
        Args:
            xml: The RekordboxXml instance
            playlist_node: The playlist node to add tracks to
            playlist_id: ID of the playlist to get tracks for
        """
        # Get tracks in playlist
        playlist_entries = []
        
        # SQLクエリを使用してプレイリスト内の曲情報を取得
        try:
            from sqlalchemy import text
            
            if hasattr(self.db, 'engine'):
                with self.db.engine.connect() as conn:
                    # プレイリスト内の曲を取得
                    query = text(f"SELECT ContentID, TrackNo FROM djmdSongPlaylist WHERE PlaylistID = :playlist_id ORDER BY TrackNo")
                    entries = conn.execute(query, {"playlist_id": playlist_id}).fetchall()
                    
                    for entry in entries:
                        entry_dict = {
                            'TrackID': entry[0],
                            'TrackNo': entry[1]
                        }
                        playlist_entries.append(entry_dict)
                    
                    if self.console and len(playlist_entries) > 0:
                        self.console.log(f"[green]Found {len(playlist_entries)} tracks in playlist {playlist_id} using SQL query[/green]")
            else:
                # 従来のメソッドを試す（フォールバック）
                if hasattr(self.db, 'get_playlist_entries'):
                    playlist_entries = self.db.get_playlist_entries(playlist_id)
                elif hasattr(self.db, 'get_playlist_songs'):
                    playlist_entries = self.db.get_playlist_songs(playlist_id)
                elif hasattr(self.db, 'get_playlist_contents'):
                    playlist_entries = self.db.get_playlist_contents(playlist_id)
        except Exception as e:
            if self.console:
                self.console.log(f"[yellow]Warning: Failed to get playlist entries using SQL: {e}[/yellow]")
            
            # 従来のメソッドを試す（フォールバック）
            try:
                if hasattr(self.db, 'get_playlist_entries'):
                    playlist_entries = self.db.get_playlist_entries(playlist_id)
                elif hasattr(self.db, 'get_playlist_songs'):
                    playlist_entries = self.db.get_playlist_songs(playlist_id)
                elif hasattr(self.db, 'get_playlist_contents'):
                    playlist_entries = self.db.get_playlist_contents(playlist_id)
            except Exception as e2:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get playlist entries using fallback methods: {e2}[/yellow]")
        
        # Normalize playlist entries
        normalized_entries = []
        for entry in playlist_entries:
            entry_dict = {}
            
            # Try to get track ID from object attributes first
            try:
                if hasattr(entry, 'ContentID'):
                    entry_dict['TrackID'] = getattr(entry, 'ContentID')
                elif hasattr(entry, 'ID'):
                    entry_dict['TrackID'] = getattr(entry, 'ID')
                elif hasattr(entry, 'TrackID'):
                    entry_dict['TrackID'] = getattr(entry, 'TrackID')
                
                # If we couldn't get the required fields, try dictionary access
                if 'TrackID' not in entry_dict:
                    # Try dictionary access for various field names
                    for field in ['TrackID', 'track_id', 'ID', 'id', 'ContentID', 'content_id']:
                        if hasattr(entry, '__getitem__') and field in entry:
                            entry_dict['TrackID'] = entry[field]
                            break
                
                if 'TrackID' in entry_dict:
                    normalized_entries.append(entry_dict)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not process playlist entry: {str(e)}[/yellow]")
        
        # Add tracks to playlist
        for entry in normalized_entries:
            track_id = entry.get('TrackID')
            if track_id:
                try:
                    # pyrekordbox 0.4.0のAPIでは、add_trackメソッドはtrack_idキーワード引数を受け付けない
                    # 代わりにトラックIDを直接渡す
                    playlist_node.add_track(str(track_id))
                except Exception as e:
                    # 別の方法を試す
                    try:
                        # XMLオブジェクトからトラックを取得して追加する
                        track = xml.get_track(str(track_id))
                        if track:
                            playlist_node.add_track(track)
                        else:
                            # トラックIDを持つ要素を直接作成して追加
                            track_elem = etree.Element("TRACK", KEY=str(track_id))
                            playlist_node.append(track_elem)
                    except Exception as e2:
                        if self.console:
                            self.console.log(f"[yellow]Warning: Could not add track {track_id} to playlist: {str(e)} / {str(e2)}[/yellow]")
    
    def _add_playlist_to_node(self, parent_node: etree.Element, playlist: Dict) -> etree.Element:
        """
        Add a playlist as a NODE to a parent NODE.
        
        Args:
            parent_node: Parent NODE element
            playlist: Playlist data from the database
            
        Returns:
            The created playlist NODE element
        """
        # Create playlist node
        playlist_node = etree.SubElement(
            parent_node,
            "NODE",
            Name=playlist.get('Name', 'Unnamed Playlist'),
            Type="1",  # Playlist type
            KeyType="0",  # Track ID type
            Entries="0"  # Will update count later
        )
        
        # Get tracks in this playlist
        playlist_tracks = []
        playlist_id = playlist.get('Id')
        
        # Try different methods to get playlist tracks
        if hasattr(self.db, 'get_playlist_entries'):
            try:
                playlist_tracks = self.db.get_playlist_entries(playlist_id)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get playlist entries for {playlist.get('Name')}: {e}[/yellow]")
        
        # Try alternative method if available
        if not playlist_tracks and hasattr(self.db, 'get_playlist_tracks'):
            try:
                playlist_tracks = self.db.get_playlist_tracks(playlist_id)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get playlist tracks for {playlist.get('Name')}: {e}[/yellow]")
        
        # Normalize track entry field names
        normalized_tracks = []
        for track_entry in playlist_tracks:
            # Find track ID with various field names
            track_id = None
            for field in ['TrackId', 'track_id', 'id', 'ID', 'track_ID', 'ContentId']:
                if field in track_entry and track_entry[field] is not None:
                    track_id = track_entry[field]
                    break
            
            if track_id:
                normalized_tracks.append({'TrackId': track_id})
        
        # Add tracks to playlist
        for track_entry in normalized_tracks:
            track_id = track_entry.get('TrackId')
            etree.SubElement(playlist_node, "TRACK", Key=str(track_id))
        
        # Update entries count
        playlist_node.set('Entries', str(len(normalized_tracks)))
        
        return playlist_node
    
    def _add_folder_to_node(self, parent_node: etree.Element, folder: Dict) -> etree.Element:
        """
        Add a folder as a NODE to a parent NODE.
        
        Args:
            parent_node: Parent NODE element
            folder: Folder data from the database
            
        Returns:
            The created folder NODE element
        """
        # Create folder node
        folder_node = etree.SubElement(
            parent_node,
            "NODE",
            Name=folder.get('Name', 'Unnamed Folder'),
            Type="0",  # Folder type
            Count="0"  # Will update count later
        )
        
        return folder_node
    
    def _add_subfolders_recursively(
        self, 
        parent_node: etree.Element, 
        parent_folder: Dict, 
        all_folders: List[Dict], 
        all_playlists: List[Dict]
    ) -> None:
        """
        Recursively add subfolders and their contents to a parent folder.
        
        Args:
            parent_node: Parent NODE element
            parent_folder: Parent folder data
            all_folders: List of all folder data
            all_playlists: List of all playlist data
        """
        parent_id = parent_folder.get('Id')
        
        # Find subfolders of this parent
        subfolders = [f for f in all_folders if f.get('ParentId') == parent_id]
        
        # Find playlists directly in this folder
        folder_playlists = [p for p in all_playlists if p.get('ParentId') == parent_id]
        
        # Update count
        parent_node.set('Count', str(len(subfolders) + len(folder_playlists)))
        
        # Add each subfolder
        for subfolder in subfolders:
            subfolder_node = self._add_folder_to_node(parent_node, subfolder)
            
            # Recursively add contents to this subfolder
            self._add_subfolders_recursively(subfolder_node, subfolder, all_folders, all_playlists)
    
    def close(self) -> None:
        """Close the database connection when done."""
        # In version 0.4.0+ closing might not be necessary, 
        # but we'll call it if the method exists
        if hasattr(self.db, 'close'):
            try:
                self.db.close()
            except Exception:
                pass  # Ignore errors when closing


def export_rekordbox_db_to_xml(db_path: Optional[str], output_path: str, verbose: bool = False, db_key: Optional[str] = None) -> None:
    """
    Export a Rekordbox database to XML format.
    
    Args:
        db_path: Path to the Rekordbox database file, or None to auto-detect
        output_path: Path where the XML file should be saved
        verbose: Show detailed output during export
        db_key: Rekordbox database key (optional, for newer Rekordbox versions)
    """
    console = Console()
    exporter = RekordboxXMLExporter(db_path, console=console, db_key=db_key)
    try:
        exporter.generate_xml(output_path, verbose)
    finally:
        exporter.close()


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:
        # With specified database
        db_path = sys.argv[1]
        output_path = sys.argv[2]
        export_rekordbox_db_to_xml(db_path, output_path, verbose=True)
    elif len(sys.argv) == 2:
        # Auto-detect database
        output_path = sys.argv[1]
        export_rekordbox_db_to_xml(None, output_path, verbose=True)
    else:
        print("Usage:")
        print("  python rkbdb2xml.py /path/to/output.xml")
        print("  python rkbdb2xml.py /path/to/rekordbox.db /path/to/output.xml")
        sys.exit(1)

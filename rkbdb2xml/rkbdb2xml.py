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
        Download the Rekordbox database key using pyrekordbox CLI.
        
        Returns:
            The downloaded key if successful, None otherwise
        """
        try:
            import subprocess
            import sys
            import json
            import os
            from pathlib import Path
            
            if self.console:
                self.console.log("[yellow]Downloading Rekordbox database key...[/yellow]")
            
            # Get the Python executable path from the current environment
            python_exe = sys.executable
            
            # Run the pyrekordbox CLI command to download the key
            result = subprocess.run(
                [python_exe, "-m", "pyrekordbox", "download-key"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                if self.console:
                    self.console.log("[green]Successfully downloaded Rekordbox database key[/green]")
                
                # Try to read the key from the pyrekordbox config file
                try:
                    # Find the pyrekordbox config file location
                    home_dir = Path.home()
                    config_dir = home_dir / ".pyrekordbox"
                    config_file = config_dir / "config.json"
                    
                    if config_file.exists():
                        with open(config_file, 'r') as f:
                            config = json.load(f)
                            if 'dp' in config:
                                return config['dp']
                except Exception as config_error:
                    if self.console:
                        self.console.log(f"[yellow]Could not read key from config: {str(config_error)}[/yellow]")
                
                return None
            else:
                if self.console:
                    self.console.log(f"[red]Failed to download key: {result.stderr}[/red]")
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
        if hasattr(self.db, 'search_content'):
            # search_content now requires a text parameter, use empty string to get all tracks
            tracks = self.db.search_content("")
        elif hasattr(self.db, 'get_content'):
            tracks = self.db.get_content()
        elif hasattr(self.db, 'get_tracks'):
            tracks = self.db.get_tracks()
        else:
            tracks = []
            if self.console:
                self.console.log("[yellow]Warning: Unable to find method to get tracks[/yellow]")
        
        if verbose:
            self.console.log(f"Found {len(tracks)} tracks in database")
        
        # Create a track processing task if in verbose mode
        track_task = None
        if verbose:
            track_task = progress.add_task("Processing tracks...", total=len(tracks))
        
        # Add each track to the collection
        for track in tracks:
            self._add_track_to_xml(xml, track)
            if track_task:
                progress.update(track_task, advance=1)
    
    def _add_track_to_xml(self, xml, track) -> None:
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
            
            # For location, check if FolderPath and FileNameL exist and combine them
            folder_path = getattr(track, 'FolderPath', '')
            file_name = getattr(track, 'FileNameL', '')
            if folder_path and file_name:
                location = os.path.join(folder_path, file_name)
            else:
                location = ''
                
            # Prepare track attributes
            track_attrs = {}
            for db_field, xml_attr in self._track_attribute_mapping().items():
                # Try to get the attribute value
                if hasattr(track, db_field):
                    value = getattr(track, db_field)
                    if value is not None:
                        value = str(value)
                        # Handle special case for file location
                        if db_field == 'Location' or (db_field == 'FolderPath' and file_name):
                            value = self._format_file_location(location)
                            location = value  # Store formatted location for add_track method
                        track_attrs[xml_attr] = value
        except Exception as attr_error:
            # Fallback to dictionary access if attribute access fails
            try:
                track_id = str(track.get('ID', ''))
                location = track.get('Location', '')
                
                # Prepare track attributes
                track_attrs = {}
                for db_field, xml_attr in self._track_attribute_mapping().items():
                    if db_field in track and track[db_field] is not None:
                        value = str(track[db_field])
                        # Handle special case for file location
                        if db_field == 'Location':
                            value = self._format_file_location(value)
                            location = value  # Store formatted location for add_track method
                        track_attrs[xml_attr] = value
            except Exception as dict_error:
                if self.console:
                    self.console.log(f"[yellow]Warning: Could not process track: {str(dict_error)}[/yellow]")
                return
        
        # Add track to XML
        try:
            # Use pyrekordbox.rbxml's add_track method
            xml_track = xml.add_track(location, **track_attrs)
            
            # Add tempo markers and position markers if available
            # Note: In the future, we can modify this to use pyrekordbox.rbxml's API
            # for adding tempo and position markers if it becomes available
            pass
        except Exception as e:
            if self.console:
                self.console.log(f"[yellow]Warning: Could not add track {track_id}: {str(e)}[/yellow]")
    
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
            'Composer': 'Composer',
            'Album': 'Album',
            'Grouping': 'Grouping',
            'Genre': 'Genre',
            'Kind': 'Kind',
            'Size': 'Size',
            'TotalTime': 'TotalTime',
            'DiscNumber': 'DiscNumber',
            'TrackNumber': 'TrackNumber',
            'Year': 'Year',
            'AverageBpm': 'AverageBpm', 
            'DateAdded': 'DateAdded',
            'BitRate': 'BitRate',
            'SampleRate': 'SampleRate',
            'Comments': 'Comments',
            'PlayCount': 'PlayCount',
            'Rating': 'Rating',
            'Location': 'Location',
            'Remixer': 'Remixer',
            'Tonality': 'Tonality',
            'Label': 'Label',
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
        Format file path as Rekordbox XML expects.
        
        Args:
            path: File path from the database
            
        Returns:
            Formatted file URL
        """
        if path.startswith('file://'):
            return path
        
        # Convert to file:// URL format
        # Encode spaces and special characters
        import urllib.parse
        path = os.path.abspath(path)
        path = urllib.parse.quote(path)
        
        # Ensure localhost is in the path
        if not path.startswith('/'):
            path = '/' + path
        
        return f"file://localhost{path}"
    
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
        
        # Get playlist folders
        if hasattr(self.db, 'get_playlist_folders'):
            try:
                playlist_folders = self.db.get_playlist_folders()
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get playlist folders: {e}[/yellow]")
                
                # Try alternative methods
                if hasattr(self.db, 'get_folders'):
                    try:
                        playlist_folders = self.db.get_folders()
                    except Exception as e2:
                        if self.console:
                            self.console.log(f"[yellow]Warning: Failed to get folders: {e2}[/yellow]")
        
        # Get regular playlists
        if hasattr(self.db, 'get_playlists'):
            try:
                regular_playlists = self.db.get_playlists()
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get playlists: {e}[/yellow]")
        
        # Handle different API formats for playlists and folders
        # Normalize field names
        for folder in playlist_folders:
            # Ensure ID is available as 'Id'
            if 'Id' not in folder and 'id' in folder:
                folder['Id'] = folder['id']
            elif 'Id' not in folder and 'ID' in folder:
                folder['Id'] = folder['ID']
            elif 'Id' not in folder and 'folder_id' in folder:
                folder['Id'] = folder['folder_id']
                
            # Ensure Parent ID is available as 'ParentId'
            if 'ParentId' not in folder and 'parent_id' in folder:
                folder['ParentId'] = folder['parent_id']
            elif 'ParentId' not in folder and 'parentId' in folder:
                folder['ParentId'] = folder['parentId']
            elif 'ParentId' not in folder and 'parent' in folder:
                folder['ParentId'] = folder['parent']
            
            # Ensure Name is available
            if 'Name' not in folder and 'name' in folder:
                folder['Name'] = folder['name']
                
            # Default ParentId to 0 if missing
            if 'ParentId' not in folder:
                folder['ParentId'] = 0
        
        # Normalize playlist fields
        for playlist in regular_playlists:
            # Ensure ID is available as 'Id'
            if 'Id' not in playlist and 'id' in playlist:
                playlist['Id'] = playlist['id']
            elif 'Id' not in playlist and 'ID' in playlist:
                playlist['Id'] = playlist['ID']
            elif 'Id' not in playlist and 'playlist_id' in playlist:
                playlist['Id'] = playlist['playlist_id']
                
            # Ensure Parent ID is available as 'ParentId'
            if 'ParentId' not in playlist and 'parent_id' in playlist:
                playlist['ParentId'] = playlist['parent_id']
            elif 'ParentId' not in playlist and 'parentId' in playlist:
                playlist['ParentId'] = playlist['parentId']
            elif 'ParentId' not in playlist and 'parent' in playlist:
                playlist['ParentId'] = playlist['parent']
                
            # Ensure Name is available
            if 'Name' not in playlist and 'name' in playlist:
                playlist['Name'] = playlist['name']
                
            # Default ParentId to 0 if missing
            if 'ParentId' not in playlist:
                playlist['ParentId'] = 0
        
        if verbose:
            self.console.log(f"Found {len(regular_playlists)} playlists and {len(playlist_folders)} folders")
            playlist_task = progress.add_task("Processing playlists...", total=len(regular_playlists) + len(playlist_folders))
        else:
            playlist_task = None
        
        # Process folders and playlists using pyrekordbox.rbxml API
        folder_map = {0: xml.root_playlist_folder}  # Map folder IDs to Node objects, 0 is ROOT
        
        # First add all folders
        for folder in sorted(playlist_folders, key=lambda f: f.get('ParentId', 0)):
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
        for playlist in regular_playlists:
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
        
        # Try different methods to get playlist entries
        if hasattr(self.db, 'get_playlist_entries'):
            try:
                playlist_entries = self.db.get_playlist_entries(playlist_id)
            except Exception as e:
                if self.console:
                    self.console.log(f"[yellow]Warning: Failed to get playlist entries: {e}[/yellow]")
        
        # Add tracks to playlist
        for entry in playlist_entries:
            track_id = None
            # Try different field names for track ID
            for field in ['TrackID', 'track_id', 'ID', 'id', 'ContentID', 'content_id']:
                if field in entry and entry[field] is not None:
                    track_id = entry[field]
                    break
            
            if track_id:
                try:
                    # Add track to playlist using track ID
                    playlist_node.add_track(track_id=track_id)
                except Exception as e:
                    if self.console:
                        self.console.log(f"[yellow]Warning: Could not add track {track_id} to playlist: {str(e)}[/yellow]")
    
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

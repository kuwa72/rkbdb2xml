#!/usr/bin/env python3
"""
Compare tracks between two Rekordbox XML files and list tracks that exist only in the first file.
"""

import sys
import xml.etree.ElementTree as ET
from typing import List, Dict, Set, Tuple
from rich.console import Console
from rich.table import Table

def extract_tracks(xml_file: str) -> Dict[str, Dict]:
    """
    Extract tracks from a Rekordbox XML file.
    
    Args:
        xml_file: Path to the XML file
        
    Returns:
        Dictionary of tracks with TrackID as key
    """
    tree = ET.parse(xml_file)
    root = tree.getroot()
    
    tracks = {}
    for track in root.findall('.//TRACK'):
        track_id = track.get('TrackID')
        if track_id:
            track_data = {attr: track.get(attr) for attr in track.attrib}
            tracks[track_id] = track_data
    
    return tracks

def compare_tracks(file1: str, file2: str) -> Tuple[Dict[str, Dict], Set[str], Set[str], Set[str]]:
    """
    Compare tracks between two XML files.
    
    Args:
        file1: Path to the first XML file
        file2: Path to the second XML file
        
    Returns:
        Tuple containing:
        - Dictionary of tracks from file1
        - Set of track IDs only in file1
        - Set of track IDs only in file2
        - Set of track IDs in both files
    """
    tracks1 = extract_tracks(file1)
    tracks2 = extract_tracks(file2)
    
    track_ids1 = set(tracks1.keys())
    track_ids2 = set(tracks2.keys())
    
    only_in_file1 = track_ids1 - track_ids2
    only_in_file2 = track_ids2 - track_ids1
    in_both = track_ids1.intersection(track_ids2)
    
    return tracks1, only_in_file1, only_in_file2, in_both

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <file1.xml> <file2.xml>")
        sys.exit(1)
    
    file1 = sys.argv[1]
    file2 = sys.argv[2]
    
    console = Console()
    
    try:
        tracks1, only_in_file1, only_in_file2, in_both = compare_tracks(file1, file2)
        
        console.print(f"\n[bold]トラック比較: {file1} と {file2}[/bold]")
        console.print(f"[green]合計トラック数: {file1}={len(tracks1)}, {file2}={len(extract_tracks(file2))}[/green]")
        console.print(f"[yellow]{file1}のみに存在するトラック数: {len(only_in_file1)}[/yellow]")
        console.print(f"[yellow]{file2}のみに存在するトラック数: {len(only_in_file2)}[/yellow]")
        console.print(f"[green]両方に存在するトラック数: {len(in_both)}[/green]")
        
        if only_in_file1:
            console.print(f"\n[bold]{file1}のみに存在するトラック:[/bold]")
            
            table = Table(show_header=True, header_style="bold")
            table.add_column("TrackID", style="dim")
            table.add_column("Name")
            table.add_column("Artist")
            table.add_column("Album")
            table.add_column("Genre")
            table.add_column("Location", width=50)
            
            for track_id in sorted(only_in_file1):
                track = tracks1[track_id]
                table.add_row(
                    track_id,
                    track.get('Name', ''),
                    track.get('Artist', ''),
                    track.get('Album', ''),
                    track.get('Genre', ''),
                    track.get('Location', '')[:50]  # Truncate long locations
                )
            
            console.print(table)
    
    except Exception as e:
        console.print(f"[bold red]エラー: {str(e)}[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    main()

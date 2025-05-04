"""
Command line interface for rkbdb2xml.
"""

import os
from pathlib import Path
from typing import Optional, List

import typer

from .rkbdb2xml import export_rekordbox_db_to_xml

app = typer.Typer(
    help="Generate XML file from Rekordbox database using pyrekordbox library.",
    add_completion=False,
)

@app.command()
def export(
    db_path: Optional[Path] = typer.Argument(
        None,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to the Rekordbox database file (optional, auto-detected if not provided)",
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        file_okay=True,
        dir_okay=False,
        writable=True,
        help="Path where the XML file should be saved",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite output file if it already exists"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show verbose output"),
    db_key: Optional[str] = typer.Option(
        None,
        "--key",
        "-k",
        help="Rekordbox database key (required for Rekordbox 6.6.5+)",
    ),
    roman: bool = typer.Option(
        False,
        "--roman",
        help="Convert title, artist, album to romaji using romann library."
    ),
    bpm: bool = typer.Option(
        False,
        "--bpm",
        help="Add BPM as integer at the beginning of the title."
    ),
    orderby: str = typer.Option(
        "default",
        "--orderby",
        help="Specify the order of tracks in the playlist (default/bpm). bpm specifies BPM in ascending order."
    ),
    playlists: Optional[List[str]] = typer.Option(
        None,
        "--playlists", "-p",
        help="Comma-separated or repeated list of playlist IDs, names, or hierarchical paths."
    ),
) -> None:
    """
    Export a Rekordbox database to XML format.

    This tool creates an XML file in the same format as the Rekordbox XML export feature.
    If no database path is provided, pyrekordbox will attempt to automatically locate
    the Rekordbox database on your system.
    """
    if output.exists() and not force:
        print(f"Output file {output} already exists. Use --force to overwrite.")
        raise typer.Exit(1)
    
    # Parse playlist options into list of specs
    parsed_playlists: Optional[List[str]] = None
    if playlists:
        parsed: List[str] = []
        for spec in playlists:
            parsed.extend([s.strip() for s in spec.split(',') if s.strip()])
        parsed_playlists = parsed

    try:
        # Convert Path to str if db_path is provided, otherwise pass None
        db_path_str = str(db_path) if db_path else None
        export_rekordbox_db_to_xml(
            db_path_str,
            str(output),
            db_key,
            verbose,
            roman,
            bpm,
            orderby,
            parsed_playlists,
        )
    except Exception as e:
        print(f"Failed to export Rekordbox database to XML: {e}")
        if verbose:
            # Print full traceback
            import traceback
            traceback.print_exc()
        raise typer.Exit(1)


@app.command("list-playlists")
def list_playlists(
    db_path: Optional[Path] = typer.Argument(
        None,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to the Rekordbox database file (optional, auto-detected if not provided)"
    ),
    format: str = typer.Option(
        "table",
        "--format", "-f",
        help="Output format: table|csv|json"
    ),
) -> None:
    """
    List available playlists from the Rekordbox database, showing hierarchy.
    """
    import json, csv, sys
    from pyrekordbox.db6 import Rekordbox6Database as RekordboxDatabase

    db_path_str = str(db_path) if db_path else None
    db = RekordboxDatabase(db_path_str)
    pls = db.get_playlist().all()
    id_map = {pl.ID: pl for pl in pls}
    parent_map: dict = {}
    for pl in pls:
        parent_map.setdefault(pl.ParentID, []).append(pl)
    # find roots
    root_parents = [pid for pid in parent_map.keys() if pid not in id_map]
    rows: list = []
    def traverse(pid, depth=0):
        for pl in sorted(parent_map.get(pid, []), key=lambda x: x.Name):
            rows.append({
                "id": pl.ID,
                "name": "  " * depth + pl.Name,
                "is_folder": pl.is_folder,
                "parent_id": pl.ParentID,
            })
            traverse(pl.ID, depth + 1)
    for rp in root_parents:
        traverse(rp)
    # output
    if format == "table":
        wid_id = max(len(str(r["id"])) for r in rows + [{"id":"ID"}])
        wid_name = max(len(r["name"]) for r in rows + [{"name":"Name"}])
        wid_folder = len("Folder")
        wid_parent = max(len(str(r["parent_id"])) for r in rows + [{"parent_id":"Parent"}])
        header = f"{'ID':<{wid_id}}  {'Name':<{wid_name}}  {'Folder':<{wid_folder}}  {'Parent':<{wid_parent}}"
        typer.echo(header)
        typer.echo("-" * len(header))
        for r in rows:
            typer.echo(f"{r['id']:<{wid_id}}  {r['name']:<{wid_name}}  {str(r['is_folder']):<{wid_folder}}  {r['parent_id']:<{wid_parent}}")
    elif format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["id","name","is_folder","parent_id"])
        for r in rows:
            writer.writerow([r['id'],r['name'],r['is_folder'],r['parent_id']])
    elif format == "json":
        typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"Unknown format: {format}", err=True)
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the version of rkbdb2xml."""
    from . import __version__
    print(f"rkbdb2xml version {__version__}")


def main() -> None:
    """Entry point for the application."""
    app()


if __name__ == "__main__":
    main()

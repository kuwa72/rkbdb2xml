"""
Command line interface for rkbdb2xml.
"""

import os
from pathlib import Path
from typing import Optional

import typer

from .rkbdb2xml import export_rekordbox_db_to_xml

app = typer.Typer(
    help="Generate XML file from Rekordbox database using pyrekordbox library.", 
    add_completion=False
)

@app.command()
def export(
    db_path: Optional[Path] = typer.Argument(
        None,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to the Rekordbox database file (optional, auto-detected if not provided)"
    ),
    output: Path = typer.Option(
        ...,
        "--output", "-o",
        file_okay=True,
        dir_okay=False,
        writable=True,
        help="Path where the XML file should be saved"
    ),
    force: bool = typer.Option(
        False,
        "--force", "-f",
        help="Overwrite output file if it already exists"
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose", "-v",
        help="Show verbose output"
    ),
    db_key: Optional[str] = typer.Option(
        None,
        "--key", "-k",
        help="Rekordbox database key (required for Rekordbox 6.6.5+)"
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
    
    try:
        # Convert Path to str if db_path is provided, otherwise pass None
        db_path_str = str(db_path) if db_path else None
        export_rekordbox_db_to_xml(db_path_str, str(output), db_key, verbose)
    except Exception as e:
        print(f"Failed to export Rekordbox database to XML: {e}")
        if verbose:
            # Print full traceback
            import traceback
            traceback.print_exc()
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

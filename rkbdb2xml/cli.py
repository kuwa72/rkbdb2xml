"""
Command line interface for rkbdb2xml.
"""

import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

from .rkbdb2xml import export_rekordbox_db_to_xml

app = typer.Typer(
    help="Generate XML file from Rekordbox database using pyrekordbox library.", 
    add_completion=False
)

console = Console()


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
        if not Confirm.ask(f"Output file {output} already exists. Overwrite?"):
            console.print("[bold red]Operation cancelled.[/bold red]")
            raise typer.Exit(1)
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}[/bold blue]"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Exporting Rekordbox database to XML...", total=None)
        
        try:
            # Convert Path to str if db_path is provided, otherwise pass None
            db_path_str = str(db_path) if db_path else None
            export_rekordbox_db_to_xml(db_path_str, str(output), verbose, db_key)
            progress.update(task, completed=True)
            console.print(f"[bold green]Successfully exported database to {output}[/bold green]")
        except Exception as e:
            progress.update(task, completed=True)
            console.print(f"[bold red]Error: {str(e)}[/bold red]")
            if verbose:
                console.print_exception()
            raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the version of rkbdb2xml."""
    from . import __version__
    console.print(f"rkbdb2xml version [bold]{__version__}[/bold]")


def main() -> None:
    """Entry point for the application."""
    app()


if __name__ == "__main__":
    main()

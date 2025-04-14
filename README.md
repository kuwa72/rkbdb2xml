# rkbdb2xml

A modern tool to generate XML from Rekordbox database using pyrekordbox library.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Overview

rkbdb2xml allows you to create XML exports from your Rekordbox database in the same format as the native Rekordbox XML export feature. This can be useful for:

- Backing up your collection in a portable format
- Analyzing your music library using other tools
- Batch processing your tracks and playlists
- Integrating with other software that supports Rekordbox XML format
- Creating custom DJ tools that interact with Rekordbox data

## Features

- Modern CLI interface with progress indicators
- Auto-detection of Rekordbox database location
- Export complete track metadata
- Support for playlists including nested folders
- Include tempo markers (beatgrids)  
- Include position markers (cue points)
- Well-structured output matching native Rekordbox XML format
- Comprehensive validation and comparison tools

## Installation

### Using pip (recommended)

```bash
# Create and activate a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate

# Install from PyPI
pip install rkbdb2xml
```

### Development Installation with Poetry

```bash
# Clone the repository
git clone https://github.com/kuwa72/rkbdb2xml.git
cd rkbdb2xml

# Create a virtual environment and install with Poetry
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate
pip install poetry
poetry install
```

### Alternative Development Installation with pip

```bash
# Clone the repository
git clone https://github.com/kuwa72/rkbdb2xml.git
cd rkbdb2xml

# Create a virtual environment and install in development mode
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate
pip install -e .
```

## Usage

The command-line interface provides easy access to all functionality:

### Basic Commands

```bash
# Auto-detect Rekordbox database and export to XML
rkbdb2xml export -o rekordbox_export.xml

# Specify a custom database path
rkbdb2xml export /path/to/rekordbox.db -o rekordbox_export.xml

# Show detailed progress with verbose flag
rkbdb2xml export -o rekordbox_export.xml --verbose

# Overwrite existing output file with force flag
rkbdb2xml export -o rekordbox_export.xml --force

# Show version information
rkbdb2xml version
```

### Command Help

```bash
# General help
rkbdb2xml --help

# Specific command help
rkbdb2xml export --help
```

## Python API Usage

You can also use rkbdb2xml as a library in your own Python code:

```python
from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_xml

# Auto-detect Rekordbox database and export to XML
export_rekordbox_db_to_xml(None, "output.xml", verbose=True)

# Specify a custom database path
export_rekordbox_db_to_xml("/path/to/rekordbox.db", "output.xml")
```

More advanced usage with custom configuration:

```python
from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter
from rich.console import Console

# Create a console for output
console = Console()

# Create an exporter with auto-detection
exporter = RekordboxXMLExporter(console=console)

# Generate XML
exporter.generate_xml("output.xml", verbose=True)

# Close the database connection
exporter.close()
```

## Validation and Comparison Tools

The project includes several utility tools for validating and comparing XML files:

```bash
# Compare two XML files
python tools/compare_xml.py original.xml generated.xml

# Analyze an XML file structure
python tools/analyze_xml.py rekordbox.xml

# Validate output against a sample
python tools/validate_xml.py sample.xml --output generated.xml

# Clean rewrite an XML file for structure verification
python tools/rewrite_xml.py input.xml output.xml
```

## Troubleshooting

### Common Issues

1. **Database not found**: If auto-detection fails, manually specify the database path:
   ```bash
   rkbdb2xml export /path/to/database/rekordbox.db -o output.xml
   ```

2. **Database location by OS**:
   - **Windows**: `C:\Users\[username]\AppData\Roaming\Pioneer\rekordbox\[version]\database.db`
   - **macOS**: `/Users/[username]/Library/Pioneer/rekordbox/[version]/database.db`

3. **Missing dependencies**: Ensure all dependencies are installed:
   ```bash
   pip install -r requirements.txt
   ```

4. **Permission errors**: Make sure you have appropriate read permissions for the Rekordbox database and write permissions for the output directory.

5. **Rekordbox version compatibility**: This tool is tested with Rekordbox 6.x. For other versions, please report any issues on the GitHub repository.

## Requirements

- Python 3.8+
- pyrekordbox
- lxml
- click and typer (for command line interface)
- rich (for terminal output formatting)

## Development

This project uses [Poetry](https://python-poetry.org/) for dependency management.

```bash
# Setup development environment
poetry install

# Run tests
poetry run pytest

# Run specific tests
poetry run pytest tests/test_rkbdb2xml.py

# Run with code coverage
poetry run pytest --cov=rkbdb2xml

# Run linting
poetry run flake8
poetry run mypy .
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

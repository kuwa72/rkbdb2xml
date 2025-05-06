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

- Modern CLI interface (export, list-playlists, version)
- Auto-detection of Rekordbox database path
- Export complete track metadata in Rekordbox XML format
- Support for nested playlist folders
- Optional romaji conversion (--roman) and BPM prefix (--bpm)
- Order tracks by default or BPM (--orderby bpm)
- Copy audio files to output directory, updating metadata tags
- Overwrite output with --force flag and verbose logging with --verbose

## Installation

### Using pip (recommended)

```bash
python -m venv .venv
.venv\Scripts\activate  # On Windows
pip install rkbdb2xml
```

### Development Installation

```bash
git clone https://github.com/kuwa72/rkbdb2xml.git
cd rkbdb2xml
python -m venv .venv
.venv\Scripts\activate  # On Windows
pip install -r requirements.txt
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

You can use rkbdb2xml as a library in your Python code:

```python
from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_xml

# Auto-detect and export to XML
export_rekordbox_db_to_xml(None, "output.xml", verbose=True)

# Specify a custom database path
export_rekordbox_db_to_xml("/path/to/rekordbox.db", "output.xml")
```

```python
from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter

# Create exporter with verbose output
exporter = RekordboxXMLExporter(None, None, use_verbose=True)
exporter.generate_xml("output.xml")
exporter.close()
```

## Requirements

- Python 3.8+
- pyrekordbox>=0.4.0
- lxml
- typer
- rich
- mutagen
- psutil

## Development

```bash
# Clone repository and setup development environment
git clone https://github.com/kuwa72/rkbdb2xml.git
cd rkbdb2xml
python -m venv .venv
.venv\Scripts\activate  # On Windows
pip install -r requirements.txt
pip install -e .

# Run tests
pytest tests/

# Run with coverage
pytest --cov=rkbdb2xml

# Lint and type-check
flake8
mypy .
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

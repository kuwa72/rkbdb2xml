# rkbdb2xml

Rekordbox のプレイリストや楽曲データを、XMLエクスポートおよび楽曲ファイル複製・タグ変換（ローマ字変換・BPM付与）するGUI / CLIツールです。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

---

## 🚀 かんたんクイックスタート (GUIアプリを使う)

プログラミングや黒い画面（ターミナル）の操作は不要です。アプリをダウンロードしてダブルクリックするだけで使えます。

### 1. アプリのダウンロード
[GitHub Releases 最新版](../../releases/latest) から、お使いのパソコンに合ったファイルをダウンロードしてください：
- **Windows**: `rkbdb2xml-gui-windows-amd64.exe`
- **macOS**: `rkbdb2xml-gui-macos-amd64.zip`（解凍して開く）
- **Linux**: `rkbdb2xml-gui-linux-amd64`

> **💡 初回起動時のセキュリティ画面について**
> - **Windows**: 「WindowsによってPCが保護されました」と出た場合は、**「詳細情報」** をクリックして **「実行」** を押してください。
> - **macOS**: 「開発元が未確認のため開けません」と出た場合は、アプリアイコンを **「右クリック（Controlキーを押しながらクリック）」→「開く」** を選択してください。

### 2. かんたん3ステップの使い方
1. **アプリを起動**: Rekordboxのプレイリストが自動で一覧表示されます。
2. **設定を選ぶ & リアルタイムプレビュー & 試聴再生**:
   - 書き出したいプレイリストに **チェック** を入れます（親フォルダをチェックすると配下すべてにチェックが入ります）。
   - **画面下部に選択中の「合計曲数・トータル容量（MB/GB）」および「16GB USBメモリ使用率・残り容量目安（32GB/64GB動的推奨）」が自動計算・常時表示**されます。
   - プレイリストをクリックすると、**右側のパネルに出力前後の曲名・ローマ字変換・BPM付与・ファイル存在状態がリアルタイムでプレビュー表示**されます。
   - **🎧 ミニ楽曲プレイヤー搭載**: プレビュー一覧の曲を **ダブルクリック（または「▶️ 再生」ボタン）** すると、その場で実音源を試聴再生（シークバー・音量調節付き）できます。
   - 必要に応じて **「ローマ字」** や **「BPM付加」**、**「曲の並び順」** を設定（「⚙️ 一括設定」ボタンで一括変更も可能）。
3. **「🚀 エクスポート開始」をクリック**:
   - エクスポートが完了すると、保存先フォルダに `rekordbox.xml` と変換済み楽曲ファイルが生成されます。
   - 完了後に表示される **「📂 出力先フォルダを開く」** を押すと、保存場所が直接開きます。




---

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

### Building GUI Binaries

You can compile a standalone single-file GUI executable locally using PyInstaller:

1. Install PyInstaller in your virtual environment:
   ```bash
   pip install pyinstaller
   ```
2. Run PyInstaller to build the executable:
   - **Windows:**
     ```bash
     pyinstaller --clean --onefile --noconsole --name rkbdb2xml-gui run_gui.py
     ```
   - **macOS / Linux:**
     ```bash
     pyinstaller --clean --onefile --noconsole --name rkbdb2xml-gui run_gui.py
     ```
   The built binary will be generated in the `dist/` directory.

### GitHub Releases (Multi-platform)

The project includes a GitHub Actions workflow that automatically builds and packages the GUI executable for Windows, macOS, and Linux when you push a version tag (e.g. `v1.0.0`):
1. Tag your commit: `git tag v1.0.0`
2. Push the tag: `git push origin v1.0.0`
The workflow will compile the binaries on all three operating systems and attach them as release assets.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

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

rkbdb2xml は Rekordbox のデータベースから、Rekordbox 標準のエクスポートと同じ形式の XML を書き出します。あわせて楽曲ファイルを出力先にコピーし、タグをローマ字化したり BPM を付けたりできます。

用途:

- コレクションを可搬な形式でバックアップする
- CDJ など、日本語表示に対応しない機器向けに曲名をローマ字化して持ち出す
- 曲名の先頭に BPM を付けて機器側でソートしやすくする
- Rekordbox XML を読める他のソフトと連携する

## Features

- プレイリストのツリー表示とチェックによる選択（親フォルダのチェックで配下も選択）
- 出力前後の曲名・ローマ字変換・BPM 付与・ファイル存在状態のリアルタイムプレビュー
- 選択中の合計曲数・総容量・USB メモリ使用率の自動計算
- ミニ楽曲プレイヤーによる試聴（シークバー・音量・出力デバイス選択）
- ローマ字変換 / BPM 付加 / 曲の並び順をプレイリスト単位または一括で設定
- 楽曲ファイルを出力先にコピーし、タグを変換して書き込み
- Rekordbox データベースパスの自動検出

## Requirements

GUI バイナリを使う場合、インストールは不要です。ソースから動かす場合:

- Python 3.8+
- pyrekordbox>=0.4.0 / PySide6 / lxml / mutagen / romann / psutil

## Development

```bash
git clone https://github.com/kuwa72/rkbdb2xml.git
cd rkbdb2xml
scripts/setup_env.sh          # .venv 作成 + 依存インストール
scripts/test.sh               # 構文チェック + テスト
```

GUI をソースから起動する場合:

```bash
.venv/bin/python run_gui.py
```

### Python API

エクスポート処理はライブラリとしても呼び出せます:

```python
from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_xml

# データベースを自動検出して XML を書き出す
export_rekordbox_db_to_xml(None, "output.xml", verbose=True)
```

### ローカルビルド

```bash
scripts/build_local.sh        # dist/ に単一実行ファイルを生成
```

`rkbdb2xml-gui-console.spec` はコンソール付きのビルド定義です。プレイヤーの診断ログなど、標準出力を見たいときに使います。

### リリース

バージョンタグを push すると、GitHub Actions が Windows / macOS / Linux のバイナリをビルドして Release に添付します。

```bash
scripts/release.sh 0.6.1 "fix: 何を直したか"
```

バグ修正はパッチバージョン（3桁目）を上げます。

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

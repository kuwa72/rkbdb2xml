# Export機能追加 ToDo

以下のタスクを順序立てて実装し、完了した項目にはチェックを入れてください。別のチャットに渡しても再開できるよう詳細に記載します。

## 1. プレイリスト選択オプション
- [x] `cli.py`に`--playlists`オプションを追加。
    - 値はカンマ区切りで指定（例：`--playlists 1,2,4`または`--playlists "My List","Rock"`）。
    - 数値としてパースできるものはID、それ以外はNameとして扱う。
    - `--playlist`オプションを複数回指定（`-p ID -p Name`）する形も許可。
- [x] オプションが与えられた場合、指定されたプレイリスト名またはパスに該当するプレイリストとそのサブプレイリストのみを処理するロジックを`export_rekordbox_db_to_xml`に実装。未指定時は全プレイリストを対象。
- [x] 不正なプレイリスト名／IDが含まれる場合のエラーハンドリングを追加。

### 使用例
```bash
# 1) IDで複数指定
rkbdb2xml export \
  --playlists 10,23,42 \
  -o export.xml

# 2) 名前で複数指定
rkbdb2xml export \
  --playlists "Favorites","Rock Classics" \
  -o export.xml

# 3) 階層構造の下のプレイリストを指定
#    └─ フォルダ: “Party”
#        └─ サブフォルダ: “March”
#            └─ プレイリスト: “EDM Hits”
rkbdb2xml export \
  --playlists "Party/March/EDM Hits" \
  -o export.xml

# 4) ID と 階層パス を混在指定
rkbdb2xml export \
  --playlists 5,"Party/March/EDM Hits",12 \
  -o export.xml

# 5) オプションを複数回指定するパターン
rkbdb2xml export \
  -p 5 \
  -p "Party/March/EDM Hits" \
  -p "Chillout" \
  -o export.xml
```
- 階層は「親フォルダ/子フォルダ/プレイリスト名」の文字列で指定。
- カンマ区切りまたは `-p` 繰り返し指定どちらでもOK。

## 2. プレイリスト一覧出力コマンド
- [x] `cli.py`にサブコマンド`list-playlists`を追加。
- [x] `--format [table|csv|json]`オプションを追加（デフォルトは`table`）。
    - table: 整形テーブル表示
    - csv: `id,name,is_folder,parent_id`ヘッダー付きCSV
    - json: オブジェクト配列
- [x] `Rekordbox6Database.get_playlist()`で取得した各プレイリストのID・Name・is_folderを表形式（テーブルまたはCSV）で標準出力。
- [x] 階層情報（フォルダ構造）がある場合はインデント表示。

## 3. エクスポートディレクトリとファイルコピー
- [x] 出力XMLファイルのパスから同名のディレクトリを作成。
- [x] ファイルをFolderPathのMD5ハッシュ名（拡張子付き）でフラットにコピー。

## 4. タグ書き換え（ステップ3ファイル複製時に実行）
- [x] Mutagenライブラリを導入し、少なくともmp3/aac形式のファイルタグ(ID3/MP4)を編集。Mutagenはこれら形式をサポートしており適切なライブラリ。
- [x] 既存の`--roman`および`--bpm`オプションの処理を参照し、同様にタグ編集を実装。
    - `--roman`有効時: 既存ロジックを踏襲し、`Title`/`Artist`/`Album`をローマ字化。
    - `--bpm`有効時: 既存ロジックを踏襲し、BPMを`Title`タグ先頭に付与（例: `128 - SongTitle`）。

## 5. XML更新
- [x] 複製後のファイルパスに合わせてXML内の`<LOCATION>`要素を更新。
- [x] 修正したXMLを既存ファイルまたは新規ファイルに書き出し。
- [ ] 生成ディレクトリ内に最終XMLを配置。

## 6. テスト
- [ ] テスト用サンプルDBとモック音楽ファイルを用意し、各機能（フィルタ、コピー、タグ編集、XML更新）を統合テスト。
- [ ] Windows環境（%USERPROFILE%）とUnix環境（$HOME）の双方で相対パス計算を検証。

## 7. ドキュメント更新
- [ ] `README.md`に`list-playlists`と`export`の新オプション（`--playlists`、`--romaji`、`--bpm-title`）の使用例を追加。
- [ ] 実行手順と注意事項（ホームフォルダ構造保持など）を記載。

---

以上をタスク化しました。進捗管理にご活用ください。

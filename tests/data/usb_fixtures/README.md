# usb_fixtures — 実 Rekordbox 製デバイスライブラリ

実機 Rekordbox が USB メモリに書き出した `PIONEER/` ツリーの実サンプル集。
`PdbExporter`（rkbdb2xml/pdb_export.py）の出力と突き合わせるための
正解データとして使う。合成データではなく、すべて Rekordbox 本体が
生成したファイル。RB5.8.7 と RB6.8.0 の世代ごとに分離して扱う。

## 生成環境

| 項目 | 値 |
|---|---|
| Rekordbox | 5.8.7（`C:\Program Files\Pioneer\rekordbox 5.8.7`）および 6.8.0（`rkb680_*` 系） |
| 出力先 | 実 USB メモリ（FAT32、KIOXIA TransMemory） |
| 入力 | RB5: `scripts/gen_fixture_input.py` の音声 + rekordbox XML。RB6: `tests/data/rb680_database/master.db` |
| 回収 | `scripts/capture_usb_fixture.py /mnt/f <name>` |

生成手順の概要:

1. `gen_fixture_input.py` で 621 トラック・96 プレイリスト・12 シナリオの
   音声ファイルと rekordbox XML を生成（生成物は `tests/data/fixture_input/`
   にコミット済み。実機へ読ませるときは Windows 側 `C:\rkb-fixtures` 等に置く）
2. Rekordbox 5.8.7 の「rekordbox xml」ブリッジで XML を読み込み、
   コレクションへインポート → 解析
3. シナリオのフォルダを右クリック →「フォルダをエクスポート」→ USB
4. 出力された `PIONEER/` と `Contents/` を `capture_usb_fixture.py` で
   このディレクトリにコピー（コピー時に kaitai パーサーの `walk_pdb()`
   で export.pdb を全テーブル走査して検証済み）
5. 次のシナリオのため、デバイス上のフォルダを削除してから繰り返す

なお Rekordbox は起動中デバイスの export.pdb をロックするため、
シナリオ間のリセットは Rekordbox 側のデバイスビューで
「フォルダを削除」する方式を取った。

## Rekordbox 6.8.0 fixture

RB6 の主検証は、次の実データを使う。

- 入力DB: `tests/data/rb680_database/master.db`（`datafile.edb`、
  `masterPlaylists6.xml` と同梱）
- 参照出力: `rkb680_sc01_one_ascii/`（1曲）、`rkb680_all_scenarios/`（620曲）
- 静的ページ: `rkbdb2xml/data/pdb_static_rb6.bin` は
  `rkb680_sc01_one_ascii` のテーブル 6, 16, 17, 18, 19 から抽出したもの
- 設定ファイル: `rkbdb2xml/data/*_rb6.DAT` は同出力の
  `DEVSETTING.DAT` / `MYSETTING*.DAT` / `DJMMYSETTING.DAT` から抽出したもの
- 比較テスト: `tests/test_rb6_binary_fixture.py`
- DB E2E: `RB6_DB_KEY` を設定して同じテストを実行すると、暗号化
  `master.db` からの USB 生成も検証する（キー未設定時は skip）

RB5 の `rkb587_*` は旧世代／旧CDJ向けのlegacy fixtureであり、RB6の
正解比較には混ぜない。RB6の実DBからUSBを生成するWindows E2Eは、
入力DBと `pdb_profile="rb6"` を固定して別途実行する。

## 各フィクスチャの構成

```
<fixture>/
├── PIONEER/
│   ├── rekordbox/
│   │   ├── export.pdb      デバイスライブラリ本体（ページ構造）
│   │   └── exportExt.pdb   拡張データ（My Tag 等、RB6 系でも出力）
│   ├── USBANLZ/Pxxx/XXXXXXXX/ANLZ0000.{DAT,EXT}
│   │                       解析データ（波形・ビートグリッド）
│   ├── Artwork/<track_id>/a{N}.jpg, a{N}_m.jpg   アートワーク（あれば）
│   ├── DEVSETTING.DAT      デバイス設定
│   ├── MYSETTING.DAT / MYSETTING2.DAT
│   └── djprofile.nxs
└── Contents/<Artist>/<Album>/<file>   コピーされた音声ファイル
```

`Contents/` 配下は `<アーティスト>/<アルバム>` のディレクトリに
元ファイル名のまま配置される。アーティスト・アルバムが空のトラックは
`UnknownArtist/UnknownAlbum/` に落ちる（SC12 で確認）。

## フィクスチャ一覧

| ディレクトリ | トラック | 内容 |
|---|---|---|
| `rkb587_empty` | 0 | 空のデバイスライブラリ。export.pdb/exportExt.pdb の骨格のみ。最小構成の参照用 |
| `rkb587_sc01_one_ascii` | 1 | 単一プレイリスト・単一トラックの最小例 |
| `rkb587_sc02_japanese` | 6 | 日本語メタデータ。ひらがな/カタカナ/半角カナ/全角英数/混合/長音符・波線・特殊記号 |
| `rkb587_sc03_long_strings` | 10 | 長い文字列。ASCII 40/63/64/65/100/255/300 文字、日本語 63/64/100 文字。文字列長の境界値 |
| `rkb587_sc04_special_chars` | 8 | 絵文字・引用符・`&` `<` `>`・アクセント・キリル・前後空白・日英絵文字混合 |
| `rkb587_sc05_many_tracks` | 400 | 大量トラック。ページ・インデックス跨ぎの検証用（artist 17 種・album 9 種・BPM 120-179） |
| `rkb587_sc06_nested_playlists` | 6 | 4 段ネストのフォルダ（L1/L2/L3/L4）と各階層のプレイリスト |
| `rkb587_sc07_many_playlists` | 160 | 80 プレイリスト × 各 2 トラック。プレイリストツリーのページ跨ぎ |
| `rkb587_sc08_ratings_keys_colors` | 12 | Rating 0-5・Tonality（Am/12A/3B/空）・Colour（RGB hex/空）の組み合わせ |
| `rkb587_sc09_file_types` | 5 | ファイル形式バリエーション（mp3/wav/flac/m4a）。※AIFF 入力 1 曲は RB5.8.7 がエクスポートせず |
| `rkb587_sc10_bpm` | 5 | BPM 境界値。0.00 / 60.00 / 128.50 / 200.99 / 999.00 |
| `rkb587_sc11_artwork` | 4 | アートワーク付き（jpg/png）+ なし。`PIONEER/Artwork/` に実画像あり |
| `rkb587_sc12_misc` | 3 | 空プレイリスト・同一トラック重複参照（playlist entries=4/track=3）・アーティスト空 |
| `rkb587_all_scenarios` | 621 | 上記全シナリオ + トップレベル単独 SC01 プレイリスト + 空の「無題のリスト」×3 を一括エクスポートしたもの。最大規模 |
| `rkb680_sc01_one_ascii` | 1 | Rekordbox 6.8.0 の `master.db` から作成した RB6 主検証用出力 |
| `rkb680_all_scenarios` | 620 | Rekordbox 6.8.0 の全シナリオ一括出力。113プレイリストノード、ANLZ 1860ファイル |

シナリオ → プレイリスト名の対応は `scenarios.json` を参照
（`gen_fixture_input.py` が出力したものと同一）。

## 検証方法

```bash
# export.pdb を kaitai パーサーで全テーブル走査（回収時と同じチェック）
.venv/bin/python -c "
import sys; sys.path.insert(0, 'tests')
from test_export_validation import walk_pdb
print(walk_pdb('tests/data/usb_fixtures/rkb587_sc05_many_tracks/PIONEER/rekordbox/export.pdb'))
"
```

テスト側は `tests/test_export_validation.py` の `walk_pdb()` を再利用する。
実DBから生成した USB 全体は、手動確認や次のスクリプトでも比較できる。


```bash
python scripts/compare_usb_exports.py <Rekordbox出力> <rkbdb2xml出力>
```

### 既知の差分

- `Contents/` は Rekordbox の `Artist/Album/元ファイル名` ではなく、
  rkbdb2xml のハッシュ名配置になる
- `djprofile.nxs` / `exportExt.pdb` / Artwork は現時点では生成しない
- 単一プレイリスト出力では祖先フォルダを保持する（参照出力はフラット）
- ANLZ は DB の `share` 実体がない環境ではコピーされない

pyrekordbox による ANLZ パース検証は Rekordbox インストール環境でのみ可能。

## 注意事項

- Rekordbox 5.8.7 は AIFF をエクスポートしなかった（SC09: 6 曲中 5 曲）。
  入力 XML には存在するが USB には出ないケースの実例として残す
- `rkb587_all_scenarios` の Contents は 621 ファイルだが export.pdb の
  tracks テーブル行数は 620（SC12 の重複参照トラックが 1 行に集約）
- Contents のディレクトリ名に `"` や `<` を含むケースは RB がサニタイズ
  するため、タグ値とファイルシステム上の名前は一致しないことがある

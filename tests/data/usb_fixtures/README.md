# usb_fixtures — 実 Rekordbox 製デバイスライブラリ

実機 Rekordbox が USB メモリに書き出した `PIONEER/` ツリーの実サンプル集。
`PdbExporter`（rkbdb2xml/pdb_export.py）の出力と突き合わせるための
正解データとして使う。合成データではなく、すべて Rekordbox 本体が
生成したファイル。

## 生成環境

| 項目 | 値 |
|---|---|
| Rekordbox | 5.8.7（`C:\Program Files\Pioneer\rekordbox 5.8.7`） |
| 出力先 | 実 USB メモリ（FAT32、KIOXIA TransMemory） |
| 入力 | `scripts/gen_fixture_input.py` が生成した音声 + rekordbox XML |
| 回収 | `scripts/capture_usb_fixture.py /mnt/f <name>` |

生成手順の概要:

1. `gen_fixture_input.py` で 621 トラック・96 プレイリスト・12 シナリオの
   音声ファイルと rekordbox XML を生成（Windows 側は `C:\rkb-fixtures`）
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
| `rkb587_all_scenarios` | 620 | 上記全シナリオ + トップレベル単独 SC01 プレイリスト + 空の「無題のリスト」×3 を一括エクスポートしたもの。最大規模 |

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
pyrekordbox による ANLZ パース検証は Rekordbox インストール環境でのみ可能。

## 注意事項

- Rekordbox 5.8.7 は AIFF をエクスポートしなかった（SC09: 6 曲中 5 曲）。
  入力 XML には存在するが USB には出ないケースの実例として残す
- `rkb587_all_scenarios` の Contents は 621 ファイルだが export.pdb の
  tracks テーブル行数は 620（SC12 の重複参照トラックが 1 行に集約）
- Contents のディレクトリ名に `"` や `<` を含むケースは RB がサニタイズ
  するため、タグ値とファイルシステム上の名前は一致しないことがある

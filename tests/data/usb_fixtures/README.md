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
- 参照出力: `rkb680_sc01_one_ascii/`（1曲）、`rkb680_all_scenarios/`（2026-09-24にRekordbox 6.8.0で再生成した620曲。AIFF 1曲はRekordbox仕様により除外）
- 静的ページ: `rkbdb2xml/data/pdb_static_rb6.bin` は
  `rkb680_sc01_one_ascii` のテーブル 6, 16, 17, 18, 19 から抽出したもの
- 設定ファイル: `rkbdb2xml/data/*_rb6.DAT` は同出力の
  `DEVSETTING.DAT` / `MYSETTING*.DAT` / `DJMMYSETTING.DAT` から抽出したもの
- 比較テスト: `tests/test_rb6_binary_fixture.py`
- DB E2E: `RB6_DB_KEY` を設定して同じテストを実行すると、暗号化
  `master.db` からの USB 生成も検証する（キー未設定時は skip）

RB5 の `rkb587_*` fixtureディレクトリは削除済み。`fixture_input` と
`scenarios.json` の入力メタデータは残し、fixture不在時は legacy tests を
skipする。RB6の実DBからUSBを生成するWindows E2Eは、入力DBと
`pdb_profile="rb6"` を固定して別途実行する。

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
| `rkb680_sc01_one_ascii` | 1 | Rekordbox 6.8.0 の `master.db` から作成した RB6 主検証用出力 |
| `rkb680_all_scenarios` | 620 | Rekordbox 6.8.0 の全シナリオ一括出力。113プレイリストノード、ANLZ 1860ファイル、PDB 458752バイト。`Export Log 6.8.0.0010 2026-09-24.txt` 付き |

シナリオ → プレイリスト名の対応は `scenarios.json` を参照
（`gen_fixture_input.py` が出力したものと同一）。

## 検証方法

```bash
# export.pdb を kaitai パーサーで全テーブル走査（回収時と同じチェック）
.venv/bin/python -c "
import sys; sys.path.insert(0, 'tests')
from test_export_validation import walk_pdb
print(walk_pdb('tests/data/usb_fixtures/rkb680_all_scenarios/PIONEER/rekordbox/export.pdb'))
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

- RB6 の `rkb680_all_scenarios` も AIFF 1曲（`trk_00608.aiff`）を
  Rekordbox仕様でエクスポートせず、620曲になっている
- Contents のディレクトリ名に `"` や `<` を含むケースは RB がサニタイズ
  するため、タグ値とファイルシステム上の名前は一致しないことがある

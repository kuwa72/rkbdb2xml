# fixture_input — usb_fixtures の元データ

`tests/data/usb_fixtures/` の各フィクスチャを生成するために
実機 Rekordbox 5.8.7 に読み込ませた入力一式。
`PdbExporter` の出力や export.pdb の中身を突き合わせるときの
正解（ground truth）として使う。

## 構成

| パス | 内容 |
|---|---|
| `rekordbox.xml` | Rekordbox XML ブリッジ用ライブラリ。TRACK 621 件 + SCENARIOS フォルダ配下 96 プレイリスト（12 シナリオ） |
| `audio/` | タグ付き音声ファイル 626 個（トラック分 621: mp3 615 / wav 1 / flac 2 / m4a 2 / aiff 1、+ テンプレート `_base.*` 5 個）。1 秒・440Hz 正弦波 |
| `_art.jpg` / `_art.png` | SC11 で埋め込んだアートワーク画像 |
| `scenarios.json` | シナリオ名 → プレイリスト名の対応表（`usb_fixtures/scenarios.json` と同一） |
| `set_xmlpath.ps1` | `rekordbox3.settings` の `bridgeImportedLibraryFile` にこの XML のパスを書き込む補助スクリプト |

## 再生成

```bash
.venv/bin/python scripts/gen_fixture_input.py <出力先> [XML中のWindowsパス]
# 例: .venv/bin/python scripts/gen_fixture_input.py /mnt/c/rkb-fixtures 'C:\rkb-fixtures'
```

`rekordbox.xml` 内の `Location` は `file://localhost/C:/rkb-fixtures/audio/...`
形式。別パスに置いて Rekordbox に読ませる場合は第2引数か Location の
書き換えが必要。

## 突合時に期待される差分

入力 XML と export.pdb / rkbdb2xml 出力を比較するとき、以下は
Rekordbox 側の仕様による変換であり差異としてカウントしない。

- `Fmt AIFF`（`trk_00608.aiff`）は RB5.8.7 がエクスポートしない。
  sc09 / all_scenarios のどちらにも存在しない
- アーティスト・アルバムが空のトラックは `Contents/UnknownArtist/UnknownAlbum/`
  に配置される（SC12 `No Artist Track`）
- 同一ディレクトリ内のファイル名重複は `-1` 等のサフィックスで退避
  （例: `trk_00001-1.mp3`）
- SC12 の重複参照は tracks テーブル 1 行に集約される
  （playlist entries=4 / track=3）
- アーティスト/アルバム名の `"` `<` 等は Contents のディレクトリ名で
  サニタイズされるため、タグ値とパスは一致しないことがある
- Rating は XML の 0/51/102/153/204/255 ↔ 0〜5 星
- `Location` は `C:/rkb-fixtures/audio/...` からデバイス上の
  `/Contents/<Artist>/<Album>/<file>` に書き換わる
- 旧RB5 fixture（削除済み）の `rkb587_all_scenarios` には XML 外の要素が含まれていた
  （トップレベルの `SC01 one_ascii` プレイリストと空の「無題のリスト」×3）。
  インポート作業中にコレクション側へ個別に取り込まれたもので、
  この XML には存在しない

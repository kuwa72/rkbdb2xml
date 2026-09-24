# rekordbox 6.8.0 vs rkbdb2xml バイナリ互換性レポート

**対象**: 実機 Rekordbox 6.8.0 が USB に書き出した出力
（`tests/data/usb_fixtures/rkb680_all_scenarios`、620曲）と、同一 `master.db` から
rkbdb2xml が生成した USB 出力（`pdb_profile="rb6"`）の突合。

**生成条件**: E2E テストと同一経路（音声・ANLZ は fixture 実体を参照、
`RB6_DB_KEY` で暗号化 master.db を復号）。

**実行日**: 2026-09-24 / `scripts/compare_usb_exports.py` + kaitai 独立パーサー

## 総合判定

**構造・意味レベルで互換（32/32 チェックパス）**。生バイトは完全一致しないが、
差分はすべて「読取側が参照しない不透明領域」（行ID・シーケンス・ヒープ詰め）と
「意図的に未実装の機能」に限定される。CDJ 読み込みに必要な全要素は一致。

## 1. コンテンツ一致（32/32 PASS）

| 項目 | 結果 |
|---|---|
| トラック数 / 属性 multiset（19字段） | 620 = 620、欠落0・余剰0 |
| プレイリストツリー（113ノード） | 構造一致 |
| プレイリストエントリ（621件、曲順付き） | 全プレイリスト一致 |
| 静的テーブル（colors/columns/artists/albums/genres/keys/labels） | 8/27/123/33/7/1/0 全一致 |
| 設定ファイル（DEVSETTING/MYSETTING/MYSETTING2/DJMMYSETTING） | **4ファイルともバイト完全一致**（140/148/148/160B） |
| ANLZ 1,860ファイル | 両側1,860、配置ハッシュ dir・`PPTH == file_path` 全一致（620曲×3） |
| Contents ファイル数 / 拡張子分布 | 620 = 620、`.mp3:615 .flac:2 .m4a:2 .wav:1` 一致 |
| Contents 相対パス ↔ DB `file_path` | 両側 internally 整合（missing/orphan 0） |

## 2. RAW export.pdb 差分（定量）

| 指標 | Rekordbox 6.8.0 | rkbdb2xml | 差 |
|---|---|---|---|
| ファイルサイズ | 458,752 B | 475,136 B | +16,384 B（+4ページ） |
| ページ数（4096B） | 112 | 116 | +4 |
| バイト同一ページ（共通112枚中） | — | — | **35枚（31%）** |
| 差分バイト | — | — | 193,840 B |
| 差分ページ / ヘッダ差分ページ | — | — | 77 / 74 |
| 行数合計（kaitai 検証済み `num_rows`） | 1,596 | 1,593 | **−3** |
| 行数不一致ページ | — | — | 51 |

### 行数差（−3）の原因は特定済み

**table 13（artwork）のみ**: 実機 3行/2ページ → rkbdb2xml 0行/1ページ。
他テーブルは全行数一致:

```
table  0 (tracks)           620 = 620      table 13 (artwork)   3 ≠ 0  ← 唯一の差
table  7 (playlist_tree)    113 = 113      table 16 (columns)   27 = 27
table  8 (playlist_entries) 621 = 621      table 17             22 = 22
table  2 (artists)          123 = 123      table 18             17 = 17
table  3 (albums)            33 = 33       他 static 全一致
```

### ページ数差（+4）の原因

tracks テーブルのヒープ使用量のみ差:

| | 実機 | rkbdb2xml |
|---|---|---|
| tracks データページ | 57枚 / 219,056 B | 61枚 / 230,676 B（+11,620 B） |

行内容の multiset は一致するため、**行の内部パディング／不透明ID列の詰め差**。
読取側は行オフセット索引で辿るため影響なし。

### 静的ページ（table 6/16/17/18/19）のバイト一致

- table 6, 16: 2/2ページ完全一致
- table 17, 18: 1/2一致（後続ページの next/sequence が全体ページ数112 vs 116 を反映して異なる）
- table 19: 0/2（行数は 1=1、リンク先参照の差のみ）

## 3. 既知の差分（分類別、FAIL にならない [INFO]）

| 分類 | 内容 |
|---|---|
| **rkbdb2xml未実装** | `PIONEER/djprofile.nxs`（Kuvo プロフィール・個人情報のため非生成）／`exportExt.pdb`（Device Library Plus、CDJ-3000+ 向け。#53 検討中）／`PIONEER/Artwork/` + artwork テーブル3行（CDJ-350/800 は非表示、`artwork_id=0` 固定。#53） |
| **入力由来** | Contents の配置規則（実機 `Artist/Album/元ファイル名` vs rkbdb2xml `md5ハッシュ.mp3`）。相対パス一致数 0/620 だが、CDJ は PDB の `file_path` 経由で辿るため再生・閲覧に影響しない。`analyze_path` も同理由で集合一致0（配置ハッシュ自体は全一致） |

**分類「Rekordbox世代／履歴由来」は今回0件**（設定ファイル4点がバイト一致したため）。

## 4. 参考: 1曲バイナリ基線（既存テストの固定値）

`rkb680_sc01_one_ascii` 1曲出力での差分は `[(page2, 11B), (page8, 1B)]` のみ
= **不透明行ID2箇所**。620曲規模でも差分の性質は同一で、規模拡大により
ヒープ詰め差が4ページ分現れた、という関係。

## 5. 結論

- **CDJ 読み込みに必要な全要素（トラック属性・プレイリスト構造・曲順・
  静的テーブル・設定ファイル・ANLZ 配置と PPTH・Contents 実在）は完全に一致**。
  実機検証（#57）で問題が出た場合、原因は下記3点に絞られる:
  1. artwork / exportExt.pdb 欠落（→ 新世代機で issue #53 の範囲）
  2. Contents ハッシュ命名（機種がファイルシステム直読みしている場合のみ影響）
  3. tracks ヒープの詰め差（不透明領域、読取互換性は理論上無影響）
- 生バイト一致（dd 比較）は**非互換ではなく設計上あえて目指していない**領域を
  含むため、比較観点としては行数・ページ構造・意味一致が適切。

## 再現手順

```bash
# rkbdb2xml 版 USB の生成（E2E と同じ経路）
RB6_DB_KEY=<key> pytest -q tests/test_rb6_all_scenarios_fixture.py

# 突合
python scripts/compare_usb_exports.py \
  tests/data/usb_fixtures/rkb680_all_scenarios <生成USBルート>
```

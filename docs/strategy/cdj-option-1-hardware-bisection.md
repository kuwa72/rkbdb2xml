# 案1: 実機 oracle による CDJ 読み込み問題の二分探索

- **状態**: バイナリ canary 実装済み / 実機検証待ち
- **作成日**: 2026-09-24
- **対象**: `rkbdb2xml` の USB デバイスライブラリ直接出力
- **Related issues**: #31, #34, #48

## 1. 目的

CDJ での読み込み失敗について、行・プレイリスト・ANLZ が意味的には一致していても、物理的な USB/PDB/ANLZ のどの部分が実機の受理条件を破っているか特定する。

この案の目標は、最初に「何が壊れているか」を短時間で特定することであり、推測で `export.pdb` の項目を次々に追加することではない。

## 2. 現在の判断

### 確認できていること

- `rekordbox_pdb.Database.from_file` で生成物を読み戻せる。
- Kaitai 系の独立パーサーでも全テーブルを走査できる。
- Rekordbox 5.8.7 製 fixture と、トラック属性・プレイリスト構造・ANLZ のパース結果を比較できる。
- 既存テストは green だが、実機では依然として読み込めない。
- ただし、現在の主検証は Rekordbox 6.8.0 の `master.db` 入力と Rekordbox 6.8.0 製 USB 出力の組に統一する。RB5 fixture は旧世代 format の参考としてだけ使う。

### 今回進めたこと（実機なし）

- `rb680_database/master.db` と `rkb680_sc01_one_ascii` を作業ツリーへ追加した。
- `pdb_profile="rb6"` にRB6.8.0由来の静的ページと設定ファイルを選択的に割り当てた。
- RB6の1曲 canary では、ページヘッダ・table directory・静的テーブル・設定ファイルの比較テストを追加した。
- `RB6_DB_KEY` を設定した環境では、実 `master.db` からの USB 生成と参照比較も通る。
- canary のPDB残差を測定ところ、残る差分は12バイト（track/lookup row の内部ID・unique値）に限定された。実機受理条件の証明ではない。

### まだ確認できていないこと

- CDJ が `export.pdb` のどの物理ページ/フィールドを必須としているか。
- 失敗が `export.pdb`、`Contents`、`USBANLZ`、補助ファイル、USB のファイルシステムのどれに起因するか。
- 検証対象の CDJ モデル・ファームウェア・Rekordbox バージョンのどれか。

したがって、parser の成功を「CDJ 互換性の証拠」として扱わない。

### 検証のバージョン軸

入力DBと参照USB出力は、必ず同じRekordbox世代で揃える。

| 検証 | 入力 | 参照出力 | 用途 |
|---|---|---|---|
| 主検証（RB6 E2E） | `tests/data/rb680_database/master.db` | `rkb680_sc01_one_ascii` / `rkb680_all_scenarios` | Rekordbox 6.8.0 との端到端比較 |
| 旧世代 format 参考 | RB5相当の入力またはXML fixture | `rkb587_*` | rb5 output / 旧CDJ compatibilityの参考 |

`rkb587_*` と `rkb680_*` を同じ「正解」として扱わない。DBバージョン、Rekordboxの出力バージョン、対象のCDJモデルを混在させない。

## 3. 仮説

### 仮説A: PDB のページ生成・トランザクション情報

同じ1曲 fixture を実機出力と自前出力で比較したところ、意味的な行は一致しても、動的ページのヘッダは一致していない。

観測例（旧世代 format の参考値。Rekordbox 5.8.7 の1曲 fixture。RB6主検証の根拠ではない）:

| ページ | 実機 | 自前生成 |
|---|---:|---:|
| tracks data page の sequence | 11 | 2 |
| playlist tree data page の sequence | 7 | 2 |
| playlist entries data page の sequence | 12 | 2 |

この例は、旧世代 output と自前生成の物理差分の参考値として記録する。RB6 の主検証では、同じ版の `rkb680_*` 出力を使って同じ比較を行う。

また、一部テーブルの `empty_candidate` の割り当て順も異なる。

これは原因の証明ではないが、次のような実装上の境界を示している。

- `rkbdb2xml/pdb_export.py` の `create_empty_pdb()` は実機 export の複製ではなく、合成された初期ページを使う。
- `PdbEditor` は既存 PDB の編集には向いているが、新規 export 時に実機と同じページ sequence / transaction metadata を再現するとは限らない。
- `rb5` / `rb6` profile は主にトラック行の定数を切り替える。ページ生成・ページチェーン・sequence まで同一化する仕組みではない。

### 仮説B: PDB 以外の成果物

同じ USB 構成でも、次の変更で挙動が変わる可能性がある。

- `exportExt.pdb`、`exportLibrary.db`、`djprofile.nxs`
- `DEVSETTING.DAT`、`MYSETTING.DAT`、`MYSETTING2.DAT`
- `ANLZ0000.DAT` / `ANLZ0000.EXT` / `ANLZ0000.2EX`
- `export.pdb.bak`、`RBFLTR.DAT`、古い `playlists*.sync` などの残留物
- FAT32、Allocation Unit、パーティション、usb メモリの物理状態

## 4. 対象を固定する

実機試験を始める前に、次を記録して混同を防ぐ。

```text
CDJ model:
Firmware:
Rekordbox version:
検証した branch / commit:
検証した binary:
USB maker / model:
Filesystem:
Allocation Unit:
Error message:
Error timing:
- USB 挿入直後
- ブラウズ画面
- プレイリスト選択
- トラック load / play
純正 Rekordbox output は同じ CDJ で読めるか:
```

対象が新しい CDJ/XDJ の場合は、legacy `export.pdb` だけで対応完了と判断せず、OneLibrary 系（`exportLibrary.db`、`exportExt.pdb`、`.2EX` など）を別の検証対象として扱う。

## 5. 試験手順

### Step 0: クリーンな baseline を作る

毎回、次の USB を使う。

1. FAT32 のクリーンな USB を用意する。
2. Rekordbox 6.8.0 の `master.db` から、純正 Rekordbox の1曲 export（`rkb680_sc01_one_ascii` 相当）を作り、同一 CDJ で読み込みを確認する。
3. 候補 USB にも同じ入力・同じファイル名・同じ `Contents` パスを使う。
4. 試験ごとに USB を再初期化し、古い Rekordbox ファイルを混在させない。

主検証の fixture は作業ツリーに追加済み。実機では、Windows / Rekordbox 6.8.0 で同じ入力から純正 USB を作り、同一 CDJ で比較する。

### Step 1: 成果物単位で二分する

同一入力の1曲 fixture を使って、次の4系統を作る。

| Variant | `export.pdb` | `Contents` / ANLZ | 目的 |
|---|---|---|---|
| A | 純正 | 純正 | baseline |
| B | 自前生成 | 純正 | PDB だけを疑う |
| C | 純正 | 自前生成 | 音声 / ANLZ だけを疑う |
| D | 自前生成 | 自前生成 | end-to-end |

B が失敗すれば PDB、C だけが失敗すれば音声/ANLZ というように、原因層を切り分ける。

### 現在のテスト経路

- `tests/test_rb6_binary_fixture.py` は、キー不要の1曲 canary と、`RB6_DB_KEY` を設定した実際の `master.db` E2E を分けている。
- `scripts/compare_usb_exports.py` は USB ツリー全体の比較用で、Windows / Rekordbox 環境を手動で実行する。
- `rkb680_all_scenarios` と、複数ページ・多数曲ケースの完全一致は未検証であり、1曲 canary の結果を一般化とは扱わない。

残る主な差は、入力由来の一時値（tempo / bitrate 等）、Rekordbox 内部の opaque ID / unique 値、`Contents/` の配置、補助ファイル、ANLZ の実体がない環境である。

### Step 2: PDB 内部をページ単位で二分する

B が失敗した場合、正解 PDB と自前 PDB の logical page group を比較する。

1. page 0 と table directory
2. static table pages（colors / columns / history など）
3. tracks の index / data pages
4. playlist tree / playlist entry pages
5. 空 page candidate と file header の next/sequence

ページ単体の随意差し替えはチェーンを壊す可能性があるため、最初に page + directory の組で試験する。結果は手で記録せず、variant 名とハッシュを保存する。

### Step 3: ANLZ だけを切り分ける

CDJ が `ANLZ0001.DAT` / `ANLZ0001.EXT` を新たに作る場合、ANLZ を読めたが拒否した可能性が高い。`export.pdb` 自体の拒否とは分けて扱う。

確認項目:

- hash 計算されたディレクトリ
- `.DAT` と `.EXT` の存在
- `PPTH` のパス
- `PPTH` の null terminator
- track の `file_path` と `PPTH` の一致
- 音声ファイルの実在とフォーマット

## 6. 判定基準

### 成功とみなす条件

対象 CDJ について、次をすべて満たすまで「成功」としない。

- USB 挿入後に DB read error が出ない。
- プレイリスト/フォルダを browse できる。
- トラックを load/play できる。
- `ANLZ0001.*` が不要に生成されない。
- 1曲だけでなく、複数曲・長すぎる文字列を含むケースでも成立する。
- 再実行しても同じ USB で成功する。

### 案件を「PDB 起因」と断定する条件

B（自前 PDB + 純正 media）が A（純正 baseline）を壊し、C（純正 PDB + 自前 media）が通る場合のみ、PDB 起因とする。複数 CDJ/ファームウェアで確認するまでは「その CDJ の PDB 受理条件」と表現する。

## 7. 分岐と移行条件

### 分岐1: ページ metadata が原因だった

実機 template を seed にした `TemplatePdbEditor` を試す。

- 実機の空 library / 最小 export を base にする。
- page header、sequence、empty candidate、transaction metadata を保持する。
- 既存 parser test に加えて、対象 fixture の raw page header を assertion する。
- `create_empty_pdb()` は production path から外す。

### 分岐2: PDB と ANLZ の両方に差分がある

ANLZ と PDB を同時に直そうとせず、CDJ が「mount 時点で失敗」なのか「load 時点で失敗」なのかを分ける。CDJ が生成する `ANLZ0001.*` を必ず確認する。

### 分岐3: 原因が収束しない

短期間の hardware bisection で明確な原因が収束しなければ、from-scratch `export.pdb` の direct export を experimental として降格し、Rekordbox bridge mode（XML/DB 入力を Rekordbox に渡し、純正 USB export を作る方式）を fallback として検討する。

## 8. 今回やらないこと

- 根拠のない track/profile 定数の追加
- parser が通っただけで CDJ 互換と宣言すること
- 全 CDJ モデルへの同時対応
- 既存 fixture を壊すような一括 format normalization
- ANLZ と PDB の問題を同時に修正すること

## 9. 最初のタスク

- [ ] 対象 CDJ model / firmware / Rekordbox version を記録する
- [x] `rkb680_database/master.db` と `rkb680_sc01_one_ascii` を作業ツリーへ用意する
- [x] Rekordbox 6.8.0 の1曲 baseline USB（`rkb680_sc01_one_ascii`）を用意する
- [x] キー不要のRB6 binary canaryと、`RB6_DB_KEY` で実行する `master.db` E2Eをpytestに追加する
- [ ] A / B / C / D の4 variant を作る
- [ ] 結果を以下の表に記録する

```text
Date:
Variant:
commit / binary:
export.pdb SHA-256:
ANLZ file count:
CDJ model / firmware:
Mount:
Browse:
Load:
Play:
CDJ-created files:
Notes:
```

- [ ] B の結果から PDB / media の主因を判定する
- [ ] PDB が原因なら raw page diff の variant を作る
- [ ] PDB が原因でないなら ANLZ / 補助ファイル / USB 状態を切り分ける

## 10. 関連資料

- `rkbdb2xml/pdb_export.py`
- `rkbdb2xml/anlz.py`
- `tests/test_fixture_comparison.py`
- `tests/test_export_validation.py`
- `tests/data/usb_fixtures/`
- `tests/data/rb680_database/`
- `rkb680_sc01_one_ascii` / `rkb680_all_scenarios`（Rekordbox 6.8.0 実出力）
- Issue #31: legacy PDB の完全互換
- Issue #34: 実機 bisection
- Issue #48: master.db → USB の端到端突合

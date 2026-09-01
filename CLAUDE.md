# rkbdb2xml

Rekordbox のプレイリストを XML エクスポートし、楽曲ファイルをタグ変換つきでコピーする **GUI ツール**。CDJ-350/800 など日本語表示に対応しない機器へ持ち出すのが主目的。

## 構成

| パス | 役割 |
|---|---|
| `rkbdb2xml/gui.py` | PySide6 の GUI。ウィジェットと画面遷移のみを持つ |
| `rkbdb2xml/player.py` | 試聴用ミニプレイヤー `PreviewPlayer`。再生状態はすべてここに閉じる |
| `rkbdb2xml/rkbdb2xml.py` | エクスポート本体（XML 生成・ファイルコピー・タグ変換） |
| `run_gui.py` | GUI のエントリポイント |
| `scripts/` | `setup_env.sh` / `test.sh` / `build_local.sh` / `release.sh` |

## 運用ルール

- Python の実行はすべて `.venv` 経由。
- 繰り返す作業は `scripts/` のスクリプトにまとめてから使う。
- リリースは `scripts/release.sh <version> "<message>"`。タグ push で GitHub Actions が Windows/macOS/Linux のバイナリをビルドして Release に添付する。
- **バグ修正はパッチバージョン（3桁目）だけ上げる。** マイナー以上は新機能・構造変更のときだけ。
- 利用は GUI のみ。CLI 向けの互換維持のために設計を歪めない。
- PEP8 に従う。テストを先に書く。

## テスト

- `scripts/test.sh` で構文チェックとテストを実行する。
- **モックでごまかさない。** ただし Qt のマルチメディアだけは例外で、`tests/test_audio_player.py` の `FakeMediaPlayer` が QMediaPlayer の「非同期ロード」と「stop() が同期でシグナルを再発火する」挙動を再現している。この2つが実際のバグの原因だったので、フェイクの側でそれを再現しないとテストの意味がなくなる。
- エクスポート系のテストは `tests/data/rekordbox_test.db` と、Rekordbox6 で書き出した `tests/data/test_rkb6_export.xml` を比較する。Rekordbox がインストールされていない環境（Linux など）では pyrekordbox が動かず失敗するのは既知。

## QMediaPlayer の落とし穴（再発させないこと）

`PreviewPlayer` の設計はすべてこの3点に由来する。触るときは `tests/test_audio_player.py` を先に読むこと。

1. `setSource()` は非同期。直後に `play()` を呼ぶとローダと競合し、再生状態を示すのに音が進まない。`LoadedMedia` を待つ。
2. `stop()` と `setSource()` は、**破棄される前のメディア**の `mediaStatusChanged` を同期的に再発火する。保留中の要求はティアダウンの**前**に無効化する。
3. `play()` を `mediaStatusChanged` スロットの中から再入的に呼ぶと、バックエンドは受理して Buffering→Buffered まで進むのにクロックが動かない。`QTimer.singleShot(0, ...)` でシグナルスタックの外から呼ぶ。

`QAudioOutput` は起動時の1個を使い回す。作り直すと position だけ進んで無音になる。

## スコープ

Rekordbox との完全互換は目指さない。

- 対象: トラック情報（filepath / bpm / title / artist / album）とプレイリスト
- 対象外: hot cue / memory cue / beat grid
- オプション機能（既定オフ）: ローマ字変換、曲名への BPM 付加、BPM 順ソート
- Rekordbox v6 / v7 を対象とする

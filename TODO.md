# TODO

- [ ] XML ライブラリの統一
   - `lxml.etree` と `xml.etree.ElementTree` が混在している。`rkbdb2xml.py` 640 行目のローカル import を含め、どちらかに寄せる。

- [ ] プレイリスト取得のフォールバック整理
   - `get_playlist_entries` / `get_playlist_songs` / `get_playlist_contents` の使い分けを、pyrekordbox API の一本に統一する。

- [ ] BPM 帯でのプレイリスト分割（未着手のオプション機能）
   - 10 BPM 刻みなどでプレイリストを再構成する。

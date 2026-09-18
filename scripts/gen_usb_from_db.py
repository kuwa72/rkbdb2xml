"""Rekordbox のライブラリ DB から直接 USB デバイスツリーを生成する。

GUI を介さず ``export_rekordbox_db_to_device`` を呼ぶ検証用ランナー。
実機 Rekordbox エクスポートとの端到端突合に使う（Issue #48）。

Rekordbox 6/7 がインストールされた Windows 環境で実行すること
（pyrekordbox が master.db の復号鍵を OS から取得するため）::

    .venv\\Scripts\\python scripts\\gen_usb_from_db.py F:\\rkb-ours --profile rb6

特定プレイリストだけ出す場合::

    ... --playlists "SCENARIOS/SC05_many_tracks"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_device  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", help="USB ツリーの出力先ルート")
    p.add_argument("--db", default=None,
                   help="master.db のパス（省略時は自動検出）")
    p.add_argument("--profile", default="rb5", choices=("rb5", "rb6"),
                   help="export.pdb のトラック行プロファイル")
    p.add_argument("--playlists", nargs="*", default=None,
                   help="階層パス ('Folder/Playlist')。省略時は全プレイリスト")
    args = p.parse_args()

    export_rekordbox_db_to_device(
        args.db,
        args.output,
        verbose=True,
        playlists=args.playlists,
        pdb_profile=args.profile,
    )
    print(f"done: {args.output}")


if __name__ == "__main__":
    main()

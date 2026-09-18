"""実 Rekordbox エクスポートから静的テーブルページを抜き出し pdb_static.bin を生成する。

create_empty_pdb() が埋め込む静的ページ（テーブル 6,16,17,18,19 の
index+data ペア）は実機形式との一致のため生バイトを保存している。
Rekordbox のバージョンを差し替える際にこのスクリプトで再生成する。

使い方::

    python scripts/extract_pdb_static.py <実機 export.pdb> [出力先]
"""

import struct
import sys
from pathlib import Path

PAGE_SIZE = 4096
STATIC_TABLES = (6, 16, 17, 18, 19)


def extract(export_pdb: Path, out: Path) -> None:
    data = export_pdb.read_bytes()
    blob = bytearray()
    for table in STATIC_TABLES:
        _typ, _ec, first, last = struct.unpack_from(
            "<IIII", data, 0x1C + table * 16
        )
        if last != first + 1:
            raise SystemExit(
                f"table {table}: index+data ペアではない "
                f"(first={first} last={last})"
            )
        blob += data[first * PAGE_SIZE : (last + 1) * PAGE_SIZE]
    out.write_bytes(blob)
    print(f"{out}: {len(blob)} bytes from {export_pdb}")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        "rkbdb2xml/data/pdb_static.bin"
    )
    extract(src, dst)


if __name__ == "__main__":
    main()

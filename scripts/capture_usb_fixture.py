"""USB 上の実 Rekordbox エクスポートを fixture として回収する。

Rekordbox が USB (WSL 側は /mnt/f 等) に書き出した PIONEER/ と
Contents/ を tests/data/usb_fixtures/<name>/ にコピーし、
kaitai パーサーで export.pdb をウォークしてテーブル行数を表示する。

Usage:
    .venv/bin/python scripts/capture_usb_fixture.py /mnt/f <name>

事前に USB を WSL へマウントしておくこと:
    sudo mkdir -p /mnt/f && sudo mount -t drvfs F: /mnt/f
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from test_export_validation import walk_pdb  # noqa: E402

CAPTURE_DIRS = ("PIONEER", "Contents")


def main() -> None:
    usb = Path(sys.argv[1])
    name = sys.argv[2]
    dest = (Path(__file__).resolve().parent.parent
            / "tests" / "data" / "usb_fixtures" / name)
    if dest.exists():
        shutil.rmtree(dest)
    for d in CAPTURE_DIRS:
        src = usb / d
        if src.exists():
            shutil.copytree(src, dest / d)
            print(f"copied {d}: "
                  f"{sum(f.stat().st_size for f in (dest / d).rglob('*') if f.is_file())} bytes")
    pdb = dest / "PIONEER" / "rekordbox" / "export.pdb"
    if pdb.exists():
        print("tables:", walk_pdb(pdb))
    else:
        print("WARNING: export.pdb not found", file=sys.stderr)


if __name__ == "__main__":
    main()

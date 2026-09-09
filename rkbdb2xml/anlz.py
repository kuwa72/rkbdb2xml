"""ANLZ analysis-file helpers for USB device exports."""

from pathlib import Path
from typing import Any, Dict, Tuple


def anlz_path_hash(file_path: str) -> Tuple[int, int]:
    """Compute the Pioneer ANLZ directory hash from a USB-relative path.

    The returned ``(p_value, hash_value)`` are used to build the directory
    name ``P{p:03X}/{h:08X}`` under ``PIONEER/USBANLZ``.

    This is the algorithm found in the rekordbox binary by reverse
    engineering and verified against several rekordbox exports.

    Args:
        file_path: USB-relative audio path, e.g. ``/Contents/abc.mp3``.
                   Must start with ``/`` and use forward slashes.

    Returns:
        (p_value, hash_value) used for the ANLZ folder name.
    """
    hash_val = 0
    for char in file_path:
        c = ord(char) & 0xFFFF
        temp = (hash_val * 0x5BC9 + c) & 0xFFFFFFFF
        hash_val = (temp * 0x93B5 + c) & 0xFFFFFFFF
    hash_result = hash_val % 200003  # 0x30D43

    p = 0
    p |= (hash_result >> 0) & 0x01
    p |= (hash_result >> 1) & 0x02
    p |= (hash_result >> 4) & 0x04
    p |= (hash_result >> 4) & 0x08
    p |= (hash_result >> 5) & 0x10
    p |= (hash_result >> 8) & 0x20
    p |= (hash_result >> 10) & 0x40
    return p, hash_result


def anlz_dir(usb_path: str) -> Path:
    """Return the ``P.../........`` directory path for a USB audio path."""
    p, h = anlz_path_hash(usb_path)
    return Path(f"P{p:03X}") / f"{h:08X}"


def copy_anlz_for_content(
    db: Any,
    content: Any,
    usb_root: Path,
    usb_path: str,
    anlz_types: Tuple[str, ...] = ("DAT", "EXT"),
    verbose: bool = False,
) -> None:
    """Copy and rewrite the local ANLZ files for ``content`` to a USB tree.

    This rewrites the embedded ``PPTH`` path to ``usb_path`` so the CDJ
    can match the analysis data to the copied audio file.
    """
    try:
        get_anlz_paths = getattr(db, "get_anlz_paths", None)
        if get_anlz_paths is None:
            return
        paths: Dict[str, Any] = get_anlz_paths(content)
    except Exception as exc:
        if verbose:
            print(f"[WARN] ANLZ path 取得失敗: {exc}")
        return

    if not paths:
        return

    try:
        from pyrekordbox.anlz import AnlzFile
    except Exception as exc:
        if verbose:
            print(f"[WARN] pyrekordbox.anlz 読み込み失敗: {exc}")
        return

    dst_dir = usb_root / "PIONEER" / "USBANLZ" / anlz_dir(usb_path)
    dst_dir.mkdir(parents=True, exist_ok=True)

    for typ in anlz_types:
        src = paths.get(typ)
        if not src:
            continue
        src_path = Path(src)
        if not src_path.exists():
            continue
        dst = dst_dir / f"ANLZ0000.{typ}"
        try:
            af = AnlzFile.parse_file(str(src_path))
            af.set_path(usb_path)
            af.save(str(dst))
            if verbose:
                print(f"[INFO] ANLZ {typ} コピー: {dst}")
        except Exception as exc:
            if verbose:
                print(
                    f"[WARN] ANLZ {typ} コピー失敗 "
                    f"({src_path} -> {dst}): {exc}"
                )

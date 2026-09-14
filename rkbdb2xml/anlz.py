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


def rewrite_anlz_path(src: Path, dst: Path, usb_path: str) -> bool:
    """Rewrite the PPTH path of an ANLZ file with a byte-level patch.

    The tag keeps its structure and only ``len_path``/``len_tag`` and the
    path bytes are touched; every other byte stays identical, so readers
    that walk tags via ``len_tag`` keep working.

    The tag is always normalised to an exact fit
    (``len_tag == len_header + len_path``), matching what
    ``AnlzFile.set_path`` + ``save`` produces.  Slack left inside the tag
    could be read as part of the path by stricter readers and break the
    ANLZ/track association, so the path region is spliced to the new
    length whether it grows or shrinks, and ``len_tag`` plus the
    file-header ``len_file`` are adjusted by the difference.

    Returns ``True`` when the patch was applied, ``False`` when the caller
    should fall back to parsing and rebuilding the file (the structure is
    not recognised).
    """
    try:
        data = src.read_bytes()
    except OSError:
        return False
    if len(data) < 12 or data[0:4] != b"PMAI":
        return False
    len_header = int.from_bytes(data[4:8], "big")
    len_file = int.from_bytes(data[8:12], "big")
    if len_header < 12 or len_file > len(data):
        return False

    new_bytes = usb_path.encode("utf-16-be")
    new_len_path = len(new_bytes) + 2  # + 2 zero tail bytes

    buf = bytearray(data)
    i = len_header
    while i + 12 <= len_file:
        tag_type = bytes(buf[i : i + 4])
        len_tag = int.from_bytes(buf[i + 8 : i + 12], "big")
        if len_tag <= 0 or i + len_tag > len_file:
            return False
        if tag_type == b"PPTH":
            tag_len_header = int.from_bytes(buf[i + 4 : i + 8], "big")
            cur_len_path = int.from_bytes(buf[i + 12 : i + 16], "big")
            # PPTH layout: type(4) len_header(4) len_tag(4) len_path(4),
            # then len_path bytes of UTF-16-BE path incl. a 2-byte zero tail.
            if tag_len_header < 16 or cur_len_path <= 0:
                return False
            if i + 16 + cur_len_path > i + len_tag:
                return False
            path_off = i + 16
            # Splice the path region (path + any slack up to the tag end)
            # with the exact-fit new path, shifting the following tags.
            buf[path_off : i + len_tag] = new_bytes + b"\x00\x00"
            new_len_tag = tag_len_header + new_len_path
            delta = new_len_tag - len_tag
            if delta:
                buf[i + 8 : i + 12] = new_len_tag.to_bytes(4, "big")
                buf[8:12] = (len_file + delta).to_bytes(4, "big")
            buf[i + 12 : i + 16] = new_len_path.to_bytes(4, "big")
            Path(dst).write_bytes(buf)
            return True
        i += len_tag
    return False


def existing_anlz_matches(dst: Path, usb_path: str) -> bool:
    """Check that an existing ANLZ file already points at ``usb_path``.

    Only the header area is read: the PPTH tag must be reachable within the
    first few KB, hold an exact-fit tag (``len_tag == len_header +
    len_path``) and contain exactly ``usb_path``.  Anything else is
    treated as stale and rewritten.
    """
    try:
        with open(dst, "rb") as f:
            head = f.read(8192)
    except OSError:
        return False
    if len(head) < 12 or head[0:4] != b"PMAI":
        return False
    len_header = int.from_bytes(head[4:8], "big")
    len_file = int.from_bytes(head[8:12], "big")
    if len_header < 12:
        return False
    i = len_header
    limit = min(len_file, len(head))
    while i + 16 <= limit:
        tag_type = head[i : i + 4]
        len_tag = int.from_bytes(head[i + 8 : i + 12], "big")
        if len_tag <= 0:
            return False
        if tag_type == b"PPTH":
            tag_len_header = int.from_bytes(head[i + 4 : i + 8], "big")
            len_path = int.from_bytes(head[i + 12 : i + 16], "big")
            if tag_len_header < 16 or len_tag != tag_len_header + len_path:
                return False
            if i + 16 + len_path > len(head):
                return False
            path = head[i + 16 : i + 16 + len_path].decode(
                "utf-16-be", "replace"
            ).rstrip("\x00")
            return path == usb_path
        i += len_tag
    return False


def copy_anlz_for_content(
    db: Any,
    content: Any,
    usb_root: Path,
    usb_path: str,
    anlz_types: Tuple[str, ...] = ("DAT", "EXT", "2EX"),
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
        if dst.exists() and existing_anlz_matches(dst, usb_path):
            # 再エクスポート時は同じ内容になるためスキップするが、PPTH が
            # 期待値と違う（旧バージョンで書かれた等）場合は書き直す
            continue
        try:
            # Fast path: byte-level PPTH rewrite (~1 ms vs ~100 ms for a
            # full parse + rebuild). Falls back to the slow path when the
            # tag structure is not recognised.
            if not rewrite_anlz_path(src_path, dst, usb_path):
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

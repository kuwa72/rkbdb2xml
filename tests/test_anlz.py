"""Tests for ANLZ USB path hash and analysis-file handling."""

from pathlib import Path

import pytest

from rkbdb2xml.anlz import (
    anlz_dir,
    anlz_path_hash,
    existing_anlz_matches,
    rewrite_anlz_path,
)


@pytest.mark.parametrize(
    "usb_path, expected_p, expected_hash",
    [
        (
            "/Contents/Leo Portela/Bon Vibrant - Leo Portela.flac",
            0x00E,
            0x000281CE,
        ),
        (
            "/Contents/Daniela Cast/Jazzy - Daniela Cast.flac",
            0x00A,
            0x0000CC9C,
        ),
    ],
)
def test_anlz_path_hash_verified_cases(
    usb_path: str, expected_p: int, expected_hash: int
) -> None:
    p, h = anlz_path_hash(usb_path)
    assert p == expected_p
    assert h == expected_hash
    expected_dir = Path(f"P{expected_p:03X}") / f"{expected_hash:08X}"
    assert anlz_dir(usb_path) == expected_dir


def test_anlz_dir_format() -> None:
    path = "/Contents/test.mp3"
    p, h = anlz_path_hash(path)
    result = anlz_dir(path)
    assert result.parts[0].startswith("P")
    assert len(result.parts[0]) == 4
    assert len(result.parts[1]) == 8


# ----- rewrite_anlz_path ---------------------------------------------------


def make_anlz(
    path_text: str, with_dummy_tag: bool = True, slack: int = 0
) -> bytes:
    """Build a minimal ANLZ file: PMAI header + PPTH tag (+ a dummy tag).

    The dummy tag lets tests verify that tag-walking still reaches the end of
    the file after a patch (i.e. nothing after PPTH broke).  ``slack`` adds
    zero padding inside the PPTH tag after the path, which real files have
    when Rekordbox shortens a stored path.
    """
    path_bytes = path_text.encode("utf-16-be")
    len_path = len(path_bytes) + 2  # + 2 zero tail bytes
    len_tag = 16 + len_path + slack
    ppth = (
        b"PPTH"
        + (16).to_bytes(4, "big")
        + len_tag.to_bytes(4, "big")
        + len_path.to_bytes(4, "big")
        + path_bytes
        + b"\x00\x00"
        + b"\x00" * slack
    )
    extra = b""
    if with_dummy_tag:
        # type(4) + len_header(4) + len_tag(4) + content(4) = 16 bytes
        extra = (
            b"XXXX"
            + (12).to_bytes(4, "big")
            + (16).to_bytes(4, "big")
            + b"\x00" * 4
        )
    len_file = 28 + len(ppth) + len(extra)
    header = (
        b"PMAI"
        + (28).to_bytes(4, "big")
        + len_file.to_bytes(4, "big")
        + b"\x00" * 16
    )
    return header + ppth + extra


def read_ppth(data: bytes) -> str:
    """Walk tags and return the PPTH path (same layout as the real format)."""
    assert data[0:4] == b"PMAI"
    lh = int.from_bytes(data[4:8], "big")
    lf = int.from_bytes(data[8:12], "big")
    i = lh
    while i + 12 <= lf:
        lt = int.from_bytes(data[i + 8 : i + 12], "big")
        assert lt > 0 and i + lt <= lf, "tag walk must stay inside the file"
        if data[i : i + 4] == b"PPTH":
            lp = int.from_bytes(data[i + 12 : i + 16], "big")
            return data[i + 16 : i + 16 + lp - 2].decode("utf-16-be")
        i += lt
    raise AssertionError("PPTH tag not found")


def ppth_len_tag(data: bytes) -> int:
    """Return the len_tag field of the PPTH tag."""
    lh = int.from_bytes(data[4:8], "big")
    lf = int.from_bytes(data[8:12], "big")
    i = lh
    while i + 12 <= lf:
        lt = int.from_bytes(data[i + 8 : i + 12], "big")
        if data[i : i + 4] == b"PPTH":
            return lt
        i += lt
    raise AssertionError("PPTH tag not found")


def test_rewrite_anlz_path_shrinks_tag_to_exact_fit(tmp_path):
    """新しいパスが短い場合はタグを縮小し、len_tag == len_header + len_path
    の exact fit にする（パディングを残さない）。"""
    src = tmp_path / "in.dat"
    dst = tmp_path / "out.dat"
    old = "C:/Users/xxx/Music/iTunes/long/path/track.m4a"
    new = "/Contents/abc.m4a"
    src.write_bytes(make_anlz(old))

    assert rewrite_anlz_path(src, dst, new) is True

    patched = dst.read_bytes()
    delta = len(old.encode("utf-16-be")) - len(new.encode("utf-16-be"))
    assert len(patched) == len(src.read_bytes()) - delta
    assert int.from_bytes(patched[8:12], "big") == len(patched)  # len_file
    assert ppth_len_tag(patched) == 16 + len(new.encode("utf-16-be")) + 2
    assert read_ppth(patched) == new


def test_rewrite_anlz_path_removes_slack_inside_tag(tmp_path):
    """タグ内にパディングがある入力でも exact fit に正規化する。"""
    src = tmp_path / "in.dat"
    dst = tmp_path / "out.dat"
    new = "/Contents/abc.m4a"
    src.write_bytes(make_anlz("?/a.m4a", slack=64))

    assert rewrite_anlz_path(src, dst, new) is True

    patched = dst.read_bytes()
    assert ppth_len_tag(patched) == 16 + len(new.encode("utf-16-be")) + 2
    assert int.from_bytes(patched[8:12], "big") == len(patched)
    assert read_ppth(patched) == new


def test_rewrite_anlz_path_grows_tag_when_path_is_longer(tmp_path):
    """Rekordbox の短いパス（?/name.ext 等）より USB パスが長い場合は、
    タグを拡張して後続タグをシフトし、len_tag / len_file を更新する。"""
    src = tmp_path / "in.dat"
    dst = tmp_path / "out.dat"
    src.write_bytes(make_anlz("?/a.m4a"))

    assert rewrite_anlz_path(src, dst, "/Contents/9f2c3a1b7e4d5c6a7b8c9d0e1f2a3b4c.m4a") is True

    original = src.read_bytes()
    patched = dst.read_bytes()
    delta = len("/Contents/9f2c3a1b7e4d5c6a7b8c9d0e1f2a3b4c.m4a".encode("utf-16-be")) + 2
    delta -= len("?/a.m4a".encode("utf-16-be")) + 2
    assert len(patched) == len(original) + delta
    assert int.from_bytes(patched[8:12], "big") == len(patched)  # len_file
    assert read_ppth(patched) == "/Contents/9f2c3a1b7e4d5c6a7b8c9d0e1f2a3b4c.m4a"


def test_rewrite_anlz_path_round_trips_with_pyrekordbox(tmp_path):
    """パッチ後のファイルが pyrekordbox のパーサで読めること。"""
    pytest.importorskip("pyrekordbox.anlz")
    from pyrekordbox.anlz import AnlzFile

    src = tmp_path / "in.dat"
    dst = tmp_path / "out.dat"
    src.write_bytes(make_anlz("?/a.m4a", with_dummy_tag=False))

    assert rewrite_anlz_path(src, dst, "/Contents/abc.m4a") is True

    af = AnlzFile.parse_file(str(dst))
    assert af.get("PPTH") == "/Contents/abc.m4a"


def test_rewrite_anlz_path_matches_pyrekordbox_rebuild(tmp_path):
    """パッチ結果が AnlzFile.set_path + save の出力とバイト同一であること。

    Rekordbox が読めることが実証済みの形式と完全に一致させるための
    回帰テスト。
    """
    pytest.importorskip("pyrekordbox.anlz")
    from pyrekordbox.anlz import AnlzFile

    new_path = "/Contents/9f2c3a1b7e4d5c6a7b8c9d0e1f2a3b4c.m4a"
    for path_text, slack in (
        ("?/a.m4a", 0),
        ("?/a.m4a", 64),
        ("C:/Users/xxx/Music/iTunes/long/path/track.m4a", 0),
    ):
        src = tmp_path / "in.dat"
        dst_patch = tmp_path / "patch.dat"
        dst_rebuild = tmp_path / "rebuild.dat"
        src.write_bytes(make_anlz(path_text, with_dummy_tag=False,
                                  slack=slack))

        assert rewrite_anlz_path(src, dst_patch, new_path) is True
        af = AnlzFile.parse_file(str(src))
        af.set_path(new_path)
        af.save(str(dst_rebuild))

        assert dst_patch.read_bytes() == dst_rebuild.read_bytes()


def test_rewrite_anlz_path_rejects_unknown_structure(tmp_path):
    src = tmp_path / "bad.dat"
    dst = tmp_path / "out.dat"
    src.write_bytes(b"NOTANLZ" + b"\x00" * 32)
    assert rewrite_anlz_path(src, dst, "/Contents/abc.m4a") is False
    assert not dst.exists()


def test_rewrite_anlz_path_rejects_missing_ppth(tmp_path):
    src = tmp_path / "noppth.dat"
    dst = tmp_path / "out.dat"
    # PMAI header + one non-PPTH tag
    tag = b"PMAI" + (28).to_bytes(4, "big") + (44).to_bytes(4, "big") + b"\x00" * 16
    tag += b"XXXX" + (12).to_bytes(4, "big") + (16).to_bytes(4, "big") + b"\x00" * 4
    src.write_bytes(tag)
    assert rewrite_anlz_path(src, dst, "/Contents/abc.m4a") is False
    assert not dst.exists()


# ----- existing_anlz_matches -----------------------------------------------


def test_existing_anlz_matches_exact_fit(tmp_path):
    """exact-fit で同じパスを持つ既存ファイルはスキップ対象。"""
    dst = tmp_path / "ANLZ0000.DAT"
    dst.write_bytes(make_anlz("/Contents/abc.m4a"))
    assert existing_anlz_matches(dst, "/Contents/abc.m4a") is True
    assert existing_anlz_matches(dst, "/Contents/other.m4a") is False


def test_existing_anlz_matches_rejects_slack(tmp_path):
    """タグ内パディングがある旧形式ファイルは書き直し対象。"""
    dst = tmp_path / "ANLZ0000.DAT"
    dst.write_bytes(make_anlz("/Contents/abc.m4a", slack=64))
    assert existing_anlz_matches(dst, "/Contents/abc.m4a") is False


def test_existing_anlz_matches_rejects_garbage(tmp_path):
    dst = tmp_path / "ANLZ0000.DAT"
    dst.write_bytes(b"GARBAGE")
    assert existing_anlz_matches(dst, "/Contents/abc.m4a") is False
    assert existing_anlz_matches(tmp_path / "missing.DAT",
                                 "/Contents/abc.m4a") is False

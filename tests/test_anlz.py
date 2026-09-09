"""Tests for ANLZ USB path hash and analysis-file handling."""

from pathlib import Path

import pytest

from rkbdb2xml.anlz import anlz_dir, anlz_path_hash


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

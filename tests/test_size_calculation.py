import pytest
from rkbdb2xml.gui import format_bytes

def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(1024 * 1024) == "1.0 MB"
    assert format_bytes(15 * 1024 * 1024) == "15.0 MB"
    assert format_bytes(1024 * 1024 * 1024) == "1.00 GB"
    assert format_bytes(int(14.8 * 1024 * 1024 * 1024)) == "14.80 GB"
    assert format_bytes(int(29.3 * 1024 * 1024 * 1024)) == "29.30 GB"


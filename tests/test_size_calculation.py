import pytest
from rkbdb2xml.gui import (
    SIZE_ESTIMATED,
    SIZE_EXACT,
    SIZE_MISSING,
    SIZE_UNKNOWN,
    format_bytes,
    resolve_track_size,
)


class FakeContent:
    """Minimal stand-in for a pyrekordbox DjmdContent row."""

    def __init__(
        self,
        folder_path=None,
        file_size=None,
        length=None,
        bit_rate=None,
        file_type=None,
        kind=None,
    ):
        self.FolderPath = folder_path
        self.FileSize = file_size
        self.Length = length
        self.BitRate = bit_rate
        self.FileType = file_type
        self.Kind = kind


def test_format_bytes():
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(1024 * 1024) == "1.0 MB"
    assert format_bytes(15 * 1024 * 1024) == "15.0 MB"
    assert format_bytes(1024 * 1024 * 1024) == "1.00 GB"
    assert format_bytes(int(14.8 * 1024 * 1024 * 1024)) == "14.80 GB"
    assert format_bytes(int(29.3 * 1024 * 1024 * 1024)) == "29.30 GB"
    assert format_bytes(-500) == "0 B"


def test_overflow_restoration():
    overflowed = -289099128
    restored = overflowed & 0xFFFFFFFF
    assert restored == 4005868168
    assert format_bytes(restored) == "3.73 GB"


# ----- resolve_track_size: exact (実測) -----------------------------------


def test_exact_size_from_db_file_size():
    size, status = resolve_track_size(FakeContent(file_size=5_000_000))
    assert (size, status) == (5_000_000, SIZE_EXACT)


def test_exact_size_from_overflowed_db_file_size():
    # Rekordbox stores FileSize as a 32-bit signed int; -289099128 is 4005868168.
    size, status = resolve_track_size(FakeContent(file_size=-289099128))
    assert size == 4005868168
    assert status == SIZE_EXACT


def test_small_db_file_size_is_still_exact():
    # Below the old 100 KB floor a real size was silently downgraded to an estimate.
    size, status = resolve_track_size(FakeContent(file_size=80_000))
    assert (size, status) == (80_000, SIZE_EXACT)


def test_zero_file_size_is_not_exact():
    size, status = resolve_track_size(FakeContent(file_size=0, length=60, bit_rate=128))
    assert (size, status) == (60 * 16_000, SIZE_ESTIMATED)


def test_exact_size_from_local_file(tmp_path):
    f = tmp_path / "track.mp3"
    f.write_bytes(b"x" * 1234)
    size, status = resolve_track_size(
        FakeContent(folder_path=str(f)), resolve_path=lambda loc: f
    )
    assert size == 1234
    assert status == SIZE_EXACT


def test_missing_file_is_not_exportable_even_with_db_file_size():
    # ファイルが無い曲はエクスポートされないので、DB に FileSize があっても
    # サイズに含めない（対象外）。
    size, status = resolve_track_size(
        FakeContent(folder_path="/deleted/track.mp3", file_size=7_000_000),
        resolve_path=lambda loc: None,
    )
    assert (size, status) == (0, SIZE_MISSING)


def test_empty_folder_path_is_not_exportable():
    size, status = resolve_track_size(
        FakeContent(folder_path=None, file_size=5_000_000),
        resolve_path=lambda loc: None,
    )
    assert (size, status) == (0, SIZE_MISSING)


# ----- resolve_track_size: estimated (推定) -------------------------------


def test_estimate_from_length_and_bitrate():
    # 180 s at 320 kbps.
    size, status = resolve_track_size(FakeContent(length=180, bit_rate=320))
    assert (size, status) == (180 * 40_000, SIZE_ESTIMATED)


def test_estimate_matches_rekordbox_wav_reference():
    # NOISE.wav in tests/data/test_rkb6_export.xml: TotalTime=5 s, BitRate=2116,
    # actual Size=1382226. The bitrate-based estimate is within ~5%.
    content = FakeContent(length=5, bit_rate=2116, file_type="WAV ファイル")
    size, status = resolve_track_size(content)
    assert status == SIZE_ESTIMATED
    assert abs(size - 1_382_226) / 1_382_226 < 0.05


def test_estimate_from_lossless_extension_without_bitrate():
    content = FakeContent(folder_path="C:/Music/track.wav", length=60)
    size, status = resolve_track_size(content)
    assert (size, status) == (60 * 176_400, SIZE_ESTIMATED)


def test_estimate_from_file_type_int_enum():
    # DjmdContent.FileType is pyrekordbox's FileType IntEnum: WAV=11, AIFF=12, FLAC=5.
    size, status = resolve_track_size(FakeContent(file_type=11, length=60))
    assert (size, status) == (60 * 176_400, SIZE_ESTIMATED)
    size, status = resolve_track_size(FakeContent(file_type=5, length=60))
    assert (size, status) == (60 * 100_000, SIZE_ESTIMATED)


def test_estimate_from_file_type_without_folder_path():
    content = FakeContent(length=60, file_type="FLAC ファイル")
    size, status = resolve_track_size(content)
    assert (size, status) == (60 * 100_000, SIZE_ESTIMATED)


def test_estimate_does_not_apply_minimum_floor():
    # A short low-bitrate track must not be inflated to 1 MB.
    size, status = resolve_track_size(FakeContent(length=30, bit_rate=128))
    assert (size, status) == (30 * 16_000, SIZE_ESTIMATED)


# ----- resolve_track_size: missing (対象外) -------------------------------


def test_missing_file_with_no_size_signal_is_excluded():
    content = FakeContent(folder_path="/gone/track.mp3", length=None, bit_rate=None)
    size, status = resolve_track_size(content, resolve_path=lambda loc: None)
    assert (size, status) == (0, SIZE_MISSING)


def test_missing_file_without_length_is_excluded_not_estimated():
    # ファイルが無い曲は推定すらせず対象外にする（エクスポートされないため）。
    content = FakeContent(folder_path="/gone/track.mp3", bit_rate=320)
    size, status = resolve_track_size(content, resolve_path=lambda loc: None)
    assert (size, status) == (0, SIZE_MISSING)


# ----- resolve_track_size: unknown (不明、resolver なし) ------------------


def test_unknown_without_any_size_signal():
    # resolve_path なし（純 DB 行）のときだけ UNKNOWN が返る。
    size, status = resolve_track_size(FakeContent(length=None, bit_rate=None))
    assert (size, status) == (0, SIZE_UNKNOWN)


def test_unknown_when_length_is_zero():
    size, status = resolve_track_size(FakeContent(length=0, bit_rate=320))
    assert (size, status) == (0, SIZE_UNKNOWN)


def test_unknown_when_length_is_invalid():
    size, status = resolve_track_size(FakeContent(length="abc", bit_rate=320))
    assert (size, status) == (0, SIZE_UNKNOWN)

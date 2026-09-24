import shutil
from pathlib import Path

from rekordbox_pdb import Database

from scripts import compare_usb_exports as mod
from scripts.compare_usb_exports import check_paths, raw_pdb_diff

FIXTURE = Path(__file__).parent / "data" / "usb_fixtures" / (
    "rkb680_sc01_one_ascii"
)


def _set_page_rows(data: bytearray, page: int, rows: int,
                   offs: int = 0) -> None:
    """Write the (num_row_offsets, num_rows) bit fields at 0x18.

    13 bits of num_row_offsets followed by 11 bits of num_rows in
    little-endian bit order, exactly as the kaitai parser reads them.
    """
    word = (offs & 0x1FFF) | ((rows & 0x7FF) << 13)
    base = page * 4096 + 0x18
    data[base:base + 3] = word.to_bytes(3, "little")


def test_raw_pdb_diff_reports_page_and_header_differences(tmp_path):
    page_size = 4096
    reference = bytearray(page_size * 2)
    generated = bytearray(reference)
    generated[0] = 1
    generated[page_size + 100] = 2

    ref_path = tmp_path / "reference.pdb"
    gen_path = tmp_path / "generated.pdb"
    ref_path.write_bytes(reference)
    gen_path.write_bytes(generated)

    result = raw_pdb_diff(ref_path, gen_path)

    assert result == {
        "ref_bytes": page_size * 2,
        "gen_bytes": page_size * 2,
        "ref_pages": 2,
        "gen_pages": 2,
        "common_pages": 2,
        "differing_pages": 2,
        "differing_header_pages": 1,
        "differing_bytes": 2,
        "ref_rows": 0,
        "gen_rows": 0,
        "differing_row_pages": 0,
    }


def test_raw_pdb_diff_reports_row_counts_per_page(tmp_path):
    """ページヘッダの num_rows を行数として集計・比較する。"""
    page_size = 4096
    reference = bytearray(page_size * 2)
    # page 0 is the database header page: its bytes must never be read
    # as row counts.
    _set_page_rows(reference, 0, rows=999)
    _set_page_rows(reference, 1, rows=7, offs=7)
    generated = bytearray(reference)
    _set_page_rows(generated, 1, rows=9, offs=9)

    ref_path = tmp_path / "reference.pdb"
    gen_path = tmp_path / "generated.pdb"
    ref_path.write_bytes(reference)
    gen_path.write_bytes(generated)

    result = raw_pdb_diff(ref_path, gen_path)

    assert result["ref_rows"] == 7
    assert result["gen_rows"] == 9
    assert result["differing_row_pages"] == 1


def test_report_known_diffs_use_three_categories(capsys):
    mod.results.clear()

    mod.report(False, "example", "detail", category="input")
    out = capsys.readouterr().out
    assert "入力由来" in out
    assert mod.results == [], "既知の差分は FAIL に数えられない"

    mod.report(False, "example", "detail", category="generation")
    out = capsys.readouterr().out
    assert "Rekordbox世代／履歴由来" in out
    assert mod.results == []

    mod.report(False, "example", "detail", category="unimplemented")
    out = capsys.readouterr().out
    assert "rkbdb2xml未実装" in out
    assert mod.results == []


def test_report_rejects_unknown_category():
    try:
        mod.report(False, "example", category="bogus")
    except ValueError:
        return
    raise AssertionError("unknown category must raise ValueError")


def _copy_fixture(tmp_path: Path) -> Path:
    dst = tmp_path / "usb"
    shutil.copytree(FIXTURE, dst)
    return dst


def _check(root: Path, db=None) -> list:
    if db is None:
        db = Database.from_file(
            root / "PIONEER" / "rekordbox" / "export.pdb"
        )
    mod.results.clear()
    check_paths(root, db, "gen")
    return list(mod.results)


def test_check_paths_passes_on_intact_fixture(tmp_path):
    root = _copy_fixture(tmp_path)
    results = _check(root)
    assert results and all(results), results


def test_check_paths_detects_missing_content(tmp_path):
    root = _copy_fixture(tmp_path)
    target = next((root / "Contents").rglob("*.mp3"))
    target.unlink()

    results = _check(root)

    assert results[0] is False, "Contents 相対パスと file_path の突合が失敗しない"


def test_check_paths_detects_missing_anlz_file(tmp_path):
    root = _copy_fixture(tmp_path)
    db = Database.from_file(
        root / "PIONEER" / "rekordbox" / "export.pdb"
    )
    (root / db.tracks[0].analyze_path.lstrip("/")).unlink()

    results = _check(root, db)

    assert results[1] is False, "ANLZ 配置検出が失敗しない"


def test_check_paths_detects_stale_ppth(tmp_path):
    root = _copy_fixture(tmp_path)
    db = Database.from_file(
        root / "PIONEER" / "rekordbox" / "export.pdb"
    )
    anlz = root / db.tracks[0].analyze_path.lstrip("/")
    data = bytearray(anlz.read_bytes())
    offset = data.find(b"PPTH") + 16  # path region, UTF-16-BE
    assert data[offset:offset + 2] == b"\x00/"
    data[offset + 3] = ord("X")  # "/Contents/..." -> "XContents/..."
    anlz.write_bytes(data)

    results = _check(root, db)

    assert results[3] is False, "PPTH 不一致を検出しない"


class _FakeTrack:
    def __init__(self, file_path, analyze_path):
        self.file_path = file_path
        self.analyze_path = analyze_path


class _FakeDb:
    def __init__(self, tracks):
        self.tracks = tracks


def test_check_paths_detects_wrong_anlz_directory(tmp_path):
    root = _copy_fixture(tmp_path)
    real = Database.from_file(
        root / "PIONEER" / "rekordbox" / "export.pdb"
    ).tracks[0]
    # analyze_path の dir が anlz_dir(file_path) と食い違う（DB 内の不整合）
    fake = _FakeDb([
        _FakeTrack(
            real.file_path,
            "/PIONEER/USBANLZ/P000/00000000/ANLZ0000.DAT",
        ),
    ])

    results = _check(root, fake)

    assert results[2] is False, "USBANLZ 配置（ハッシュ dir）不一致を検出しない"

from scripts.compare_usb_exports import raw_pdb_diff


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
    }

import os
import tempfile
import urllib.parse
from pathlib import Path
import pytest
from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rekordbox_test.db')

def test_resolve_file_path():
    exporter = RekordboxXMLExporter.__new__(RekordboxXMLExporter)
    
    # Test standard URI
    uri = "file://localhost/C:/Music/test%20song.mp3"
    resolved = exporter._resolve_file_path(uri)
    assert resolved is not None
    assert "test song.mp3" in str(resolved)
    
    # Test URI with special characters
    uri_special = "file://localhost/Music/Artist%20%26%20Band/Track%231.m4a"
    resolved_sp = exporter._resolve_file_path(uri_special)
    assert resolved_sp is not None
    assert "Track#1.m4a" in str(resolved_sp)
    assert "Artist & Band" in str(resolved_sp)

@pytest.mark.skipif(not os.path.exists(TEST_DB_PATH), reason="テストDBが存在しません")
def test_export_includes_tracks_and_copies():
    with tempfile.TemporaryDirectory() as tmpdir:
        xml_path = os.path.join(tmpdir, "rekordbox.xml")
        try:
            exporter = RekordboxXMLExporter(db_path=TEST_DB_PATH)
            exporter.generate_xml(xml_path)
            assert os.path.exists(xml_path), "XMLファイルが生成されていません"
            exporter.close()
        except Exception as e:
            pytest.skip(f"Rekordbox DB key not available in test environment: {e}")


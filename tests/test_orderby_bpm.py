import os
import tempfile
import xml.etree.ElementTree as ET
import pytest
from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_xml

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rekordbox_test.db')

@pytest.mark.skipif(not os.path.exists(TEST_DB_PATH), reason="テストDBが存在しません")
def test_playlist_order_by_bpm():
    """
    --orderby=bpm指定時、プレイリスト内の曲順がBPM昇順になることを確認
    """
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as tmp:
        temp_path = tmp.name
    try:
        export_rekordbox_db_to_xml(TEST_DB_PATH, temp_path, orderby="bpm")
        tree = ET.parse(temp_path)
        root = tree.getroot()
        playlists = root.find('PLAYLISTS')
        assert playlists is not None
        # 最初の通常プレイリストを取得
        for pl in playlists.findall('NODE'):
            if pl.attrib.get('Type') == 'PLAYLIST':
                tracks = pl.findall('TRACK')
                if not tracks:
                    continue
                bpms = []
                for tr in tracks:
                    bpm = tr.attrib.get('AverageBpm', None)
                    try:
                        bpm_val = float(bpm)
                    except Exception:
                        bpm_val = float('inf')
                    bpms.append(bpm_val)
                # BPM昇順になっているか
                assert bpms == sorted(bpms), f"BPM昇順になっていません: {bpms}"
                break
        else:
            pytest.skip("検証用プレイリストが見つかりません")
    finally:
        os.remove(temp_path)

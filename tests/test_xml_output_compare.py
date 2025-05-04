import os
import tempfile
import xml.etree.ElementTree as ET
import pytest
from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_xml

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rekordbox_test.db')
REFERENCE_XML_PATH = os.path.join(os.path.dirname(__file__), 'data', 'test_rkb6_export.xml')

def test_top_level_and_collection_playlists_and_track_attributes():
    """
    Rekordbox純正XML（test_rkb6_export.xml）と現状の出力XMLのトップレベル要素、
    COLLECTION配下のTRACK数・主要属性、PLAYLISTS配下のNODE数を比較する。
    """
    if not (os.path.exists(TEST_DB_PATH) and os.path.exists(REFERENCE_XML_PATH)):
        pytest.skip("テストDBまたは正規XMLが存在しません")
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as tmp:
        temp_path = tmp.name
    try:
        export_rekordbox_db_to_xml(TEST_DB_PATH, temp_path)
        ref_tree = ET.parse(REFERENCE_XML_PATH)
        out_tree = ET.parse(temp_path)
        ref_root = ref_tree.getroot()
        out_root = out_tree.getroot()
        # ルート要素名・属性比較
        assert ref_root.tag == out_root.tag
        assert ref_root.attrib.keys() == out_root.attrib.keys()
        # トップレベル子要素名リスト比較
        ref_children = [c.tag for c in ref_root]
        out_children = [c.tag for c in out_root]
        assert ref_children == out_children
        # COLLECTION要素配下のTRACK数比較
        ref_collection = ref_root.find('COLLECTION')
        out_collection = out_root.find('COLLECTION')
        assert ref_collection is not None and out_collection is not None
        ref_tracks = ref_collection.findall('TRACK')
        out_tracks = out_collection.findall('TRACK')
        assert len(ref_tracks) == len(out_tracks), f"COLLECTION/TRACK数: expected {len(ref_tracks)}, got {len(out_tracks)}"
        # 主要属性比較（Name, Artist, Album, Location, AverageBpmのみ）: ソート順無視
        key_attrs = ["TrackID", "Name", "Artist", "Album", "AverageBpm"]
        ref_map = {
            tr.attrib['TrackID']: {attr: tr.attrib.get(attr) for attr in key_attrs}
            for tr in ref_tracks
        }
        out_map = {
            tr.attrib['TrackID']: {attr: tr.attrib.get(attr) for attr in key_attrs}
            for tr in out_tracks
        }
        assert set(ref_map.keys()) == set(out_map.keys()), \
            f"TRACK IDs mismatch: {set(ref_map.keys())} vs {set(out_map.keys())}"
        for tid in ref_map:
            assert ref_map[tid] == out_map[tid], \
                f"TRACK {tid} attrs mismatch: expected {ref_map[tid]}, got {out_map[tid]}"
        # PLAYLISTS要素配下のNODE数比較
        ref_playlists = ref_root.find('PLAYLISTS')
        out_playlists = out_root.find('PLAYLISTS')
        assert ref_playlists is not None and out_playlists is not None
        ref_nodes = ref_playlists.findall('NODE')
        out_nodes = out_playlists.findall('NODE')
        assert len(ref_nodes) == len(out_nodes), f"PLAYLISTS/NODE数: expected {len(ref_nodes)}, got {len(out_nodes)}"
        # TEMPO要素検証: 各TRACKに1つのTEMPOがあり、Bpm属性がAverageBpmと一致
        for tr in out_tracks:
            tempos = tr.findall('TEMPO')
            assert len(tempos) == 1, f"Track {tr.attrib['TrackID']} Tempo count: {len(tempos)}"
            assert tempos[0].attrib.get('Bpm') == tr.attrib.get('AverageBpm')
    finally:
        os.remove(temp_path)

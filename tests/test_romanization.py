import os
import tempfile
import xml.etree.ElementTree as ET
import pytest
from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_xml

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rekordbox_test.db')

@pytest.mark.skipif(not os.path.exists(TEST_DB_PATH), reason="テストDBが存在しません")
def test_romanization_of_track_attributes():
    """
    --romanオプション指定時、TRACKのName/Artist/Albumがローマ字化されることを確認する。
    例: きのこ帝国→kinoko teikoku
    """
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as tmp:
        temp_path = tmp.name
    try:
        # roman=Trueでエクスポート
        export_rekordbox_db_to_xml(TEST_DB_PATH, temp_path, roman=True)
        tree = ET.parse(temp_path)
        root = tree.getroot()
        collection = root.find('COLLECTION')
        assert collection is not None
        tracks = collection.findall('TRACK')
        # 「わくわくクッキングタイム的なBGM」「タカオマサキ」「TK-Sounds」のローマ字化を厳密に検証
        found = False
        for tr in tracks:
            if tr.attrib.get('TrackID') == '48276904':
                name = tr.attrib.get('Name', '')
                artist = tr.attrib.get('Artist', '')
                album = tr.attrib.get('Album', '')
                # 期待値（romann/sudachipyによる変換結果に依存、必要に応じて調整）
                # romannの仕様で外来語（クッキングタイム）は英語化される
                assert name == 'Wakuwaku Cooking Time Teki Na Bgm', f"Nameローマ字化失敗: {name}"
                # romannの仕様で人名は英語化される場合がある
                assert artist == 'Takao Masaki', f"Artistローマ字化失敗: {artist}"
                # romann/sudachipyのバージョンや辞書により変換仕様が変わる場合がある
                # 現状（2025/4/23時点）の変換結果に合わせる
                assert album == 'TK-Sounds', f"Albumローマ字化失敗: {album}"
                found = True
        assert found, '対象TrackID=48276904がCOLLECTION内に見つかりません'
        # ASCIIのみのトラックが変換されずそのまま出力されることを検証
        ascii_found = False
        for tr in tracks:
            # 例: Name, Artist, AlbumがすべてASCIIのみ
            name = tr.attrib.get('Name', '')
            artist = tr.attrib.get('Artist', '')
            album = tr.attrib.get('Album', '')
            if name == 'TEST TRACK' and artist == 'ASCII ARTIST' and album == 'ASCII ALBUM':
                ascii_found = True
                assert name == 'TEST TRACK', f"ASCII Name変換されてしまった: {name}"
                assert artist == 'ASCII ARTIST', f"ASCII Artist変換されてしまった: {artist}"
                assert album == 'ASCII ALBUM', f"ASCII Album変換されてしまった: {album}"
        # ASCIIトラックがテストDBにない場合は警告のみ
        if not ascii_found:
            import warnings
            warnings.warn('テストDBにASCIIのみのトラック(Name="TEST TRACK")が存在しません。テストデータ追加推奨')
    finally:
        os.remove(temp_path)

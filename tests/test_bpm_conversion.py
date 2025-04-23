#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pytest
import sys
import os

# プロジェクトのルートディレクトリをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter

# テスト用DBパス
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rekordbox_test.db')

@pytest.fixture
def exporter():
    return RekordboxXMLExporter(db_path=TEST_DB_PATH)

def test_bpm_conversion(exporter):
    """実データのBPM値が正しく変換されることをテスト（mock不使用）"""
    tracks = exporter.db.search_content("")
    assert len(tracks) > 0, "テスト用DBにトラックが存在しません"
    track = tracks[0]
    bpm_raw = getattr(track, 'BPM', None)
    assert bpm_raw is not None, "トラックにBPM値がありません"
    bpm_converted = f"{bpm_raw / 100:.2f}"
    assert 60.0 <= float(bpm_converted) <= 200.0, f"変換後BPM値が不正: {bpm_converted}"

def test_bpm_conversion_dict_access(exporter):
    tracks = exporter.db.search_content("")
    assert len(tracks) > 0, "テスト用DBにトラックが存在しません"
    track = tracks[0]
    try:
        bpm_val = getattr(track, 'BPM', None)
        if bpm_val is None:
            pytest.skip("トラックにBPM属性がありません")
        bpm_float = float(bpm_val)
    except Exception:
        pytest.skip(f"BPM値が数値で取得できません: {getattr(track, 'BPM', None)}")
    track_dict = {
        'ID': getattr(track, 'ID', None),
        'Title': getattr(track, 'Title', None),
        'BPM': bpm_float,
        'Location': getattr(track, 'Location', None)
    }
    bpm_converted = f"{track_dict['BPM'] / 100:.2f}"
    assert 60.0 <= float(bpm_converted) <= 200.0, f"変換後BPM値が不正: {bpm_converted}"

def test_bpm_conversion_edge_cases(exporter):
    tracks = exporter.db.search_content("")
    edge_tracks = [t for t in tracks if hasattr(t, 'BPM') and isinstance(t.BPM, (int, float)) and (t.BPM < 7000 or t.BPM > 18000)]
    if not edge_tracks:
        pytest.skip("エッジケースとなるBPM値のトラックが見つかりません")
    for track in edge_tracks:
        try:
            bpm_converted = float(track.BPM) / 100
            assert 0.0 <= bpm_converted <= 300.0, f"エッジケースBPM変換値が不正: {bpm_converted}"
        except Exception:
            pytest.fail(f"BPM値変換失敗: {track.BPM}")
    # ケース3: BPM値が文字列の場合
    track = edge_tracks[0]
    track.BPM = "12345"
    try:
        bpm_converted = float(track.BPM) / 100
        assert f"{bpm_converted:.2f}" == "123.45"
    except Exception:
        pytest.fail(f"BPM値変換失敗: {track.BPM}")
    # ケース4: BPM値が変換できない文字列の場合
    track.BPM = "invalid"
    with pytest.raises(ValueError):
        _ = float(track.BPM) / 100
    class DummyXML:
        def add_track(self, *args, **kwargs):
            return None
    try:
        exporter._add_track_to_xml(DummyXML(), track)
    except Exception as e:
        pytest.fail(f"_add_track_to_xmlで例外発生: {e}")

import tempfile
import xml.etree.ElementTree as ET
from rkbdb2xml.rkbdb2xml import export_rekordbox_db_to_xml

@pytest.mark.skipif(not os.path.exists(TEST_DB_PATH), reason="テストDBが存在しません")
def test_bpm_option_adds_bpm_to_title():
    """
    --bpmオプション指定時にタイトル先頭へBPM整数値が付与されることを確認する
    """
    with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as tmp:
        temp_path = tmp.name
    try:
        export_rekordbox_db_to_xml(TEST_DB_PATH, temp_path, bpm=True)
        tree = ET.parse(temp_path)
        root = tree.getroot()
        collection = root.find('COLLECTION')
        assert collection is not None
        tracks = collection.findall('TRACK')
        found = False
        for tr in tracks:
            name = tr.attrib.get('Name', '')
            bpm = tr.attrib.get('AverageBpm', None)
            # BPMが0以外かつタイトルが"<BPM(整数)><空白>"で始まるものを探す
            if bpm and float(bpm) > 0:
                bpm_int = str(int(float(bpm)))
                if name.startswith(bpm_int + ' '):
                    found = True
                    break
        assert found, '--bpm指定時にBPM整数値がタイトル先頭に付与されていません'
    finally:
        os.remove(temp_path)



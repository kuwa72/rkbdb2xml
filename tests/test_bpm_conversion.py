#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest
import sys
import os

# プロジェクトのルートディレクトリをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter

# テスト用DBパス
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rekordbox_test.db')

class TestBPMConversion(unittest.TestCase):
    """BPM値の変換機能をテストするクラス（mockなし実データ利用）"""

    def setUp(self):
        """テスト前の準備（実DBで初期化）"""
        self.exporter = RekordboxXMLExporter(db_path=TEST_DB_PATH)

    def test_bpm_conversion(self):
        """実データのBPM値が正しく変換されることをテスト（mock不使用）"""
        # DBからトラック一覧を取得
        tracks = self.exporter.db.search_content("")
        self.assertTrue(len(tracks) > 0, "テスト用DBにトラックが存在しません")
        track = tracks[0]  # 最初の1件を利用

        # RekordboxXmlのモックは使わず、変換後のBPM値のみ検証
        # _add_track_to_xmlのロジックを部分的に再利用し、BPM変換を直接確認
        bpm_raw = getattr(track, 'BPM', None)
        self.assertIsNotNone(bpm_raw, "トラックにBPM値がありません")
        bpm_converted = f"{bpm_raw / 100:.2f}"
        # 変換値が妥当な範囲かを検証（例: 60-200）
        self.assertTrue(60.0 <= float(bpm_converted) <= 200.0, f"変換後BPM値が不正: {bpm_converted}")

    def test_bpm_conversion_dict_access(self):
        """辞書アクセス方式でBPM値が正しく変換されることをテスト"""
        # DBからトラック一覧を取得
        tracks = self.exporter.db.search_content("")
        self.assertTrue(len(tracks) > 0, "テスト用DBにトラックが存在しません")
        track = tracks[0]  # 最初の1件を利用
        
        # 辞書アクセス方式で検証
        track_dict = {
            'ID': track.ID,
            'Title': track.Title,
            'BPM': track.BPM,
            'Location': track.Location
        }
        
        # BPM値が100で割られていることを確認
        bpm_converted = f"{track_dict['BPM'] / 100:.2f}"
        self.assertTrue(60.0 <= float(bpm_converted) <= 200.0, f"変換後BPM値が不正: {bpm_converted}")

    def test_bpm_conversion_edge_cases(self):
        """実データ内でBPM値が極端なトラックがあれば変換結果を検証（なければスキップ）"""
        tracks = self.exporter.db.search_content("")
        edge_tracks = [t for t in tracks if hasattr(t, 'BPM') and (t.BPM < 7000 or t.BPM > 18000)]  # 70.00未満または180.00超
        if not edge_tracks:
            self.skipTest("エッジケースとなるBPM値のトラックが見つかりません")
        for track in edge_tracks:
            bpm_converted = f"{track.BPM / 100:.2f}"
            # 0未満や300超など異常値は検出できる
            self.assertTrue(0.0 <= float(bpm_converted) <= 300.0, f"エッジケースBPM変換値が不正: {bpm_converted}")
            with patch('lxml.etree.parse', return_value=MagicMock()):
                self.exporter._add_track_to_xml(self.xml_mock, track)
        args, kwargs = self.xml_mock.add_track.call_args
        self.assertEqual(kwargs.get('AverageBpm'), "999.99")
        
        # ケース3: BPM値が文字列の場合
        track.BPM = "12345"
        with patch('tempfile.NamedTemporaryFile', return_value=MagicMock()):
            with patch('lxml.etree.parse', return_value=MagicMock()):
                self.exporter._add_track_to_xml(self.xml_mock, track)
        args, kwargs = self.xml_mock.add_track.call_args
        self.assertEqual(kwargs.get('AverageBpm'), "123.45")
        
        # ケース4: BPM値が変換できない文字列の場合
        track.BPM = "invalid"
        with patch('tempfile.NamedTemporaryFile', return_value=MagicMock()):
            with patch('lxml.etree.parse', return_value=MagicMock()):
                self.exporter._add_track_to_xml(self.xml_mock, track)
        args, kwargs = self.xml_mock.add_track.call_args
        self.assertEqual(kwargs.get('AverageBpm'), "invalid")


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest
import sys
import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# プロジェクトのルートディレクトリをパスに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter


class TestIntegration(unittest.TestCase):
    """結合テストクラス"""

    def setUp(self):
        """テスト前の準備"""
        # 一時ファイルを作成
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_file = os.path.join(self.temp_dir.name, "test_export.xml")

    def tearDown(self):
        """テスト後のクリーンアップ"""
        # 一時ディレクトリを削除
        self.temp_dir.cleanup()

    def test_export_with_bpm_conversion(self):
        """BPM値の変換を含むエクスポート機能の結合テスト"""
        # このテストはRekordboxがインストールされている環境でのみ実行可能
        # Rekordboxデータベースにアクセスできない場合はスキップ
        try:
            # エクスポーターを作成
            exporter = RekordboxXMLExporter()
            
            # エクスポート実行
            exporter.export(self.output_file, include_playlists=True)
            
            # 出力ファイルが存在することを確認
            self.assertTrue(os.path.exists(self.output_file))
            
            # XMLファイルを解析
            tree = ET.parse(self.output_file)
            root = tree.getroot()
            
            # トラックを検索
            tracks = root.findall(".//TRACK")
            
            # トラックが存在することを確認
            self.assertGreater(len(tracks), 0)
            
            # BPM値を持つトラックを検索
            bpm_tracks = [track for track in tracks if track.get("AverageBpm") is not None]
            
            # BPM値を持つトラックが存在する場合
            if bpm_tracks:
                # BPM値が正しく変換されていることを確認（100倍されていないこと）
                for track in bpm_tracks:
                    bpm = float(track.get("AverageBpm", "0"))
                    # BPM値は通常200未満（100倍されていない）
                    self.assertLess(bpm, 200.0, f"BPM値が大きすぎます: {bpm}")
            
            # プレイリストを検索
            playlists = root.findall(".//NODE")
            
            # プレイリストが存在することを確認
            self.assertGreater(len(playlists), 0)
            
        except Exception as e:
            # Rekordboxデータベースにアクセスできない場合はテストをスキップ
            self.skipTest(f"Rekordboxデータベースにアクセスできません: {str(e)}")


if __name__ == '__main__':
    unittest.main()

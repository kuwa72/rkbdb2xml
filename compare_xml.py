#!/usr/bin/env python
"""
XMLファイルの構造を解析して比較するスクリプト
lxmlを使わずに標準ライブラリのxml.etreeを使用
"""

import xml.etree.ElementTree as ET
import sys
import os
from collections import Counter

def analyze_xml_structure(xml_file):
    """XMLファイルの構造を解析して基本情報を返す"""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # 基本情報
        info = {
            "root_tag": root.tag,
            "root_attributes": root.attrib,
            "child_elements": Counter(),
            "total_elements": 0,
            "max_depth": 0,
            "element_types": set(),
        }
        
        # 要素の種類とその数をカウント
        def count_elements(element, depth=0):
            info["total_elements"] += 1
            info["element_types"].add(element.tag)
            info["child_elements"][element.tag] += 1
            info["max_depth"] = max(info["max_depth"], depth)
            
            for child in element:
                count_elements(child, depth + 1)
        
        count_elements(root)
        
        return info
    
    except Exception as e:
        print(f"Error analyzing {xml_file}: {e}")
        return None

def compare_xml_files(file1, file2):
    """2つのXMLファイルの構造を比較"""
    print(f"Comparing {os.path.basename(file1)} and {os.path.basename(file2)}")
    
    info1 = analyze_xml_structure(file1)
    info2 = analyze_xml_structure(file2)
    
    if not info1 or not info2:
        return
    
    print("\n=== 基本構造の比較 ===")
    print(f"ルート要素: {info1['root_tag']} vs {info2['root_tag']} - {'一致' if info1['root_tag'] == info2['root_tag'] else '不一致'}")
    
    # ルート属性の比較
    print("\nルート属性:")
    for key in set(info1['root_attributes'].keys()) | set(info2['root_attributes'].keys()):
        val1 = info1['root_attributes'].get(key, 'なし')
        val2 = info2['root_attributes'].get(key, 'なし')
        print(f"  {key}: {val1} vs {val2} - {'一致' if val1 == val2 else '不一致'}")
    
    # 要素数の比較
    print(f"\n総要素数: {info1['total_elements']} vs {info2['total_elements']}")
    print(f"最大深度: {info1['max_depth']} vs {info2['max_depth']}")
    
    # 要素タイプの比較
    all_types = info1['element_types'] | info2['element_types']
    print("\n要素タイプの比較:")
    for elem_type in sorted(all_types):
        count1 = info1['child_elements'].get(elem_type, 0)
        count2 = info2['child_elements'].get(elem_type, 0)
        print(f"  {elem_type}: {count1} vs {count2}")

def analyze_track_elements(xml_file):
    """TRACKエレメントの属性を分析"""
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        
        # COLLECTION要素を探す
        collection = None
        for child in root:
            if child.tag == "COLLECTION":
                collection = child
                break
        
        if not collection:
            print(f"No COLLECTION element found in {xml_file}")
            return
        
        # すべてのTRACK要素の属性を収集
        track_attributes = set()
        for track in collection:
            if track.tag == "TRACK":
                for attr in track.attrib:
                    track_attributes.add(attr)
        
        # サンプルトラックの属性を表示
        print(f"\n=== {os.path.basename(xml_file)}のTRACK属性 ===")
        print(f"属性の種類: {len(track_attributes)}")
        print("属性リスト:", ", ".join(sorted(track_attributes)))
        
        # 最初のトラックの詳細を表示
        for track in collection:
            if track.tag == "TRACK":
                print("\n最初のトラックの詳細:")
                for attr, value in sorted(track.attrib.items()):
                    print(f"  {attr}: {value}")
                break
        
        return track_attributes
    
    except Exception as e:
        print(f"Error analyzing tracks in {xml_file}: {e}")
        return None

def main():
    if len(sys.argv) != 3:
        print("Usage: python compare_xml.py <xml_file1> <xml_file2>")
        sys.exit(1)
    
    file1 = sys.argv[1]
    file2 = sys.argv[2]
    
    if not os.path.exists(file1) or not os.path.exists(file2):
        print("One or both files do not exist.")
        sys.exit(1)
    
    compare_xml_files(file1, file2)
    
    # トラック要素の分析
    attrs1 = analyze_track_elements(file1)
    attrs2 = analyze_track_elements(file2)
    
    if attrs1 and attrs2:
        # 属性の違いを表示
        print("\n=== TRACK属性の比較 ===")
        only_in_1 = attrs1 - attrs2
        only_in_2 = attrs2 - attrs1
        common = attrs1 & attrs2
        
        print(f"共通の属性: {len(common)} - {', '.join(sorted(common))}")
        if only_in_1:
            print(f"{os.path.basename(file1)}のみの属性: {len(only_in_1)} - {', '.join(sorted(only_in_1))}")
        if only_in_2:
            print(f"{os.path.basename(file2)}のみの属性: {len(only_in_2)} - {', '.join(sorted(only_in_2))}")

if __name__ == "__main__":
    main()

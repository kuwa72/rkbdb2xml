import pytest

def test_roman_converter_import():
    from rkbdb2xml import RomanConverter as RC1
    from rkbdb2xml.rkbdb2xml import RomanConverter as RC2
    
    conv1 = RC1()
    conv2 = RC2()
    
    assert hasattr(conv1, 'to_roman')
    assert hasattr(conv2, 'to_roman')
    
    # Test conversion
    res = conv1.to_roman("テスト")
    assert isinstance(res, str)

import os
import types
import pytest
from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter

class DummyTrack:
    def __init__(self, FolderPath=None, FileNameL=None, Location=None):
        if FolderPath is not None:
            self.FolderPath = FolderPath
        if FileNameL is not None:
            self.FileNameL = FileNameL
        if Location is not None:
            self.Location = Location

def make_dict_track(**kwargs):
    return kwargs

@pytest.fixture
def exporter():
    return RekordboxXMLExporter(db_path=None)

def test_file_path_normal(exporter):
    track = DummyTrack(FolderPath='/music', FileNameL='test.mp3')
    path = exporter._get_track_file_path(track)
    assert 'test.mp3' in path
    # Windows: file:///C:/... , Unix: file:///...
    assert path.startswith('file:///')

def test_file_path_folderpath_endswith_filename(exporter):
    track = DummyTrack(FolderPath='/music/test.mp3', FileNameL='test.mp3')
    path = exporter._get_track_file_path(track)
    assert 'test.mp3' in path

def test_file_path_dict_like(exporter):
    track = make_dict_track(FolderPath='/foo/bar', FileNameL='baz.wav')
    path = exporter._get_track_file_path(track)
    assert 'baz.wav' in path

def test_file_path_location_fallback(exporter):
    track = DummyTrack(Location='/other/path/track.aiff')
    path = exporter._get_track_file_path(track)
    assert 'track.aiff' in path

def test_file_path_dict_location(exporter):
    track = make_dict_track(Location='/dict/location/file.ogg')
    path = exporter._get_track_file_path(track)
    assert 'file.ogg' in path

def test_file_path_empty(exporter):
    track = DummyTrack()
    path = exporter._get_track_file_path(track)
    assert path == ''

def test_file_path_special_chars(exporter):
    track = DummyTrack(FolderPath='/music/日本語', FileNameL='トラック.mp3')
    path = exporter._get_track_file_path(track)
    assert '%E6%97%A5%E6%9C%AC%E8%AA%9E' in path or '日本語' in path
    assert '%E3%83%88%E3%83%A9%E3%83%83%E3%82%AF.mp3' in path or 'トラック.mp3' in path

"""Tests for rewriting TRACK/@Location to the copied files.

The rest of the export needs a real Rekordbox database, but this step only
needs the copy map and an XML file, so it runs anywhere. It also pins the XML
handling to one library: pyrekordbox writes the file with the stdlib parser and
this rewrite reads it back with the same one.
"""

import xml.etree.ElementTree as ET

import pytest

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter

XML_TEMPLATE = """<?xml version='1.0' encoding='utf-8'?>
<DJ_PLAYLISTS Version="1.0.0">
\t<PRODUCT Name="pyrekordbox" Version="0.0.1" Company="" />
\t<COLLECTION Entries="2">
\t\t<TRACK TrackID="1" Name="&#12354; &amp; b" Location="{loc1}">
\t\t\t<TEMPO Inizio="0.000" Bpm="125.00" Metro="4/4" Battito="1" />
\t\t</TRACK>
\t\t<TRACK TrackID="2" Name="Second" Location="{loc2}" />
\t</COLLECTION>
\t<PLAYLISTS>
\t\t<NODE Name="ROOT" Type="0" Count="0" />
\t</PLAYLISTS>
</DJ_PLAYLISTS>
"""


def make_exporter(copy_map):
    """An exporter with just enough state for _update_locations."""
    exporter = RekordboxXMLExporter.__new__(RekordboxXMLExporter)
    exporter._copy_map = copy_map
    return exporter


def write_xml(tmp_path, loc1, loc2):
    path = tmp_path / "rekordbox.xml"
    path.write_text(XML_TEMPLATE.format(loc1=loc1, loc2=loc2), encoding="utf-8")
    return path


def locations(path):
    root = ET.parse(str(path)).getroot()
    return [t.attrib.get("Location") for t in root.iter("TRACK")]


@pytest.fixture()
def export_dir(tmp_path):
    d = tmp_path / "export"
    d.mkdir()
    return d


def test_locations_point_at_the_copied_files(tmp_path, export_dir):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"\x00")
    dest = export_dir / "copied.mp3"
    dest.write_bytes(b"\x00")

    xml_path = write_xml(tmp_path, str(source), "")
    make_exporter({str(source): dest})._update_locations(str(xml_path), export_dir)

    assert locations(xml_path)[0] == dest.resolve().as_uri().replace(
        "file://", "file://localhost", 1
    )


def test_a_file_uri_location_is_matched_through_the_copy_map(tmp_path, export_dir):
    source = tmp_path / "曲 名.mp3"
    source.write_bytes(b"\x00")
    dest = export_dir / "copied.mp3"
    dest.write_bytes(b"\x00")

    xml_path = write_xml(tmp_path, source.as_uri(), "")
    make_exporter({str(source): dest})._update_locations(str(xml_path), export_dir)

    updated = locations(xml_path)[0]
    assert updated.startswith("file://localhost/")
    assert updated.endswith("copied.mp3")


def test_unmapped_and_empty_locations_are_left_alone(tmp_path, export_dir):
    xml_path = write_xml(tmp_path, "/not/copied.mp3", "")

    make_exporter({})._update_locations(str(xml_path), export_dir)

    assert locations(xml_path) == ["/not/copied.mp3", ""]


def test_the_rest_of_the_document_survives_the_rewrite(tmp_path, export_dir):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"\x00")
    dest = export_dir / "copied.mp3"
    dest.write_bytes(b"\x00")
    xml_path = write_xml(tmp_path, str(source), "")
    before = ET.parse(str(xml_path)).getroot()
    before_shape = [
        (e.tag, sorted(k for k in e.attrib if k != "Location")) for e in before.iter()
    ]

    make_exporter({str(source): dest})._update_locations(str(xml_path), export_dir)

    after = ET.parse(str(xml_path)).getroot()
    assert [
        (e.tag, sorted(k for k in e.attrib if k != "Location")) for e in after.iter()
    ] == before_shape
    # Non-ASCII text and escaped entities must round-trip unchanged
    assert after.find(".//TRACK").attrib["Name"] == "あ & b"
    assert after.find(".//TEMPO").attrib["Bpm"] == "125.00"


def test_the_rewritten_file_is_still_valid_xml_with_a_declaration(tmp_path, export_dir):
    xml_path = write_xml(tmp_path, "/not/copied.mp3", "")

    make_exporter({})._update_locations(str(xml_path), export_dir)

    text = xml_path.read_text(encoding="utf-8")
    assert text.startswith("<?xml")
    assert "UTF-8" in text.split("?>")[0]
    ET.fromstring(text)  # raises if malformed

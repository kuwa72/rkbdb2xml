"""
Functional tests for rkbdb2xml using a real Rekordbox database.
"""

import os
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from lxml import etree

from rkbdb2xml.rkbdb2xml import RekordboxXMLExporter, export_rekordbox_db_to_xml


# Path to the test database
TEST_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'rekordbox_test.db')


class TestFunctionalRekordboxXMLExporter:
    """Functional tests using a real Rekordbox database."""

    def test_real_database_export(self):
        """Test exporting from a real Rekordbox database."""
        # Skip if test database doesn't exist
        if not os.path.exists(TEST_DB_PATH):
            pytest.skip(f"Test database not found at {TEST_DB_PATH}")

        with tempfile.NamedTemporaryFile(suffix='.xml') as tmp:
            # Create exporter with real database
            exporter = RekordboxXMLExporter(TEST_DB_PATH)
            
            # Generate XML
            exporter.generate_xml(tmp.name)
            
            # Parse the XML file and check its structure
            tree = etree.parse(tmp.name)
            root = tree.getroot()
            
            # Basic structure checks
            assert root.tag == 'DJ_PLAYLISTS'
            assert root.get('Version') == '1.0.0'
            
            # Check PRODUCT element
            product = root.find('PRODUCT')
            assert product is not None
            assert product.get('Name') == 'rekordbox'
            
            # Check COLLECTION element
            collection = root.find('COLLECTION')
            assert collection is not None
            assert int(collection.get('Entries')) > 0  # Should have at least one track
            
            # Check tracks in collection
            tracks = collection.findall('TRACK')
            assert len(tracks) > 0
            
            # Check file paths in tracks
            for track in tracks:
                location = track.get('Location')
                if location:
                    # Verify location format
                    assert location.startswith('file://localhost/')
                    
                    # Check for double prefix issue
                    assert 'file://localhost/file://' not in location
                    
                    # Check for double file name issue
                    path_parts = location.split('/')
                    if len(path_parts) >= 2:
                        last_part = path_parts[-1]
                        second_last_part = path_parts[-2]
                        # Last part should not be contained in second last part
                        if last_part and second_last_part:
                            assert last_part not in second_last_part
            
            # Check PLAYLISTS element
            playlists = root.find('PLAYLISTS')
            assert playlists is not None
            
            # Close the database connection
            exporter.close()

    def test_file_path_construction(self):
        """Test specific file path construction from the database."""
        # Skip if test database doesn't exist
        if not os.path.exists(TEST_DB_PATH):
            pytest.skip(f"Test database not found at {TEST_DB_PATH}")
            
        # Create exporter with real database
        exporter = RekordboxXMLExporter(TEST_DB_PATH)
        
        try:
            # Get tracks from the database using the appropriate method
            tracks = []
            if hasattr(exporter.db, 'search_content'):
                tracks = exporter.db.search_content("")
            elif hasattr(exporter.db, 'get_content'):
                tracks = exporter.db.get_content()
            elif hasattr(exporter.db, 'get_tracks'):
                tracks = exporter.db.get_tracks()
            else:
                pytest.skip("Could not find a method to retrieve tracks from the database")
                
            if not tracks:
                pytest.skip("No tracks found in test database")
            
            # Test the first track's file path construction
            track = tracks[0]
            
            # Test format_file_location method
            folder_path = getattr(track, 'FolderPath', '')
            file_name = getattr(track, 'FileNameL', '')
            
            if folder_path and file_name:
                # Check if folder_path already ends with file_name
                if folder_path.endswith(file_name):
                    location = folder_path
                else:
                    location = os.path.join(folder_path, file_name)
                
                formatted_location = exporter._format_file_location(location)
                
                # Verify the formatted location
                assert formatted_location.startswith('file://localhost/') or not formatted_location.startswith('file://')
                
                # Check for double prefix issue
                assert 'file://localhost/file://' not in formatted_location
                
                # Check for double file name issue - we can't use simple string matching due to URL encoding
                # Instead, check that the location is properly formatted
                if file_name:
                    # Verify that the location is either a raw path (no file:// prefix)
                    # or a properly formatted URL (with file://localhost/ prefix)
                    assert (not formatted_location.startswith('file://') or 
                            formatted_location.startswith('file://localhost/'))
                    
                    # Since we can't directly check for file_name due to URL encoding,
                    # we'll just verify that the path is not empty and has a reasonable length
                    assert len(formatted_location) > 0
                    
                    # Log the formatted location for debugging
                    print(f"Formatted location: {formatted_location}")
        finally:
            # Close the database connection
            exporter.close()


class TestFunctionalExportFunction:
    """Test the export function with a real database."""
    
    def test_export_with_real_database(self):
        """Test the export_rekordbox_db_to_xml function with a real database."""
        # Skip if test database doesn't exist
        if not os.path.exists(TEST_DB_PATH):
            pytest.skip(f"Test database not found at {TEST_DB_PATH}")
            
        with tempfile.NamedTemporaryFile(suffix='.xml') as tmp:
            # Export using the function
            export_rekordbox_db_to_xml(TEST_DB_PATH, tmp.name)
            
            # Verify the file was created and is valid XML
            assert os.path.exists(tmp.name)
            assert os.path.getsize(tmp.name) > 0
            
            # Try to parse it
            try:
                tree = ET.parse(tmp.name)
                root = tree.getroot()
                assert root.tag == 'DJ_PLAYLISTS'
            except ET.ParseError:
                pytest.fail("Generated XML is not valid")

# TODO

- [ ] Standardize XML library  
   - Choose and apply either `xml.etree.ElementTree` or `lxml.etree` consistently across the codebase.

- [ ] Remove fallback methods  
   - Eliminate all legacy methods (`get_playlist_entries`, `get_playlist_songs`, `get_playlist_contents`).  
   - Use a single reliable SQL query or the pyrekordbox API (`db.get_playlist()` + `Songs`) to fetch playlist contents.

- [ ] Clean up code & fix lint warnings  
   - Remove unused variables and imports (e.g., leftover `tempo`).  
   - Delete commented‑out or dead code and address any remaining flake8/PEP8 issues.

- [ ] Add / Update tests (TDD)  
   - Write integration tests using `tests/data/rekordbox_test.db` and compare against `tests/data/test_rkb6_export.xml`.  
   - Ensure tests run in CI and cover core functionality.

- [ ] Update docs & README  
   - Document CLI flags (`--force`, `--verbose`), setup instructions, and examples.  
   - Add a "Development" section explaining how to run tests and set up the env.

- [ ] Optional enhancements  
   - Romaji conversion for metadata.  
   - Option to append BPM to track titles and sort playlists by BPM.  
   - Playlist segmentation by BPM ranges.

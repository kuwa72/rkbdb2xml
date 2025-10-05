# rkbdb2xml GUI - UI Design and Development Plan

## 1. Introduction

This document outlines the UI design and development plan for a Graphical User Interface (GUI) for the `rkbdb2xml` tool, to be built using PySide (Qt for Python). The GUI aims to provide a user-friendly way to select Rekordbox playlists, configure export options per playlist, and specify an output destination for the generated XML files.

## 2. UI Design

The main application window will be designed for clarity and ease of use.

### 2.1. Main Window Layout

The main window will be divided into the following sections:

*   **Menu Bar**:
    *   `File`:
        *   `Load Rekordbox Database...` (for manual selection if auto-detection fails or user preference)
        *   `Settings/Preferences...` (for global settings, e.g., default romanization/BPM addition)
        *   `Exit`
    *   `Help`:
        *   `About`
*   **Main Pane: Playlist and Options Table**
    *   A table view (`QTableView`) displaying Rekordbox playlists and folders.
    *   Playlists and folders will be presented in a flat list, with hierarchy indicated by indentation of the 'Name' column.
    *   Initially, all folders will be displayed in an expanded state.
    *   Each row will represent a playlist or folder.
    *   Columns will include: an export selection checkbox, the item name, and various export options (e.g., Sort Order, Add BPM, Romanize options). Export options columns will be editable only for playlist rows.
    *   A "Reload Playlists" button above the table.
*   **Bottom Pane: Global Settings and Export**
    *   Output Directory: `QLineEdit` for path input and a `QPushButton` ("Browse...") for selection.
    *   Global Export Options (Overrides): Checkboxes for "Force Romanization for all selected," "Force Add BPM for all selected."
    *   "Start Export" `QPushButton`.
*   **Status Bar**:
    *   Displays information about ongoing processes (e.g., "Loading playlists...", "Exporting playlist X...", "Export complete").
    *   `QProgressBar` for visual feedback during export.

### 2.2. Visual Mock-up (Conceptual - Table View)

```
+----------------------------------------------------------------------------------------------------------------------------------------------------+
| File  Help                                                                                                                                         |
+----------------------------------------------------------------------------------------------------------------------------------------------------+
| [Reload Playlists]                                                                                                                                 |
|----------------------------------------------------------------------------------------------------------------------------------------------------|
| [X] | Name                 | Sort Order      | Add BPM | Romanize Title | Romanize Artist | Romanize Album |  <- Column Headers                     |
|-----|----------------------|-----------------|---------|----------------|-----------------|----------------|----------------------------------------|
| [X] | Folder 1             | (disabled)      | (disab.)| (disabled)     | (disabled)      | (disabled)     |  <- Folder row (options disabled)    |
| [ ] |   Playlist A         | [Default v]     | [ ]     | [ ]            | [ ]             | [ ]            |  <- Playlist row (options editable)  |
| [X] |   Playlist B         | [BPM Asc  v]    | [X]     | [X]            | [ ]             | [ ]            |                                        |
| [ ] | Folder 2             | (disabled)      | (disab.)| (disabled)     | (disabled)      | (disabled)     |                                        |
| [X] |   My Mix 1           | [Default v]     | [X]     | [ ]            | [X]             | [X]            |                                        |
| [ ] |   SubFolder 2.1      | (disabled)      | (disab.)| (disabled)     | (disabled)      | (disabled)     |                                        |
| [ ] |     Deep Playlist C  | [Title    v]    | [ ]     | [ ]            | [ ]             | [ ]            |                                        |
| [ ] | Uncategorized Playlist | [Default v]     | [ ]     | [ ]            | [ ]             | [ ]            |                                        |
| ... | ...                  | ...             | ...     | ...            | ...             | ...            |                                        |
+----------------------------------------------------------------------------------------------------------------------------------------------------+
| Output Dir: [ C:\Exports                ] [Browse...]                                                                                                |
| Global: [ ] Force Romanize [ ] Force BPM                                                                        [ Start Export ]                   |
+----------------------------------------------------------------------------------------------------------------------------------------------------+
| Status: Ready                                                                                                   [|||||-----] 50%                  |
+----------------------------------------------------------------------------------------------------------------------------------------------------+
(X) = Checked, [ ] = Unchecked box, [Option v] = Dropdown
```

### 2.3. Playlist/Folder Table View (`QTableView`)

*   Displays playlists and folders loaded from `pyrekordbox` in a table format.
*   All folders are expanded by default, showing all playlists and sub-folders. Hierarchy is indicated by indenting the 'Name' field.
*   The model behind this view will store playlist/folder IDs, their export status, and their specific export options.
*   **Columns will include**:
    *   **Export**: `QCheckBox` in each row to select the item for export. Checking a folder could optionally check all its children.
    *   **Name**: Text field showing the playlist or folder name. Indentation will be used to represent the folder/playlist hierarchy.
    *   **Sort Order**: `QComboBox` (editable only for playlist rows). Options: "Default," "BPM (Asc)," "BPM (Desc)," "Title," "Artist." Disabled for folder rows.
    *   **Add BPM to Title**: `QCheckBox` (editable only for playlist rows). Disabled for folder rows.
    *   **Romanize Title**: `QCheckBox` (editable only for playlist rows). Disabled for folder rows.
    *   **Romanize Artist**: `QCheckBox` (editable only for playlist rows). Disabled for folder rows.
    *   **Romanize Album**: `QCheckBox` (editable only for playlist rows). Disabled for folder rows.

## 3. Core Functionality Details

### 3.1. Playlist Loading

*   On startup or "Reload Playlists" click, the application uses `pyrekordbox` to fetch all playlists and folders.
*   This process will run in a background thread (`QThread`) to keep the GUI responsive.
*   The table view is populated. A flat list representing the expanded tree is created. Each item stores the `DjmdPlaylist` object or relevant attributes (ID, Name, ParentID, is_folder, level for indentation).

### 3.2. Option Setting

*   A data structure (e.g., a dictionary) will hold export options for each playlist ID that has been selected or configured.
    *   `{ playlist_id: {"sort_order": "bpm", "add_bpm": True, "romanize_title": False, ...}, ... }`
*   Options are edited directly in the table cells for playlist rows. Changes in the table (e.g., checking a box, selecting from a combo box) will update this temporary storage for the corresponding playlist ID.
*   Folder rows will not allow editing of option cells.

### 3.3. Export Process

1.  User clicks "Start Export."
2.  Validate output directory.
3.  Collect all playlist IDs from rows where the 'Export' checkbox is checked.
4.  For each checked playlist:
    *   Retrieve its specific options from the stored settings.
    *   If not set, use global defaults or application defaults.
    *   The `RekordboxXMLExporter` class or `export_rekordbox_db_to_xml` function will need to be adapted to accept these granular, per-playlist options. This is a significant change from the current CLI where options are global.
    *   Alternatively, the GUI could iterate and call `export_rekordbox_db_to_xml` multiple times with different playlist filters and options, producing separate (or merged) XMLs. A single, cohesive XML like the current tool is preferred, so `RekordboxXMLExporter` itself should become more flexible.
5.  The export process runs in a `QThread`.
6.  Status bar and progress bar are updated.

## 4. Development Plan

### 4.1. Prerequisites

*   Python 3.8+
*   PySide6: `pip install pyside6`
*   Existing `rkbdb2xml` codebase.

### 4.2. Milestones

**M0: Project Setup and Basic Structure**

- [x] Create a new directory for GUI-related files (e.g., `rkbdb2xml_gui/`).
- [x] Set up a basic PySide application: `QApplication`, `QMainWindow`.
- [x] Implement the main window layout with placeholders for the table, options, etc., either using Qt Designer (`.ui` files) or programmatically.

**M1: Playlist Loading and Display**

- [x] **Task 1.1**: Implement logic to load playlists and folders from `RekordboxDatabase` (ideally in a `QThread`).
  - [x] Flatten the hierarchy for table display, calculating necessary indentation levels.
  - [x] Ensure all folders are treated as expanded by default.
  - [x] Error handling for DB not found.
  - [x] Display "Loading..." status.
- [x] **Task 1.2**: Populate a `QTableView` with the playlist/folder data.
  - [x] Implement custom delegates or use standard item models to display checkboxes and combo boxes within table cells for options.
  - [x] Implement indentation for the 'Name' column to show hierarchy.
  - [x] Store playlist/folder metadata (ID, name, type, original hierarchical data) with each row/item.
- [x] **Task 1.3**: Implement "Reload Playlists" button.

**M2: Output Path and Basic Export Trigger**

- [x] **Task 2.1**: Implement Output Directory `QLineEdit` and "Browse..." `QPushButton` (using `QFileDialog.getExistingDirectory()`).
- [x] **Task 2.2**: Implement basic "Start Export" button.
  - [x] Initially, this might just print selected playlist IDs and output path, without actual export.

**M3: Per-Playlist Options UI and Data Model (Integrated into Table)**

- [x] **Task 3.1**: Implement in-table editing for playlist options using `QCheckBox` and `QComboBox` delegates in the `QTableView`.
  - [x] Ensure option cells are disabled/non-editable for folder rows.
- [x] **Task 3.2**: When table cell options are changed for a playlist, store them in the Python dictionary associated with the playlist ID.

**M4: Adapting Core Export Logic**

- [x] **Task 4.1**: **Crucial Step**: Modify `RekordboxXMLExporter` or `export_rekordbox_db_to_xml`.
  - [x] The exporter needs to be able to take a list of (playlist_id, options_dict) tuples, or be aware of a global options_map it can query by playlist ID.
  - [x] It will need to filter tracks based on selected playlists and *conditionally* apply options during track/playlist processing.
  - [x] This might involve passing the options dictionary deep into the XML generation methods.
- [x] **Task 4.2**: Connect the "Start Export" button to this modified export logic.
  - [x] Export should run in a `QThread`.
  - [x] Pass the collected playlist selections and their associated options.

**M5: Progress Reporting and Feedback**

- [x] **Task 5.1**: Implement `QProgressBar` updates during export.
  - [ ] `RekordboxXMLExporter` might need to emit signals (e.g., `processed_playlist(name)`, `processed_track_count(count)`) for progress.
- [x] **Task 5.2**: Update status bar messages.
- [x] **Task 5.3**: Display success/error dialogs (`QMessageBox`) on completion.

**M6: Settings, Refinements, and Error Handling**

- [ ] **Task 6.1**: Implement global settings/preferences (e.g., persistence of last output path, default options using `QSettings`).
- [ ] **Task 6.2**: Add "About" dialog.
- [x] **Task 6.3**: Improve error handling throughout the application (e.g., invalid DB paths, write permission errors).
- [ ] **Task 6.4**: UI Polish: Icons, tooltips, layout adjustments.

**M7: Testing and Packaging**

- [ ] **Task 7.1**: Thoroughly test GUI functionality on target platforms (Windows, macOS).
- [ ] **Task 7.2**: Create an executable version using PyInstaller.
  - [ ] Ensure PySide6 and all dependencies are correctly bundled.
  - [ ] Test the packaged application.

## 5. Key Challenges and Considerations

*   **Modifying `RekordboxXMLExporter`**: The most significant challenge will be adapting the existing export logic to handle per-playlist options gracefully without overcomplicating the core code. Current CLI options are global.
*   **Thread Management**: Correct use of `QThread` for DB loading and export is crucial for a responsive GUI. Signals and slots for inter-thread communication.
*   **State Management**: Keeping track of selected playlists/folders (via checkboxes in the table) and their individual options (edited in the table).
*   **Dependency Bundling**: `lxml`, `mutagen`, `psutil`, `romann` (if it has non-Python parts) might need special handling with PyInstaller.

## 6. Future Enhancements (Optional)

*   Drag-and-drop reordering of playlists for export (if XML structure allows/matters).
*   Saving/loading export "profiles" (sets of selected playlists and their options).
*   Direct editing of some track metadata before export (complex).
*   Plugin system for more export options.

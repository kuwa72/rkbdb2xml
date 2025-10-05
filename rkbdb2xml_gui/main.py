import sys
from PySide6.QtCore import Qt, QThread, Signal, Slot, QObject, QTimer, QModelIndex
from PySide6.QtGui import QAction, QIcon
import os
import shutil
from typing import Dict, List, Any, Optional
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime
from pyrekordbox.db6 import Rekordbox6Database
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QCheckBox,
    QLabel,
    QLineEdit,
    QTableView,
    QAbstractItemView,
    QHeaderView,
    QProgressBar,
    QStatusBar,
    QMenuBar,
    QFileDialog,
    QMessageBox
)
from PySide6.QtGui import QAction
from pathlib import Path # For path manipulation
import traceback # For detailed error logging
import logging

# Assuming rkbdb2xml_path is correctly set up to import RekordboxXMLExporter
import sys
# sys.path.append(str(Path(__file__).parent.parent / 'rkbdb2xml')) # Old problematic line
# Add the project root directory (parent of rkbdb2xml_gui and rkbdb2xml packages) to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root)) # Prepend to sys.path for robust import

from rkbdb2xml import RekordboxXMLExporter, DEFAULT_XML_FILENAME

logger = logging.getLogger(__name__)


class ExportThread(QThread):
    """バックグラウンドでエクスポート処理を実行するスレッド"""
    progress_updated = Signal(int, str)  # 進捗率, メッセージ
    finished = Signal()

    def __init__(self, options: Dict[str, Any]):
        super().__init__()
        self.options = options

    def run(self):
        try:
            self.progress_updated.emit(0, "Starting export...")
            
            # 出力ディレクトリを作成
            output_dir = Path(self.options['output_dir'])
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # ここに実際のエクスポート処理を実装
            # 例: 各プレイリストをエクスポート
            total = len(self.options['playlists'])
            for i, playlist in enumerate(self.options['playlists'], 1):
                progress = int((i / total) * 100)
                self.progress_updated.emit(
                    progress, 
                    f"Exporting {playlist['name']}... ({i}/{total})"
                )
                
                # ここで実際のエクスポート処理を実行
                # 例: self._export_playlist(playlist, output_dir)
                
                # 進行状況を更新
                self.msleep(100)  # デモ用の遅延
            
            self.progress_updated.emit(100, "Export completed")
            
        except Exception as e:
            self.progress_updated.emit(0, f"Export failed: {str(e)}")
            raise
        finally:
            self.finished.emit()
    
    def _export_playlist(self, playlist: Dict[str, Any], output_dir: Path):
        """個々のプレイリストをエクスポート"""
        # ここにプレイリストのエクスポート処理を実装
        # 例: XMLの生成、ファイルのコピーなど
        pass


class PlaylistModel(QAbstractTableModel):
    EXPORT_COL = 0
    NAME_COL = 1
    SORT_ORDER_COL = 2
    ADD_BPM_COL = 3
    ROMANIZE_TEXT_COL = 4 # Consolidated Romanization column
    # Hidden columns for internal data, adjust if more visible columns are added before these
    IS_FOLDER_COL = 5 # Internal data, was 7
    ID_COL = 6        # Internal data, was 8
    LEVEL_COL = 7     # Internal data, was 9

    # Total number of columns that will be visible or used by the model logic explicitly
    # This should match the number of headers defined in headerData for Qt.Horizontal
    VISIBLE_COLUMN_COUNT = 5 # Export, Name, Sort Order, Add BPM, Romanize Text

    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self._data = data or []
        self._headers = [
            "Export", "Name", "Sort Order", "Add BPM", "Romanize Text"
        ]

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        # Should return the number of columns you want to display/manage.
        # If IS_FOLDER_COL, ID_COL, LEVEL_COL are purely internal and not displayed as separate columns,
        # then VISIBLE_COLUMN_COUNT is correct. Otherwise, it should be len(self._data[0]) if _data is populated.
        return self.VISIBLE_COLUMN_COUNT

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
            
        row = index.row()
        col = index.column()
        
        if row >= len(self._data):
            return None

        if role == Qt.DisplayRole:
            if col == self.NAME_COL or col == self.SORT_ORDER_COL: # Name and Sort Order
                return self._data[row][col]
            # For boolean values that are not checkboxes, you might want to return "Yes"/"No" or leave blank
            # Checkboxes are handled by Qt.CheckStateRole primarily
            return None # Checkboxes will be drawn, no extra text needed

        elif role == Qt.CheckStateRole:
            if col == self.EXPORT_COL or col == self.ADD_BPM_COL or col == self.ROMANIZE_TEXT_COL:
                return Qt.Checked if self._data[row][col] else Qt.Unchecked
            return None
            
        elif role == Qt.UserRole:
            # For internal data columns
            if col == self.IS_FOLDER_COL or col == self.ID_COL or col == self.LEVEL_COL:
                return self._data[row][col]

        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False

        row = index.row()
        col = index.column()

        if role == Qt.CheckStateRole:
            if col == self.EXPORT_COL or col == self.ADD_BPM_COL or col == self.ROMANIZE_TEXT_COL:
                # Store previous value to check if there's a real change
                old_value = self._data[row][col]
                # Qt.Checked値からbool値への変換（0=Qt.Unchecked, 2=Qt.Checked）
                new_value = (value == Qt.Checked)
                
                # 実際に値が変わった場合のみ更新
                if old_value != new_value:
                    self._data[row][col] = new_value
                    # Emit dataChanged for the specific cell with all relevant roles
                    self.dataChanged.emit(index, index, [Qt.CheckStateRole, Qt.DisplayRole])
                    
                    # If changing a folder's export status, propagate to children
                    if col == self.EXPORT_COL and self._data[row][self.IS_FOLDER_COL]:
                        self._propagate_folder_check_state(row, self._data[row][col])
                    
                return True
            return False
        
        if role == Qt.EditRole:
            # Handle edits for editable text columns like Sort Order (future)
            if col == self.SORT_ORDER_COL:
                # Basic validation or transformation could go here
                self._data[row][col] = value
                self.dataChanged.emit(index, index, [Qt.EditRole, Qt.DisplayRole])
                return True

        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            if section < len(self._headers):
                return self._headers[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        row = index.row()
        col = index.column()
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable

        # Safety check for index out of bounds
        if row >= len(self._data):
            return flags

        if col == self.EXPORT_COL or col == self.ADD_BPM_COL or col == self.ROMANIZE_TEXT_COL:
            flags |= Qt.ItemIsUserCheckable
            
            # Disable option checkboxes for folders except the Export checkbox
            if col != self.EXPORT_COL and self._data[row][self.IS_FOLDER_COL]:
                flags &= ~Qt.ItemIsEnabled  # Remove the enabled flag for folder option cells
                
        # elif col == self.SORT_ORDER_COL and not self._data[index.row()][self.IS_FOLDER_COL]: # Make Sort Order editable only for playlists
            # flags |= Qt.ItemIsEditable 
            # TODO: Implement editing for Sort Order for non-folders when that feature is active

        return flags

    def update_data(self, new_data):
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()

    def _propagate_folder_check_state(self, folder_row_index, is_checked):
        # This function propagates the check state of a folder to its children.
        folder_level = self._data[folder_row_index][self.LEVEL_COL]
        folder_id = self._data[folder_row_index][self.ID_COL]
        
        # Iterate through rows below the folder
        for i in range(folder_row_index + 1, self.rowCount()):
            current_level = self._data[i][self.LEVEL_COL]
            # If we encounter a row at the same or higher level, it's no longer a child of the current folder tree
            if current_level <= folder_level:
                break
            
            # Update the child's export state
            old_value = self._data[i][self.EXPORT_COL]
            if old_value != is_checked:  # Only update if there's an actual change
                self._data[i][self.EXPORT_COL] = is_checked
                # Emit dataChanged for the child's export cell with all relevant roles
                child_index = self.index(i, self.EXPORT_COL)
                self.dataChanged.emit(child_index, child_index, [Qt.CheckStateRole, Qt.DisplayRole])
                
                # If this child is also a folder, propagate to its children too
                if self._data[i][self.IS_FOLDER_COL]:
                    self._propagate_folder_check_state(i, is_checked)


class RekordboxLoadThread(QThread):
    data_ready = Signal(list)
    error = Signal(str)

    def __init__(self, db_path=None, parent=None):
        super().__init__(parent)
        self.db_path = db_path

    def _flatten_playlists_recursive(self, playlists_map, playlist_id, level, flat_list):
        playlist = playlists_map.get(playlist_id) # playlist_id should always be an int ID here
        if not playlist:
            # This debug message will now correctly show the ID that was not found
            print(f"DEBUG: Playlist object not found in map for ID: {playlist_id}")
            return

        # Debug print: Show current playlist being processed, its level, and if it's a folder.
        print(f"DEBUG: Processing: Level={level}, Name='{playlist.Name}', Folder={playlist.is_folder}, ID={playlist.ID}, ParentID={playlist.Parent.ID if playlist.Parent else None}")

        indent = "  " * level
        # [Export, Name, Sort Order, Add BPM, Romanize Text, is_folder, id, level]
        item_data = [
            False,  # Export by default
            f"{indent}{playlist.Name}",
            "N/A" if playlist.is_folder else "Default", # Placeholder for Sort Order
            False, # Add BPM
            False, # Romanize Text (consolidated)
            playlist.is_folder,
            playlist.ID, # Store the actual playlist ID
            level
        ]
        flat_list.append(item_data)

        if playlist.is_folder and playlist.Children: # playlist.Children is a list of DjmdPlaylist objects
            # Debug print: Show children of the current folder.
            child_obj_names = []
            for child_obj in playlist.Children: # Iterate over actual DjmdPlaylist objects
                child_obj_names.append(child_obj.Name)
            print(f"DEBUG: Folder '{playlist.Name}' (ID: {playlist.ID}) has children (names): {child_obj_names}")
            
            # Sort children (which are DjmdPlaylist objects) by their Name attribute
            sorted_children_objects = sorted(
                playlist.Children, # This is a list of DjmdPlaylist objects
                key=lambda child_obj: child_obj.Name # Sort by name of the child object
            )
            
            for child_object in sorted_children_objects: # Iterate over child DjmdPlaylist objects
                # Pass the ID of the child_object for the recursive call
                self._flatten_playlists_recursive(playlists_map, child_object.ID, level + 1, flat_list)

    def run(self):
        try:
            # If self.db_path is None, Rekordbox6Database will try to find the default path.
            # If self.db_path is provided (e.g., by user selection), it will use that path.
            db = Rekordbox6Database(path=self.db_path)
            
            all_db_playlists = db.get_playlist() # Gets all DjmdPlaylist objects
            if not all_db_playlists:
                self.data_ready.emit([])
                return

            playlists_map = {p.ID: p for p in all_db_playlists}
            root_playlists = sorted(
                [p for p in all_db_playlists if p.Parent is None],
                key=lambda p: p.Name # Sort root items by name
            )

            flat_playlist_data = []
            for root_playlist in root_playlists:
                self._flatten_playlists_recursive(playlists_map, root_playlist.ID, 0, flat_playlist_data)
            
            self.data_ready.emit(flat_playlist_data)

        # except RekordboxDatabaseMissingError as e: # Commented out again
        #     self.error.emit(f"Failed to load Rekordbox database: {str(e)}. "
        #                     f"Please ensure Rekordbox is installed or specify the database path manually via File menu.")
        except Exception as e: # Generic catch will handle all errors for now
            error_str = str(e).lower()
            # Crude check for DB missing type errors, as specific exception import fails
            is_db_missing_error = "database not found" in error_str or \
                                  "unable to open database file" in error_str or \
                                  "no such table" in error_str # Could indicate empty/corrupt db
            
            if is_db_missing_error:
                self.error.emit(f"Failed to load Rekordbox database: {str(e)}. "
                                f"It might be missing or corrupted. "
                                f"Please ensure Rekordbox is installed and working, or specify the database path manually.")
            else:
                self.error.emit(f"An unexpected error occurred while loading playlists: {str(e)}\n{traceback.format_exc()}")


class ExportThread(QThread):
    """Runs the Rekordbox XML export process in a separate thread."""
    finished = Signal(str)  # Emits output file path on success
    error = Signal(str)     # Emits error message on failure

    def __init__(self, db_path: str, output_xml_path: str, playlist_configs: list):
        super().__init__()
        self.db_path = db_path
        self.output_xml_path = output_xml_path
        self.playlist_configs = playlist_configs

    def run(self):
        try:
            logger.info(f"ExportThread started for DB: {self.db_path}, Output: {self.output_xml_path}")
            logger.info(f"Playlist configs for export: {self.playlist_configs}")
            
            exporter = RekordboxXMLExporter(db_path=self.db_path)
            exporter.generate_xml(path=self.output_xml_path, playlist_configs=self.playlist_configs)
            
            self.finished.emit(self.output_xml_path)
            logger.info(f"ExportThread finished successfully.")
        except Exception as e:
            logger.error(f"Error during XML export: {e}", exc_info=True)
            self.error.emit(f"Error during XML export: {e}\n{traceback.format_exc()}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        print("Initializing MainWindow...")  # デバッグ用

        self.setWindowTitle("rkbdb2xml GUI")
        self.setGeometry(100, 100, 1000, 700)  # x, y, width, height

        print("Creating menu bar...")  # デバッグ用
        self._create_menu_bar()
        
        print("Creating main layout...")  # デバッグ用
        self._create_main_layout()
        
        print("Creating status bar...")  # デバッグ用
        self._create_status_bar()

        self.load_thread = None
        self.export_thread = None  # Initialize export thread variable
        
        print("Loading playlists asynchronously...")  # デバッグ用
        self.load_playlists_async()  # Load on startup
        
        print("MainWindow initialization complete.")  # デバッグ用

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        load_db_action = QAction("Load Rekordbox Database...", self)
        load_db_action.triggered.connect(self.select_and_load_rekordbox_database) # Changed
        file_menu.addAction(load_db_action)
        settings_action = QAction("Settings/Preferences...", self)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("About", self)
        help_menu.addAction(about_action)

    def _create_main_layout(self):
        print("Creating main layout...")  # デバッグ用
        # セントラルウィジェットを作成
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        print("Central widget set")  # デバッグ用
        
        # メインレイアウト
        main_layout = QVBoxLayout(central_widget)
        print("Main layout created")  # デバッグ用
        
        # リロードボタン
        self.reload_button = QPushButton("Reload Playlists")
        self.reload_button.clicked.connect(self.load_playlists_async)
        main_layout.addWidget(self.reload_button)
        
        # テーブルビューの作成
        self.playlist_table_view = QTableView()
        self.playlist_model = PlaylistModel()
        self.playlist_table_view.setModel(self.playlist_model)
        
        # テーブル設定
        self.playlist_table_view.setAlternatingRowColors(True)
        self.playlist_table_view.setSelectionBehavior(QTableView.SelectRows)
        self.playlist_table_view.setSelectionMode(QTableView.SingleSelection)
        self.playlist_table_view.setShowGrid(True)
        
        # チェックボックスのクリックを確実に処理するための設定
        self.playlist_table_view.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.playlist_table_view.clicked.connect(self._handle_table_click)
        
        # ヘッダー設定
        header = self.playlist_table_view.horizontalHeader()
        header.setSectionResizeMode(PlaylistModel.NAME_COL, QHeaderView.Stretch)
        
        # チェックボックス列の幅を固定
        for col in [PlaylistModel.EXPORT_COL, PlaylistModel.ADD_BPM_COL, PlaylistModel.ROMANIZE_TEXT_COL]:
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.playlist_table_view.setColumnWidth(col, 60)
        
        # 内部使用列を非表示
        self.playlist_table_view.setColumnHidden(PlaylistModel.ID_COL, True)
        self.playlist_table_view.setColumnHidden(PlaylistModel.IS_FOLDER_COL, True)
        self.playlist_table_view.setColumnHidden(PlaylistModel.LEVEL_COL, True)
        
        # テーブルをメインレイアウトに追加
        main_layout.addWidget(self.playlist_table_view)
        
        # 出力ディレクトリ設定
        output_dir_layout = QHBoxLayout()
        output_dir_label = QLabel("Output Directory:")
        self.output_dir_line_edit = QLineEdit()
        self.output_dir_browse_button = QPushButton("Browse...")
        self.output_dir_browse_button.clicked.connect(self.browse_output_directory)
        
        output_dir_layout.addWidget(output_dir_label)
        output_dir_layout.addWidget(self.output_dir_line_edit)
        output_dir_layout.addWidget(self.output_dir_browse_button)
        
        # オプションボタン
        options_layout = QHBoxLayout()
        self.force_romanize_checkbox = QCheckBox("Force Romanize")
        self.force_bpm_checkbox = QCheckBox("Add BPM to Title")
        self.sort_by_bpm_checkbox = QCheckBox("Sort by BPM")
        self.start_export_button = QPushButton("Start Export")
        self.start_export_button.clicked.connect(self._export_xml)
        
        options_layout.addWidget(self.force_romanize_checkbox)
        options_layout.addWidget(self.force_bpm_checkbox)
        options_layout.addWidget(self.sort_by_bpm_checkbox)
        options_layout.addStretch()
        options_layout.addWidget(self.start_export_button)
        
        # レイアウトをメインに追加
        main_layout.addLayout(output_dir_layout)
        main_layout.addLayout(options_layout)
        
        # ウィンドウの最小サイズを設定
        self.setMinimumSize(800, 600)

    def _create_status_bar(self):
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.status_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False) # Initially hidden

        status_bar.addWidget(self.status_label, 1) # Add with stretch factor
        status_bar.addPermanentWidget(self.progress_bar)

    def select_and_load_rekordbox_database(self):
        db_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Rekordbox Database (master.db)",
            "", # Start directory
            "Rekordbox Database (master.db);;All Files (*)"
        )
        if db_path:
            self.load_playlists_async(db_path=db_path)

    def load_playlists_async(self, db_path=None):
        if self.load_thread and self.load_thread.isRunning():
            # Optionally, inform user or cancel previous thread
            return

        self.status_label.setText("Loading playlists...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0,0) # Indeterminate progress
        self.reload_button.setEnabled(False)

        self.load_thread = RekordboxLoadThread(db_path=db_path)
        self.load_thread.data_ready.connect(self._on_playlist_data_ready)
        self.load_thread.error.connect(self._on_playlist_load_error)
        self.load_thread.finished.connect(self._on_playlist_load_finished)
        self.load_thread.start()

    def _on_playlist_data_ready(self, data):
        self.playlist_model.update_data(data)
        self.status_label.setText(f"Loaded {len(data)} items.")
        # Stretch last column if needed, or set column widths
        self.playlist_table_view.resizeColumnsToContents()

    def _on_playlist_load_error(self, error_message):
        self.status_label.setText(f"Error: {error_message}")
        self.playlist_model.update_data([]) # Clear table on error

    def _on_playlist_load_finished(self):
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0,100) # Reset for determinate progress later
        self.reload_button.setEnabled(True)
        self.load_thread = None # Allow garbage collection

    def _export_xml(self):
        if not self.db_path:
            QMessageBox.warning(self, "Database Not Loaded", "Please load a Rekordbox database first (File > Open Rekordbox DB).")
            return

        output_dir_str = self.output_dir_line_edit.text()
        if not output_dir_str:
            QMessageBox.warning(self, "Output Directory Not Set", "Please select an output directory before exporting.")
            return
        
        output_dir = Path(output_dir_str)
        if not output_dir.is_dir():
            QMessageBox.critical(self, "Invalid Output Directory", f"The selected output directory does not exist or is not a directory: {output_dir_str}")
            return

        output_xml_path = output_dir / DEFAULT_XML_FILENAME

        playlist_configs = self._get_export_settings_from_model()
        if not playlist_configs:
            QMessageBox.information(self, "No Playlists Selected", "No playlists are marked for export, or no playlists loaded.")
            return
        
        # Show a confirmation dialog with the number of playlists to be exported
        folder_playlists = [p for p in playlist_configs if "from_folder" in p]
        direct_playlists = [p for p in playlist_configs if "from_folder" not in p]
        
        message = f"Ready to export {len(playlist_configs)} playlists:\n"
        message += f"- {len(direct_playlists)} directly selected playlists\n"
        if folder_playlists:
            message += f"- {len(folder_playlists)} playlists from selected folders\n"
        message += f"\nOutput file: {output_xml_path}"
        
        confirm = QMessageBox.question(self, "Confirm Export", message, 
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        
        if confirm != QMessageBox.Yes:
            return

        logger.info(f"Starting XML export to: {output_xml_path}")
        logger.info(f"Export settings: {playlist_configs}")

        self.start_export_button.setEnabled(False)
        self.status_label.setText(f"Exporting to {output_xml_path}...")

        # Create and start the export thread
        self.export_thread = ExportThread(self.db_path, str(output_xml_path), playlist_configs)
        self.export_thread.finished.connect(self._on_export_finished)
        self.export_thread.error.connect(self._on_export_error)
        self.export_thread.start()

    def _get_export_settings_from_model(self) -> list:
        settings = []
        model = self.playlist_model
        if model.rowCount() == 0:
            return settings

        # First pass: collect all directly selected playlists and folders
        selected_folders = []
        selected_playlists = []

        for row in range(model.rowCount()):
            export_item = model.data(model.index(row, PlaylistModel.EXPORT_COL), Qt.CheckStateRole)
            if export_item == Qt.CheckState.Checked:
                name = model.data(model.index(row, PlaylistModel.NAME_COL), Qt.DisplayRole)
                is_folder = model.data(model.index(row, PlaylistModel.IS_FOLDER_COL), Qt.UserRole)
                playlist_id = model.data(model.index(row, PlaylistModel.ID_COL), Qt.UserRole)
                level = model.data(model.index(row, PlaylistModel.LEVEL_COL), Qt.UserRole)
                
                if is_folder:
                    selected_folders.append((row, name.strip(), level))
                else:
                    add_bpm = model.data(model.index(row, PlaylistModel.ADD_BPM_COL), Qt.CheckStateRole) == Qt.CheckState.Checked
                    romanize_text = model.data(model.index(row, PlaylistModel.ROMANIZE_TEXT_COL), Qt.CheckStateRole) == Qt.CheckState.Checked
                    
                    selected_playlists.append({
                        "id": playlist_id,
                        "name": name.strip(),
                        "add_bpm": add_bpm,
                        "romanize_text": romanize_text,
                        "row": row,
                        "level": level
                    })
        
        # Add all playlists to the settings list
        settings.extend([p for p in selected_playlists if "row" in p])
        
        # Second pass: ensure all playlists under selected folders are included
        for folder_row, folder_name, folder_level in selected_folders:
            # Find all playlists that are children of this folder
            for row in range(folder_row + 1, model.rowCount()):
                current_level = model.data(model.index(row, PlaylistModel.LEVEL_COL), Qt.UserRole)

        if not selected_playlists:
            QMessageBox.warning(self, "エラー", "エクスポートするプレイリストが選択されていません")
            return

        # グローバルオプションを取得
        options = {
            'output_dir': output_dir,
            'force_romanize': self.force_romanize_checkbox.isChecked(),
            'add_bpm': self.force_bpm_checkbox.isChecked(),
            'sort_by_bpm': self.sort_by_bpm_checkbox.isChecked(),
            'playlists': selected_playlists
        }

        try:
            # エクスポートをバックグラウンドスレッドで実行
            self.export_thread = ExportThread(options)
            self.export_thread.progress_updated.connect(self._update_export_progress)
            self.export_thread.finished.connect(self._on_export_finished)
            self.export_thread.start()
            self.output_dir_line_edit.text() # Start from current path if any
        )
        if directory:
            self.output_dir_line_edit.setText(directory)
            
    def _handle_table_click(self, index):
        """Handle clicks on table cells to toggle checkboxes properly"""
        # Only process clicks on checkbox columns
        col = index.column()
        row = index.row()
        model = self.playlist_table_view.model()
        
        # チェックボックス列のみ処理
        if col == PlaylistModel.EXPORT_COL or col == PlaylistModel.ADD_BPM_COL or col == PlaylistModel.ROMANIZE_TEXT_COL:
            # 範囲チェック
            if row < 0 or row >= model.rowCount():
                return
            
            # フォルダのBPM/ロマナイズ列は無効
            if model._data[row][PlaylistModel.IS_FOLDER_COL] and col != PlaylistModel.EXPORT_COL:
                return
            
            # 現在の状態を取得してトグル
            current = model._data[row][col]
            # トグル処理（反転）
            model._data[row][col] = not current
            
            # ログ出力
            print(f"Toggled checkbox at row {row}, col {col}: {current} -> {model._data[row][col]}")
            
            # 変更を通知（重要）
            model.dataChanged.emit(index, index, [Qt.CheckStateRole, Qt.DisplayRole])
            
            # エクスポート列のフォルダ項目の場合は子要素に伝播
            if col == PlaylistModel.EXPORT_COL and model._data[row][PlaylistModel.IS_FOLDER_COL]:
                model._propagate_folder_check_state(row, model._data[row][col])


def main():
    logging.basicConfig(level=logging.INFO, 
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    # You might want to set a more verbose level for development, e.g., logging.DEBUG
    # Or configure file logging here as well
    # Example: logging.getLogger('rkbdb2xml_gui').setLevel(logging.DEBUG)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

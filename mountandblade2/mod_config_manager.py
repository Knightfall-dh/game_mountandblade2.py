import os
import logging
import json
from pathlib import Path
from PyQt6.QtCore import QDir, Qt, QStandardPaths, QUrl, QFileSystemWatcher
from PyQt6.QtWidgets import QMainWindow, QTreeWidget, QTreeWidgetItem, QPushButton, QVBoxLayout, QWidget, QHeaderView, QMessageBox, QTabWidget, QLabel
from PyQt6.QtGui import QDesktopServices
import mobase
import shutil
from datetime import datetime

class ModConfigManagerWidget(QWidget):
    def __init__(self, parent: QMainWindow, organizer: mobase.IOrganizer):
        super().__init__(parent)
        self._parent = parent
        self._organizer = organizer
        self._file_timestamps = {}  # Track file modification times
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.directoryChanged.connect(self._on_directory_changed)
        self._file_watcher.fileChanged.connect(self._on_file_changed)
        self._current_profile_path = Path(self._organizer.profilePath())
        self._init_ui()
        self._setup_watcher()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Tab widget for Mod Configs and Status
        self._tab_widget = QTabWidget()
        layout.addWidget(self._tab_widget)

        # Mod Configs tab
        self._configs_tab = QWidget()
        configs_layout = QVBoxLayout(self._configs_tab)

        self._config_tree = QTreeWidget(self)
        self._config_tree.setHeaderLabels(["Config File", "Profile Path"])
        self._config_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._config_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        configs_layout.addWidget(self._config_tree)

        self._open_button = QPushButton("Open in External Editor", self)
        self._open_button.clicked.connect(self._open_external)
        self._open_button.setEnabled(False)
        configs_layout.addWidget(self._open_button)

        self._config_tree.itemSelectionChanged.connect(self._update_button_state)
        self._configs_tab.setLayout(configs_layout)
        self._tab_widget.addTab(self._configs_tab, "Mod Configs")

        # Status tab
        self._status_tab = QWidget()
        status_layout = QVBoxLayout(self._status_tab)
        self._status_label = QLabel("Configs Synced")
        self._status_label.setToolTip("Profile and game configurations are synchronized")
        status_layout.addWidget(self._status_label)
        self._status_tab.setLayout(status_layout)
        self._tab_widget.addTab(self._status_tab, "Status")

        self.setLayout(layout)
        self._load_configs()

    def _setup_watcher(self):
        """Set up QFileSystemWatcher to monitor the Configs directories."""
        try:
            docs_path = Path(QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)).filePath("Mount and Blade II Bannerlord/Configs"))
            profile_configs = Path(self._organizer.profilePath()) / "mod_configs"
            for path in [docs_path, profile_configs]:
                if path.exists():
                    self._file_watcher.addPath(str(path))
                    logging.info(f"ModConfigManagerWidget: Watching directory {path}")
                else:
                    logging.warning(f"ModConfigManagerWidget: Directory does not exist: {path}")
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to set up file watcher: {str(e)}")

    def _on_directory_changed(self, path: str):
        """Handle directory changes by updating configs and status."""
        logging.debug(f"ModConfigManagerWidget: Directory changed: {path}")
        self._load_configs()
        self._update_status()

    def _on_file_changed(self, path: str):
        """Handle file changes by updating configs and status."""
        logging.debug(f"ModConfigManagerWidget: File changed: {path}")
        self._load_configs()
        self._update_status()

    def refresh_on_profile_change(self):
        """Refresh configs when profile changes and force sync to game directory."""
        if hasattr(self, '_refreshing') and self._refreshing:
            logging.debug("ModConfigManagerWidget: Skipping refresh due to re-entrant call")
            return
        try:
            self._refreshing = True  # Set guard
            new_profile_path = Path(self._organizer.profilePath())
            if new_profile_path != self._current_profile_path:
                logging.info(f"ModConfigManagerWidget: Profile changed to {new_profile_path}")
                self._current_profile_path = new_profile_path
                self._file_timestamps.clear()
                self._load_configs()
                self.sync_to_game(force=True)  # Force sync to game directory on profile change
                # Update watcher for new profile's mod_configs directory
                profile_configs = Path(self._organizer.profilePath()) / "mod_configs"
                if profile_configs.exists():
                    # Remove existing paths to avoid duplicate watching
                    for path in self._file_watcher.directories():
                        if path != str(profile_configs):
                            self._file_watcher.removePath(path)
                    self._file_watcher.addPath(str(profile_configs))
                    logging.info(f"ModConfigManagerWidget: Added watcher for {profile_configs}")
            else:
                logging.debug("ModConfigManagerWidget: Profile path unchanged, skipping refresh")
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to refresh on profile change: {str(e)}")
        finally:
            self._refreshing = False  # Clear guard

    def _find_mod_configs(self) -> list[tuple[Path, Path]]:
        configs = []
        docs_path = Path(QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)).filePath("Mount and Blade II Bannerlord/Configs"))
        profile_path = Path(self._organizer.profilePath()) / "mod_configs"
        config_extensions = {".xml", ".json", ".ini"}
        excluded_files = {"engine_config.txt", "BannerlordConfig.txt", "LauncherData.xml"}
        known_folders = {"Configs", "Config", "Modules", "ModSettings"}

        for file in docs_path.rglob("*"):
            if (file.suffix.lower() in config_extensions and
                any(folder in file.parts for folder in known_folders) and
                file.name not in excluded_files):
                # Validate JSON files
                if file.suffix.lower() == ".json":
                    try:
                        with open(file, "r", encoding="utf-8-sig") as f:
                            json.load(f)
                        logging.debug(f"Valid JSON config: {file}")
                    except json.JSONDecodeError as e:
                        logging.warning(f"Invalid JSON config: {file} - Error: {e}")
                        continue
                relative_path = file.relative_to(docs_path)
                profile_file = profile_path / relative_path
                configs.append((file, profile_file))
                self._file_timestamps[str(file)] = file.stat().st_mtime
                logging.debug(f"Found config: {file} -> Profile: {profile_file}")

        # Check profile configs to include files not in game directory
        for profile_file in profile_path.rglob("*"):
            if (profile_file.suffix.lower() in config_extensions and
                any(folder in profile_file.parts for folder in known_folders) and
                profile_file.name not in excluded_files):
                # Validate JSON files
                if profile_file.suffix.lower() == ".json":
                    try:
                        with open(profile_file, "r", encoding="utf-8-sig") as f:
                            json.load(f)
                        logging.debug(f"Valid JSON profile config: {profile_file}")
                    except json.JSONDecodeError as e:
                        logging.warning(f"Invalid JSON profile config: {profile_file} - Error: {e}")
                        continue
                relative_path = profile_file.relative_to(profile_path)
                game_file = docs_path / relative_path
                if (game_file, profile_file) not in configs:
                    configs.append((game_file, profile_file))
                    self._file_timestamps[str(game_file)] = game_file.stat().st_mtime if game_file.exists() else 0
                    logging.debug(f"Found profile-only config: {game_file} -> Profile: {profile_file}")

        return configs

    def _load_configs(self):
        logging.info("ModConfigManagerWidget: Loading config files")
        self._config_tree.clear()
        configs = self._find_mod_configs()
        profile_path = Path(self._organizer.profilePath()) / "mod_configs"

        for orig_path, profile_file in configs:
            # Initialize profile file if it doesn't exist
            if orig_path.exists() and not profile_file.exists():
                profile_file.parent.mkdir(parents=True, exist_ok=True)
                if orig_path.suffix.lower() == ".json":
                    try:
                        with open(orig_path, "r", encoding="utf-8-sig") as f:
                            json.load(f)
                        shutil.copyfile(orig_path, profile_file)
                        logging.info(f"Initialized profile config: {profile_file}")
                    except json.JSONDecodeError as e:
                        logging.warning(f"Skipped copying invalid JSON config: {orig_path} - Error: {e}")
                else:
                    shutil.copyfile(orig_path, profile_file)
                    logging.info(f"Initialized profile config: {profile_file}")

            item = QTreeWidgetItem(self._config_tree)
            item.setText(0, orig_path.name)
            item.setText(1, str(profile_file.relative_to(profile_path)))
            item.setToolTip(0, str(orig_path))
            item.setToolTip(1, str(profile_file))
            item.setData(0, Qt.ItemDataRole.UserRole, str(profile_file))

        logging.info(f"ModConfigManagerWidget: Loaded {len(configs)} config files")
        self._update_status()

    def _update_button_state(self):
        selected = len(self._config_tree.selectedItems()) > 0
        self._open_button.setEnabled(selected)

    def _open_external(self):
        selected_items = self._config_tree.selectedItems()
        if not selected_items:
            logging.warning("ModConfigManagerWidget: No config file selected for opening")
            return

        item = selected_items[0]
        profile_path = Path(item.data(0, Qt.ItemDataRole.UserRole))

        try:
            if not profile_path.exists():
                logging.warning(f"ModConfigManagerWidget: Profile config does not exist: {profile_path}")
                QMessageBox.warning(self, "File Not Found", f"Config file not found: {profile_path}")
                return

            # Validate JSON before opening
            if profile_path.suffix.lower() == ".json":
                try:
                    with open(profile_path, "r", encoding="utf-8-sig") as f:
                        json.load(f)
                    logging.debug(f"ModConfigManagerWidget: Valid JSON before opening: {profile_path}")
                except json.JSONDecodeError as e:
                    logging.error(f"ModConfigManagerWidget: Cannot open invalid JSON config: {profile_path} - Error: {e}")
                    QMessageBox.critical(self, "Invalid JSON", f"Cannot open invalid JSON file: {e}")
                    return

            logging.info(f"ModConfigManagerWidget: Opening profile config in external editor: {profile_path}")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(profile_path)))
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to open {profile_path}: {str(e)}")
            QMessageBox.critical(self, "Open Error", f"Failed to open config file: {str(e)}")

    def _clear_game_configs(self, excluded_dirs: set = None):
        """Clear all config files in the game directory, except those in excluded directories."""
        try:
            docs_path = Path(QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)).filePath("Mount and Blade II Bannerlord/Configs"))
            config_extensions = {".xml", ".json", ".ini"}
            excluded_files = {"engine_config.txt", "BannerlordConfig.txt", "LauncherData.xml"}
            known_folders = {"Configs", "Config", "Modules", "ModSettings"}
            excluded_dirs = excluded_dirs or set()

            cleared = 0
            for file in docs_path.rglob("*"):
                if (file.suffix.lower() in config_extensions and
                    any(folder in file.parts for folder in known_folders) and
                    file.name not in excluded_files and
                    not any(excluded_dir in file.parts for excluded_dir in excluded_dirs)):
                    file.unlink()
                    cleared += 1
                    logging.debug(f"ModConfigManagerWidget: Cleared game config: {file}")
            logging.info(f"ModConfigManagerWidget: Cleared {cleared} config files from game directory")
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to clear game configs: {str(e)}")

    def sync_to_game(self, force: bool = False):
        """Copy profile configs to game directory, optionally forcing the sync."""
        try:
            logging.info("ModConfigManagerWidget: Syncing profile configs to game directory")
            configs = self._find_mod_configs()
            docs_path = Path(QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)).filePath("Mount and Blade II Bannerlord/Configs"))
            profile_path = Path(self._organizer.profilePath()) / "mod_configs"
            synced = 0

            # Clear game config directory to prevent overlap from previous profiles
            if force:
                self._clear_game_configs()

            for orig_path, profile_file in configs:
                # Initialize profile file if it doesn't exist and force is True
                if force and orig_path.exists() and not profile_file.exists():
                    profile_file.parent.mkdir(parents=True, exist_ok=True)
                    if orig_path.suffix.lower() == ".json":
                        try:
                            with open(orig_path, "r", encoding="utf-8-sig") as f:
                                json.load(f)
                            shutil.copyfile(orig_path, profile_file)
                            logging.info(f"ModConfigManagerWidget: Initialized profile config: {profile_file}")
                        except json.JSONDecodeError as e:
                            logging.warning(f"ModConfigManagerWidget: Skipped copying invalid JSON config: {orig_path} - Error: {e}")
                            continue
                    else:
                        shutil.copyfile(orig_path, profile_file)
                        logging.info(f"ModConfigManagerWidget: Initialized profile config: {profile_file}")

                # Sync profile file to game directory
                if profile_file.exists():
                    profile_mtime = profile_file.stat().st_mtime
                    orig_mtime = orig_path.stat().st_mtime if orig_path.exists() else 0
                    if force or profile_mtime > orig_mtime + 1:  # Allow 1-second tolerance
                        if profile_file.suffix.lower() == ".json":
                            try:
                                with open(profile_file, "r", encoding="utf-8-sig") as f:
                                    json.load(f)
                            except json.JSONDecodeError as e:
                                logging.warning(f"ModConfigManagerWidget: Skipping invalid JSON profile config: {profile_file} - Error: {e}")
                                continue
                        orig_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(profile_file, orig_path)
                        self._file_timestamps[str(orig_path)] = orig_path.stat().st_mtime
                        logging.info(f"ModConfigManagerWidget: Synced profile config to game: {profile_file} -> {orig_path}")
                        synced += 1
            logging.info(f"ModConfigManagerWidget: Synced {synced} configs to game directory")
            self._load_configs()
            if synced > 0:
                logging.debug(f"ModConfigManagerWidget: Synced {synced} configs, updating UI")
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to sync to game directory: {str(e)}")
            QMessageBox.critical(self, "Sync Error", f"Failed to sync configs to game directory: {str(e)}")

    def sync_to_profile(self):
        """Copy modified game configs to profile directory."""
        try:
            logging.info("ModConfigManagerWidget: Syncing game configs to profile")
            configs = self._find_mod_configs()
            docs_path = Path(QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)).filePath("Mount and Blade II Bannerlord/Configs"))
            profile_path = Path(self._organizer.profilePath()) / "mod_configs"
            synced = 0

            for orig_path, profile_file in configs:
                if orig_path.exists():
                    orig_mtime = orig_path.stat().st_mtime
                    profile_mtime = profile_file.stat().st_mtime if profile_file.exists() else 0
                    if orig_mtime > profile_mtime + 1:  # Allow 1-second tolerance
                        if orig_path.suffix.lower() == ".json":
                            try:
                                with open(orig_path, "r", encoding="utf-8-sig") as f:
                                    json.load(f)
                            except json.JSONDecodeError as e:
                                logging.warning(f"ModConfigManagerWidget: Skipping invalid JSON game config: {orig_path} - Error: {e}")
                                continue
                        profile_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(orig_path, profile_file)
                        self._file_timestamps[str(orig_path)] = orig_mtime
                        logging.info(f"ModConfigManagerWidget: Synced game config to profile: {orig_path} -> {profile_file}")
                        synced += 1
            logging.info(f"ModConfigManagerWidget: Synced {synced} configs to profile")
            self._load_configs()
            if synced > 0:
                logging.debug(f"ModConfigManagerWidget: Synced {synced} configs to profile, updating UI")
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to sync to profile: {str(e)}")
            QMessageBox.critical(self, "Sync Error", f"Failed to sync configs to profile: {str(e)}")

    def _update_status(self):
        """Update the status label based on config sync state."""
        try:
            if self._configs_in_sync():
                self._status_label.setText("Configs Synced")
                self._status_label.setToolTip("Profile and game configurations are synchronized")
                logging.debug("ModConfigManagerWidget: Status updated to Configs Synced")
            else:
                self._status_label.setText("Manual Edit Detected")
                self._status_label.setToolTip("Changes detected in profile or game configurations")
                logging.debug("ModConfigManagerWidget: Status updated to Manual Edit Detected")
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to update status: {str(e)}")

    def _configs_in_sync(self) -> bool:
        """Check if profile and game config directories are in sync."""
        try:
            docs_path = Path(QDir(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)).filePath("Mount and Blade II Bannerlord/Configs"))
            profile_path = Path(self._organizer.profilePath()) / "mod_configs"
            if not profile_path.exists() or not docs_path.exists():
                logging.debug("ModConfigManagerWidget: One or both config directories missing, assuming synced")
                return True
            profile_files = {f for f in profile_path.rglob("*") if f.is_file() and f.suffix.lower() in {".xml", ".json", ".ini"}}
            game_files = {f for f in docs_path.rglob("*") if f.is_file() and f.suffix.lower() in {".xml", ".json", ".ini"}}
            common_files = {(f.relative_to(profile_path) if f.is_relative_to(profile_path) else f.relative_to(docs_path)) for f in profile_files.intersection(game_files)}
            for rel_path in common_files:
                profile_file = profile_path / rel_path
                game_file = docs_path / rel_path
                if not self._compare_files(profile_file, game_file):
                    logging.debug(f"ModConfigManagerWidget: Mismatch detected between {profile_file} and {game_file}")
                    return False
            logging.debug("ModConfigManagerWidget: All common config files are in sync")
            return True
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to check config sync: {str(e)}")
            return True  # Default to True to avoid false positives

    def _compare_files(self, file1: Path, file2: Path) -> bool:
        """Compare two files for equality."""
        try:
            with open(file1, 'rb') as f1, open(file2, 'rb') as f2:
                return f1.read() == f2.read()
        except Exception as e:
            logging.error(f"ModConfigManagerWidget: Failed to compare files {file1} and {file2}: {str(e)}")
            return False
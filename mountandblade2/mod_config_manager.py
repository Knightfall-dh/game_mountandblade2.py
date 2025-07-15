# V:\Mod.Organizer-2.5.3beta2\plugins\games\mountandblade2\mod_config_manager.py
import os
from pathlib import Path
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QPushButton, QHBoxLayout, QTextEdit, QSplitter, QFileDialog, QMessageBox
from PyQt6.QtCore import Qt, QUrl, QRegularExpression, QStandardPaths
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QDesktopServices
import mobase
import logging
import shutil
import json
import xml.etree.ElementTree as ET
from typing import List, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConfigHighlighter(QSyntaxHighlighter):
    def __init__(self, parent, file_type: str):
        super().__init__(parent)
        self.file_type = file_type.lower()
        self._highlight_rules = []
        
        # Define highlighting rules
        if self.file_type == "ini":
            # INI: Key=value, comments
            key_format = QTextCharFormat()
            key_format.setForeground(QColor("blue"))
            self._highlight_rules.append((QRegularExpression(r"^\w+\s*="), key_format))
            comment_format = QTextCharFormat()
            comment_format.setForeground(QColor("gray"))
            self._highlight_rules.append((QRegularExpression(r";.*$"), comment_format))
        elif self.file_type == "json":
            # JSON: Keys, strings, numbers
            key_format = QTextCharFormat()
            key_format.setForeground(QColor("purple"))
            self._highlight_rules.append((QRegularExpression(r'"\w+"(?=\s*:)'), key_format))
            string_format = QTextCharFormat()
            string_format.setForeground(QColor("green"))
            self._highlight_rules.append((QRegularExpression(r'"[^"]*"'), string_format))
            number_format = QTextCharFormat()
            number_format.setForeground(QColor("red"))
            self._highlight_rules.append((QRegularExpression(r'\b\d+\.?\d*\b'), number_format))
        elif self.file_type == "xml":
            # XML: Tags, attributes
            tag_format = QTextCharFormat()
            tag_format.setForeground(QColor("blue"))
            self._highlight_rules.append((QRegularExpression(r'</?\w+'), tag_format))
            attr_format = QTextCharFormat()
            attr_format.setForeground(QColor("purple"))
            self._highlight_rules.append((QRegularExpression(r'\w+(?=\s*=)'), attr_format))

    def highlightBlock(self, text: str):
        for pattern, fmt in self._highlight_rules:
            expression = QRegularExpression(pattern)
            it = expression.globalMatch(text)
            while it.hasNext():
                match = it.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

class ModConfigManagerWidget(QWidget):
    def __init__(self, parent: QWidget | None, organizer: mobase.IOrganizer):
        super().__init__(parent)
        self._organizer = organizer
        self._layout = QVBoxLayout(self)
        
        # Splitter for tree and editor
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._layout.addWidget(self._splitter)
        
        # Config tree
        self._config_tree = QTreeWidget(self)
        self._config_tree.setHeaderLabels(["Mod", "Config File", "Profile Path"])
        self._config_tree.setColumnWidth(0, 200)
        self._config_tree.setColumnWidth(1, 300)
        self._config_tree.itemClicked.connect(self._load_config)
        self._splitter.addWidget(self._config_tree)
        
        # Editor
        self._editor = QTextEdit(self)
        self._editor.setPlaceholderText("Select a config file to edit...")
        self._editor.textChanged.connect(self._on_text_changed)
        self._splitter.addWidget(self._editor)
        self._current_config_path = None
        self._highlighter = None
        
        # Buttons
        button_layout = QHBoxLayout()
        self._refresh_button = QPushButton("Refresh Configs", self)
        self._refresh_button.clicked.connect(self._refresh_configs)
        button_layout.addWidget(self._refresh_button)
        
        self._save_button = QPushButton("Save Changes", self)
        self._save_button.clicked.connect(self._save_config)
        self._save_button.setEnabled(False)
        button_layout.addWidget(self._save_button)
        
        self._restore_button = QPushButton("Restore Original", self)
        self._restore_button.clicked.connect(self._restore_original)
        button_layout.addWidget(self._restore_button)
        
        self._open_external_button = QPushButton("Open in External Editor", self)
        self._open_external_button.clicked.connect(self._open_external)
        button_layout.addWidget(self._open_external_button)
        
        self._layout.addLayout(button_layout)
        self.setLayout(self._layout)
        self._refresh_configs()

    def _get_documents_path(self) -> Path:
        docs_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(docs_path) / "Mount and Blade II Bannerlord"

    def _get_profile_configs_path(self) -> Path:
        return Path(self._organizer.profilePath()) / "mod_configs"

    def _find_mod_configs(self) -> List[Tuple[str, Path, Path]]:
        configs = []
        docs_path = self._get_documents_path()
        profile_configs_path = self._get_profile_configs_path()
        profile_configs_path.mkdir(exist_ok=True)
        
        config_extensions = {".xml", ".json", ".ini", ".txt"}
        known_folders = {"Configs", "Config", "Modules"}
        
        for file in docs_path.rglob("*"):
            if file.suffix.lower() in config_extensions and any(folder in file.parts for folder in known_folders):
                mod_name = self._get_mod_name(file)
                relative_path = file.relative_to(docs_path)
                profile_path = profile_configs_path / relative_path
                configs.append((mod_name, file, profile_path))
        
        # Check SubModule.xml for explicit config paths
        for mod in self._organizer.modList().allMods():
            mod_path = Path(self._organizer.modList().getMod(mod).absolutePath())
            submodule_xml = mod_path / "SubModule.xml"
            if submodule_xml.exists():
                try:
                    tree = ET.parse(submodule_xml)
                    config_nodes = tree.findall(".//ConfigFile")
                    for node in config_nodes:
                        config_path = node.get("path")
                        if config_path:
                            full_path = docs_path / config_path
                            if full_path.exists():
                                mod_name = mod
                                relative_path = full_path.relative_to(docs_path)
                                profile_path = profile_configs_path / relative_path
                                configs.append((mod_name, full_path, profile_path))
                except Exception as e:
                    logger.error(f"Failed to parse SubModule.xml for {mod}: {str(e)}")
        
        return configs

    def _get_mod_name(self, file: Path) -> str:
        parts = file.parts
        if "Modules" in parts:
            module_idx = parts.index("Modules")
            if module_idx + 1 < len(parts):
                return parts[module_idx + 1]
        return file.parent.name

    def _refresh_configs(self):
        try:
            logger.info("ModConfigManagerWidget: Refreshing config files")
            self._config_tree.clear()
            self._editor.clear()
            self._save_button.setEnabled(False)
            configs = self._find_mod_configs()
            
            for mod_name, orig_path, profile_path in configs:
                if not profile_path.exists() and orig_path.exists():
                    profile_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(orig_path, profile_path)
                    logger.info(f"Copied {orig_path} to {profile_path}")
                
                item = QTreeWidgetItem(self._config_tree)
                item.setText(0, mod_name)
                item.setText(1, str(orig_path))
                item.setText(2, str(profile_path))
                item.setData(0, Qt.ItemDataRole.UserRole, str(profile_path))
            
            logger.info(f"ModConfigManagerWidget: Loaded {len(configs)} config files")
        except Exception as e:
            logger.error(f"ModConfigManagerWidget: Failed to refresh configs: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to refresh configs: {str(e)}")

    def _load_config(self, item: QTreeWidgetItem, column: int):
        try:
            self._current_config_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
            if not self._current_config_path.exists():
                self._editor.setPlainText("File not found in profile directory.")
                self._save_button.setEnabled(False)
                return
            
            with open(self._current_config_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            self._editor.setPlainText(content)
            file_type = self._current_config_path.suffix.lower()[1:]  # Remove dot
            self._highlighter = ConfigHighlighter(self._editor.document(), file_type)
            self._save_button.setEnabled(True)
            logger.info(f"Loaded config: {self._current_config_path}")
        except Exception as e:
            logger.error(f"Failed to load config {self._current_config_path}: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load config: {str(e)}")

    def _on_text_changed(self):
        self._save_button.setEnabled(bool(self._current_config_path and self._editor.toPlainText()))

    def _save_config(self):
        try:
            if not self._current_config_path:
                QMessageBox.warning(self, "Warning", "No config file selected")
                return
            
            content = self._editor.toPlainText()
            file_type = self._current_config_path.suffix.lower()[1:]
            
            # Basic validation
            if file_type == "json":
                try:
                    json.loads(content)
                except json.JSONDecodeError as e:
                    QMessageBox.warning(self, "Invalid JSON", f"JSON validation failed: {str(e)}")
                    return
            elif file_type == "xml":
                try:
                    ET.fromstring(content)
                except ET.ParseError as e:
                    QMessageBox.warning(self, "Invalid XML", f"XML validation failed: {str(e)}")
                    return
            
            # Backup before saving
            backup_path = self._current_config_path.with_suffix(".bak")
            if self._current_config_path.exists():
                shutil.copy(self._current_config_path, backup_path)
            
            with open(self._current_config_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Saved config: {self._current_config_path}")
            QMessageBox.information(self, "Success", f"Saved changes to {self._current_config_path}")
        except Exception as e:
            logger.error(f"Failed to save config {self._current_config_path}: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to save config: {str(e)}")

    def _restore_original(self):
        try:
            selected = self._config_tree.selectedItems()
            if not selected:
                QMessageBox.warning(self, "Warning", "No config file selected")
                return
            
            item = selected[0]
            orig_path = Path(item.text(1))
            profile_path = Path(item.data(0, Qt.ItemDataRole.UserRole))
            
            if orig_path.exists():
                profile_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(orig_path, profile_path)
                logger.info(f"Restored {orig_path} to {profile_path}")
                QMessageBox.information(self, "Success", f"Restored config to {profile_path}")
                self._load_config(item, 0)  # Reload the restored file
            else:
                QMessageBox.warning(self, "Error", f"Original file not found: {orig_path}")
        except Exception as e:
            logger.error(f"Failed to restore config: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to restore config: {str(e)}")

    def _open_external(self):
        try:
            if not self._current_config_path or not self._current_config_path.exists():
                QMessageBox.warning(self, "Warning", "No config file selected or file not found")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_config_path)))
            logger.info(f"Opened {self._current_config_path} in external editor")
        except Exception as e:
            logger.error(f"Failed to open {self._current_config_path} externally: {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to open externally: {str(e)}")
import os
import shutil
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from PyQt6.QtCore import QDir, QStandardPaths, Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QAbstractItemView, QListWidgetItem, QMessageBox
import mobase
import logging
from time import time
import re
from typing import Dict, List, Tuple, Set

logger = logging.getLogger(__name__)

class SubModuleTabWidget(QWidget):
    DEFAULT_MOD_ORDER = [
        "Native",
        "SandBoxCore",
        "BirthAndDeath",
        "CustomBattle",
        "Sandbox",
        "StoryMode",
        "Multiplayer"
    ]
    PRIORITY_MODS = [
        "Bannerlord.Harmony",
        "Bannerlord.ButterLib",
        "Bannerlord.UIExtenderEx",
        "Bannerlord.MBOptionScreen"
    ]
    MAX_BACKUPS = 3

    def __init__(self, parent: QWidget | None, organizer: mobase.IOrganizer):
        super().__init__(parent)
        logger.info("SubModuleTabWidget: Initializing")
        self._organizer = organizer
        self._layout = QVBoxLayout(self)
        self._mod_list = QListWidget(self)
        self._mod_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._mod_list.setDragEnabled(True)
        self._mod_list.setAcceptDrops(True)
        self._mod_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._mod_list.model().rowsMoved.connect(self.on_rows_moved)
        self._mod_list.itemChanged.connect(self.on_item_changed)
        self._layout.addWidget(self._mod_list)
        
        button_layout = QHBoxLayout()
        self._refresh_button = QPushButton("Refresh", self)
        self._refresh_button.clicked.connect(self.refresh_mods)
        button_layout.addWidget(self._refresh_button)
        
        self._sort_button = QPushButton("Sort Mods", self)
        self._sort_button.clicked.connect(self.sort_mods)
        button_layout.addWidget(self._sort_button)
        
        self._enable_all_button = QPushButton("Enable All", self)
        self._enable_all_button.clicked.connect(self.enable_all_mods)
        button_layout.addWidget(self._enable_all_button)
        
        self._disable_all_button = QPushButton("Disable All", self)
        self._disable_all_button.clicked.connect(self.disable_all_mods)
        button_layout.addWidget(self._disable_all_button)
        
        self._layout.addLayout(button_layout)
        self.setLayout(self._layout)
        self._last_xml_write = 0
        self._write_cooldown = 1.0  # Seconds
        self._queued_changes = {}  # Store mod_id: state for debouncing
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._process_queued_changes)
        
        # Connect to MO2's modOrderChanged signal
        try:
            self._organizer.onModOrderChanged(self._on_mod_order_changed)
            logger.info("SubModuleTabWidget: Connected to modOrderChanged signal")
        except AttributeError as e:
            logger.warning(f"SubModuleTabWidget: Failed to connect to modOrderChanged signal: {str(e)}")
        
        logger.info("SubModuleTabWidget: Initialization complete")
        self.refresh_mods()

    def _on_mod_order_changed(self):
        """Handle mod list changes from MO2's main panel."""
        logger.info("SubModuleTabWidget: Detected mod order change in main panel")
        self.refresh_mods()

    def _get_launcher_data_path(self) -> Path:
        try:
            profile_path = Path(self._organizer.profilePath()) / "LauncherData.xml"
            logger.debug(f"SubModuleTabWidget: Using profile-specific path: {profile_path}")
            return profile_path
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to get LauncherData.xml path: {str(e)}")
            return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)) / "Mount and Blade II Bannerlord" / "Configs" / "LauncherData.xml"

    def _get_default_launcher_data_path(self) -> Path:
        try:
            return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)) / "Mount and Blade II Bannerlord" / "Configs" / "LauncherData.xml"
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to get default LauncherData.xml path: {str(e)}")
            return Path.home() / "Documents" / "Mount and Blade II Bannerlord" / "Configs" / "LauncherData.xml"

    def _sync_launcher_data_to_default(self):
        try:
            profile_path = self._get_launcher_data_path()
            default_path = self._get_default_launcher_data_path()
            if profile_path.exists():
                default_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(profile_path, default_path)
                logger.info(f"SubModuleTabWidget: Copied LauncherData.xml from {profile_path} to {default_path} for native launcher")
            else:
                logger.warning(f"SubModuleTabWidget: Profile LauncherData.xml not found at {profile_path}, cannot sync to default path")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to sync LauncherData.xml to default path: {str(e)}")

    def _get_enabled_mods(self) -> list[str]:
        try:
            modlist_path = Path(self._organizer.profilePath()) / "modlist.txt"
            enabled_mods = []
            if modlist_path.exists():
                with modlist_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("+"):
                            mod_name = line[1:]
                            if not mod_name.endswith("_separator"):
                                enabled_mods.append(mod_name)
                logger.debug(f"SubModuleTabWidget: Found {len(enabled_mods)} enabled mods in modlist.txt: {enabled_mods}")
            else:
                logger.warning(f"SubModuleTabWidget: modlist.txt not found at {modlist_path}")
            return enabled_mods
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to read modlist.txt: {str(e)}")
            return []

    def _get_highest_priority_submodule_xml(self, mod_id: str, enabled_mods: list[str], enabled_mod_paths: dict[str, Path], modules_path: Path) -> tuple[Path | None, str | None]:
        """Find the highest-priority SubModule.xml for a given mod_id."""
        try:
            overwrite_path = Path(self._organizer.overwritePath()) / "Modules" / mod_id / "SubModule.xml"
            if overwrite_path.exists():
                logger.debug(f"SubModuleTabWidget: Found SubModule.xml for {mod_id} in overwrite directory: {overwrite_path}")
                return overwrite_path, None

            for mo2_mod_name in reversed(enabled_mods):
                mod_path = enabled_mod_paths[mo2_mod_name] / "Modules" / mod_id / "SubModule.xml"
                if mod_path.exists():
                    logger.debug(f"SubModuleTabWidget: Found SubModule.xml for {mod_id} in MO2 mod {mo2_mod_name}: {mod_path}")
                    return mod_path, mo2_mod_name

            game_mod_path = modules_path / mod_id / "SubModule.xml"
            if game_mod_path.exists():
                logger.debug(f"SubModuleTabWidget: Found SubModule.xml for {mod_id} in game Modules: {game_mod_path}")
                return game_mod_path, None

            logger.debug(f"SubModuleTabWidget: No SubModule.xml found for {mod_id}")
            return None, None
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to find SubModule.xml for {mod_id}: {str(e)}")
            return None, None

    def _indent_xml(self, elem, level=0):
        """Add proper indentation to XML element for pretty printing."""
        indent = "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = "\n" + indent * (level + 1)
            for child in elem:
                self._indent_xml(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = "\n" + indent * level
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = "\n" + indent * level

    def _manage_backups(self, launcher_data_path: Path):
        """Limit the number of LauncherData.xml.bak.* files to MAX_BACKUPS."""
        try:
            backup_pattern = launcher_data_path.with_name("LauncherData.xml.bak.*")
            backup_files = sorted(
                launcher_data_path.parent.glob("LauncherData.xml.bak.*"),
                key=lambda x: x.stat().st_mtime
            )
            while len(backup_files) >= self.MAX_BACKUPS:
                oldest_backup = backup_files.pop(0)
                oldest_backup.unlink()
                logger.info(f"SubModuleTabWidget: Removed oldest backup {oldest_backup}")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to manage backups: {str(e)}")

    def _process_queued_changes(self):
        """Process all queued mod state changes and update LauncherData.xml."""
        if not self._queued_changes:
            logger.debug("SubModuleTabWidget: No queued changes to process")
            return
        try:
            logger.debug(f"SubModuleTabWidget: Processing {len(self._queued_changes)} queued changes")
            for mod_id, state in self._queued_changes.items():
                self._update_launcher_data(changed_mod=mod_id, changed_state=state)
            self._queued_changes.clear()
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to process queued changes: {str(e)}")

    def _update_launcher_data(self, changed_mod: str | None = None, changed_state: bool | None = None):
        if time() - self._last_xml_write < self._write_cooldown:
            if changed_mod is not None and changed_state is not None:
                self._queued_changes[changed_mod] = changed_state
                self._debounce_timer.start(int(self._write_cooldown * 1000))
                logger.debug(f"SubModuleTabWidget: Queued change for {changed_mod}: IsSelected={changed_state}")
            return
        try:
            launcher_data_path = self._get_launcher_data_path()
            logger.debug(f"SubModuleTabWidget: Updating LauncherData.xml at {launcher_data_path}")
            try:
                tree = ET.parse(launcher_data_path)
                root = tree.getroot()
            except (FileNotFoundError, ET.ParseError):
                logger.warning(f"SubModuleTabWidget: Creating new LauncherData.xml at {launcher_data_path}")
                root = ET.Element("UserData")
                root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
                root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
                tree = ET.ElementTree(root)
            
            singleplayer_data = root.find("SingleplayerData")
            if singleplayer_data is None:
                singleplayer_data = ET.SubElement(root, "SingleplayerData")
            singleplayer_mods = singleplayer_data.find("ModDatas")
            if singleplayer_mods is None:
                singleplayer_mods = ET.SubElement(singleplayer_data, "ModDatas")
            
            multiplayer_data = root.find("MultiplayerData")
            if multiplayer_data is None:
                multiplayer_data = ET.SubElement(root, "MultiplayerData")
            multiplayer_mods = multiplayer_data.find("ModDatas")
            if multiplayer_mods is None:
                multiplayer_mods = ET.SubElement(multiplayer_data, "ModDatas")
            
            singleplayer_mods.clear()
            multiplayer_mods.clear()
            
            mod_versions = {}
            mod_states = {}
            mod_multiplayer = {}
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                if item:
                    mod_id = item.data(Qt.ItemDataRole.UserRole)
                    version = item.data(Qt.ItemDataRole.UserRole + 2) or "v1.0.0.0"
                    mod_versions[mod_id] = version
                    mod_states[mod_id] = item.checkState() == Qt.CheckState.Checked
                    mod_multiplayer[mod_id] = item.data(Qt.ItemDataRole.UserRole + 1) or False
                    if mod_id in ["Sandbox", "Multiplayer"]:
                        mod_states[mod_id] = True
                        item.setCheckState(Qt.CheckState.Checked)
                    if changed_mod == mod_id and changed_state is not None:
                        mod_states[mod_id] = changed_state
            
            for i in range(self._mod_list.count()):
                mod_id = self._mod_list.item(i).data(Qt.ItemDataRole.UserRole)
                if mod_id != "Multiplayer":
                    mod_data = ET.SubElement(singleplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "v1.0.0.0")
                    ET.SubElement(mod_data, "IsSelected").text = str(mod_states.get(mod_id, False)).lower()
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to SingleplayerData, IsSelected={mod_states.get(mod_id, False)}")
                
                if mod_id in ["Native", "Multiplayer"] or mod_multiplayer.get(mod_id, False):
                    mod_data = ET.SubElement(multiplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "v1.0.0.0")
                    ET.SubElement(mod_data, "IsSelected").text = "true"
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to MultiplayerData")
            
            # Ensure only one GameType tag
            existing_game_type = root.find("GameType")
            if existing_game_type is None:
                ET.SubElement(root, "GameType").text = "Singleplayer"
                logger.debug("SubModuleTabWidget: Added single GameType tag")
            
            self._indent_xml(root)
            if launcher_data_path.exists():
                self._manage_backups(launcher_data_path)
                backup_path = launcher_data_path.with_name(f"LauncherData.xml.bak.{datetime.now().strftime('%Y%m%dT%H%M%S')}")
                shutil.copy(launcher_data_path, backup_path)
                logger.info(f"SubModuleTabWidget: Backed up LauncherData.xml to {backup_path}")
            launcher_data_path.parent.mkdir(parents=True, exist_ok=True)
            tree.write(str(launcher_data_path), encoding="utf-8", xml_declaration=True)
            self._last_xml_write = time()
            self._sync_launcher_data_to_default()
            logger.info(f"SubModuleTabWidget: Updated LauncherData.xml at {launcher_data_path} and synced to default path")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to update LauncherData.xml: {str(e)}")

    def _update_launcher_data_order(self):
        try:
            launcher_data_path = self._get_launcher_data_path()
            logger.debug(f"SubModuleTabWidget: Updating LauncherData.xml order at {launcher_data_path}")
            try:
                tree = ET.parse(launcher_data_path)
                root = tree.getroot()
            except (FileNotFoundError, ET.ParseError):
                logger.warning(f"SubModuleTabWidget: Creating new LauncherData.xml for order at {launcher_data_path}")
                root = ET.Element("UserData")
                root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
                root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
                tree = ET.ElementTree(root)
            
            # Store non-mod tags, excluding GameType to avoid duplicates
            non_mod_tags = {elem.tag: ET.Element(elem.tag, elem.attrib) for elem in root if elem.tag not in ("SingleplayerData", "MultiplayerData", "DLLCheckData", "GameType")}
            for elem in root:
                if elem.tag in non_mod_tags:
                    non_mod_tags[elem.tag].text = elem.text
            
            root.clear()
            root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
            root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
            
            singleplayer_data = ET.SubElement(root, "SingleplayerData")
            singleplayer_mods = ET.SubElement(singleplayer_data, "ModDatas")
            multiplayer_data = ET.SubElement(root, "MultiplayerData")
            multiplayer_mods = ET.SubElement(multiplayer_data, "ModDatas")
            
            mod_versions = {}
            mod_states = {}
            mod_multiplayer = {}
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                if item:
                    mod_id = item.data(Qt.ItemDataRole.UserRole)
                    version = item.data(Qt.ItemDataRole.UserRole + 2) or "v1.0.0.0"
                    mod_versions[mod_id] = version
                    mod_states[mod_id] = item.checkState() == Qt.CheckState.Checked
                    mod_multiplayer[mod_id] = item.data(Qt.ItemDataRole.UserRole + 1) or False
                    if mod_id in ["Sandbox", "Multiplayer"]:
                        mod_states[mod_id] = True
                        item.setCheckState(Qt.CheckState.Checked)
            
            for i in range(self._mod_list.count()):
                mod_id = self._mod_list.item(i).data(Qt.ItemDataRole.UserRole)
                if mod_id != "Multiplayer":
                    mod_data = ET.SubElement(singleplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "v1.0.0.0")
                    ET.SubElement(mod_data, "IsSelected").text = str(mod_states.get(mod_id, False)).lower()
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to SingleplayerData, IsSelected={mod_states.get(mod_id, False)}")
                
                if mod_id in ["Native", "Multiplayer"] or mod_multiplayer.get(mod_id, False):
                    mod_data = ET.SubElement(multiplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "v1.0.0.0")
                    ET.SubElement(mod_data, "IsSelected").text = "true"
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to MultiplayerData")
            
            # Restore non-mod tags
            for tag, element in non_mod_tags.items():
                new_elem = ET.SubElement(root, tag)
                new_elem.text = element.text
                new_elem.attrib.update(element.attrib)
                logger.debug(f"SubModuleTabWidget: Restored non-mod tag {tag}")
            
            # Ensure only one GameType tag
            ET.SubElement(root, "GameType").text = "Singleplayer"
            logger.debug("SubModuleTabWidget: Added single GameType tag")
            
            self._indent_xml(root)
            if launcher_data_path.exists():
                self._manage_backups(launcher_data_path)
                backup_path = launcher_data_path.with_name(f"LauncherData.xml.bak.{datetime.now().strftime('%Y%m%dT%H%M%S')}")
                shutil.copy(launcher_data_path, backup_path)
                logger.info(f"SubModuleTabWidget: Backed up LauncherData.xml to {backup_path}")
            launcher_data_path.parent.mkdir(parents=True, exist_ok=True)
            tree.write(str(launcher_data_path), encoding="utf-8", xml_declaration=True)
            self._last_xml_write = time()
            self._sync_launcher_data_to_default()
            logger.info(f"SubModuleTabWidget: Updated LauncherData.xml at {launcher_data_path} and synced to default path")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to update LauncherData.xml order: {str(e)}")

    def _parse_version(self, version_text: str | None, mod_id: str | None = None) -> str:
        """Parse and validate version string from SubModule.xml, normalizing format."""
        if not version_text:
            logger.warning(f"SubModuleTabWidget: Version text is empty for mod {mod_id or 'unknown'}, defaulting to v1.0.0.0")
            return "v1.0.0.0"
        version_text = version_text.strip()
        match = re.match(r"^[ve](\d+)\.(\d+)\.(\d+)(\.\d+)?(\.\d+)?$", version_text)
        if match:
            prefix = version_text[0]
            components = [str(int(match.group(i))) for i in range(1, 4)]
            if match.group(4):
                components.append(str(int(match.group(4)[1:])))
            else:
                components.append("0")
            if match.group(5):
                components.append(str(int(match.group(5)[1:])))
            return f"{prefix}{'.'.join(components)}"
        match = re.match(r"^[ve](\d+)\.(\d+)\.(\d+)$", version_text)
        if match:
            prefix = version_text[0]
            components = [str(int(match.group(i))) for i in range(1, 4)]
            components.append("0")
            return f"{prefix}{'.'.join(components)}"
        logger.warning(f"SubModuleTabWidget: Invalid version format '{version_text}' for mod {mod_id or 'unknown'}, defaulting to v1.0.0.0")
        return "v1.0.0.0"

    def _build_dependency_graph(self, mod_data: List[Dict]) -> Tuple[Dict[str, List[Tuple[str, str, bool, str]]], List[str]]:
        """Build a dependency graph from SubModule.xml files and detect issues."""
        dependencies = {}
        issues = []
        for mod in mod_data:
            mod_id = mod["id"]
            dependencies[mod_id] = []
            xml_path = mod["source_path"]
            try:
                tree = ET.parse(xml_path)
                root = tree.getroot()
                for dep in root.findall(".//DependedModuleMetadata"):
                    dep_id = dep.get("id")
                    order = dep.get("order", "LoadAfterThis")
                    optional = dep.get("optional", "false").lower() == "true"
                    incompatible = dep.get("incompatible", "false").lower() == "true"
                    version = dep.get("version", "*")
                    if dep_id:
                        if incompatible:
                            if dep_id in [m["id"] for m in mod_data]:
                                issues.append(f"Mod {mod_id} is incompatible with {dep_id}")
                            continue
                        dependencies[mod_id].append((dep_id, order, optional, version))
            except ET.ParseError as e:
                issues.append(f"Failed to parse SubModule.xml for {mod_id}: {str(e)}")
        # Ensure PRIORITY_MODS load before native modules
        for mod_id in self.PRIORITY_MODS:
            if mod_id in dependencies:
                for native_mod in self.DEFAULT_MOD_ORDER:
                    if native_mod in [m["id"] for m in mod_data] and (native_mod, "LoadBeforeThis", False, "*") not in dependencies[mod_id]:
                        dependencies[mod_id].append((native_mod, "LoadBeforeThis", False, "*"))
                        logger.debug(f"SubModuleTabWidget: Enforced {mod_id} to load before {native_mod}")
        return dependencies, issues

    def _topological_sort(self, dependencies: Dict[str, List[Tuple[str, str, bool, str]]], mod_data: List[Dict], mod_id_to_data: Dict[str, Dict]) -> List[Dict]:
        """Perform topological sort based on dependencies, enforcing PRIORITY_MODS and DEFAULT_MOD_ORDER."""
        def dfs(mod_id: str, visited: Set[str], temp_mark: Set[str], result: List[str], dependencies: Dict[str, List[Tuple[str, str, bool, str]]]):
            if mod_id in temp_mark:
                raise ValueError(f"Circular dependency detected involving {mod_id}")
            if mod_id not in visited:
                temp_mark.add(mod_id)
                for dep_id, order, optional, _ in dependencies.get(mod_id, []):
                    if order == "LoadAfterThis" and dep_id in mod_id_to_data and not optional:
                        dfs(dep_id, visited, temp_mark, result, dependencies)
                    elif order == "LoadBeforeThis" and dep_id in mod_id_to_data and not optional:
                        if dep_id not in visited:  # Only recurse if not visited to avoid infinite loops
                            dfs(dep_id, visited, temp_mark, result, dependencies)
                temp_mark.remove(mod_id)
                visited.add(mod_id)
                result.append(mod_id)
        
        visited = set()
        temp_mark = set()
        result = []
        
        # Process PRIORITY_MODS first
        for mod_id in self.PRIORITY_MODS:
            if mod_id in mod_id_to_data and mod_id not in visited:
                dfs(mod_id, visited, temp_mark, result, dependencies)
        
        # Process DEFAULT_MOD_ORDER next
        for mod_id in self.DEFAULT_MOD_ORDER:
            if mod_id in mod_id_to_data and mod_id not in visited:
                dfs(mod_id, visited, temp_mark, result, dependencies)
        
        # Process remaining mods
        for mod in mod_data:
            mod_id = mod["id"]
            if mod_id not in visited:
                dfs(mod_id, visited, temp_mark, result, dependencies)
        
        # Convert sorted mod IDs to mod_data entries
        sorted_mods = []
        for mod_id in result:
            if mod_id in mod_id_to_data:
                sorted_mods.append(mod_id_to_data[mod_id])
        
        return sorted_mods

    def _map_modlist_to_submodules(self, enabled_mods: List[str], mod_data: List[Dict]) -> List[str]:
        """Map MO2 modlist.txt order to submodule IDs, respecting upside-down priority."""
        mod_id_to_mo2_name = {mod["id"]: mod.get("mo2_mod_name") for mod in mod_data if mod.get("mo2_mod_name")}
        sorted_mod_ids = []
        # Reverse enabled_mods to match MO2's priority (bottom = highest)
        for mo2_mod_name in reversed(enabled_mods):
            for mod_id, name in mod_id_to_mo2_name.items():
                if name == mo2_mod_name and mod_id not in sorted_mod_ids:
                    sorted_mod_ids.append(mod_id)
        # Add PRIORITY_MODS and DEFAULT_MOD_ORDER at the start if not included
        for mod_id in self.PRIORITY_MODS:
            if mod_id in mod_id_to_mo2_name and mod_id not in sorted_mod_ids:
                sorted_mod_ids.insert(0, mod_id)
        for mod_id in self.DEFAULT_MOD_ORDER:
            if mod_id not in sorted_mod_ids:
                sorted_mod_ids.append(mod_id)
        # Add any remaining mod IDs not in modlist.txt
        for mod in mod_data:
            mod_id = mod["id"]
            if mod_id not in sorted_mod_ids:
                sorted_mod_ids.append(mod_id)
        return sorted_mod_ids

    def sort_mods(self):
        """Sort mods based on dependencies and modlist.txt, enforcing PRIORITY_MODS and native modules."""
        try:
            logger.info("SubModuleTabWidget: Starting sort_mods")
            start_time = time()
            
            # Get enabled mods and paths
            enabled_mods = self._get_enabled_mods()
            mo2_mods_path = Path(self._organizer.modsPath())
            modules_path = Path(self._organizer.managedGame().gameDirectory().absolutePath()) / "Modules"
            enabled_mod_paths = {mo2_mod_name: mo2_mods_path / mo2_mod_name for mo2_mod_name in enabled_mods}
            
            # Collect mod data
            mod_data = []
            mod_id_to_data = {}
            xml_cache = {}
            
            # Scan game Modules directory
            if modules_path.exists():
                for mod_dir in modules_path.iterdir():
                    if mod_dir.is_dir():
                        mod_id = mod_dir.name
                        xml_path, _ = self._get_highest_priority_submodule_xml(mod_id, enabled_mods, enabled_mod_paths, modules_path)
                        if xml_path and xml_path.exists() and xml_path not in xml_cache:
                            try:
                                tree = ET.parse(xml_path)
                                root = tree.getroot()
                                mod_id = root.find("Id").get("value").strip() if root.find("Id") is not None else mod_dir.name
                                version_elem = root.find("Version")
                                raw_version = version_elem.get("value").strip() if version_elem is not None and version_elem.get("value") else (version_elem.text.strip() if version_elem is not None and version_elem.text else "v1.0.0.0")
                                mod_version = self._parse_version(raw_version, mod_id)
                                multiplayer_elem = root.find("MultiplayerModule")
                                is_multiplayer = multiplayer_elem is not None and multiplayer_elem.get("value").strip() == "true"
                                category_elem = root.find("ModuleCategory")
                                is_multiplayer |= category_elem is not None and category_elem.get("value").strip() == "Multiplayer"
                                deps = [f"{dep.get('id')} ({dep.get('version', '*')})" for dep in root.findall(".//DependedModuleMetadata") if dep.get("id")]
                                dep_text = ", ".join(deps) if deps else "None"
                                xml_cache[xml_path] = {
                                    "id": mod_id,
                                    "raw_version": raw_version,
                                    "version": mod_version,
                                    "is_multiplayer": is_multiplayer,
                                    "deps": dep_text,
                                    "is_native": True,
                                    "source_path": xml_path
                                }
                                mod_data.append(xml_cache[xml_path])
                                mod_id_to_data[mod_id] = mod_data[-1]
                            except ET.ParseError as e:
                                logger.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}: {str(e)}")
            
            # Scan MO2 mods directory
            if mo2_mods_path.exists():
                for mo2_mod_name in enabled_mods:
                    mod_path = enabled_mod_paths[mo2_mod_name]
                    xml_files = list(mod_path.glob("**/SubModule.xml"))
                    for xml_path in xml_files:
                        if xml_path in xml_cache:
                            continue
                        try:
                            xml_priority_path, xml_mo2_mod_name = self._get_highest_priority_submodule_xml(
                                xml_path.parent.name, enabled_mods, enabled_mod_paths, modules_path)
                            if xml_priority_path and xml_priority_path != xml_path:
                                logger.debug(f"SubModuleTabWidget: Skipping {xml_path} as higher-priority file exists: {xml_priority_path}")
                                continue
                            tree = ET.parse(xml_path)
                            root = tree.getroot()
                            mod_id = root.find("Id").get("value").strip() if root.find("Id") is not None else xml_path.parent.name
                            version_elem = root.find("Version")
                            raw_version = version_elem.get("value").strip() if version_elem is not None and version_elem.get("value") else (version_elem.text.strip() if version_elem is not None and version_elem.text else "v1.0.0.0")
                            mod_version = self._parse_version(raw_version, mod_id)
                            multiplayer_elem = root.find("MultiplayerModule")
                            is_multiplayer = multiplayer_elem is not None and multiplayer_elem.get("value").strip() == "true"
                            category_elem = root.find("ModuleCategory")
                            is_multiplayer |= category_elem is not None and category_elem.get("value").strip() == "Multiplayer"
                            deps = [f"{dep.get('id')} ({dep.get('version', '*')})" for dep in root.findall(".//DependedModuleMetadata") if dep.get("id")]
                            dep_text = ", ".join(deps) if deps else "None"
                            xml_cache[xml_path] = {
                                "name": mod_id,
                                "id": mod_id,
                                "raw_version": raw_version,
                                "version": mod_version,
                                "deps": dep_text,
                                "is_native": False,
                                "is_multiplayer": is_multiplayer,
                                "mo2_mod_name": mo2_mod_name,
                                "source_path": xml_path
                            }
                            mod_data.append(xml_cache[xml_path])
                            mod_id_to_data[mod_id] = mod_data[-1]
                        except ET.ParseError as e:
                            logger.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}: {str(e)}")
            
            # Read saved states from LauncherData.xml
            launcher_data_path = self._get_launcher_data_path()
            saved_mod_states = {}
            saved_mod_order = []
            if launcher_data_path.exists():
                try:
                    tree = ET.parse(launcher_data_path)
                    root = tree.getroot()
                    mod_datas = root.find(".//SingleplayerData/ModDatas")
                    if mod_datas is not None:
                        for user_mod_data in mod_datas.findall("UserModData"):
                            mod_id = user_mod_data.findtext("Id")
                            is_selected = user_mod_data.findtext("IsSelected", "false").lower() == "true"
                            if mod_id:
                                saved_mod_states[mod_id] = is_selected
                                saved_mod_order.append(mod_id)
                                logger.debug(f"SubModuleTabWidget: Read {mod_id} IsSelected={is_selected} from LauncherData.xml")
                except Exception as e:
                    logger.error(f"SubModuleTabWidget: Failed to read LauncherData.xml: {str(e)}")
            
            # Enforce Sandbox and Multiplayer as enabled
            for mod_id in ["Sandbox", "Multiplayer"]:
                saved_mod_states[mod_id] = True
                logger.debug(f"SubModuleTabWidget: Forced {mod_id} to IsSelected=true")
            
            # Build dependency graph and check for issues
            dependencies, issues = self._build_dependency_graph(mod_data)
            
            # Show compatibility issues if any
            if issues:
                QMessageBox.warning(self, "Mod Compatibility Issues", "\n".join(issues))
                logger.warning(f"SubModuleTabWidget: Found compatibility issues: {issues}")
            
            # Perform topological sort
            try:
                sorted_mods = self._topological_sort(dependencies, mod_data, mod_id_to_data)
            except ValueError as e:
                QMessageBox.critical(self, "Sort Error", f"Failed to sort mods: {str(e)}")
                logger.error(f"SubModuleTabWidget: Sort failed: {str(e)}")
                return
            
            # Align with modlist.txt for non-priority, non-native mods
            modlist_order = self._map_modlist_to_submodules(enabled_mods, mod_data)
            if modlist_order:
                final_mods = []
                seen = set()
                # Add PRIORITY_MODS first
                for mod_id in self.PRIORITY_MODS:
                    if mod_id in mod_id_to_data and mod_id not in seen:
                        final_mods.append(mod_id_to_data[mod_id])
                        seen.add(mod_id)
                # Add DEFAULT_MOD_ORDER next
                for mod_id in self.DEFAULT_MOD_ORDER:
                    if mod_id in mod_id_to_data and mod_id not in seen:
                        final_mods.append(mod_id_to_data[mod_id])
                        seen.add(mod_id)
                # Add remaining mods in modlist.txt order, respecting dependencies
                for mod_id in modlist_order:
                    if mod_id in mod_id_to_data and mod_id not in seen and mod_id not in self.PRIORITY_MODS and mod_id not in self.DEFAULT_MOD_ORDER:
                        final_mods.append(mod_id_to_data[mod_id])
                        seen.add(mod_id)
                # Add any remaining mods from topological sort
                for mod in sorted_mods:
                    if mod["id"] not in seen:
                        final_mods.append(mod)
                        seen.add(mod["id"])
                sorted_mods = final_mods
                logger.info("SubModuleTabWidget: Aligned sort with modlist.txt order, prioritizing PRIORITY_MODS and DEFAULT_MOD_ORDER")
            
            # Update UI
            self._mod_list.blockSignals(True)
            self._mod_list.clear()
            current_states = {self._mod_list.item(i).data(Qt.ItemDataRole.UserRole): self._mod_list.item(i).checkState() == Qt.CheckState.Checked for i in range(self._mod_list.count()) if self._mod_list.item(i)}
            
            for mod in sorted_mods:
                mod_id = mod["id"]
                raw_version = mod["raw_version"]
                mod_version = mod["version"]
                is_multiplayer = mod["is_multiplayer"]
                dep_text = mod["deps"]
                mo2_mod_name = mod.get("mo2_mod_name", "Unknown")
                source_path = mod.get("source_path", "Unknown")
                display_text = f"{mod_id} ({raw_version})"
                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, is_multiplayer)
                item.setData(Qt.ItemDataRole.UserRole + 2, mod_version)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Enforce native modules and priority mods as checked unless disabled in LauncherData.xml
                mod_state = saved_mod_states.get(mod_id, mod_id in self.DEFAULT_MOD_ORDER or mod_id in self.PRIORITY_MODS)
                if mod_id in ["Sandbox", "Multiplayer"]:
                    mod_state = True
                item.setCheckState(Qt.CheckState.Checked if mod_state else Qt.CheckState.Unchecked)
                item.setToolTip(f"ID: {mod_id}\nVersion: {raw_version}\nMultiplayer: {is_multiplayer}\nDependencies: {dep_text}\nSource: {'Game Modules' if mod['is_native'] else f'MO2 Mods ({mo2_mod_name})'}\nPath: {source_path}")
                self._mod_list.addItem(item)
                logger.info(f"SubModuleTabWidget: Added sorted mod {mod_id} (ID: {mod_id}, Raw Version: {raw_version}, Parsed Version: {mod_version}, Multiplayer: {is_multiplayer}, Source: {'Game Modules' if mod['is_native'] else f'MO2 Mods ({mo2_mod_name})'}, State: {mod_state})")
            
            self._mod_list.blockSignals(False)
            self._update_launcher_data_order()
            logger.info(f"SubModuleTabWidget: Sorted {self._mod_list.count()} mods in {time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to sort mods: {str(e)}")
            QMessageBox.critical(self, "Sort Error", f"Failed to sort mods: {str(e)}")

    def refresh_mods(self):
        try:
            logger.info("SubModuleTabWidget: Starting refresh_mods")
            start_time = time()
            game = self._organizer.managedGame()
            if not game:
                logger.error("SubModuleTabWidget: No managed game found")
                return
            
            # Store current UI state and order
            current_order = [self._mod_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._mod_list.count()) if self._mod_list.item(i)]
            current_states = {self._mod_list.item(i).data(Qt.ItemDataRole.UserRole): self._mod_list.item(i).checkState() == Qt.CheckState.Checked for i in range(self._mod_list.count()) if self._mod_list.item(i)}
            logger.debug(f"SubModuleTabWidget: Saved current order: {current_order}, states: {current_states}")
            
            # Get enabled mods and paths
            enabled_mods = self._get_enabled_mods()
            mo2_mods_path = Path(self._organizer.modsPath())
            modules_path = Path(game.gameDirectory().absolutePath()) / "Modules"
            enabled_mod_paths = {mo2_mod_name: mo2_mods_path / mo2_mod_name for mo2_mod_name in enabled_mods}
            
            # Collect all SubModule.xml files in one pass
            mod_data = []
            mod_id_to_data = {}
            xml_cache = {}  # Cache parsed SubModule.xml data
            
            # Scan game Modules directory
            logger.debug(f"SubModuleTabWidget: Scanning game Modules directory: {modules_path}")
            if modules_path.exists():
                for mod_dir in modules_path.iterdir():
                    if mod_dir.is_dir():
                        mod_id = mod_dir.name
                        xml_path, _ = self._get_highest_priority_submodule_xml(mod_id, enabled_mods, enabled_mod_paths, modules_path)
                        if xml_path and xml_path.exists() and xml_path not in xml_cache:
                            try:
                                tree = ET.parse(xml_path)
                                root = tree.getroot()
                                mod_id = root.find("Id").get("value").strip() if root.find("Id") is not None else mod_dir.name
                                version_elem = root.find("Version")
                                raw_version = version_elem.get("value").strip() if version_elem is not None and version_elem.get("value") else (version_elem.text.strip() if version_elem is not None and version_elem.text else "v1.0.0.0")
                                mod_version = self._parse_version(raw_version, mod_id)
                                multiplayer_elem = root.find("MultiplayerModule")
                                is_multiplayer = multiplayer_elem is not None and multiplayer_elem.get("value").strip() == "true"
                                category_elem = root.find("ModuleCategory")
                                is_multiplayer |= category_elem is not None and category_elem.get("value").strip() == "Multiplayer"
                                deps = [f"{dep.get('id')} ({dep.get('version', '*')})" for dep in root.findall(".//DependedModuleMetadata") if dep.get("id")]
                                dep_text = ", ".join(deps) if deps else "None"
                                xml_cache[xml_path] = {
                                    "id": mod_id,
                                    "raw_version": raw_version,
                                    "version": mod_version,
                                    "is_multiplayer": is_multiplayer,
                                    "deps": dep_text,
                                    "is_native": True,
                                    "source_path": xml_path
                                }
                                mod_data.append(xml_cache[xml_path])
                                mod_id_to_data[mod_id] = mod_data[-1]
                                logger.info(f"SubModuleTabWidget: Found native mod {mod_id} (ID: {mod_id}, Raw Version: {raw_version}, Parsed Version: {mod_version}, Multiplayer: {is_multiplayer}, Source: {xml_path})")
                            except ET.ParseError as e:
                                logger.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}: {str(e)}")
            
            # Scan MO2 mods directory
            logger.debug(f"SubModuleTabWidget: Scanning MO2 mods directory: {mo2_mods_path}")
            if mo2_mods_path.exists():
                for mo2_mod_name in enabled_mods:
                    mod_path = enabled_mod_paths[mo2_mod_name]
                    xml_files = list(mod_path.glob("**/SubModule.xml"))
                    for xml_path in xml_files:
                        if xml_path in xml_cache:
                            continue
                        try:
                            xml_priority_path, xml_mo2_mod_name = self._get_highest_priority_submodule_xml(
                                xml_path.parent.name, enabled_mods, enabled_mod_paths, modules_path)
                            if xml_priority_path and xml_priority_path != xml_path:
                                logger.debug(f"SubModuleTabWidget: Skipping {xml_path} as higher-priority file exists: {xml_priority_path}")
                                continue
                            tree = ET.parse(xml_path)
                            root = tree.getroot()
                            mod_id = root.find("Id").get("value").strip() if root.find("Id") is not None else xml_path.parent.name
                            version_elem = root.find("Version")
                            raw_version = version_elem.get("value").strip() if version_elem is not None and version_elem.get("value") else (version_elem.text.strip() if version_elem is not None and version_elem.text else "v1.0.0.0")
                            mod_version = self._parse_version(raw_version, mod_id)
                            multiplayer_elem = root.find("MultiplayerModule")
                            is_multiplayer = multiplayer_elem is not None and multiplayer_elem.get("value").strip() == "true"
                            category_elem = root.find("ModuleCategory")
                            is_multiplayer |= category_elem is not None and category_elem.get("value").strip() == "Multiplayer"
                            deps = [f"{dep.get('id')} ({dep.get('version', '*')})" for dep in root.findall(".//DependedModuleMetadata") if dep.get("id")]
                            dep_text = ", ".join(deps) if deps else "None"
                            xml_cache[xml_path] = {
                                "name": mod_id,
                                "id": mod_id,
                                "raw_version": raw_version,
                                "version": mod_version,
                                "deps": dep_text,
                                "is_native": False,
                                "is_multiplayer": is_multiplayer,
                                "mo2_mod_name": mo2_mod_name,
                                "source_path": xml_path
                            }
                            mod_data.append(xml_cache[xml_path])
                            mod_id_to_data[mod_id] = mod_data[-1]
                            logger.info(f"SubModuleTabWidget: Found enabled MO2 mod {mod_id} (ID: {mod_id}, Raw Version: {raw_version}, Parsed Version: {mod_version}, Multiplayer: {is_multiplayer}, MO2 name: {mo2_mod_name}, Source: {xml_path})")
                        except ET.ParseError as e:
                            logger.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}: {str(e)}")
            
            # Read saved states and order from LauncherData.xml
            launcher_data_path = self._get_launcher_data_path()
            saved_mod_states = {}
            saved_mod_order = []
            if launcher_data_path.exists():
                try:
                    tree = ET.parse(launcher_data_path)
                    root = tree.getroot()
                    mod_datas = root.find(".//SingleplayerData/ModDatas")
                    if mod_datas is not None:
                        for user_mod_data in mod_datas.findall("UserModData"):
                            mod_id = user_mod_data.findtext("Id")
                            is_selected = user_mod_data.findtext("IsSelected", "false").lower() == "true"
                            if mod_id:
                                saved_mod_states[mod_id] = is_selected
                                saved_mod_order.append(mod_id)
                                logger.debug(f"SubModuleTabWidget: Read {mod_id} IsSelected={is_selected} from LauncherData.xml")
                except Exception as e:
                    logger.error(f"SubModuleTabWidget: Failed to read LauncherData.xml: {str(e)}")
            
            for mod_id in ["Sandbox", "Multiplayer"]:
                saved_mod_states[mod_id] = True
                logger.debug(f"SubModuleTabWidget: Forced {mod_id} to IsSelected=true")
            
            # Determine mod order: use saved order on startup, current order otherwise
            sorted_mods = []
            seen_mods = set()
            if not current_order and saved_mod_order:  # On startup, prioritize LauncherData.xml order
                for mod_id in saved_mod_order:
                    if mod_id in mod_id_to_data and mod_id not in seen_mods:
                        sorted_mods.append(mod_id_to_data[mod_id])
                        seen_mods.add(mod_id)
                        logger.debug(f"SubModuleTabWidget: Restored mod {mod_id} from LauncherData.xml order")
            else:  # Within session, prioritize current UI order
                for mod_id in current_order:
                    if mod_id in mod_id_to_data and mod_id not in seen_mods:
                        sorted_mods.append(mod_id_to_data[mod_id])
                        seen_mods.add(mod_id)
                        logger.debug(f"SubModuleTabWidget: Preserved mod {mod_id} in current UI order")
            
            # Add remaining mods: PRIORITY_MODS, DEFAULT_MOD_ORDER, then others
            for mod_id in self.PRIORITY_MODS:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
                    logger.debug(f"SubModuleTabWidget: Added new priority mod {mod_id}")
            
            for mod_id in self.DEFAULT_MOD_ORDER:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
                    logger.debug(f"SubModuleTabWidget: Added new native mod {mod_id}")
            
            for mod in mod_data:
                mod_id = mod["id"]
                if mod_id not in seen_mods:
                    sorted_mods.append(mod)
                    seen_mods.add(mod_id)
                    logger.debug(f"SubModuleTabWidget: Added new mod {mod_id}")
            
            self._mod_list.blockSignals(True)
            self._mod_list.clear()
            for mod in sorted_mods:
                mod_id = mod["id"]
                raw_version = mod["raw_version"]
                mod_version = mod["version"]
                is_multiplayer = mod["is_multiplayer"]
                dep_text = mod["deps"]
                mo2_mod_name = mod.get("mo2_mod_name", "Unknown")
                source_path = mod.get("source_path", "Unknown")
                display_text = f"{mod_id} ({raw_version})"
                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setData(Qt.ItemDataRole.UserRole + 1, is_multiplayer)
                item.setData(Qt.ItemDataRole.UserRole + 2, mod_version)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                mod_state = current_states.get(mod_id, saved_mod_states.get(mod_id, mod_id in self.DEFAULT_MOD_ORDER or mod_id in self.PRIORITY_MODS))
                if mod_id in ["Sandbox", "Multiplayer"]:
                    mod_state = True
                item.setCheckState(Qt.CheckState.Checked if mod_state else Qt.CheckState.Unchecked)
                item.setToolTip(f"ID: {mod_id}\nVersion: {raw_version}\nMultiplayer: {is_multiplayer}\nDependencies: {dep_text}\nSource: {'Game Modules' if mod['is_native'] else f'MO2 Mods ({mo2_mod_name})'}\nPath: {source_path}")
                self._mod_list.addItem(item)
                logger.info(f"SubModuleTabWidget: Added mod {mod_id} (ID: {mod_id}, Raw Version: {raw_version}, Parsed Version: {mod_version}, Multiplayer: {is_multiplayer}, Source: {'Game Modules' if mod['is_native'] else f'MO2 Mods ({mo2_mod_name})'}, State: {mod_state})")
            
            self._mod_list.blockSignals(False)
            self._update_launcher_data()
            logger.info(f"SubModuleTabWidget: Loaded {self._mod_list.count()} mods in {time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to refresh mods: {str(e)}")

    def on_item_changed(self, item):
        try:
            mod_id = item.data(Qt.ItemDataRole.UserRole)
            if not mod_id:
                logger.warning("SubModuleTabWidget: Item has no UserRole data")
                return
            mod_name = item.text().split(" (")[0]
            mod_state = item.checkState() == Qt.CheckState.Checked
            if mod_id in ["Sandbox", "Multiplayer"]:
                mod_state = True
                item.setCheckState(Qt.CheckState.Checked)
                logger.debug(f"SubModuleTabWidget: Forced {mod_id} to checked in UI")
            self._queued_changes[mod_id] = mod_state
            self._debounce_timer.start(int(self._write_cooldown * 1000))
            logger.info(f"SubModuleTabWidget: Queued mod {mod_name} (ID: {mod_id}) {'enabled' if mod_state else 'disabled'}")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to change mod state for {mod_id or 'unknown'}: {str(e)}")

    def on_rows_moved(self, parent, start, end, destination, row):
        try:
            current_order = [self._mod_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._mod_list.count())]
            logger.debug(f"SubModuleTabWidget: New mod order: {current_order}")
            self._update_launcher_data_order()
            logger.info("SubModuleTabWidget: Mod order updated")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to update mod order: {str(e)}")

    def enable_all_mods(self):
        try:
            self._mod_list.blockSignals(True)
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                mod_id = item.data(Qt.ItemDataRole.UserRole)
                item.setCheckState(Qt.CheckState.Checked)
                self._queued_changes[mod_id] = True
                logger.debug(f"SubModuleTabWidget: Enabled mod {mod_id}")
            self._mod_list.blockSignals(False)
            self._debounce_timer.start(int(self._write_cooldown * 1000))
            logger.info("SubModuleTabWidget: Queued enable all mods")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to enable all mods: {str(e)}")

    def disable_all_mods(self):
        try:
            self._mod_list.blockSignals(True)
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                mod_id = item.data(Qt.ItemDataRole.UserRole)
                if mod_id in ["Sandbox", "Multiplayer"]:
                    item.setCheckState(Qt.CheckState.Checked)
                    self._queued_changes[mod_id] = True
                    logger.debug(f"SubModuleTabWidget: Forced {mod_id} to remain enabled")
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
                    self._queued_changes[mod_id] = False
                    logger.debug(f"SubModuleTabWidget: Disabled mod {mod_id}")
            self._mod_list.blockSignals(False)
            self._debounce_timer.start(int(self._write_cooldown * 1000))
            logger.info("SubModuleTabWidget: Queued disable all mods (except Sandbox and Multiplayer)")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to disable all mods: {str(e)}")
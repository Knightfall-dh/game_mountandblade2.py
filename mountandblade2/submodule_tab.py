import os
import shutil
import json
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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    WRITE_COOLDOWN = 0.5

    def __init__(self, parent: QWidget | None, organizer: mobase.IOrganizer):
        super().__init__(parent)
        logger.debug("SubModuleTabWidget: Initializing")
        self._organizer = organizer
        self._xml_cache = {}
        self._xml_cache_timestamps = {}
        self._dependency_cache = {}
        self._last_modlist_mtime = 0  # Track modlist.txt timestamp
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
        self._write_cooldown = self.WRITE_COOLDOWN
        self._queued_changes = {}
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._process_queued_changes)
        
        logger.debug("SubModuleTabWidget: Initialization complete")
        self.refresh_mods()
        
    def get_enabled_load_order(self) -> list[str]:
        """Return the list of enabled mod IDs in their current order."""
        try:
            logger.debug("SubModuleTabWidget: Retrieving enabled load order")
            load_order = []
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                if item and item.checkState() == Qt.CheckState.Checked:
                    mod_id = item.data(Qt.ItemDataRole.UserRole)
                    if mod_id:
                        load_order.append(mod_id)
            logger.debug(f"SubModuleTabWidget: Enabled load order: {load_order}")
            # Debug: Write load order to a file
            with open(Path(self._organizer.profilePath()) / "load_order_debug.txt", "w") as f:
                f.write(str(load_order))
            return load_order
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to retrieve enabled load order: {str(e)}")
            return []
            
    def _check_modlist_changed(self) -> bool:
        """Check if modlist.txt has changed since last refresh/sort."""
        try:
            modlist_path = Path(self._organizer.profilePath()) / "modlist.txt"
            if modlist_path.exists():
                current_mtime = modlist_path.stat().st_mtime
                if current_mtime != self._last_modlist_mtime:
                    logger.debug("SubModuleTabWidget: Detected modlist.txt change")
                    self._last_modlist_mtime = current_mtime
                    return True
            return False
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to check modlist.txt: {str(e)}")
            return False

    def _get_launcher_data_path(self) -> Path:
        try:
            profile_path = Path(self._organizer.profilePath()) / "LauncherData.xml"
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
                logger.debug(f"SubModuleTabWidget: Synced LauncherData.xml to {default_path}")
            else:
                logger.warning(f"SubModuleTabWidget: Profile LauncherData.xml not found at {profile_path}")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to sync LauncherData.xml: {str(e)}")

    def _get_enabled_mods(self) -> tuple[list[str], list[str]]:
        try:
            modlist_path = Path(self._organizer.profilePath()) / "modlist.txt"
            enabled_mods = []
            disabled_mods = []
            if modlist_path.exists():
                with modlist_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("+"):
                            mod_name = line[1:]
                            if not mod_name.endswith("_separator"):
                                enabled_mods.append(mod_name)
                        elif line.startswith("-"):
                            mod_name = line[1:]
                            if not mod_name.endswith("_separator"):
                                disabled_mods.append(mod_name)
            return enabled_mods, disabled_mods
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to read modlist.txt: {str(e)}")
            return [], []

    def _load_mod_id_map(self) -> Dict[str, str]:
        try:
            map_path = Path(self._organizer.profilePath()) / "mod_id_map.json"
            if map_path.exists():
                with map_path.open("r", encoding="utf-8") as f:
                    mod_id_map = json.load(f)
                if not isinstance(mod_id_map, dict):
                    logger.warning("SubModuleTabWidget: mod_id_map.json is not a valid dictionary")
                    return {}
                return mod_id_map
            return {}
        except Exception as e:
            logger.warning(f"SubModuleTabWidget: Failed to load mod_id_map.json: {str(e)}")
            return {}

    def _get_highest_priority_submodule_xml(self, mod_id: str, enabled_mods: list[str], enabled_mod_paths: dict[str, Path], modules_path: Path, disabled_mods: list[str]) -> tuple[Path | None, str | None]:
        try:
            overwrite_path = Path(self._organizer.overwritePath()) / "Modules" / mod_id / "SubModule.xml"
            if overwrite_path.exists():
                return overwrite_path, None
            for mo2_mod_name in reversed(enabled_mods):
                mod_path = enabled_mod_paths[mo2_mod_name] / "Modules" / mod_id / "SubModule.xml"
                if mod_path.exists():
                    return mod_path, mo2_mod_name
            game_mod_path = modules_path / mod_id / "SubModule.xml"
            if game_mod_path.exists():
                return game_mod_path, None
            return None, None
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to find SubModule.xml for {mod_id}: {str(e)}")
            return None, None

    def _parse_xml(self, xml_path: Path, mod_id: str, mo2_mod_name: str | None = None, is_native: bool = False) -> Dict | None:
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            mod_id = root.find("Id").get("value").strip() if root.find("Id") is not None else mod_id
            version_elem = root.find("Version")
            raw_version = version_elem.get("value").strip() if version_elem is not None and version_elem.get("value") else (version_elem.text.strip() if version_elem is not None and version_elem.text else "v1.0.0.0")
            mod_version = self._parse_version(raw_version, mod_id)
            multiplayer_elem = root.find("MultiplayerModule")
            is_multiplayer = multiplayer_elem is not None and multiplayer_elem.get("value").strip() == "true"
            category_elem = root.find("ModuleCategory")
            is_multiplayer |= category_elem is not None and category_elem.get("value").strip() == "Multiplayer"
            deps = [f"{dep.get('id')} ({dep.get('version', '*')})" for dep in root.findall(".//DependedModuleMetadata") if dep.get("id")]
            dep_text = ", ".join(deps) if deps else "None"
            return {
                "id": mod_id,
                "raw_version": raw_version,
                "version": mod_version,
                "is_multiplayer": is_multiplayer,
                "deps": dep_text,
                "is_native": is_native,
                "mo2_mod_name": mo2_mod_name,
                "source_path": xml_path
            }
        except ET.ParseError as e:
            logger.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}: {str(e)}")
            return None

    def _indent_xml(self, elem, level=0):
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
        try:
            backup_files = sorted(
                launcher_data_path.parent.glob("LauncherData.xml.bak.*"),
                key=lambda x: x.stat().st_mtime
            )
            while len(backup_files) >= self.MAX_BACKUPS:
                oldest_backup = backup_files.pop(0)
                oldest_backup.unlink()
                logger.debug(f"SubModuleTabWidget: Removed oldest backup {oldest_backup}")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to manage backups: {str(e)}")

    def _process_queued_changes(self):
        if not self._queued_changes:
            return
        try:
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
            return
        try:
            launcher_data_path = self._get_launcher_data_path()
            try:
                tree = ET.parse(launcher_data_path)
                root = tree.getroot()
            except (FileNotFoundError, ET.ParseError):
                root = ET.Element("UserData")
                root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
                root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
                tree = ET.ElementTree(root)
            
            singleplayer_data = root.find("SingleplayerData") or ET.SubElement(root, "SingleplayerData")
            singleplayer_mods = singleplayer_data.find("ModDatas") or ET.SubElement(singleplayer_data, "ModDatas")
            multiplayer_data = root.find("MultiplayerData") or ET.SubElement(root, "MultiplayerData")
            multiplayer_mods = multiplayer_data.find("ModDatas") or ET.SubElement(multiplayer_data, "ModDatas")
            
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
                
                if mod_id in ["Native", "Multiplayer"] or mod_multiplayer.get(mod_id, False):
                    mod_data = ET.SubElement(multiplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "v1.0.0.0")
                    ET.SubElement(mod_data, "IsSelected").text = "true"
            
            if root.find("GameType") is None:
                ET.SubElement(root, "GameType").text = "Singleplayer"
            
            self._indent_xml(root)
            if launcher_data_path.exists():
                self._manage_backups(launcher_data_path)
                backup_path = launcher_data_path.with_name(f"LauncherData.xml.bak.{datetime.now().strftime('%Y%m%dT%H%M%S')}")
                shutil.copy(launcher_data_path, backup_path)
            launcher_data_path.parent.mkdir(parents=True, exist_ok=True)
            tree.write(str(launcher_data_path), encoding="utf-8", xml_declaration=True)
            self._last_xml_write = time()
            self._sync_launcher_data_to_default()
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to update LauncherData.xml: {str(e)}")

    def _update_launcher_data_order(self):
        try:
            launcher_data_path = self._get_launcher_data_path()
            try:
                tree = ET.parse(launcher_data_path)
                root = tree.getroot()
            except (FileNotFoundError, ET.ParseError):
                root = ET.Element("UserData")
                root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
                root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
                tree = ET.ElementTree(root)
            
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
                
                if mod_id in ["Native", "Multiplayer"] or mod_multiplayer.get(mod_id, False):
                    mod_data = ET.SubElement(multiplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "v1.0.0.0")
                    ET.SubElement(mod_data, "IsSelected").text = "true"
            
            for tag, element in non_mod_tags.items():
                new_elem = ET.SubElement(root, tag)
                new_elem.text = element.text
                new_elem.attrib.update(element.attrib)
            
            ET.SubElement(root, "GameType").text = "Singleplayer"
            self._indent_xml(root)
            if launcher_data_path.exists():
                self._manage_backups(launcher_data_path)
                backup_path = launcher_data_path.with_name(f"LauncherData.xml.bak.{datetime.now().strftime('%Y%m%dT%H%M%S')}")
                shutil.copy(launcher_data_path, backup_path)
            launcher_data_path.parent.mkdir(parents=True, exist_ok=True)
            tree.write(str(launcher_data_path), encoding="utf-8", xml_declaration=True)
            self._last_xml_write = time()
            self._sync_launcher_data_to_default()
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to update LauncherData.xml order: {str(e)}")

    def _parse_version(self, version_text: str | None, mod_id: str | None = None) -> str:
        if not version_text:
            logger.warning(f"SubModuleTabWidget: Empty version for {mod_id or 'unknown'}, defaulting to v1.0.0.0")
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
        logger.warning(f"SubModuleTabWidget: Invalid version '{version_text}' for {mod_id or 'unknown'}, defaulting to v1.0.0.0")
        return "v1.0.0.0"

    def _compare_versions(self, mod_version: str, dep_version: str, mod_id: str, dep_id: str) -> bool:
        try:
            # Handle wildcard version
            if dep_version.strip().endswith(".*") or dep_version.strip() == "*":
                logger.debug(
                    f"SubModuleTabWidget: Wildcard version for {mod_id} vs {dep_id} ({dep_version}), assuming compatible")
                return True

            # Parse version strings
            mod_parts = [int(x) for x in mod_version.lstrip("ve").split(".")]
            dep_parts = [int(x) for x in dep_version.lstrip("ve").split(".")]

            # Normalize version parts to 4 components
            mod_parts += [0] * (4 - len(mod_parts))
            dep_parts += [0] * (4 - len(dep_parts))

            # Compare version components
            for m, d in zip(mod_parts, dep_parts):
                if m < d:
                    return False
                if m > d:
                    return True
            return True
        except (ValueError, AttributeError):
            # Log only if the version format is unexpected and not a wildcard
            logger.debug(
                f"SubModuleTabWidget: Could not compare versions for {mod_id} ({mod_version}) vs {dep_id} ({dep_version}), assuming compatible")
            return True

    def _build_dependency_graph(self, mod_data: List[Dict], enabled_mods: list[str], disabled_mods: list[str]) -> Tuple[Dict[str, List[Tuple[str, str, bool, str]]], List[str]]:
        cache_key = tuple(sorted([mod["id"] for mod in mod_data]))
        if cache_key in self._dependency_cache:
            return self._dependency_cache[cache_key]
        
        dependencies = {}
        issues = []
        mod_id_to_version = {mod["id"]: mod["version"] for mod in mod_data}
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
                    version_req = dep.get("version", "*")
                    if dep_id:
                        if incompatible:
                            if dep_id in mod_id_to_version:
                                issues.append(f"Mod {mod_id} is incompatible with {dep_id}")
                            continue
                        if dep_id not in mod_id_to_version and not optional:
                            if dep_id in disabled_mods:
                                issues.append(f"Mod {mod_id} requires {dep_id}, which is disabled in modlist.txt")
                            else:
                                issues.append(f"Mod {mod_id} requires missing mod {dep_id}")
                        elif dep_id in mod_id_to_version and version_req != "*":
                            if not self._compare_versions(mod_id_to_version[dep_id], version_req, dep_id, mod_id):
                                issues.append(f"Mod {mod_id} requires {dep_id} version {version_req}, but {mod_id_to_version[dep_id]} is installed")
                        dependencies[mod_id].append((dep_id, order, optional, version_req))
            except ET.ParseError as e:
                issues.append(f"Failed to parse SubModule.xml for {mod_id}: {str(e)}")
        for mod_id in self.PRIORITY_MODS:
            if mod_id in dependencies:
                for native_mod in self.DEFAULT_MOD_ORDER:
                    if native_mod in mod_id_to_version and (native_mod, "LoadBeforeThis", False, "*") not in dependencies[mod_id]:
                        dependencies[mod_id].append((native_mod, "LoadBeforeThis", False, "*"))
        self._dependency_cache[cache_key] = (dependencies, issues)
        return dependencies, issues

    def _topological_sort(self, dependencies: Dict[str, List[Tuple[str, str, bool, str]]], mod_data: List[Dict], mod_id_to_data: Dict[str, Dict], changed_mods: Set[str] = None) -> List[Dict]:
        if not changed_mods:
            changed_mods = set(mod_id_to_data.keys())
        
        def dfs(mod_id: str, visited: Set[str], temp_mark: Set[str], result: List[str]):
            if mod_id in temp_mark:
                raise ValueError(f"Circular dependency detected involving {mod_id}")
            if mod_id not in visited and mod_id in changed_mods:
                temp_mark.add(mod_id)
                for dep_id, order, optional, _ in dependencies.get(mod_id, []):
                    if order == "LoadAfterThis" and dep_id in mod_id_to_data and not optional:
                        dfs(dep_id, visited, temp_mark, result)
                    elif order == "LoadBeforeThis" and dep_id in mod_id_to_data and not optional:
                        if dep_id not in visited:
                            dfs(dep_id, visited, temp_mark, result)
                temp_mark.remove(mod_id)
                visited.add(mod_id)
                result.append(mod_id)
        
        visited = set()
        temp_mark = set()
        result = []
        
        for mod_id in self.PRIORITY_MODS:
            if mod_id in mod_id_to_data and mod_id not in visited:
                dfs(mod_id, visited, temp_mark, result)
        
        for mod_id in self.DEFAULT_MOD_ORDER:
            if mod_id in mod_id_to_data and mod_id not in visited:
                dfs(mod_id, visited, temp_mark, result)
        
        for mod in mod_data:
            mod_id = mod["id"]
            if mod_id not in visited:
                dfs(mod_id, visited, temp_mark, result)
        
        sorted_mods = [mod_id_to_data[mod_id] for mod_id in result if mod_id in mod_id_to_data]
        return sorted_mods

    def _map_modlist_to_submodules(self, enabled_mods: List[str], mod_data: List[Dict], mod_id_map: Dict[str, str]) -> List[str]:
        mod_id_to_mo2_name = {mod["id"]: mod.get("mo2_mod_name") for mod in mod_data if mod.get("mo2_mod_name")}
        mo2_name_to_mod_id = {v: k for k, v in mod_id_map.items()}
        sorted_mod_ids = []
        unmapped_mods = []
        
        for mo2_mod_name in reversed(enabled_mods):
            mod_id = mo2_name_to_mod_id.get(mo2_mod_name, next((k for k, v in mod_id_to_mo2_name.items() if v == mo2_mod_name), None))
            if mod_id and mod_id not in sorted_mod_ids:
                sorted_mod_ids.append(mod_id)
            elif not mod_id:
                unmapped_mods.append(mo2_mod_name)
        
        if unmapped_mods:
            logger.warning(f"SubModuleTabWidget: Unmapped mods in modlist.txt: {unmapped_mods}")
        
        for mod_id in self.PRIORITY_MODS:
            if mod_id in mod_id_to_mo2_name and mod_id not in sorted_mod_ids:
                sorted_mod_ids.insert(0, mod_id)
        for mod_id in self.DEFAULT_MOD_ORDER:
            if mod_id not in sorted_mod_ids:
                sorted_mod_ids.append(mod_id)
        for mod in mod_data:
            mod_id = mod["id"]
            if mod_id not in sorted_mod_ids:
                sorted_mod_ids.append(mod_id)
        return sorted_mod_ids

    def sort_mods(self):
        try:
            logger.info("SubModuleTabWidget: Starting sort_mods")
            start_time = time()
            
            if self._check_modlist_changed():
                self._xml_cache.clear()
                self._xml_cache_timestamps.clear()
                self._dependency_cache.clear()
            
            enabled_mods, disabled_mods = self._get_enabled_mods()
            mod_id_map = self._load_mod_id_map()
            mo2_mods_path = Path(self._organizer.modsPath())
            modules_path = Path(self._organizer.managedGame().gameDirectory().absolutePath()) / "Modules"
            enabled_mod_paths = {mo2_mod_name: mo2_mods_path / mo2_mod_name for mo2_mod_name in enabled_mods}
            
            modlist_path = Path(self._organizer.profilePath()) / "modlist.txt"
            modlist_mtime = modlist_path.stat().st_mtime if modlist_path.exists() else 0
            changed_mods = set()
            for xml_path in list(self._xml_cache.keys()):
                if not xml_path.exists() or xml_path.stat().st_mtime > self._xml_cache_timestamps.get(xml_path, 0):
                    changed_mods.add(self._xml_cache[xml_path]["id"])
                    del self._xml_cache[xml_path]
                    del self._xml_cache_timestamps[xml_path]
            
            mod_data = []
            mod_id_to_data = {}
            
            def process_mod_dir(mod_dir: Path, is_native: bool):
                mod_id = mod_dir.name
                xml_path, mo2_mod_name = self._get_highest_priority_submodule_xml(mod_id, enabled_mods, enabled_mod_paths, modules_path, disabled_mods)
                if xml_path and xml_path.exists() and xml_path not in self._xml_cache:
                    data = self._parse_xml(xml_path, mod_id, None if is_native else mo2_mod_name, is_native)
                    if data:
                        self._xml_cache[xml_path] = data
                        self._xml_cache_timestamps[xml_path] = xml_path.stat().st_mtime
                        return data
                return None

            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_mod = {}
                if modules_path.exists():
                    for mod_dir in modules_path.iterdir():
                        if mod_dir.is_dir():
                            future_to_mod[executor.submit(process_mod_dir, mod_dir, True)] = mod_dir.name
                
                if mo2_mods_path.exists():
                    for mo2_mod_name in enabled_mods:
                        mod_path = enabled_mod_paths[mo2_mod_name]
                        for xml_path in mod_path.glob("**/SubModule.xml"):
                            if xml_path in self._xml_cache:
                                continue
                            xml_priority_path, xml_mo2_mod_name = self._get_highest_priority_submodule_xml(
                                xml_path.parent.name, enabled_mods, enabled_mod_paths, modules_path, disabled_mods)
                            if xml_priority_path and xml_priority_path != xml_path:
                                continue
                            future_to_mod[executor.submit(self._parse_xml, xml_path, xml_path.parent.name, mo2_mod_name, False)] = xml_path.parent.name
                
                for future in as_completed(future_to_mod):
                    data = future.result()
                    if data:
                        mod_data.append(data)
                        mod_id_to_data[data["id"]] = data
                        if data["id"] not in changed_mods:
                            changed_mods.add(data["id"])
            
            for xml_path, data in self._xml_cache.items():
                if xml_path not in [mod["source_path"] for mod in mod_data]:
                    mod_data.append(data)
                    mod_id_to_data[data["id"]] = data
                    changed_mods.add(data["id"])
            
            dependencies, issues = self._build_dependency_graph(mod_data, enabled_mods, disabled_mods)
            if issues:
                logger.warning(f"SubModuleTabWidget: Compatibility issues detected: {issues}")
            
            try:
                sorted_mods = self._topological_sort(dependencies, mod_data, mod_id_to_data, changed_mods)
            except ValueError as e:
                logger.error(f"SubModuleTabWidget: Sort failed: {str(e)}")
                QMessageBox.critical(self, "Sort Error", f"Failed to sort mods: {str(e)}")
                return
            
            modlist_order = self._map_modlist_to_submodules(enabled_mods, mod_data, mod_id_map)
            if modlist_order:
                final_mods = []
                seen = set()
                for mod_id in self.PRIORITY_MODS:
                    if mod_id in mod_id_to_data and mod_id not in seen:
                        final_mods.append(mod_id_to_data[mod_id])
                        seen.add(mod_id)
                for mod_id in self.DEFAULT_MOD_ORDER:
                    if mod_id in mod_id_to_data and mod_id not in seen:
                        final_mods.append(mod_id_to_data[mod_id])
                        seen.add(mod_id)
                for mod_id in modlist_order:
                    if mod_id in mod_id_to_data and mod_id not in seen and mod_id not in self.PRIORITY_MODS and mod_id not in self.DEFAULT_MOD_ORDER:
                        final_mods.append(mod_id_to_data[mod_id])
                        seen.add(mod_id)
                for mod in sorted_mods:
                    if mod["id"] not in seen:
                        final_mods.append(mod)
                        seen.add(mod["id"])
                sorted_mods = final_mods
            
            self._mod_list.blockSignals(True)
            current_states = {self._mod_list.item(i).data(Qt.ItemDataRole.UserRole): self._mod_list.item(i).checkState() == Qt.CheckState.Checked for i in range(self._mod_list.count()) if self._mod_list.item(i)}
            current_order = [self._mod_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._mod_list.count()) if self._mod_list.item(i)]
            new_order = [mod["id"] for mod in sorted_mods]
            
            if current_order != new_order:
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
                    mod_state = current_states.get(mod_id, mod_id in self.DEFAULT_MOD_ORDER or mod_id in self.PRIORITY_MODS)
                    if mod_id in ["Sandbox", "Multiplayer"]:
                        mod_state = True
                    item.setCheckState(Qt.CheckState.Checked if mod_state else Qt.CheckState.Unchecked)
                    item.setToolTip(f"ID: {mod_id}\nVersion: {raw_version}\nMultiplayer: {is_multiplayer}\nDependencies: {dep_text}\nSource: {'Game Modules' if mod['is_native'] else f'MO2 Mods ({mo2_mod_name})'}\nPath: {source_path}")
                    self._mod_list.addItem(item)
            else:
                for i, mod in enumerate(sorted_mods):
                    mod_id = mod["id"]
                    item = self._mod_list.item(i)
                    if item and item.data(Qt.ItemDataRole.UserRole) == mod_id:
                        mod_state = current_states.get(mod_id, mod_id in self.DEFAULT_MOD_ORDER or mod_id in self.PRIORITY_MODS)
                        if mod_id in ["Sandbox", "Multiplayer"]:
                            mod_state = True
                        item.setCheckState(Qt.CheckState.Checked if mod_state else Qt.CheckState.Unchecked)
            
            self._mod_list.blockSignals(False)
            self._update_launcher_data_order()
            
            load_order_summary = "\n".join([f"{i+1}. {mod['id']} ({'Enabled' if mod['id'] in self.DEFAULT_MOD_ORDER or mod['id'] in self.PRIORITY_MODS or current_states.get(mod['id'], False) else 'Disabled'})" for i, mod in enumerate(sorted_mods[:10])])
            if len(sorted_mods) > 10:
                load_order_summary += f"\n... and {len(sorted_mods) - 10} more mods"
            QMessageBox.information(self, "Sort Complete", f"Mods sorted successfully:\n{load_order_summary}")
            
            self._last_modlist_mtime = modlist_path.stat().st_mtime if modlist_path.exists() else 0
            logger.info(f"SubModuleTabWidget: Sorted {len(sorted_mods)} mods in {time() - start_time:.2f} seconds")
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
            
            if self._check_modlist_changed():
                self._xml_cache.clear()
                self._xml_cache_timestamps.clear()
                self._dependency_cache.clear()
            
            current_order = [self._mod_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._mod_list.count()) if self._mod_list.item(i)]
            current_states = {self._mod_list.item(i).data(Qt.ItemDataRole.UserRole): self._mod_list.item(i).checkState() == Qt.CheckState.Checked for i in range(self._mod_list.count()) if self._mod_list.item(i)}
            
            enabled_mods, disabled_mods = self._get_enabled_mods()
            mod_id_map = self._load_mod_id_map()
            mo2_mods_path = Path(self._organizer.modsPath())
            modules_path = Path(game.gameDirectory().absolutePath()) / "Modules"
            enabled_mod_paths = {mo2_mod_name: mo2_mods_path / mo2_mod_name for mo2_mod_name in enabled_mods}
            
            modlist_path = Path(self._organizer.profilePath()) / "modlist.txt"
            modlist_mtime = modlist_path.stat().st_mtime if modlist_path.exists() else 0
            for xml_path in list(self._xml_cache.keys()):
                if not xml_path.exists() or xml_path.stat().st_mtime > self._xml_cache_timestamps.get(xml_path, 0):
                    del self._xml_cache[xml_path]
                    del self._xml_cache_timestamps[xml_path]
            
            mod_data = []
            mod_id_to_data = {}
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_mod = {}
                if modules_path.exists():
                    for mod_dir in modules_path.iterdir():
                        if mod_dir.is_dir():
                            future_to_mod[executor.submit(self._parse_xml, mod_dir / "SubModule.xml", mod_dir.name, None, True)] = mod_dir.name
                
                if mo2_mods_path.exists():
                    for mo2_mod_name in enabled_mods:
                        mod_path = enabled_mod_paths[mo2_mod_name]
                        for xml_path in mod_path.glob("**/SubModule.xml"):
                            if xml_path in self._xml_cache:
                                continue
                            xml_priority_path, xml_mo2_mod_name = self._get_highest_priority_submodule_xml(
                                xml_path.parent.name, enabled_mods, enabled_mod_paths, modules_path, disabled_mods)
                            if xml_priority_path and xml_priority_path != xml_path:
                                continue
                            future_to_mod[executor.submit(self._parse_xml, xml_path, xml_path.parent.name, mo2_mod_name, False)] = xml_path.parent.name
                
                for future in as_completed(future_to_mod):
                    data = future.result()
                    if data:
                        mod_data.append(data)
                        mod_id_to_data[data["id"]] = data
                        self._xml_cache[data["source_path"]] = data
                        self._xml_cache_timestamps[data["source_path"]] = data["source_path"].stat().st_mtime
            
            for xml_path, data in self._xml_cache.items():
                if xml_path not in [mod["source_path"] for mod in mod_data]:
                    mod_data.append(data)
                    mod_id_to_data[data["id"]] = data
            
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
                except Exception as e:
                    logger.error(f"SubModuleTabWidget: Failed to read LauncherData.xml: {str(e)}")
            
            for mod_id in ["Sandbox", "Multiplayer"]:
                saved_mod_states[mod_id] = True
            
            sorted_mods = []
            seen_mods = set()
            if not current_order and saved_mod_order:
                for mod_id in saved_mod_order:
                    if mod_id in mod_id_to_data and mod_id not in seen_mods:
                        sorted_mods.append(mod_id_to_data[mod_id])
                        seen_mods.add(mod_id)
            else:
                for mod_id in current_order:
                    if mod_id in mod_id_to_data and mod_id not in seen_mods:
                        sorted_mods.append(mod_id_to_data[mod_id])
                        seen_mods.add(mod_id)
            
            for mod_id in self.PRIORITY_MODS:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
            
            for mod_id in self.DEFAULT_MOD_ORDER:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
            
            for mod in mod_data:
                mod_id = mod["id"]
                if mod_id not in seen_mods:
                    sorted_mods.append(mod)
                    seen_mods.add(mod_id)
            
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
            
            self._mod_list.blockSignals(False)
            self._update_launcher_data()
            self._last_modlist_mtime = modlist_mtime
            logger.info(f"SubModuleTabWidget: Loaded {len(sorted_mods)} mods in {time() - start_time:.2f} seconds")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to refresh mods: {str(e)}")

    def on_item_changed(self, item):
        try:
            mod_id = item.data(Qt.ItemDataRole.UserRole)
            if not mod_id:
                return
            mod_state = item.checkState() == Qt.CheckState.Checked
            if mod_id in ["Sandbox", "Multiplayer"]:
                mod_state = True
                item.setCheckState(Qt.CheckState.Checked)
            self._queued_changes[mod_id] = mod_state
            self._debounce_timer.start(int(self._write_cooldown * 1000))
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to change mod state for {mod_id or 'unknown'}: {str(e)}")

    def on_rows_moved(self, parent, start, end, destination, row):
        try:
            current_order = [self._mod_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._mod_list.count())]
            self._update_launcher_data_order()
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
            self._mod_list.blockSignals(False)
            self._debounce_timer.start(int(self._write_cooldown * 1000))
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
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
                    self._queued_changes[mod_id] = False
            self._mod_list.blockSignals(False)
            self._debounce_timer.start(int(self._write_cooldown * 1000))
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to disable all mods: {str(e)}")
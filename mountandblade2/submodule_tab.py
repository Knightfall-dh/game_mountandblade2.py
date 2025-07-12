import os
import shutil
from datetime import datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from PyQt6.QtCore import QDir, QStandardPaths, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QAbstractItemView, QListWidgetItem
import mobase
import logging
from time import time

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
        logger.info("SubModuleTabWidget: Initialization complete")
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

    def _update_launcher_data(self, changed_mod: str | None = None, changed_state: bool | None = None):
        if time() - self._last_xml_write < self._write_cooldown:
            logger.debug("SubModuleTabWidget: Skipping LauncherData.xml write due to cooldown")
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
            
            unverified_mods = root.find("UnverifiedModDatas")
            if unverified_mods is None:
                unverified_mods = ET.SubElement(root, "UnverifiedModDatas")
            
            singleplayer_mods.clear()
            multiplayer_mods.clear()
            unverified_mods.clear()
            
            mod_versions = {}
            mod_states = {}
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                if item:
                    mod_id = item.data(Qt.ItemDataRole.UserRole)
                    version = item.text().split("(v")[1].rstrip(")") if "(v" in item.text() else "1.2.12"
                    version = version.lstrip("v")
                    mod_versions[mod_id] = version
                    # Use UI check state directly
                    mod_states[mod_id] = item.checkState() == Qt.CheckState.Checked
                    # Force specific mods to be enabled
                    if mod_id in ["Sandbox", "Multiplayer"]:
                        mod_states[mod_id] = True
                        item.setCheckState(Qt.CheckState.Checked)
                    # Update state if this is the changed mod
                    if changed_mod == mod_id and changed_state is not None:
                        mod_states[mod_id] = changed_state
            
            for i in range(self._mod_list.count()):
                mod_id = self._mod_list.item(i).data(Qt.ItemDataRole.UserRole)
                if mod_id != "Multiplayer":
                    mod_data = ET.SubElement(singleplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "1.2.12")
                    ET.SubElement(mod_data, "IsSelected").text = str(mod_states.get(mod_id, False)).lower()
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to SingleplayerData, IsSelected={mod_states.get(mod_id, False)}")
                
                if mod_id in ["Native", "Multiplayer", "Bannerlord.Harmony"]:
                    mod_data = ET.SubElement(multiplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "1.2.12")
                    ET.SubElement(mod_data, "IsSelected").text = "true"
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to MultiplayerData")
            
            for mod_id in mod_states:
                if mod_id not in self.DEFAULT_MOD_ORDER and mod_id != "Bannerlord.Harmony":
                    mod_data = ET.SubElement(unverified_mods, "UnverifiedModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "Unknown")
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to UnverifiedModDatas")
            
            if not root.find("DLLCheckData"):
                dll_check_data = ET.SubElement(root, "DLLCheckData")
                dll_data = ET.SubElement(dll_check_data, "DLLData")
                for mod_id in ["Bannerlord.ButterLib", "Bannerlord.Harmony", "Bannerlord.MBOptionScreen", "Bannerlord.UIExtenderEx", "RBM"]:
                    if mod_id in mod_states:
                        dll_check = ET.SubElement(dll_data, "DLLCheckData")
                        dll_name = f"{mod_id}.dll".replace("Bannerlord.", "")
                        if mod_id == "Bannerlord.MBOptionScreen":
                            dll_name = "MCMv5.dll"
                        ET.SubElement(dll_check, "DLLName").text = dll_name
                        ET.SubElement(dll_check, "DLLVerifyInformation")
                        ET.SubElement(dll_check, "LatestSizeInBytes").text = "0"
                        ET.SubElement(dll_check, "IsDangerous").text = "true"
                        logger.debug(f"SubModuleTabWidget: Added {dll_name} to DLLCheckData")
            
            if not root.find("GameType"):
                ET.SubElement(root, "GameType").text = "Singleplayer"
            
            self._indent_xml(root)
            if launcher_data_path.exists():
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
            
            non_mod_tags = {elem.tag: ET.Element(elem.tag, elem.attrib) for elem in root if elem.tag not in ("SingleplayerData", "MultiplayerData", "DLLCheckData", "UnverifiedModDatas")}
            for elem in root:
                if elem.tag in non_mod_tags:
                    non_mod_tags[elem.tag].text = elem.text
            if "GameType" not in non_mod_tags:
                non_mod_tags["GameType"] = ET.Element("GameType")
                non_mod_tags["GameType"].text = "Singleplayer"
            
            root.clear()
            root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
            root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
            
            singleplayer_data = ET.SubElement(root, "SingleplayerData")
            singleplayer_mods = ET.SubElement(singleplayer_data, "ModDatas")
            multiplayer_data = ET.SubElement(root, "MultiplayerData")
            multiplayer_mods = ET.SubElement(multiplayer_data, "ModDatas")
            unverified_mods = ET.SubElement(root, "UnverifiedModDatas")
            dll_check_data = ET.SubElement(root, "DLLCheckData")
            dll_data = ET.SubElement(dll_check_data, "DLLData")
            
            mod_versions = {}
            mod_states = {}
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                if item:
                    mod_id = item.data(Qt.ItemDataRole.UserRole)
                    version = item.text().split("(v")[1].rstrip(")") if "(v" in item.text() else "1.2.12"
                    version = version.lstrip("v")
                    mod_versions[mod_id] = version
                    mod_states[mod_id] = item.checkState() == Qt.CheckState.Checked
                    if mod_id in ["Sandbox", "Multiplayer"]:
                        mod_states[mod_id] = True
                        item.setCheckState(Qt.CheckState.Checked)
            
            for i in range(self._mod_list.count()):
                mod_id = self._mod_list.item(i).data(Qt.ItemDataRole.UserRole)
                if mod_id != "Multiplayer":
                    mod_data = ET.SubElement(singleplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "1.2.12")
                    ET.SubElement(mod_data, "IsSelected").text = str(mod_states.get(mod_id, False)).lower()
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to SingleplayerData, IsSelected={mod_states.get(mod_id, False)}")
                
                if mod_id in ["Native", "Multiplayer", "Bannerlord.Harmony"]:
                    mod_data = ET.SubElement(multiplayer_mods, "UserModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "1.2.12")
                    ET.SubElement(mod_data, "IsSelected").text = "true"
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to MultiplayerData")
            
            for mod_id in mod_states:
                if mod_id not in self.DEFAULT_MOD_ORDER and mod_id != "Bannerlord.Harmony":
                    mod_data = ET.SubElement(unverified_mods, "UnverifiedModData")
                    ET.SubElement(mod_data, "Id").text = mod_id
                    ET.SubElement(mod_data, "LastKnownVersion").text = mod_versions.get(mod_id, "Unknown")
                    logger.debug(f"SubModuleTabWidget: Added {mod_id} to UnverifiedModDatas")
            
            for mod_id in ["Bannerlord.ButterLib", "Bannerlord.Harmony", "Bannerlord.MBOptionScreen", "Bannerlord.UIExtenderEx", "RBM"]:
                if mod_id in mod_states:
                    dll_check = ET.SubElement(dll_data, "DLLCheckData")
                    dll_name = f"{mod_id}.dll".replace("Bannerlord.", "")
                    if mod_id == "Bannerlord.MBOptionScreen":
                        dll_name = "MCMv5.dll"
                    ET.SubElement(dll_check, "DLLName").text = dll_name
                    ET.SubElement(dll_check, "DLLVerifyInformation")
                    ET.SubElement(dll_check, "LatestSizeInBytes").text = "0"
                    ET.SubElement(dll_check, "IsDangerous").text = "true"
                    logger.debug(f"SubModuleTabWidget: Added {dll_name} to DLLCheckData")
            
            for tag, element in non_mod_tags.items():
                new_elem = ET.SubElement(root, tag)
                new_elem.text = element.text
                new_elem.attrib.update(element.attrib)
                logger.debug(f"SubModuleTabWidget: Restored non-mod tag {tag}")
            
            self._indent_xml(root)
            if launcher_data_path.exists():
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

    def refresh_mods(self):
        try:
            logger.info("SubModuleTabWidget: Starting refresh_mods")
            game = self._organizer.managedGame()
            if not game:
                logger.error("SubModuleTabWidget: No managed game found")
                return
            
            # Store current order and states
            current_order = [self._mod_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._mod_list.count()) if self._mod_list.item(i)]
            current_states = {self._mod_list.item(i).data(Qt.ItemDataRole.UserRole): self._mod_list.item(i).checkState() == Qt.CheckState.Checked for i in range(self._mod_list.count()) if self._mod_list.item(i)}
            logger.debug(f"SubModuleTabWidget: Saved current order: {current_order}, states: {current_states}")
            
            # Get enabled mods from modlist.txt in order
            enabled_mods = self._get_enabled_mods()
            
            modules_path = Path(game.gameDirectory().absolutePath()) / "Modules"
            mod_data = []
            mod_id_to_data = {}
            logger.debug(f"SubModuleTabWidget: Scanning game Modules directory: {modules_path}")
            if modules_path.exists():
                for mod_dir in modules_path.iterdir():
                    if mod_dir.is_dir():
                        xml_path = mod_dir / "SubModule.xml"
                        if xml_path.exists():
                            try:
                                tree = ET.parse(xml_path)
                                root = tree.getroot()
                                mod_name = root.findtext("Name") or mod_dir.name
                                mod_id = root.findtext("Id") or mod_dir.name
                                version_elem = root.find("Version")
                                mod_version = version_elem.get("value") if version_elem is not None and version_elem.get("value") else (version_elem.text if version_elem is not None else "1.2.12")
                                mod_version = mod_version.strip().lstrip("ve")
                                deps = [f"{dep.get('id')} ({dep.get('version', '*')})" for dep in root.findall(".//DependedModuleMetadata") if dep.get("id")]
                                dep_text = ", ".join(deps) if deps else "None"
                                mod_data.append({
                                    "name": mod_name,
                                    "id": mod_id,
                                    "version": mod_version,
                                    "deps": dep_text,
                                    "is_native": True
                                })
                                mod_id_to_data[mod_id] = mod_data[-1]
                                logger.info(f"SubModuleTabWidget: Found native mod {mod_name} (ID: {mod_id}, Version: {mod_version})")
                            except ET.ParseError as e:
                                logger.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}: {str(e)}")
                        else:
                            logger.warning(f"SubModuleTabWidget: SubModule.xml not found in {mod_dir}")
            
            # Ensure all native mods are included
            for mod_id in self.DEFAULT_MOD_ORDER:
                if mod_id not in mod_id_to_data:
                    mod_data.append({
                        "name": mod_id,
                        "id": mod_id,
                        "version": "1.2.12",
                        "deps": "None",
                        "is_native": True
                    })
                    mod_id_to_data[mod_id] = mod_data[-1]
                    logger.info(f"SubModuleTabWidget: Added missing native mod {mod_id}")
            
            mo2_mods_path = Path(self._organizer.modsPath())
            logger.debug(f"SubModuleTabWidget: Scanning MO2 mods directory: {mo2_mods_path}")
            if mo2_mods_path.exists():
                for mo2_mod_name in enabled_mods:
                    mod_path = mo2_mods_path / mo2_mod_name
                    for xml_path in mod_path.glob("**/SubModule.xml"):
                        try:
                            tree = ET.parse(xml_path)
                            root = tree.getroot()
                            mod_name = root.findtext("Name") or xml_path.parent.name
                            mod_id = root.findtext("Id") or xml_path.parent.name
                            version_elem = root.find("Version")
                            mod_version = version_elem.get("value") if version_elem is not None and version_elem.get("value") else (version_elem.text if version_elem is not None else "Unknown")
                            mod_version = mod_version.strip().lstrip("ve")
                            deps = [f"{dep.get('id')} ({dep.get('version', '*')})" for dep in root.findall(".//DependedModuleMetadata") if dep.get("id")]
                            dep_text = ", ".join(deps) if deps else "None"
                            mod_data.append({
                                "name": mod_name,
                                "id": mod_id,
                                "version": mod_version,
                                "deps": dep_text,
                                "is_native": False
                            })
                            mod_id_to_data[mod_id] = mod_data[-1]
                            logger.info(f"SubModuleTabWidget: Found enabled MO2 mod {mod_name} (ID: {mod_id}, Version: {mod_version}, MO2 name: {mo2_mod_name})")
                        except ET.ParseError as e:
                            logger.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}: {str(e)}")
            else:
                logger.warning(f"SubModuleTabWidget: MO2 mods directory not found: {mo2_mods_path}")
            
            launcher_data_path = self._get_launcher_data_path()
            saved_mod_order = []
            saved_mod_states = {}
            if launcher_data_path.exists():
                try:
                    tree = ET.parse(launcher_data_path)
                    root = tree.getroot()
                    mod_datas = root.find(".//SingleplayerData/ModDatas")
                    if mod_datas is not None:
                        for user_mod_data in mod_datas.findall("UserModData"):
                            mod_id = user_mod_data.findtext("Id")
                            is_selected = user_mod_data.findtext("IsSelected", "false").lower() == "true"
                            if mod_id and mod_id in mod_id_to_data:
                                saved_mod_states[mod_id] = is_selected
                                saved_mod_order.append(mod_id)
                                logger.debug(f"SubModuleTabWidget: Read {mod_id} IsSelected={is_selected} from LauncherData.xml")
                except Exception as e:
                    logger.error(f"SubModuleTabWidget: Failed to read LauncherData.xml: {str(e)}")
            
            for mod_id in ["Sandbox", "Multiplayer"]:
                saved_mod_states[mod_id] = True
                logger.debug(f"SubModuleTabWidget: Forced {mod_id} to IsSelected=true")
            
            # Prioritize modlist.txt order, then current UI order, then saved XML order, then native mods
            sorted_mods = []
            seen_mods = set()
            # First, add mods in modlist.txt order
            for mo2_mod_name in enabled_mods:
                mod_path = mo2_mods_path / mo2_mod_name
                for xml_path in mod_path.glob("**/SubModule.xml"):
                    try:
                        tree = ET.parse(xml_path)
                        root = tree.getroot()
                        mod_id = root.findtext("Id") or xml_path.parent.name
                        if mod_id in mod_id_to_data and mod_id not in seen_mods:
                            sorted_mods.append(mod_id_to_data[mod_id])
                            seen_mods.add(mod_id)
                    except ET.ParseError:
                        continue
            # Then, add current UI order for remaining mods
            for mod_id in current_order:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
            # Then, add saved XML order for remaining mods
            for mod_id in saved_mod_order:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
            # Finally, add remaining native mods in DEFAULT_MOD_ORDER
            for mod_id in self.DEFAULT_MOD_ORDER:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
            
            self._mod_list.blockSignals(True)
            self._mod_list.clear()
            for mod in sorted_mods:
                mod_name = mod["name"]
                mod_id = mod["id"]
                mod_version = mod["version"]
                dep_text = mod["deps"]
                display_text = f"{mod_name} (v{mod_version})"
                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Use current UI state if available, else saved state, else enabled_mods
                mod_state = current_states.get(mod_id, saved_mod_states.get(mod_id, False))
                if mod_id in ["Sandbox", "Multiplayer"]:
                    mod_state = True
                elif mod_id not in self.DEFAULT_MOD_ORDER:
                    mod_state = any(mod_id in mod for mod in enabled_mods)
                item.setCheckState(Qt.CheckState.Checked if mod_state else Qt.CheckState.Unchecked)
                item.setToolTip(f"ID: {mod_id}\nVersion: {mod_version}\nDependencies: {dep_text}\nSource: {'Game Modules' if mod['is_native'] else 'MO2 Mods'}")
                self._mod_list.addItem(item)
                logger.info(f"SubModuleTabWidget: Added mod {mod_name} (ID: {mod_id}, Version: {mod_version}, Source: {'Game Modules' if mod['is_native'] else 'MO2 Mods'}, State: {mod_state})")
            
            self._mod_list.blockSignals(False)
            self._update_launcher_data()
            logger.info(f"SubModuleTabWidget: Loaded {self._mod_list.count()} mods")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to refresh mods: {str(e)}")

    def on_item_changed(self, item):
        try:
            mod_id = item.data(Qt.ItemDataRole.UserRole)
            if not mod_id:
                logger.warning("SubModuleTabWidget: Item has no UserRole data")
                return
            mod_name = item.text().split(" (v")[0]
            mod_state = item.checkState() == Qt.CheckState.Checked
            if mod_id in ["Sandbox", "Multiplayer"]:
                mod_state = True
                item.setCheckState(Qt.CheckState.Checked)
                logger.debug(f"SubModuleTabWidget: Forced {mod_id} to checked in UI")
            self._update_launcher_data(changed_mod=mod_id, changed_state=mod_state)
            logger.info(f"SubModuleTabWidget: Mod {mod_name} (ID: {mod_id}) {'enabled' if mod_state else 'disabled'}")
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
                logger.debug(f"SubModuleTabWidget: Enabled mod {mod_id}")
            self._mod_list.blockSignals(False)
            self._update_launcher_data()
            logger.info("SubModuleTabWidget: Enabled all mods")
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
                    logger.debug(f"SubModuleTabWidget: Forced {mod_id} to remain enabled")
                else:
                    item.setCheckState(Qt.CheckState.Unchecked)
                    logger.debug(f"SubModuleTabWidget: Disabled mod {mod_id}")
            self._mod_list.blockSignals(False)
            self._update_launcher_data()
            logger.info("SubModuleTabWidget: Disabled all mods (except Sandbox and Multiplayer)")
        except Exception as e:
            logger.error(f"SubModuleTabWidget: Failed to disable all mods: {str(e)}")
import os
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET
from PyQt6.QtCore import QDir, QStandardPaths, Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout, QAbstractItemView, QListWidgetItem
import mobase
import logging

class SubModuleTabWidget(QWidget):
    # Define default load order, including Bannerlord.Harmony before native mods
    DEFAULT_MOD_ORDER = [
        "Bannerlord.Harmony",
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
        logging.info("SubModuleTabWidget: Initializing")
        self._organizer = organizer
        self._layout = QVBoxLayout(self)
        self._mod_list = QListWidget(self)
        self._mod_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # Enable drag-and-drop
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
        self.refresh_mods()
        logging.info("SubModuleTabWidget: Initialization complete")

    def _get_launcher_data_path(self):
        """Get the path to LauncherData.xml, prioritizing profile-specific path if local settings are enabled."""
        try:
            profile = self._organizer.profile()
            if profile and profile.localSettingsEnabled():
                profile_path = Path(self._organizer.profilePath()) / "LauncherData.xml"
                if profile_path.exists():
                    logging.debug(f"SubModuleTabWidget: Found LauncherData.xml at profile path: {profile_path}")
                    return profile_path
                # If profile-specific file doesn't exist, copy from Documents if available
                docs_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
                default_path = Path(docs_path) / "Mount and Blade II Bannerlord" / "Configs" / "LauncherData.xml"
                if default_path.exists():
                    profile_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(default_path, profile_path)
                    logging.info(f"SubModuleTabWidget: Copied LauncherData.xml from {default_path} to {profile_path}")
                    return profile_path
                logging.warning(f"SubModuleTabWidget: LauncherData.xml not found at {default_path}, cannot create profile-specific file")
                return None
            else:
                # Use default Documents path if local settings are disabled
                docs_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
                default_path = Path(docs_path) / "Mount and Blade II Bannerlord" / "Configs" / "LauncherData.xml"
                if default_path.exists():
                    logging.debug(f"SubModuleTabWidget: Found LauncherData.xml at default path: {default_path}")
                    return default_path
                logging.warning(f"SubModuleTabWidget: LauncherData.xml not found at {default_path}")
                return None
        except Exception as e:
            logging.error(f"SubModuleTabWidget: Failed to get LauncherData.xml path: {str(e)}")
            return None

    def _update_launcher_data(self, mod_states: dict[str, bool]):
        """Update LauncherData.xml with the given mod states."""
        try:
            launcher_data_path = self._get_launcher_data_path()
            if not launcher_data_path or not launcher_data_path.exists():
                logging.warning(f"SubModuleTabWidget: Cannot update LauncherData.xml, file does not exist: {launcher_data_path}")
                return
            
            tree = ET.parse(launcher_data_path)
            root = tree.getroot()
            mod_datas = root.find(".//SingleplayerData/ModDatas")
            if mod_datas is None:
                logging.warning("SubModuleTabWidget: No ModDatas found in LauncherData.xml")
                return
            
            # Update IsSelected for each mod
            for user_mod_data in mod_datas.findall("UserModData"):
                mod_id = user_mod_data.findtext("Id")
                if mod_id in mod_states:
                    is_selected = user_mod_data.find("IsSelected")
                    if is_selected is not None:
                        is_selected.text = str(mod_states[mod_id]).lower()
                        logging.debug(f"SubModuleTabWidget: Updated {mod_id} to IsSelected={mod_states[mod_id]}")
            
            tree.write(launcher_data_path, encoding="utf-8", xml_declaration=True)
            logging.info(f"SubModuleTabWidget: Updated LauncherData.xml at {launcher_data_path}")
        except Exception as e:
            logging.error(f"SubModuleTabWidget: Failed to update LauncherData.xml: {str(e)}")

    def _update_launcher_data_order(self):
        """Update LauncherData.xml to reflect the current mod order in the list."""
        try:
            launcher_data_path = self._get_launcher_data_path()
            if not launcher_data_path or not launcher_data_path.exists():
                logging.warning(f"SubModuleTabWidget: Cannot update LauncherData.xml order, file does not exist: {launcher_data_path}")
                return
            
            tree = ET.parse(launcher_data_path)
            root = tree.getroot()
            mod_datas = root.find(".//SingleplayerData/ModDatas")
            if mod_datas is None:
                logging.warning("SubModuleTabWidget: No ModDatas found in LauncherData.xml")
                return
            
            # Get current order from QListWidget
            mod_order = []
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                mod_id = item.data(Qt.ItemDataRole.UserRole)
                mod_order.append(mod_id)
            
            # Create new ModDatas element with ordered mods
            new_mod_datas = ET.Element("ModDatas")
            for mod_id in mod_order:
                # Find existing UserModData for this mod_id
                for user_mod_data in mod_datas.findall("UserModData"):
                    if user_mod_data.findtext("Id") == mod_id:
                        new_mod_datas.append(user_mod_data)
                        break
                else:
                    # Add new UserModData if not found
                    new_mod_data = ET.SubElement(new_mod_datas, "UserModData")
                    ET.SubElement(new_mod_data, "Id").text = mod_id
                    ET.SubElement(new_mod_data, "IsSelected").text = "true"
                    logging.debug(f"SubModuleTabWidget: Added new UserModData for {mod_id} in LauncherData.xml")
            
            # Replace old ModDatas with new ordered one
            singleplayer_data = root.find(".//SingleplayerData")
            singleplayer_data.remove(mod_datas)
            singleplayer_data.append(new_mod_datas)
            
            tree.write(launcher_data_path, encoding="utf-8", xml_declaration=True)
            logging.info(f"SubModuleTabWidget: Updated LauncherData.xml order at {launcher_data_path}")
        except Exception as e:
            logging.error(f"SubModuleTabWidget: Failed to update LauncherData.xml order: {str(e)}")

    def refresh_mods(self):
        try:
            self._mod_list.clear()
            game = self._organizer.managedGame()
            if not game:
                logging.warning("SubModuleTabWidget: No managed game found")
                return
            # Scan game Modules directory
            modules_path = Path(game.gameDirectory().absolutePath()) / "Modules"
            mod_data = []
            mod_id_to_data = {}
            if modules_path.exists():
                logging.info(f"SubModuleTabWidget: Checking game Modules path: {modules_path}")
                for mod_dir in modules_path.iterdir():
                    if mod_dir.is_dir():
                        xml_path = mod_dir / "SubModule.xml"
                        if xml_path.exists():
                            try:
                                tree = ET.parse(xml_path)
                                root = tree.getroot()
                                mod_name = root.findtext("Name") or mod_dir.name
                                mod_id = root.findtext("Id") or mod_dir.name
                                # Robust version parsing
                                version_elem = root.find("Version")
                                if version_elem is not None:
                                    mod_version = version_elem.get("value") or version_elem.text
                                    if mod_version is None:
                                        mod_version = "Unknown"
                                    mod_version = mod_version.strip()
                                    # Strip leading 'v' or 'e'
                                    if mod_version.lower().startswith(('v', 'e')):
                                        mod_version = mod_version[1:]
                                    logging.debug(f"SubModuleTabWidget: Parsed Version='{mod_version}' for {mod_name} at {xml_path}")
                                else:
                                    mod_version = "Unknown"
                                    logging.debug(f"SubModuleTabWidget: No Version tag found for {mod_name} at {xml_path}")
                                deps = []
                                for dep in root.findall(".//DependedModuleMetadata"):
                                    dep_id = dep.get("id")
                                    dep_version = dep.get("version", "*")
                                    if dep_id:
                                        deps.append(f"{dep_id} ({dep_version})")
                                dep_text = ", ".join(deps) if deps else "None"
                                mod_data.append({
                                    "name": mod_name,
                                    "id": mod_id,
                                    "version": mod_version,
                                    "deps": dep_text,
                                    "path": mod_dir,
                                    "is_native": True,
                                    "mo2_mod_name": mod_name  # For native mods, use mod_name
                                })
                                mod_id_to_data[mod_id] = mod_data[-1]
                                logging.debug(f"SubModuleTabWidget: Found native mod {mod_name} (ID: {mod_id}, Version: {mod_version})")
                            except ET.ParseError:
                                logging.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {mod_dir}")
            else:
                logging.warning(f"SubModuleTabWidget: Game Modules path does not exist: {modules_path}")
            
            # Scan MO2 mods directory
            mo2_mods_path = Path(self._organizer.modsPath())
            if mo2_mods_path.exists():
                logging.info(f"SubModuleTabWidget: Checking MO2 mods path: {mo2_mods_path}")
                for mo2_mod_name in self._organizer.modList().allMods():
                    mod_path = mo2_mods_path / mo2_mod_name
                    # Look for SubModule.xml in any subdirectory
                    for xml_path in mod_path.glob("**/SubModule.xml"):
                        try:
                            tree = ET.parse(xml_path)
                            root = tree.getroot()
                            mod_name = root.findtext("Name") or xml_path.parent.name
                            mod_id = root.findtext("Id") or xml_path.parent.name
                            # Robust version parsing
                            version_elem = root.find("Version")
                            if version_elem is not None:
                                mod_version = version_elem.get("value") or version_elem.text
                                if mod_version is None:
                                    mod_version = "Unknown"
                                mod_version = mod_version.strip()
                                # Strip leading 'v' or 'e'
                                if mod_version.lower().startswith(('v', 'e')):
                                    mod_version = mod_version[1:]
                                logging.debug(f"SubModuleTabWidget: Parsed Version='{mod_version}' for {mod_name} at {xml_path}")
                            else:
                                mod_version = "Unknown"
                                logging.debug(f"SubModuleTabWidget: No Version tag found for {mod_name} at {xml_path}")
                            deps = []
                            for dep in root.findall(".//DependedModuleMetadata"):
                                dep_id = dep.get("id")
                                dep_version = dep.get("version", "*")
                                if dep_id:
                                    deps.append(f"{dep_id} ({dep_version})")
                            dep_text = ", ".join(deps) if deps else "None"
                            mod_data.append({
                                "name": mod_name,
                                "id": mod_id,
                                "version": mod_version,
                                "deps": dep_text,
                                "path": xml_path.parent,
                                "is_native": False,
                                "mo2_mod_name": mo2_mod_name
                            })
                            mod_id_to_data[mod_id] = mod_data[-1]
                            logging.debug(f"SubModuleTabWidget: Found MO2 mod {mod_name} (ID: {mod_id}, Version: {mod_version}, MO2 name: {mo2_mod_name})")
                        except ET.ParseError:
                            logging.warning(f"SubModuleTabWidget: Failed to parse SubModule.xml in {xml_path}")
            else:
                logging.warning(f"SubModuleTabWidget: MO2 mods path does not exist: {mo2_mods_path}")
            
            # Read LauncherData.xml for mod states and order
            launcher_data_path = self._get_launcher_data_path()
            mod_states = {}
            saved_mod_order = []
            if launcher_data_path and launcher_data_path.exists():
                try:
                    tree = ET.parse(launcher_data_path)
                    root = tree.getroot()
                    mod_datas = root.find(".//SingleplayerData/ModDatas")
                    if mod_datas is not None:
                        for user_mod_data in mod_datas.findall("UserModData"):
                            mod_id = user_mod_data.findtext("Id")
                            is_selected = user_mod_data.findtext("IsSelected", "false").lower() == "true"
                            if mod_id:
                                mod_states[mod_id] = is_selected
                                saved_mod_order.append(mod_id)
                                logging.debug(f"SubModuleTabWidget: Read {mod_id} IsSelected={is_selected} from LauncherData.xml")
                except Exception as e:
                    logging.error(f"SubModuleTabWidget: Failed to read mod states from LauncherData.xml: {str(e)}")
            
            # Sort mods: prioritize saved order, then DEFAULT_MOD_ORDER, then MO2 priority or alphabetically
            sorted_mods = []
            seen_mods = set()
            # Add mods from saved order in LauncherData.xml
            for mod_id in saved_mod_order:
                if mod_id in mod_id_to_data and mod_id not in seen_mods:
                    sorted_mods.append(mod_id_to_data[mod_id])
                    seen_mods.add(mod_id)
            
            # Add mods from DEFAULT_MOD_ORDER not in saved order
            for mod_name in self.DEFAULT_MOD_ORDER:
                for mod in mod_data:
                    if mod["name"] == mod_name and mod["id"] not in seen_mods:
                        sorted_mods.append(mod)
                        seen_mods.add(mod["id"])
                        break
            
            # Add remaining mods by MO2 priority or alphabetically
            remaining_mods = [mod for mod in mod_data if mod["id"] not in seen_mods]
            remaining_mods.sort(key=lambda x: (
                -self._organizer.modList().priority(x["mo2_mod_name"]) if self._organizer.modList().state(x["mo2_mod_name"]) == mobase.ModState.ACTIVE else float('inf'),
                x["name"].lower()
            ))
            sorted_mods.extend(remaining_mods)
            
            # Add sorted mods to QListWidget and set MO2 priorities
            for i, mod in enumerate(sorted_mods):
                mod_name = mod["name"]
                mod_id = mod["id"]
                mo2_mod_name = mod["mo2_mod_name"]
                mod_version = mod["version"]
                dep_text = mod["deps"]
                display_text = f"{mod_name} (v{mod_version})"
                item = QListWidgetItem(display_text)
                item.setData(Qt.ItemDataRole.UserRole, mod_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # Prefer LauncherData.xml state, fallback to MO2 mod state
                mod_state = mod_states.get(mod_id, self._organizer.modList().state(mo2_mod_name) == mobase.ModState.ACTIVE)
                item.setCheckState(Qt.CheckState.Checked if mod_state else Qt.CheckState.Unchecked)
                tooltip = f"ID: {mod_id}\nVersion: {mod_version}\nDependencies: {dep_text}\nSource: {'Game Modules' if mod['is_native'] else 'MO2 Mods'}\nMO2 Mod Name: {mo2_mod_name}"
                item.setToolTip(tooltip)
                self._mod_list.addItem(item)
                # Set MO2 priority to match UI order
                self._organizer.modList().setPriority(mo2_mod_name, i)
                logging.debug(f"SubModuleTabWidget: Added mod {mod_name} (ID: {mod_id}, MO2 name: {mo2_mod_name}, Version: {mod_version}) at priority {i}, state={mod_state}")
            
            # Update LauncherData.xml to reflect initial order and states
            self._update_launcher_data_order()
            mod_states = {mod["id"]: (self._mod_list.item(i).checkState() == Qt.CheckState.Checked) for i, mod in enumerate(sorted_mods)}
            self._update_launcher_data(mod_states)
            logging.info(f"SubModuleTabWidget: Loaded {self._mod_list.count()} mods in saved order")
        except Exception as e:
            logging.error(f"SubModuleTabWidget: Failed to refresh mods: {str(e)}")

    def on_item_changed(self, item):
        try:
            mod_name = item.text().split(" (v")[0]
            mod_id = item.data(Qt.ItemDataRole.UserRole)
            mod_state = item.checkState() == Qt.CheckState.Checked
            # Find the MO2 mod name for this mod_id
            mo2_mod_name = None
            for i in range(self._mod_list.count()):
                current_item = self._mod_list.item(i)
                if current_item.data(Qt.ItemDataRole.UserRole) == mod_id:
                    for mod in self._mod_list.findItems(f"{mod_name} (v", Qt.MatchFlag.MatchStartsWith):
                        if mod.data(Qt.ItemDataRole.UserRole) == mod_id:
                            mo2_mod_name = mod.toolTip().split("MO2 Mod Name: ")[-1]
                            break
                    break
            if mo2_mod_name:
                self._organizer.modList().setActive(mo2_mod_name, mod_state)
                logging.debug(f"SubModuleTabWidget: Set MO2 mod {mo2_mod_name} (ID: {mod_id}) to active={mod_state}")
            else:
                logging.warning(f"SubModuleTabWidget: No MO2 mod name found for {mod_name} (ID: {mod_id})")
            # Update LauncherData.xml
            self._update_launcher_data({mod_id: mod_state})
            logging.info(f"SubModuleTabWidget: Mod {mod_name} (ID: {mod_id}) {'enabled' if mod_state else 'disabled'}")
        except Exception as e:
            # Log available IModList methods for debugging
            mod_list = self._organizer.modList()
            available_methods = [method for method in dir(mod_list) if callable(getattr(mod_list, method)) and not method.startswith('_')]
            logging.error(f"SubModuleTabWidget: Failed to change mod state for {item.text()}: {str(e)}")
            logging.debug(f"SubModuleTabWidget: Available IModList methods: {available_methods}")

    def on_rows_moved(self, parent, start, end, destination, row):
        try:
            # Update MO2 mod priorities
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                mod_name = item.text().split(" (v")[0]
                mod_id = item.data(Qt.ItemDataRole.UserRole)
                # Find MO2 mod name from tooltip
                mo2_mod_name = item.toolTip().split("MO2 Mod Name: ")[-1]
                self._organizer.modList().setPriority(mo2_mod_name, i)
                logging.debug(f"SubModuleTabWidget: Set priority for {mo2_mod_name} (ID: {mod_id}) to {i}")
            
            # Check if native modules deviate from DEFAULT_MOD_ORDER
            current_order = [self._mod_list.item(i).text().split(" (v")[0] for i in range(self._mod_list.count())]
            native_order = [mod for mod in current_order if mod in self.DEFAULT_MOD_ORDER]
            if native_order != [mod for mod in self.DEFAULT_MOD_ORDER if mod in native_order]:
                logging.warning(f"SubModuleTabWidget: Native mod order deviates from recommended: {native_order}. Recommended: {self.DEFAULT_MOD_ORDER}")
            
            # Update LauncherData.xml order
            self._update_launcher_data_order()
            logging.info("SubModuleTabWidget: Mod order updated")
        except Exception as e:
            logging.error(f"SubModuleTabWidget: Failed to update mod order: {str(e)}")

    def enable_all_mods(self):
        try:
            mod_states = {}
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                mod_name = item.text().split(" (v")[0]
                mod_id = item.data(Qt.ItemDataRole.UserRole)
                mo2_mod_name = item.toolTip().split("MO2 Mod Name: ")[-1]
                self._organizer.modList().setActive(mo2_mod_name, True)
                item.setCheckState(Qt.CheckState.Checked)
                mod_states[mod_id] = True
                logging.debug(f"SubModuleTabWidget: Enabled MO2 mod {mo2_mod_name} (ID: {mod_id})")
            # Update LauncherData.xml
            self._update_launcher_data(mod_states)
            logging.info("SubModuleTabWidget: Enabled all mods")
        except Exception as e:
            # Log available IModList methods for debugging
            mod_list = self._organizer.modList()
            available_methods = [method for method in dir(mod_list) if callable(getattr(mod_list, method)) and not method.startswith('_')]
            logging.error(f"SubModuleTabWidget: Failed to enable all mods: {str(e)}")
            logging.debug(f"SubModuleTabWidget: Available IModList methods: {available_methods}")

    def disable_all_mods(self):
        try:
            mod_states = {}
            for i in range(self._mod_list.count()):
                item = self._mod_list.item(i)
                mod_name = item.text().split(" (v")[0]
                mod_id = item.data(Qt.ItemDataRole.UserRole)
                mo2_mod_name = item.toolTip().split("MO2 Mod Name: ")[-1]
                self._organizer.modList().setActive(mo2_mod_name, False)
                item.setCheckState(Qt.CheckState.Unchecked)
                mod_states[mod_id] = False
                logging.debug(f"SubModuleTabWidget: Disabled MO2 mod {mo2_mod_name} (ID: {mod_id})")
            # Update LauncherData.xml
            self._update_launcher_data(mod_states)
            logging.info("SubModuleTabWidget: Disabled all mods")
        except Exception as e:
            # Log available IModList methods for debugging
            mod_list = self._organizer.modList()
            available_methods = [method for method in dir(mod_list) if callable(getattr(mod_list, method)) and not method.startswith('_')]
            logging.error(f"SubModuleTabWidget: Failed to disable all mods: {str(e)}")
            logging.debug(f"SubModuleTabWidget: Available IModList methods: {available_methods}")
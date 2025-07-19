import sys
import os
import json
from pathlib import Path
from typing import List, Mapping
from PyQt6.QtCore import QDir, QFileInfo, QStandardPaths, Qt, qInfo, qWarning, qCritical
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget
import mobase
import logging
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from enum import IntEnum

from ..basic_game import BasicGame
from ..basic_features import BasicLocalSavegames, BasicGameSaveGameInfo
from ..basic_features.basic_save_game_info import BasicGameSaveGame, format_date
from .mountandblade2.submodule_tab import SubModuleTabWidget
from .mountandblade2.mod_config_manager import ModConfigManagerWidget

# Ensure games directory is in sys.path
games_dir = Path(__file__).parent
if str(games_dir) not in sys.path:
    sys.path.append(str(games_dir))
    logging.info(f"Added {games_dir} to sys.path")

logging.info("MountAndBladeIIGame: Loading plugin")

class BannerlordSaveGame(BasicGameSaveGame):
    def __init__(self, filepath: Path):
        super().__init__(filepath)
        self._metadata = self._parse_metadata(filepath)

    def _parse_metadata(self, filepath: Path) -> dict:
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
                start = data.find(b'{"List":')
                if start == -1:
                    logging.error(f"No JSON section found in {filepath}")
                    return {}
                
                brace_count = 0
                end = start
                in_string = False
                escape = False
                for i, char in enumerate(data[start:]):
                    if char == ord('"') and not escape:
                        in_string = not in_string
                    elif char == ord('{') and not in_string:
                        brace_count += 1
                    elif char == ord('}') and not in_string:
                        brace_count -= 1
                        if brace_count == 0:
                            end = start + i + 1
                            break
                    escape = char == ord('\\') and not escape
                
                if brace_count != 0 or end == start:
                    logging.error(f"Invalid JSON structure in {filepath}: brace count {brace_count}")
                    return {}
                
                json_str = data[start:end].decode('utf-8', errors='replace')
                metadata = json.loads(json_str)
                return metadata.get("List", {})
        except Exception as e:
            logging.error(f"Error parsing metadata for {filepath}: {str(e)}")
            return {}

    def getName(self) -> str:
        return self._metadata.get("CharacterName", "Unknown")

    def getCharacterName(self) -> str:
        return self._metadata.get("CharacterName", "Unknown")

    def getLevel(self) -> str:
        return self._metadata.get("MainHeroLevel", "Unknown")

    def getGold(self) -> str:
        return self._metadata.get("MainHeroGold", "Unknown")

def getMetadata(savepath: Path, save: mobase.ISaveGame) -> Mapping[str, str]:
    assert isinstance(save, BannerlordSaveGame)
    file_size_bytes = Path(savepath).stat().st_size
    if file_size_bytes >= 1024 * 1024:
        file_size = f"{file_size_bytes / (1024 * 1024):.2f} MB"
    elif file_size_bytes >= 1024:
        file_size = f"{file_size_bytes / 1024:.2f} KB"
    else:
        file_size = f"{file_size_bytes} bytes"
    
    return {
        "Character": save.getCharacterName(),
        "Level": save.getLevel(),
        "Gold": save.getGold(),
        "Saved at": format_date(save.getCreationTime()),
        "File Size": file_size,
    }

def get_preview(savepath: Path) -> str | None:
    for ext in (".png", ".jpg"):
        preview_path = savepath.with_suffix(ext)
        if preview_path.exists():
            return str(preview_path)
    return None

class MountAndBladeIIModDataChecker(mobase.ModDataChecker):
    _valid_folders: list[str] = [
        "native",
        "sandboxcore",
        "birthanddeath",
        "custombattle",
        "sandbox",
        "storymode",
        "multiplayer",
    ]

    def dataLooksValid(self, filetree: mobase.IFileTree) -> mobase.ModDataChecker.CheckReturn:
        for e in filetree:
            if e.isDir():
                if e.name().lower() in self._valid_folders:
                    return mobase.ModDataChecker.VALID
                if e.exists("SubModule.xml", mobase.IFileTree.FILE):
                    return mobase.ModDataChecker.VALID
        return mobase.ModDataChecker.INVALID

class BannerlordModDataContent(mobase.ModDataContent):
    class Content(IntEnum):
        ASSET_PACK = 0
        DLL = 1
        CONFIG = 2
        SCENE = 3
        ASSETS = 4
        MUSIC = 5
        CUSTOM_MAP = 6

    def getAllContents(self) -> list[mobase.ModDataContent.Content]:
        return [
            mobase.ModDataContent.Content(self.Content.ASSET_PACK, "Asset Packs", ":/MO/gui/content/bsa"),
            mobase.ModDataContent.Content(self.Content.DLL, "DLLs", ":/MO/gui/content/script"),
            mobase.ModDataContent.Content(self.Content.CONFIG, "Configs", ":/MO/gui/content/inifile"),
            mobase.ModDataContent.Content(self.Content.SCENE, "Scenes", ":/MO/gui/content/geometries"),
            mobase.ModDataContent.Content(self.Content.ASSETS, "Assets", ":/MO/gui/content/mesh"),
            mobase.ModDataContent.Content(self.Content.MUSIC, "Music", ":/MO/gui/content/music"),
            mobase.ModDataContent.Content(self.Content.CUSTOM_MAP, "World Map", ":/MO/gui/content/texture"),
        ]

    def getContentsFor(self, filetree: mobase.IFileTree) -> list[int]:
        content = []
        extension_map = {
            "tpac": self.Content.ASSET_PACK,
            "dll": self.Content.DLL,
            "ogg": self.Content.MUSIC,
            "fbx": self.Content.ASSETS,
            "png": self.Content.ASSETS,
            "dds": self.Content.ASSETS,
            "json": self.Content.CONFIG,
            "xscene": self.Content.SCENE,
        }
        def walk_content(path: str, entry: mobase.FileTreeEntry) -> mobase.IFileTree.WalkReturn:
            if entry.isFile():
                if entry.name().lower() == "settlements_distance_cache.bin":
                    content.append(self.Content.CUSTOM_MAP)
                ext = entry.suffix().lower()
                if ext in extension_map:
                    content.append(extension_map[ext])
            return mobase.IFileTree.WalkReturn.CONTINUE

        filetree.walk(walk_content, "/")
        logging.debug(f"Detected content types for mod: {content}")
        return content

class MountAndBladeIIGame(BasicGame):
    Name = "Mount & Blade II: Bannerlord"
    Author = "d&h"
    Version = "0.1.23"
    Description = "Adds support for Mount & Blade II: Bannerlord"

    GameName = "Mount & Blade II: Bannerlord"
    GameShortName = "mountandblade2bannerlord"
    GameDataPath = "Modules"
    GameSupportURL = (
        r"https://github.com/ModOrganizer2/modorganizer-basic_games/wiki/"
        "Game:-Mount-&-Blade-II:-Bannerlord"
    )

    GameBinary = "bin/Win64_Shipping_Client/Bannerlord.exe"
    GameLauncher = "bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.Launcher.exe"
    GameDocumentsDirectory = "%DOCUMENTS%/Mount and Blade II Bannerlord/Configs"
    GameSaveExtension = "sav"
    GameSavesDirectory = "%DOCUMENTS%/Mount and Blade II Bannerlord/Game Saves"

    GameNexusId = 3174
    GameSteamId = 261550
    GameGogId = 1564781494
    GameEpicId = "Chickadee"

    def __init__(self):
        super().__init__()
        self._submodule_tab = None
        self._config_tab = None
        self._organizer = None
        self._main_window = None

    def init(self, organizer: mobase.IOrganizer):
        try:
            logging.info("MountAndBladeIIGame: Starting init")
            self._organizer = organizer
            self._register_feature(MountAndBladeIIModDataChecker())
            self._register_feature(BannerlordModDataContent())
            self._register_feature(BasicGameSaveGameInfo(get_metadata=getMetadata, get_preview=get_preview, max_width=400))
            self._register_feature(BasicLocalSavegames(self.savesDirectory()))
            try:
                logging.info("MountAndBladeIIGame: Registering UI and run callbacks")
                organizer.onUserInterfaceInitialized(self.init_tab)
                organizer.onAboutToRun(self._onAboutToRun)
                organizer.onFinishedRun(self._post_run_sync)
                organizer.onProfileChanged(self._on_profile_changed)
            except Exception as e:
                logging.error(f"MountAndBladeIIGame: Failed to register callbacks: {str(e)}")
            logging.info("MountAndBladeIIGame: Initialization complete")
            return True
        except Exception as e:
            logging.error(f"MountAndBladeIIGame: Initialization failed: {str(e)}")
            return False

    def settings(self) -> list[mobase.PluginSetting]:
        return [
            mobase.PluginSetting(
                "enforce_load_order",
                "Enforce mod load order via CLI arguments for Bannerlord.exe",
                True
            )
        ]

    def _get_enabled_mods(self) -> List[str]:
        """Get enabled mods in profile priority order."""
        mod_list = self._organizer.modList()
        mods = mod_list.allModsByProfilePriority()
        enabled_mods = [mod for mod in mods if mod_list.state(mod) & mobase.ModState.ACTIVE]
        logging.info(f"MountAndBladeIIGame: Enabled mods: {enabled_mods}")
        return enabled_mods

    def _get_mod_load_order(self) -> List[str]:
        """Retrieve mod load order, preferring SubModuleTabWidget if available."""
        if self._submodule_tab is not None:
            load_order = self._submodule_tab.get_enabled_load_order()
            if load_order:
                logging.info(f"MountAndBladeIIGame: Retrieved load order from SubModuleTabWidget: {load_order}")
                return load_order
        
        # Fallback to parsing SubModule.xml files
        load_order = []
        try:
            enabled_mods = self._get_enabled_mods()
            game_path = Path(self._gamePath)
            for mod in enabled_mods:
                # Check MO2 mod directory
                mod_path = Path(self._organizer.getMod(mod).absolutePath()) / "SubModule.xml"
                if mod_path.exists() and mod_path.stat().st_size > 0:
                    try:
                        tree = ET.parse(mod_path)
                        root = tree.getroot()
                        module_id = root.find(".//Id[@value]")
                        if module_id is not None and module_id.get("value"):
                            load_order.append(module_id.get("value"))
                            logging.debug(f"MountAndBladeIIGame: Added mod {mod} with ID {module_id.get('value')}")
                        else:
                            logging.warning(f"MountAndBladeIIGame: No Id tag found in SubModule.xml for mod {mod}")
                    except (ET.ParseError, AttributeError) as e:
                        logging.warning(f"MountAndBladeIIGame: Failed to parse SubModule.xml for mod {mod}: {str(e)}")
                else:
                    # Check native module directory
                    native_mod_path = game_path / "Modules" / mod / "SubModule.xml"
                    if native_mod_path.exists() and native_mod_path.stat().st_size > 0:
                        try:
                            tree = ET.parse(native_mod_path)
                            root = tree.getroot()
                            module_id = root.find(".//Id[@value]")
                            if module_id is not None and module_id.get("value"):
                                load_order.append(module_id.get("value"))
                                logging.debug(f"MountAndBladeIIGame: Added native mod {mod} with ID {module_id.get('value')}")
                            else:
                                logging.warning(f"MountAndBladeIIGame: No Id tag found in SubModule.xml for native mod {mod}")
                        except (ET.ParseError, AttributeError) as e:
                            logging.warning(f"MountAndBladeIIGame: Failed to parse SubModule.xml for native mod {mod}: {str(e)}")
                    else:
                        logging.warning(f"MountAndBladeIIGame: SubModule.xml not found or empty for mod {mod}")

            # Ensure core modules
            core_modules = ["Native", "SandBoxCore", "BirthAndDeath", "CustomBattle", "Sandbox", "StoryMode"]
            for core_mod in core_modules:
                if core_mod not in load_order:
                    mod_path = game_path / "Modules" / core_mod / "SubModule.xml"
                    if mod_path.exists():
                        load_order.append(core_mod)
                        logging.debug(f"MountAndBladeIIGame: Added core module {core_mod}")

            # Sort based on dependencies
            sorted_load_order = self._sort_load_order(load_order)
            logging.info(f"MountAndBladeIIGame: Retrieved and sorted load order: {sorted_load_order}")
            return sorted_load_order
        except Exception as e:
            logging.error(f"MountAndBladeIIGame: Failed to get load order: {str(e)}")
            return []

    def _sort_load_order(self, load_order: List[str]) -> List[str]:
        """Sort load order based on SubModule.xml dependencies."""
        dependencies = {}
        game_path = Path(self._gamePath)
        mod_paths = {mod: Path(self._organizer.getMod(mod).absolutePath()) if mod in self._organizer.modList().allMods()
                     else game_path / "Modules" / mod for mod in load_order}

        for mod in load_order:
            mod_path = mod_paths[mod] / "SubModule.xml"
            if mod_path.exists():
                try:
                    tree = ET.parse(mod_path)
                    root = tree.getroot()
                    deps = []
                    for dep in root.findall(".//DependedModule[@Id]"):
                        dep_id = dep.get("Id")
                        if dep_id in load_order:
                            deps.append(dep_id)
                    dependencies[mod] = deps
                    logging.debug(f"MountAndBladeIIGame: Dependencies for {mod}: {deps}")
                except ET.ParseError as e:
                    logging.warning(f"MountAndBladeIIGame: Failed to parse SubModule.xml for {mod} during sorting: {str(e)}")
                    dependencies[mod] = []
            else:
                dependencies[mod] = []
                logging.warning(f"MountAndBladeIIGame: SubModule.xml not found for {mod} during sorting")

        # Topological sort
        sorted_order = []
        visited = set()
        def dfs(mod):
            if mod in visited:
                return
            visited.add(mod)
            for dep in dependencies.get(mod, []):
                dfs(dep)
            sorted_order.append(mod)

        for mod in load_order:
            dfs(mod)
        return sorted_order

    def _onAboutToRun(self, app_path_str: str, wd: QDir, args: str) -> bool:
        """Handle game launch with custom CLI arguments, preventing infinite loop."""
        if not self.isActive():
            qInfo("MountAndBladeIIGame: Plugin not active, allowing default launch")
            return True

        app_path = Path(app_path_str)
        exe_path = Path(self.gameDirectory().absolutePath(), self.binaryName())
        if app_path != exe_path:
            qInfo(f"MountAndBladeIIGame: Skipping non-Bannerlord executable: {app_path}")
            return True

        try:
            if not self._organizer.pluginSetting(self.name(), "enforce_load_order"):
                qInfo("MountAndBladeIIGame: Load order enforcement disabled, using default launch")
                return True

            if "--mo2-processed" in args:
                qInfo("MountAndBladeIIGame: Already processed, proceeding with launch")
                return True

            # Get load order from SubModuleTabWidget
            if self._submodule_tab is None:
                qWarning("MountAndBladeIIGame: SubModuleTabWidget not initialized, falling back to default launch")
                return True
            load_order = self._submodule_tab.get_enabled_load_order()
            if not load_order:
                qWarning("MountAndBladeIIGame: Load order is empty, falling back to default launch")
                return True

            # Construct CLI arguments as a list
            load_order_str = '*'.join(load_order)
            cli_args = ["/singleplayer", f"_MODULES_*{load_order_str}*_MODULES_", "--mo2-processed"]
            qInfo(f"MountAndBladeIIGame: Launching {exe_path} with args: {cli_args}")

            # Launch with custom arguments
            result = self._organizer.startApplication(str(exe_path), cli_args)
            qInfo(f"MountAndBladeIIGame: Application started with result: {result}")
            return False  # Prevent default launch
        except Exception as e:
            qCritical(f"MountAndBladeIIGame: Failed in _onAboutToRun: {str(e)}")
            return True

    def _post_run_sync(self, appName: str, result: int):
        """Sync game directory configs to profile after game completion."""
        try:
            logging.info(f"MountAndBladeIIGame: Post-run sync for {appName}, result: {result}")
            if hasattr(self, '_config_tab'):
                self._config_tab.sync_to_profile()
            else:
                logging.warning("MountAndBladeIIGame: Config tab not initialized, skipping sync")
        except Exception as e:
            logging.error(f"MountAndBladeIIGame: Post-run sync failed: {str(e)}")

    def _on_profile_changed(self, oldProfile: mobase.IProfile, newProfile: mobase.IProfile):
        """Handle profile changes by refreshing config files."""
        try:
            old_name = oldProfile.name() if oldProfile else "None"
            new_name = newProfile.name() if newProfile else "None"
            logging.info(f"MountAndBladeIIGame: Profile changed from {old_name} to {new_name}")
            if hasattr(self, '_config_tab') and self._config_tab is not None:
                self._config_tab.refresh_on_profile_change()
            else:
                logging.debug("MountAndBladeIIGame: Config tab not initialized, skipping refresh")
        except Exception as e:
            logging.error(f"MountAndBladeIIGame: Profile change handling failed: {str(e)}")

    def init_tab(self, main_window: QMainWindow):
        try:
            logging.info("MountAndBladeIIGame: Initializing tabs")
            if self._organizer.managedGame() != self:
                logging.info("MountAndBladeIIGame: Not the managed game, skipping tab initialization")
                return
            self._main_window = main_window
            tab_widget = main_window.findChild(QTabWidget, "tabWidget")
            if not tab_widget:
                logging.warning("MountAndBladeIIGame: No QTabWidget named 'tabWidget' found")
                return
            if not tab_widget.findChild(QWidget, "espTab"):
                logging.warning("MountAndBladeIIGame: No 'espTab' found in tabWidget")
                return

            # Initialize SubModules tab
            self._submodule_tab = SubModuleTabWidget(main_window, self._organizer)
            plugin_tab = tab_widget.findChild(QWidget, "espTab")
            tab_index = tab_widget.indexOf(plugin_tab) + 1
            if not tab_widget.isTabVisible(tab_index):
                tab_index += 1
            tab_widget.insertTab(tab_index, self._submodule_tab, "SubModules")
            logging.info(f"MountAndBladeIIGame: SubModules tab inserted at index {tab_index}")

            # Initialize Mod Configs tab
            self._config_tab = ModConfigManagerWidget(main_window, self._organizer)
            tab_index += 1
            if not tab_widget.isTabVisible(tab_index):
                tab_index += 1
            tab_widget.insertTab(tab_index, self._config_tab, "Mod Configs")
            logging.info(f"MountAndBladeIIGame: Mod Configs tab inserted at index {tab_index}")
        except Exception as e:
            logging.error(f"MountAndBladeIIGame: Failed to initialize tabs: {str(e)}")

    def savesDirectory(self) -> QDir:
        try:
            docs_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            save_path = os.path.join(docs_path, "Mount and Blade II Bannerlord", "Game Saves")
            if os.path.isdir(save_path):
                logging.info(f"savesDirectory: Valid path: {save_path}")
                return QDir(save_path)
            logging.warning(f"savesDirectory: Invalid path: {save_path}, falling back to hardcoded")
            fallback_path = os.path.expanduser("~/Documents/Mount and Blade II Bannerlord/Game Saves")
            if os.path.isdir(fallback_path):
                logging.info(f"savesDirectory: Hardcoded path valid: {fallback_path}")
                return QDir(fallback_path)
            logging.error(f"savesDirectory: Hardcoded path invalid: {fallback_path}")
            return QDir()
        except Exception as e:
            logging.error(f"savesDirectory: Failed: {str(e)}")
            return QDir()

    def listSaves(self, folder: QDir) -> list[mobase.ISaveGame]:
        try:
            ext = self._mappings.savegameExtension.get()
            saves = []
            skipped_files = []
            for path in Path(folder.absolutePath()).glob(f"*.{ext}"):
                try:
                    save = BannerlordSaveGame(path)
                    saves.append(save)
                except Exception as e:
                    skipped_files.append(str(path))
            if skipped_files:
                logging.debug(f"Skipped {len(skipped_files)} invalid save files in {folder.absolutePath()}")
            logging.debug(f"Found {len(saves)} save files in {folder.absolutePath()}")
            return saves
        except Exception as e:
            logging.error(f"Failed to list saves in {folder.absolutePath()}: {str(e)}")
            return []

    def iniFiles(self) -> list[str]:
        return ["engine_config.txt", "BannerlordConfig.txt", "LauncherData.xml"]

    def executables(self) -> list[mobase.ExecutableInfo]:
        try:
            game_path = QDir(self.gameDirectory().absolutePath())
            bin_path = game_path.absoluteFilePath("bin/Win64_Shipping_Client")
            executables = [
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord",
                    QFileInfo(QDir(bin_path), "Bannerlord.exe")
                ).withWorkingDirectory(bin_path).withArgument("/singleplayer"),
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord (Launcher)",
                    QFileInfo(QDir(bin_path), "TaleWorlds.MountAndBlade.Launcher.exe")
                ).withWorkingDirectory(bin_path),
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord (Native)",
                    QFileInfo(QDir(bin_path), "Bannerlord.Native.exe")
                ).withWorkingDirectory(bin_path),
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord (Singleplayer)",
                    QFileInfo(QDir(bin_path), "TaleWorlds.MountAndBlade.Launcher.Singleplayer.exe")
                ).withWorkingDirectory(bin_path),
            ]
            for exe in executables:
                exe_info = exe.binary()
                if not exe_info.exists():
                    logging.warning(f"Executable not found: {exe_info.filePath()}")
                else:
                    logging.info(f"Registered executable: {exe_info.filePath()}")
            return executables
        except Exception as e:
            logging.error(f"Failed to generate executables: {str(e)}")
            return []
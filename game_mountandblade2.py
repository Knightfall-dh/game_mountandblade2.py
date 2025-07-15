import sys
import os
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from PyQt6.QtCore import QDir, QFileInfo, QStandardPaths, Qt
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget
import mobase
import logging
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
    Version = "0.1.21"
    Description = "Adds support for Mount & Blade II: Bannerlord"

    GameName = "Mount & Blade II: Bannerlord"
    GameShortName = "mountandblade2bannerlord"
    GameDataPath = "Modules"
    GameSupportURL = (
        r"https://github.com/ModOrganizer2/modorganizer-basic_games/wiki/"
        "Game:-Mount-&-Blade-II:-Bannerlord"
    )

    GameBinary = "bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.Launcher.exe"
    GameDocumentsDirectory = "%DOCUMENTS%/Mount and Blade II Bannerlord/Configs"
    GameSaveExtension = "sav"
    GameSavesDirectory = "%DOCUMENTS%/Mount and Blade II Bannerlord/Game Saves"

    GameNexusId = 3174
    GameSteamId = 261550
    GameGogId = 1564781494
    GameEpicId = "Chickadee"

    def init(self, organizer: mobase.IOrganizer):
        try:
            logging.info("MountAndBladeIIGame: Starting init")
            super().__init__()
            self._organizer = organizer
            self._register_feature(MountAndBladeIIModDataChecker())
            self._register_feature(BannerlordModDataContent())
            self._register_feature(BasicGameSaveGameInfo(get_metadata=getMetadata, get_preview=get_preview, max_width=400))
            self._register_feature(BasicLocalSavegames(self.savesDirectory()))
            try:
                logging.info("MountAndBladeIIGame: Registering UI callback")
                organizer.onUserInterfaceInitialized(self.init_tab)
            except Exception as e:
                logging.error(f"MountAndBladeIIGame: Failed to register UI callback: {str(e)}")
            logging.info("MountAndBladeIIGame: Initialization complete")
            return True
        except Exception as e:
            logging.error(f"MountAndBladeIIGame: Initialization failed: {str(e)}")
            return False

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
            
            # Add SubModules tab
            self._submodule_tab = SubModuleTabWidget(main_window, self._organizer)
            plugin_tab = tab_widget.findChild(QWidget, "espTab")
            tab_index = tab_widget.indexOf(plugin_tab) + 1
            if not tab_widget.isTabVisible(tab_index):
                tab_index += 1
            tab_widget.insertTab(tab_index, self._submodule_tab, "SubModules")
            logging.info(f"MountAndBladeIIGame: SubModules tab inserted at index {tab_index}")
            
            # Add Mod Configs tab
            self._config_tab = ModConfigManagerWidget(main_window, self._organizer)
            tab_widget.insertTab(tab_index + 1, self._config_tab, "Mod Configs")
            logging.info(f"MountAndBladeIIGame: Mod Configs tab inserted at index {tab_index + 1}")
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
            return [
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord (Launcher)",
                    QFileInfo(self.gameDirectory(), "bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.Launcher.exe"),
                ),
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord",
                    QFileInfo(self.gameDirectory(), "bin/Win64_Shipping_Client/Bannerlord.exe"),
                ),
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord (Native)",
                    QFileInfo(self.gameDirectory(), "bin/Win64_Shipping_Client/Bannerlord.Native.exe"),
                ),
                mobase.ExecutableInfo(
                    "Mount & Blade II: Bannerlord (Singleplayer)",
                    QFileInfo(self.gameDirectory(), "bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.Launcher.Singleplayer.exe"),
                ),
            ]
        except Exception as e:
            logging.error(f"Failed to generate executables: {str(e)}")
            return []
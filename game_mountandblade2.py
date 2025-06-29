import mobase
import os
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from PyQt6.QtCore import QFileInfo, QDir, QStandardPaths
from ..basic_game import BasicGame
from ..basic_features import BasicGameSaveGameInfo
from ..basic_features.basic_save_game_info import BasicGameSaveGame, format_date
import logging
from collections.abc import Mapping
from enum import IntEnum


class BannerlordSaveGame(BasicGameSaveGame):
    def __init__(self, filepath: Path):
        super().__init__(filepath)
        self._metadata = self._parse_metadata(filepath)

    def _parse_metadata(self, filepath: Path) -> dict:
        """Parse JSON metadata from .sav file using brace counting."""
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
                logging.debug(f"Extracted JSON from {filepath}: {json_str[:1000]}...")
                metadata = json.loads(json_str)
                return metadata.get("List", {})
        except Exception as e:
            logging.error(f"Error parsing metadata for {filepath}: {str(e)}")
            return {}

    def getName(self) -> str:
        """Return character name for Name column."""
        return self._metadata.get("CharacterName", "Unknown")

    def getCharacterName(self) -> str:
        return self._metadata.get("CharacterName", "Unknown")

    def getLevel(self) -> str:
        return self._metadata.get("MainHeroLevel", "Unknown")

    def getGold(self) -> str:
        return self._metadata.get("MainHeroGold", "Unknown")

def getMetadata(savepath: Path, save: mobase.ISaveGame) -> Mapping[str, str]:
    """Provide metadata for MO2 Saves tab tooltips."""
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

    def __init__(self):
        super().__init__()

    def dataLooksValid(self, filetree: mobase.IFileTree) -> mobase.ModDataChecker.CheckReturn:
        logging.debug("Checking mod data validity")
        for e in filetree:
            if e.isDir() and e.name().lower() in self._valid_folders:
                logging.info(f"Valid mod folder detected: {e.name()}")
                return mobase.ModDataChecker.VALID
            if e.isFile() and e.name().lower() == "submodule.xml":
                logging.info(f"Valid mod file detected: {e.name()}")
                return mobase.ModDataChecker.VALID
            if e.isFile() and e.name().lower().endswith(".asset"):
                logging.warning("Mod contains .asset files but no SubModule.xml; may not load correctly")
                return mobase.ModDataChecker.FIXABLE
        logging.debug("No valid mod structure detected")
        return mobase.ModDataChecker.INVALID

class BannerlordModDataContent(mobase.ModDataContent):
    class Content(IntEnum):
        TEXTURE = 0
        DLL = 1
        CONFIG = 2
        SCENE = 3
        ASSETS = 4
        MUSIC = 5

    def getAllContents(self) -> list[mobase.ModDataContent.Content]:
        return [
            mobase.ModDataContent.Content(
                self.Content.TEXTURE, "Textures", ":/MO/gui/content/texture"
            ),
            mobase.ModDataContent.Content(
                self.Content.DLL, "DLLs", ":/MO/gui/content/script"
            ),
            mobase.ModDataContent.Content(
                self.Content.CONFIG, "Configs", ":/MO/gui/content/inifile"
            ),
            mobase.ModDataContent.Content(
                self.Content.SCENE, "Scenes", ":/MO/gui/content/geometries"
            ),
            mobase.ModDataContent.Content(
                self.Content.ASSETS, "Assets", ":/MO/gui/content/mesh"
            ),
            mobase.ModDataContent.Content(
                self.Content.MUSIC, "Music", ":/MO/gui/content/sound"
            ),
        ]

    def getContentsFor(self, filetree: mobase.IFileTree) -> list[int]:
        content = []
        def walk_content(path: str, entry: mobase.FileTreeEntry) -> mobase.IFileTree.WalkReturn:
            name = entry.name().lower()
            path_lower = path.lower()
            if entry.isDir():
                if name in ["assetpackages", "dsassetpackages", "emassetpackages", "assetsources", "assets"]:
                    content.append(self.Content.TEXTURE)
                    logging.debug(f"Detected Textures content for folder: {path}/{name}")
            elif entry.isFile():
                ext = entry.suffix().lower()
                if ext == ["tpac", "png", "dds"]:
                    content.append(self.Content.TEXTURE)
                    logging.debug(f"Detected Textures content for file: {path}/{name}")
                elif ext == "dll":
                    content.append(self.Content.DLL)
                    logging.debug(f"Detected DLL content for file: {path}/{name}")
                elif ext == "ogg":
                    content.append(self.Content.MUSIC)
                    logging.debug(f"Detected Music content for file: {path}/{name}")
                elif ext == "fbx":
                    content.append(self.Content.ASSETS)
                    logging.debug(f"Detected Assets content for file: {path}/{name}")                    
                elif ext == "json":
                    content.append(self.Content.CONFIG)
                    logging.debug(f"Detected Configs content for file: {path}/{name}")
                elif ext == "xscene" and name.startswith("scene"):
                    content.append(self.Content.SCENE)
                    logging.debug(f"Detected Scenes content for file: {path}/{name}")
            return mobase.IFileTree.WalkReturn.CONTINUE

        filetree.walk(walk_content, "/")
        logging.info(f"Detected content types for mod: {content}")
        return content

class MountAndBladeIIGame(BasicGame):
    Name = "Mount & Blade II: Bannerlord"
    Author = "d&h"
    Version = "0.1.19"
    Description = "Adds support for Mount & Blade II: Bannerlord with enhanced mod detection, save metadata display, and content indicators"

    GameName = "Mount & Blade II: Bannerlord"
    GameShortName = "mountandblade2bannerlord"
    GameDataPath = "Modules"
    GameSupportURL = (
        r"https://github.com/ModOrganizer2/modorganizer-basic_games/wiki/"
        "Game:-Mount-and-Blade-II:-Bannerlord"
    )

    GameBinary = "bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.Launcher.exe"

    GameDocumentsDirectory = "%DOCUMENTS%/Mount and Blade II Bannerlord/Configs"
    GameSaveExtension = "sav"
    GameSavesDirectory = "%DOCUMENTS%/Mount and Blade II Bannerlord/Game Saves"

    GameNexusId = 3174
    GameSteamId = 261550
    GameGogId = 1564781494

    def init(self, organizer: mobase.IOrganizer):
        logging.info("Initializing MountAndBladeIIGame")
        try:
            super().__init__()
            self._organizer = organizer
            self._register_feature(MountAndBladeIIModDataChecker())
            self._register_feature(BannerlordModDataContent())
            self._register_feature(BasicGameSaveGameInfo(get_metadata=getMetadata, max_width=400))
            logging.info("MountAndBladeIIGame: Initialization complete")
            return True
        except Exception as e:
            logging.error(f"MountAndBladeIIGame: Initialization failed - {str(e)}")
            return False

    def savesDirectory(self) -> QDir:
        logging.debug("Accessing savesDirectory")
        try:
            docs_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            save_path = os.path.join(docs_path, "Mount and Blade II Bannerlord", "Game Saves")
            logging.debug(f"savesDirectory: Resolved path: {save_path}")
            if os.path.isdir(save_path):
                logging.info(f"savesDirectory: Valid path: {save_path}")
                return QDir(save_path)
            else:
                logging.warning(f"savesDirectory: Invalid path: {save_path}, falling back to hardcoded")
                fallback_path = os.path.expanduser("~/Documents/Mount and Blade II Bannerlord/Game Saves")
                if os.path.isdir(fallback_path):
                    logging.info(f"savesDirectory: Hardcoded path valid: {fallback_path}")
                    return QDir(fallback_path)
                else:
                    logging.error(f"savesDirectory: Hardcoded path invalid: {fallback_path}")
                    return QDir()
        except Exception as e:
            logging.error(f"savesDirectory: Failed - {str(e)}")
            return QDir()

    def listSaves(self, folder: QDir) -> list[mobase.ISaveGame]:
        logging.debug(f"Listing saves in: {folder.absolutePath()}")
        ext = self._mappings.savegameExtension.get()
        saves = [
            BannerlordSaveGame(path)
            for path in Path(folder.absolutePath()).glob(f"*.{ext}")
        ]
        for save in saves:
            logging.debug(f"Found save: {save.getName()}")
        logging.info(f"Found {len(saves)} save files")
        return saves

    def iniFiles(self):
        return ["engine_config.txt", "BannerlordConfig.txt", "LauncherData.xml"]

    def executables(self):
        return [
            mobase.ExecutableInfo(
                "Mount & Blade II: Bannerlord (Launcher)",
                QFileInfo(
                    self.gameDirectory(),
                    "bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.Launcher.exe",
                ),
            ),
            mobase.ExecutableInfo(
                "Mount & Blade II: Bannerlord",
                QFileInfo(
                    self.gameDirectory(),
                    "bin/Win64_Shipping_Client/Bannerlord.exe",
                ),
            ),
            mobase.ExecutableInfo(
                "Mount & Blade II: Bannerlord (Native)",
                QFileInfo(
                    self.gameDirectory(),
                    "bin/Win64_Shipping_Client/Bannerlord.Native.exe",
                ),
            ),
            mobase.ExecutableInfo(
                "Mount & Blade II: Bannerlord (Singleplayer)",
                QFileInfo(
                    self.gameDirectory(),
                    "bin/Win64_Shipping_Client/TaleWorlds.MountAndBlade.Launcher.Singleplayer.exe",
                ),
            ),
        ]
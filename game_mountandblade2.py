import mobase
from PyQt6.QtCore import QFileInfo

from ..basic_game import BasicGame


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

    def dataLooksValid(
        self, filetree: mobase.IFileTree
    ) -> mobase.ModDataChecker.CheckReturn:
        for e in filetree:
            if e.isDir():
                if e.name().lower() in self._valid_folders:
                    return mobase.ModDataChecker.VALID
                if e.exists("SubModule.xml", mobase.IFileTree.FILE):  # type: ignore
                    return mobase.ModDataChecker.VALID

        return mobase.ModDataChecker.INVALID


class MountAndBladeIIGame(BasicGame):
    Name = "Mount & Blade II: Bannerlord"
    Author = "Holt59, updated by d&h"
    Version = "0.1.1"
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

    def init(self, organizer: mobase.IOrganizer):
        super().init(organizer)
        self._register_feature(MountAndBladeIIModDataChecker())
        return True
    
    def iniFiles(self):
        return ["engine_config.txt","BannerlordConfig.txt","LauncherData.xml"]

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

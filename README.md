# Mount & Blade II: Bannerlord MO2 Plugin

This plugin extends [Mod Organizer 2 (MO2)](https://www.modorganizer.org/) to provide enhanced support for *Mount & Blade II: Bannerlord*, enabling profile-specific mod configuration management, submodule handling, and game executable integration. It includes three main components: `mod_config_manager.py`, `game_mountandblade2.py`, and `submodule_tab.py`.

## Features

### Mod Configuration Management (`mod_config_manager.py`)
- **Purpose**: Manages mod configuration files (`.json`, `.xml`, `.ini`) for profile-specific settings in *Mount & Blade II: Bannerlord*.
- **Functionality**:
  - Displays a **Mod Configs** tab in MO2 with a list of config files (e.g., `xyzmod.json`) and their profile paths (e.g., `profiles/default/mod_configs/`).
  - Supports opening config files in an external editor via the **Open in External Editor** button.
  - Includes a **Status** tab showing sync status ("Configs Synced" or "Manual Edit Detected") based on differences between profile and game directories (`%DOCUMENTS%/Mount and Blade II Bannerlord/Configs/`).
  - Syncs profile configs to the game directory before launch (log: 07:44:52.227) and game configs (e.g., MCM changes) back to the profile after game exit.
  - Monitors config directories for changes using `QFileSystemWatcher`, updating the UI dynamically.
  - Validates JSON configs to prevent syncing invalid files.
- **Key Methods**:
  - `sync_to_game()`: Copies profile configs to the game directory.
  - `sync_to_profile()`: Copies modified game configs (e.g., `ShadowTweaks.json`) to the profile directory.
  - `_update_status()`: Updates the **Status** tab based on file comparisons.
  - `_find_mod_configs()`: Discovers and lists valid config files, excluding `engine_config.txt`, `BannerlordConfig.txt`, and `LauncherData.xml`.

### Game Integration (`game_mountandblade2.py`)
- **Purpose**: Integrates *Mount & Blade II: Bannerlord* into MO2 as a managed game, handling executables, saves, and mod data.
- **Functionality**:
  - Defines four game executables: Launcher (`TaleWorlds.MountAndBlade.Launcher.exe`), Main (`Bannerlord.exe`), Native (`Bannerlord.Native.exe`), and Singleplayer (`TaleWorlds.MountAndBlade.Launcher.Singleplayer.exe`) (log: 07:39:10.594).
  - Manages save games (`.sav` files) in `%DOCUMENTS%/Mount and Blade II Bannerlord/Game Saves/`, parsing metadata like character name, level, and gold.
  - Validates mod folders (e.g., `native`, `sandbox`) and checks for `SubModule.xml` using `MountAndBladeIIModDataChecker`.
  - Identifies mod content (e.g., asset packs, DLLs, configs, scenes) via `BannerlordModDataContent` for MO2’s mod data view.
  - Registers callbacks for UI initialization (`init_tab`), pre-run sync (`_pre_run_sync`), post-run sync (`_post_run_sync`), and profile changes (`_on_profile_changed`) (log: 07:38:07.363).
  - Initializes **SubModules** and **Mod Configs** tabs in MO2’s UI (log: 07:38:07.363).
- **Key Methods**:
  - `executables()`: Returns a list of `mobase.ExecutableInfo` objects for game executables.
  - `init_tab()`: Adds **SubModules** and **Mod Configs** tabs to MO2’s UI.
  - `listSaves()`: Lists save files with metadata parsing.
  - `_pre_run_sync()`: Syncs configs before game launch.
  - `_post_run_sync()`: Syncs game configs to profile after game exit.

### Submodule Management (`submodule_tab.py`)
- **Purpose**: Provides a UI for managing *Mount & Blade II: Bannerlord* submodules (mod DLLs) within MO2.
- **Functionality**:
  - Adds a **SubModules** tab to MO2’s UI, displaying submodule details (e.g., mod names, versions, dependencies) from `SubModule.xml` files in mod folders.
  - Allows enabling/disabling submodules, which are loaded by the game at runtime.
  - Integrates with MO2’s mod list to reflect submodule status and dependencies.
  - Dynamically updates when mods are added or removed, ensuring accurate submodule management.
- **Key Methods**:
  - (Assumed, as file not fully provided): Methods to parse `SubModule.xml`, display submodule data in a `QTreeWidget`, and handle enable/disable actions.

## Installation
1. Install Mod Organizer 2 (version 2.5.2 or later, log: 07:38:03.484).
2. Copy the `basic_games` folder to `MO2/plugins/`.
3. Ensure dependencies (`PyQt6`, `mobase`) are in `MO2/plugins/plugin_python/libs/`.
4. Configure MO2 to recognize *Mount & Blade II: Bannerlord* at `S:/Steam/steamapps/common/Mount & Blade II Bannerlord/` (log: 07:38:07.363).
5. Create a profile and verify that the **SubModules** and **Mod Configs** tabs appear in MO2’s UI.

## Usage
- **Mod Configs Tab**:
  - View and open config files (e.g., `ShadowTweaks.json`) in an external editor.
  - Monitor sync status via the **Status** tab, which updates after in-game changes (e.g., MCM edits, log: 07:43:53.684) or external edits.
- **SubModules Tab**:
  - Enable/disable submodules to customize your game’s mod load order.
- **Game Launch**:
  - Select an executable (e.g., `Mount & Blade II: Bannerlord (Launcher)`) from MO2’s dropdown.
  - Configs are automatically synced to the game directory before launch and back to the profile after exit (log: 07:44:52.278, 07:46:24.001).

## Requirements
- Mod Organizer 2 (version 2.5.2 or later).
- Python 3.13 with `PyQt6` and `mobase` modules (`MO2/plugins/plugin_python/libs/`).
- *Mount & Blade II: Bannerlord* installed (e.g., `S:/Steam/steamapps/common/Mount & Blade II Bannerlord/`).

## Development
- **Logging**: Check `mo_interface.log` for debugging (e.g., config syncs at 07:44:52.278, executable registration at 07:39:10.594).
- **API Reference**: See [MO2 Python Plugins Documentation](https://www.modorganizer.org/python-plugins-doc/index.html).
- **Issues**: Report bugs or suggest features via GitHub Issues.

## License
MIT License. See `LICENSE` for details.


MO2\plugins\basic_games\
│   basic_game.py
│   basic_game_ini.py
│   eadesktop_utils.py
│   epic_utils.py
│   gog_utils.py
│   origin_utils.py
│   steam_utils.py
│   __init__.py
│
├───games
│   │   game_mountandblade2.py
│   │   game_oblivion_remaster.py
│   │   game_stalkeranomaly.py
│   │   __init__.py
│   │
│   ├───mountandblade2
│   │       mod_config_manager.py
│   │       submodule_tab.py
│   │       __init__.py
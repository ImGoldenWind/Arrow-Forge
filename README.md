<p align="center">
  <img src="ArrowForgeIcon.ico" width="96" alt="Arrow Forge icon">
</p>

<h1 align="center">Arrow Forge</h1>

<p align="center">
  A PyQt6 toolbox for editing <em>JoJo's Bizarre Adventure: All-Star Battle R</em> files.
</p>

<p align="center">
  <a href="https://github.com/ImGoldenWind/Arrow-Forge/releases/latest">
    <img alt="Latest release" src="https://img.shields.io/github/v/release/ImGoldenWind/Arrow-Forge?style=for-the-badge&label=latest%20release&color=2f6fed">
  </a>
  <a href="https://github.com/ImGoldenWind/Arrow-Forge/releases">
    <img alt="Total release downloads" src="https://img.shields.io/github/downloads/ImGoldenWind/Arrow-Forge/total?style=for-the-badge&label=release%20downloads&color=2f6fed">
  </a>
  <a href="https://github.com/ImGoldenWind/Arrow-Forge">
    <img alt="Repository stars" src="https://img.shields.io/github/stars/ImGoldenWind/Arrow-Forge?style=for-the-badge&label=stars&color=1f9d55">
  </a>
  <a href="https://github.com/ImGoldenWind/Arrow-Forge/issues">
    <img alt="Open issues" src="https://img.shields.io/github/issues/ImGoldenWind/Arrow-Forge?style=for-the-badge&label=issues&color=d98c1f">
  </a>
</p>

<p align="center">
  <a href="#download">Download</a>
  |
  <a href="#source">Source</a>
  |
  <a href="#features">Features</a>
  |
  <a href="#running-from-source">Run from source</a>
  |
  <a href="#building">Build</a>
  |
  <a href="#credits">Credits</a>
</p>

## About

Arrow Forge is a desktop toolkit for ASBR modding. It wraps file parsers,
editors, texture and audio helpers, and CPK unpacking tools in one interface so
you can inspect and adjust game data without jumping between one-off scripts.

The project is focused on practical editing: open a supported file, change the
data, save it back, and keep the surrounding helper files close to the app.

## Download

Get the latest packaged build from the
[Releases page](https://github.com/ImGoldenWind/Arrow-Forge/releases/latest).
Unpack the archive and run:

```powershell
ASBR-Tools.exe
```

Keep the extracted folder intact. Some editors use bundled resources and helper
tools that live next to the executable.

## Source

Clone the repository:

```powershell
git clone https://github.com/ImGoldenWind/Arrow-Forge.git
```

Download the current source archive:

- [Source code ZIP](https://github.com/ImGoldenWind/Arrow-Forge/archive/refs/heads/main.zip)
- [Source code TAR.GZ](https://github.com/ImGoldenWind/Arrow-Forge/archive/refs/heads/main.tar.gz)

## Features

- Character data editors for character codes, stats, costumes, skills, assist
  settings, speaking data, guide character data, and related parameter files.
- Battle and move data tools for battle adjustments, damage parameters,
  projectiles, effects, stage information, stage motion, and main mode data.
- Text and profile editors for messages, dictionaries, gallery art, sound test
  data, player titles, custom cards, DLC information, and info tables.
- Texture and audio helpers for XFBIN textures, NUS3BANK/AWB-related workflows,
  and bundled HCA decoding support.
- CPK unpacking support and shared UI systems for themes, translations, icons,
  settings, and update checks.

## Running From Source

Python 3.11 or newer is recommended.

Windows:

```powershell
python -m pip install -U pip
pip install PyQt6 Pillow numpy qtawesome
python ASBR-Tools.py
```

Linux:

```bash
python3 -m pip install -U pip
python3 -m pip install PyQt6 Pillow numpy qtawesome
python3 ASBR-Tools.py
```

Some audio tools also use bundled files from `tools/`, so keep that folder next
to the application when running from source. Put vgmstream builds in
`tools/vgmstream/` and VGAudioCLI builds in `tools/VGAudioCLI/`. On Linux,
vgmstream should be named `vgmstream-cli`. VGAudioCLI official releases only
ship `VGAudioCli.exe`; Linux import/encode features need a custom native
`VGAudioCli` build or a dotnet-runnable `VGAudioCli.dll` bundle. The app also
checks `PATH` and the directory set by `ASBR_TOOLS_TOOLS_DIR`.

On Linux and macOS, user settings are written outside the application folder:
`$XDG_CONFIG_HOME/arrow-forge/asbr_settings.json` on Linux, or
`~/.config/arrow-forge/asbr_settings.json` when `XDG_CONFIG_HOME` is not set.
Use `ASBR_TOOLS_CONFIG_DIR` to override that location.

## Project Layout

```text
ASBR-Tools.py        Main application entry point
ASBR-Tools.spec      PyInstaller build recipe
core/                Shared UI, themes, icons, settings, translations
editors/             Editor windows for supported ASBR file types
parsers/             Format readers and writers
locales/             Translation files
resources/           Bundled application assets
tools/               Helper binaries and support files
tools/vgmstream/     vgmstream CLI and its runtime libraries
tools/VGAudioCLI/    VGAudioCLI builds and its runtime files
```

## Building

The repository includes a PyInstaller spec for release builds. Install a current
PyInstaller into the same Python environment you build from, then create a clean
one-folder package:

```powershell
python -m pip install -U pyinstaller
python -m PyInstaller --clean ASBR-Tools.spec
```

The packaged app will be created under:

```text
dist/ASBR-Tools/
```

Zip that folder for GitHub Releases. The app can check for new releases,
download the release asset, and apply the update from the app folder on
Windows. Linux builds still check releases and open the release page, but
updates are installed manually.

## Safety Notes

Back up your game files before saving edited data. Many supported formats are
specific to ASBR, and invalid values can still break game behavior or make the
game reject a file.

## Credits

- [KojoBailey](https://github.com/KojoBailey) - 010 Editor templates used while
  making the editors in this toolbox.
- [Xemasklyr](https://www.nexusmods.com/profile/Xemasklyr/mods) - groundwork
  for the Char. Skills editor (`0xxx00prm.bin`).
- [Al-Hydra](https://github.com/Al-Hydra) - texture editor used as a base.
- [LazyBone152](https://github.com/LazyBone152) - ACE, used as a base for the
  built-in editor.
- [TheLeonX](https://github.com/TheLeonX) - XFBIN_Lib, toolbox idea, the
  talking character at the bottom, and inspiration.
- [JoJo Modding Community](https://discord.gg/bfWPHBwbr9) - for the inspiration

## Donations

Arrow Forge is free and will remain free.

If you still want to support development:

```text
BTC: bc1qglgl3zqjqhdkqn0y97thqlhfpg7hxvjg09tlv4
```

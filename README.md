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
  <img alt="Git clone counter" src="https://img.shields.io/badge/git%20clones-GitHub%20Traffic%20API-lightgrey?style=for-the-badge">
  <img alt="Source code downloads counter" src="https://img.shields.io/badge/source%20downloads-not%20public%20by%20GitHub-lightgrey?style=for-the-badge">
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

## Counters

The release download counter above is the real public total reported by GitHub
for release assets.

GitHub does not publish public all-time counters for repository clones or for
the generated `Source code (zip)` / `Source code (tar.gz)` archives. Those
badges are marked accordingly so the README does not show fake numbers. To
publish real clone statistics, the repository needs a token-backed GitHub
Action that reads the Traffic API and writes a public badge endpoint.

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

```powershell
python -m pip install -U pip
pip install PyQt6 Pillow numpy qtawesome
python ASBR-Tools.py
```

Some audio tools also use bundled files from `tools/`, so keep that folder next
to the application when running from source.

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
download the release asset, and apply the update from the app folder.

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
- [JoJo Modding Community](https://discord.gg/bfWPHBwbr9) - inspiration and
  shared ASBR modding knowledge.

## Donations

Arrow Forge is free and will remain free.

If you still want to support development:

```text
BTC: bc1qglgl3zqjqhdkqn0y97thqlhfpg7hxvjg09tlv4
```

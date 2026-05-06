# Arrow Forge

A toolbox for modding *JoJo's Bizarre Adventure: All-Star Battle R* files.

It is mostly a PyQt6 frontend around ASBR parsers/editors: character data,
costumes, moveset params, battle params, text, gallery/profile data, textures,
audio containers, and CPK unpacking.

## Download

Download the latest build from the Releases page, unpack it, and run
`ASBR-Tools.exe`.

Keep the extracted files together. Some tools use the bundled resources and
helper files next to the executable.

## Running from source

Use Python 3.11+ if possible.

```powershell
pip install PyQt6 Pillow numpy qtawesome
python ASBR-Tools.py
```

Some audio tools also use the bundled files in `tools/`, so keep that folder next
to the app.

## Project layout

- `ASBR-Tools.py` - main app entry point
- `core/` - shared UI code, themes, icons, settings, translations
- `editors/` - editor windows for different file types
- `parsers/` - ASBR format readers and writers
- `locales/` - translations
- `resources/` and `tools/` - bundled assets and helper files

## Building

The repo has a PyInstaller spec. For release builds, install a current
PyInstaller into the same Python environment you build from, then make a clean
one-folder package.

```powershell
python -m pip install -U pyinstaller
python -m PyInstaller --clean ASBR-Tools.spec
```

The packaged app will be placed under `dist/ASBR-Tools/`. Zip that folder for
GitHub Releases. The app checks for new releases, downloads the release asset,
and applies the update from the app folder.

## Credits

- [KojoBailey](https://github.com/KojoBailey) - 010 Editor templates used while
  making the editors in this toolbox
- [Xemasklyr](https://www.nexusmods.com/profile/Xemasklyr/mods) - groundwork for
  the Char. Skills editor (`0xxx00prm.bin`)
- [Al-Hydra](https://github.com/Al-Hydra) - texture editor used as a base
- [LazyBone152](https://github.com/LazyBone152) - ACE, used as a base for the
  built-in editor
- [TheLeonX](https://github.com/TheLeonX) - XFBIN_Lib, toolbox idea, the talking
  character at the bottom, and inspiration
- [JoJo Modding Community](https://discord.gg/bfWPHBwbr9) - inspiration


## Notes

Back up your game files before saving edited data. A lot of formats here are
very specific to ASBR, and bad values can still make the game unhappy.

## Donations

This project is free and will remain free.

If you still want to support development:

- BTC: bc1qglgl3zqjqhdkqn0y97thqlhfpg7hxvjg09tlv4

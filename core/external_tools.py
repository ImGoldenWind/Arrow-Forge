import os
import shutil
import sys

from core.runtime_paths import app_path


def _tools_roots() -> list[str]:
    roots = []
    env_dir = os.environ.get("ASBR_TOOLS_TOOLS_DIR", "")
    if env_dir:
        roots.append(os.path.abspath(os.path.expanduser(env_dir)))
    roots.append(app_path("tools"))
    return roots


def _tools_dirs(*subdirs: str) -> list[str]:
    dirs = []
    for root in _tools_roots():
        for subdir in subdirs:
            if subdir:
                dirs.append(os.path.join(root, subdir))
        dirs.append(root)
    return dirs


def _is_runnable(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    if path.lower().endswith(".exe") and os.name != "nt":
        return False
    if path.lower().endswith(".dll"):
        return shutil.which("dotnet") is not None
    return os.name == "nt" or os.access(path, os.X_OK)


def find_tool(*names: str, subdirs: tuple[str, ...] = ()) -> str:
    names = tuple(name for name in names if name)
    for tools_dir in _tools_dirs(*subdirs):
        for name in names:
            candidate = os.path.join(tools_dir, name)
            if _is_runnable(candidate):
                return candidate
    for name in names:
        found = shutil.which(name)
        if found and _is_runnable(found):
            return found
    return ""


def is_tool_path(path: str) -> bool:
    return _is_runnable(path)


def tool_command(path: str) -> list[str]:
    if path.lower().endswith(".dll"):
        dotnet = shutil.which("dotnet")
        if dotnet:
            return [dotnet, path]
    return [path]


def executable_name(base: str) -> str:
    return f"{base}.exe" if sys.platform.startswith("win") else base


def find_vgaudio_cli() -> str:
    return find_tool("VGAudioCli.exe", "VGAudioCli", "VGAudioCli.dll", subdirs=("VGAudioCLI", "vgaudio"))


def find_vgmstream_cli() -> str:
    return find_tool("vgmstream-cli.exe", "vgmstream-cli", subdirs=("vgmstream",))

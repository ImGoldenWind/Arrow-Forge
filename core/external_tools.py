import os
import shutil
import stat
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


def _runtime_from_env(env_name: str, *names: str) -> str:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        configured = os.path.abspath(os.path.expanduser(configured))
        if os.path.isfile(configured) and (
            os.name == "nt" or os.access(configured, os.X_OK)
        ):
            return configured
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def _dotnet_runtime() -> str:
    return _runtime_from_env("ASBR_TOOLS_DOTNET", "dotnet")


def _mono_runtime() -> str:
    return _runtime_from_env("ASBR_TOOLS_MONO", "mono")


def _wine_runtime() -> str:
    return _runtime_from_env("ASBR_TOOLS_WINE", "wine64", "wine")


def _is_managed_pe(path: str) -> bool:
    """Return whether *path* is a PE file with a CLR runtime header."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(4096)
            if len(header) < 0x40 or header[:2] != b"MZ":
                return False
            pe_offset = int.from_bytes(header[0x3C:0x40], "little")
            if pe_offset + 24 > len(header):
                handle.seek(0)
                header = handle.read(pe_offset + 512)
            if header[pe_offset:pe_offset + 4] != b"PE\0\0":
                return False
            optional_offset = pe_offset + 24
            magic = int.from_bytes(header[optional_offset:optional_offset + 2], "little")
            data_dirs_offset = optional_offset + (112 if magic == 0x20B else 96)
            clr_offset = data_dirs_offset + 14 * 8
            return int.from_bytes(header[clr_offset:clr_offset + 4], "little") != 0
    except (OSError, ValueError):
        return False


def _exe_runner(path: str) -> str:
    if os.name == "nt":
        return ""
    if _is_managed_pe(path):
        mono = _mono_runtime()
        if mono:
            return mono
    return _wine_runtime()


def _is_bundled_tool(path: str) -> bool:
    try:
        resolved = os.path.realpath(path)
        return any(
            os.path.commonpath((resolved, os.path.realpath(root)))
            == os.path.realpath(root)
            for root in _tools_roots()
        )
    except (OSError, ValueError):
        return False


def _ensure_bundled_executable(path: str) -> None:
    """Restore an execute bit lost when a source archive was unpacked."""
    if os.name == "nt" or os.access(path, os.X_OK) or not _is_bundled_tool(path):
        return
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IXUSR)
    except OSError:
        pass


def _is_runnable(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    lower_path = path.lower()
    if lower_path.endswith(".exe") and os.name != "nt":
        return bool(_exe_runner(path))
    if lower_path.endswith(".dll"):
        return bool(_dotnet_runtime())
    _ensure_bundled_executable(path)
    return os.name == "nt" or os.access(path, os.X_OK)


def find_tool(*names: str, subdirs: tuple[str, ...] = ()) -> str:
    names = tuple(name for name in names if name)
    tools_dirs = _tools_dirs(*subdirs)
    # Names are ordered by platform preference. Search PATH for a native name
    # before falling back to a bundled Windows executable through Wine.
    for name in names:
        for tools_dir in tools_dirs:
            candidate = os.path.join(tools_dir, name)
            if _is_runnable(candidate):
                return candidate
        found = shutil.which(name)
        if found and _is_runnable(found):
            return found
    return ""


def is_tool_path(path: str) -> bool:
    return _is_runnable(path)


def tool_command(path: str) -> list[str]:
    if path.lower().endswith(".dll"):
        dotnet = _dotnet_runtime()
        if dotnet:
            return [dotnet, path]
    if path.lower().endswith(".exe") and os.name != "nt":
        runner = _exe_runner(path)
        if runner:
            return [runner, path]
    return [path]


def executable_name(base: str) -> str:
    return f"{base}.exe" if sys.platform.startswith("win") else base


def find_vgaudio_cli() -> str:
    if os.name == "nt":
        names = ("VGAudioCli.exe", "VGAudioCli", "VGAudioCli.dll")
    else:
        names = ("VGAudioCli", "VGAudioCli.dll", "VGAudioCli.exe")
    return find_tool(*names, subdirs=("VGAudioCLI", "vgaudio"))


def find_vgmstream_cli() -> str:
    names = (
        ("vgmstream-cli.exe", "vgmstream-cli")
        if os.name == "nt"
        else ("vgmstream-cli", "vgmstream-cli.exe")
    )
    return find_tool(*names, subdirs=("vgmstream",))


def find_ffmpeg() -> str:
    names = ("ffmpeg.exe", "ffmpeg") if os.name == "nt" else ("ffmpeg", "ffmpeg.exe")
    return find_tool(*names, subdirs=("ffmpeg",))


def find_ffprobe() -> str:
    names = ("ffprobe.exe", "ffprobe") if os.name == "nt" else ("ffprobe", "ffprobe.exe")
    return find_tool(*names, subdirs=("ffmpeg",))


def find_rhubarb_lip_sync() -> str:
    names = (
        ("rhubarb.exe", "rhubarb")
        if os.name == "nt"
        else ("rhubarb", "rhubarb.exe")
    )
    found = find_tool(
        *names,
        subdirs=("rhubarb", "Rhubarb-Lip-Sync", "Rhubarb Lip Sync"),
    )
    if found:
        return found
    for root in _tools_roots():
        if not os.path.isdir(root):
            continue
        for name in os.listdir(root):
            lower_name = name.lower()
            if lower_name.startswith("rhubarb-lip-sync") or lower_name.startswith(
                "rhubarb lip sync"
            ):
                found = find_tool(*names, subdirs=(name,))
                if found:
                    return found
    return ""


def find_sofdec2_encoder() -> str:
    names = (
        ("sofdec2enc.exe", "sofdec2enc")
        if os.name == "nt"
        else ("sofdec2enc", "sofdec2enc.exe")
    )
    return find_tool(*names, subdirs=("Sofdec2", "sofdec2"))


def find_sofdec2_h264_encoder() -> str:
    names = (
        ("sofdec2encH264.exe", "sofdec2encH264")
        if os.name == "nt"
        else ("sofdec2encH264", "sofdec2encH264.exe")
    )
    return find_tool(*names, subdirs=("Sofdec2", "sofdec2"))


def find_cpkforge() -> str:
    names = (
        ("CPKForge.exe", "cpkforge", "CPKForge")
        if os.name == "nt"
        else ("cpkforge", "CPKForge", "CPKForge.exe")
    )
    return find_tool(*names, subdirs=("cpkforge", "CPKForge"))


def find_usm_repacker() -> str:
    native_names = ("usm_repack", "usm-repack", "usmtool")
    windows_names = ("usm_repack.exe", "usm-repack.exe", "usmtool.exe")
    names = (
        (*windows_names, *native_names)
        if os.name == "nt"
        else (*native_names, *windows_names)
    )
    return find_sofdec2_encoder() or find_tool(
        *names,
        subdirs=("usm", "cri", "sofdec"),
    )

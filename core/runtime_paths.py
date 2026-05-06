import os
import sys


def source_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_root() -> str:
    env_root = os.environ.get("ASBR_TOOLS_BASE_DIR", "")
    if env_root and os.path.isdir(env_root):
        return os.path.abspath(env_root)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return source_root()


def bundled_root() -> str:
    return getattr(sys, "_MEIPASS", app_root())


def app_path(*parts: str) -> str:
    if getattr(sys, "frozen", False) and parts:
        external_names = {"locales", "asbr_settings.json"}
        if parts[0] in external_names:
            return os.path.join(app_root(), *parts)
        return os.path.join(bundled_root(), *parts)
    return os.path.join(app_root(), *parts)

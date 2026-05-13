import os
import sys


APP_CONFIG_DIRNAME = "Arrow Forge"


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


def user_config_dir() -> str:
    env_dir = os.environ.get("ASBR_TOOLS_CONFIG_DIR", "")
    if env_dir:
        return os.path.abspath(os.path.expanduser(env_dir))

    if sys.platform.startswith("linux"):
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(base, "arrow-forge")

    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_CONFIG_DIRNAME)

    return app_root()


def user_config_path(*parts: str) -> str:
    return os.path.join(user_config_dir(), *parts)


def settings_path() -> str:
    return user_config_path("asbr_settings.json")

import json
import fnmatch
import os
import shutil

from core.runtime_paths import app_path, settings_path


DEFAULT_SETTINGS = {
    "language": "en",
    "theme": "Wonder of U",
    "game_files_dir": "",
    "backup_on_open": False,
    "check_updates_on_startup": True,
    "last_update_check": "",
    "recent_tools": [],
    "favorite_tools": [],
    "pinned_tools": {},
}


def _settings_path():
    return settings_path()


def _legacy_settings_path():
    return app_path("asbr_settings.json")


def load_settings() -> dict:
    for path in (_settings_path(), _legacy_settings_path()):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {**DEFAULT_SETTINGS, **data}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(data: dict):
    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _normalise_target_patterns(target_patterns) -> tuple[str, ...]:
    if not target_patterns:
        return ()
    if isinstance(target_patterns, str):
        target_patterns = (target_patterns,)
    result = []
    for pattern in target_patterns:
        if not isinstance(pattern, str):
            continue
        pattern = pattern.strip()
        if pattern:
            result.append(os.path.basename(pattern))
    return tuple(result)


def _find_game_file_dir(game_dir: str, target_patterns) -> str:
    patterns = _normalise_target_patterns(target_patterns)
    if not patterns or not os.path.isdir(game_dir):
        return ""

    for pattern in patterns:
        pattern_lower = pattern.lower()
        for dirpath, dirnames, filenames in os.walk(game_dir):
            dirnames.sort()
            for filename in sorted(filenames):
                if fnmatch.fnmatchcase(filename.lower(), pattern_lower):
                    return dirpath
    return ""


def game_files_dialog_dir(fallback: str = "", target_patterns=None) -> str:
    game_dir = load_settings().get("game_files_dir", "")
    if game_dir and os.path.isdir(game_dir):
        target_dir = _find_game_file_dir(game_dir, target_patterns)
        if target_dir:
            return target_dir
        return game_dir
    if fallback:
        fallback = os.path.expanduser(fallback)
        if os.path.isdir(fallback):
            return fallback
        parent = os.path.dirname(fallback)
        if parent and os.path.isdir(parent):
            return fallback
    return ""


def create_backup_on_open(path: str) -> str | None:
    """Create a side-by-side backup for a file selected for editing."""
    if not path or not load_settings().get("backup_on_open", True):
        return None
    if not os.path.isfile(path):
        return None

    folder, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    backup_path = os.path.join(folder, f"{stem}_backup{ext}")
    counter = 1
    while os.path.exists(backup_path):
        backup_path = os.path.join(folder, f"{stem}_backup_{counter}{ext}")
        counter += 1

    try:
        shutil.copy2(path, backup_path)
    except OSError:
        return None
    return backup_path

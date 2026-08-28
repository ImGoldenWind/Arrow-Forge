import json
import fnmatch
import os
import shutil
import copy

from core.runtime_paths import app_path, settings_path
from core.shortcuts import normalize_shortcut_settings
from core.qol_state import (
    append_backup_history,
    create_indexed_backup,
    normalise_backup_history,
    normalise_recent_files_by_tool,
    normalise_workspace,
)


DEFAULT_SETTINGS = {
    "language": "en",
    "theme": "Wonder of U",
    "game_files_dir": "",
    "backup_on_open": False,
    "check_updates_on_startup": True,
    "last_update_check": "",
    "recent_tools": [],
    "recent_tools_on_top": True,
    "favorite_tools": [],
    "pinned_tools": {},
    "disabled_tools": [],
    "recent_files_by_tool": {},
    "workspace": {},
    "restore_workspace_on_startup": True,
    "change_summary_disabled_by_tool": {},
    "backup_history": [],
    "animation_card_perspective": True,
    "animation_editor_fade": True,
    "animation_right_panel_fade": True,
    "animation_sidebar_highlight": True,
    "animation_theme_personality": True,
    "animation_theme_personality_motion": True,
    "shortcuts": normalize_shortcut_settings({}),
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
                    return _merge_settings(data)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    return _merge_settings({})


def _merge_settings(data: dict) -> dict:
    merged = copy.deepcopy(DEFAULT_SETTINGS)
    merged.update(data)
    merged["shortcuts"] = normalize_shortcut_settings(data.get("shortcuts", {}))
    disabled_tools = data.get("disabled_tools", [])
    if not isinstance(disabled_tools, list):
        disabled_tools = []
    merged["disabled_tools"] = list(dict.fromkeys(
        tool_id for tool_id in disabled_tools
        if isinstance(tool_id, str) and tool_id.strip()
    ))
    merged["recent_files_by_tool"] = normalise_recent_files_by_tool(data.get("recent_files_by_tool", {}))
    merged["workspace"] = normalise_workspace(data.get("workspace", {}))
    merged["backup_history"] = normalise_backup_history(data.get("backup_history", []))
    merged.pop("experimental_generic_compare_copy", None)
    if not isinstance(merged.get("change_summary_disabled_by_tool"), dict):
        merged["change_summary_disabled_by_tool"] = {}
    return merged


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


def create_backup_on_open(path: str, tool_id: str | None = None, reason: str = "open") -> dict[str, object] | None:
    """Create a side-by-side backup for a file selected for editing."""
    if not path or not load_settings().get("backup_on_open", True):
        return None
    if not os.path.isfile(path):
        return None

    try:
        entry = create_indexed_backup(path, tool_id=tool_id, reason=reason)
    except OSError:
        return None
    if not entry:
        return None
    settings = load_settings()
    append_backup_history(settings, entry)
    save_settings(settings)
    return entry


def restore_backup_entry(entry: dict) -> dict[str, object] | None:
    source_path = entry.get("source_path")
    backup_path = entry.get("backup_path")
    if not source_path or not backup_path:
        return None
    if not os.path.isfile(backup_path):
        return None

    settings = load_settings()
    safety_entry = None
    if os.path.isfile(source_path):
        safety_entry = create_indexed_backup(
            source_path,
            tool_id=entry.get("tool_id") or None,
            reason="restore_safety",
        )
        if safety_entry:
            append_backup_history(settings, safety_entry)
    shutil.copy2(backup_path, source_path)
    save_settings(settings)
    return safety_entry


def delete_backup_entry(backup_path: str) -> bool:
    settings = load_settings()
    backup_path = os.path.normpath(backup_path)
    deleted = False
    try:
        if os.path.isfile(backup_path):
            os.remove(backup_path)
            deleted = True
    except OSError:
        deleted = False
    settings["backup_history"] = [
        entry for entry in normalise_backup_history(settings.get("backup_history", []))
        if os.path.normcase(entry.get("backup_path", "")) != os.path.normcase(backup_path)
    ]
    save_settings(settings)
    return deleted


def clear_missing_backup_entries() -> int:
    settings = load_settings()
    history = normalise_backup_history(settings.get("backup_history", []))
    kept = [entry for entry in history if os.path.isfile(entry.get("backup_path", ""))]
    removed = len(history) - len(kept)
    if removed:
        settings["backup_history"] = kept
        save_settings(settings)
    return removed

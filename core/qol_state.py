from __future__ import annotations

from datetime import datetime, timezone
import os
import shutil


RECENT_FILES_LIMIT = 10
BACKUP_HISTORY_LIMIT = 200


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalise_recent_files_by_tool(value) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, list[dict[str, str]]] = {}
    for tool_id, entries in value.items():
        if not isinstance(tool_id, str) or not isinstance(entries, list):
            continue
        clean = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = os.path.normpath(str(entry.get("path", "")).strip())
            if not path or path in seen:
                continue
            seen.add(path)
            clean.append({
                "path": path,
                "name": str(entry.get("name") or os.path.basename(path)),
                "opened_at": str(entry.get("opened_at") or ""),
            })
            if len(clean) >= RECENT_FILES_LIMIT:
                break
        if clean:
            result[tool_id] = clean
    return result


def with_recent_file(settings: dict, tool_id: str | None, path: str | None) -> bool:
    if not tool_id or not path:
        return False
    path = os.path.normpath(path)
    recent = normalise_recent_files_by_tool(settings.get("recent_files_by_tool", {}))
    entries = [
        entry for entry in recent.get(tool_id, [])
        if os.path.normcase(entry.get("path", "")) != os.path.normcase(path)
    ]
    entries.insert(0, {
        "path": path,
        "name": os.path.basename(path),
        "opened_at": utc_now_iso(),
    })
    recent[tool_id] = entries[:RECENT_FILES_LIMIT]
    if recent == settings.get("recent_files_by_tool"):
        return False
    settings["recent_files_by_tool"] = recent
    return True


def normalise_workspace(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    tool_id = str(value.get("active_tool_id", "")).strip()
    if not tool_id:
        return {}
    result = {
        "active_tool_id": tool_id,
        "active_file_path": os.path.normpath(str(value.get("active_file_path", "")).strip())
        if value.get("active_file_path") else "",
        "updated_at": str(value.get("updated_at") or ""),
    }
    return result


def with_workspace(settings: dict, tool_id: str | None, file_path: str | None = None) -> bool:
    if not tool_id:
        return False
    workspace = {
        "active_tool_id": tool_id,
        "active_file_path": os.path.normpath(file_path) if file_path else "",
        "updated_at": utc_now_iso(),
    }
    if normalise_workspace(settings.get("workspace", {})) == workspace:
        return False
    settings["workspace"] = workspace
    return True


def normalise_backup_history(value) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    clean = []
    seen = set()
    for entry in value:
        if not isinstance(entry, dict):
            continue
        backup_path = os.path.normpath(str(entry.get("backup_path", "")).strip())
        source_path = os.path.normpath(str(entry.get("source_path", "")).strip())
        if not backup_path or backup_path in seen:
            continue
        seen.add(backup_path)
        clean.append({
            "source_path": source_path,
            "backup_path": backup_path,
            "tool_id": str(entry.get("tool_id") or ""),
            "size": int(entry.get("size") or 0),
            "created_at": str(entry.get("created_at") or ""),
            "reason": str(entry.get("reason") or "open"),
        })
        if len(clean) >= BACKUP_HISTORY_LIMIT:
            break
    return clean


def make_backup_path(path: str, suffix: str = "backup") -> str:
    folder, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    backup_path = os.path.join(folder, f"{stem}_{suffix}{ext}")
    counter = 1
    while os.path.exists(backup_path):
        backup_path = os.path.join(folder, f"{stem}_{suffix}_{counter}{ext}")
        counter += 1
    return backup_path


def append_backup_history(settings: dict, entry: dict[str, object]) -> None:
    history = normalise_backup_history(settings.get("backup_history", []))
    history.insert(0, entry)
    settings["backup_history"] = history[:BACKUP_HISTORY_LIMIT]


def create_indexed_backup(path: str, *, tool_id: str | None = None, reason: str = "open") -> dict[str, object] | None:
    if not path or not os.path.isfile(path):
        return None
    backup_path = make_backup_path(path, "backup" if reason == "open" else reason)
    shutil.copy2(path, backup_path)
    return {
        "source_path": os.path.normpath(path),
        "backup_path": os.path.normpath(backup_path),
        "tool_id": tool_id or "",
        "size": os.path.getsize(backup_path),
        "created_at": utc_now_iso(),
        "reason": reason,
    }

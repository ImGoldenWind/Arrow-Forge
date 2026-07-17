import json
import os
from datetime import datetime, timezone

from core.runtime_paths import user_config_path
from parsers.messageinfo_parser import crc32_of


MAP_VERSION = 1
MAP_FILENAME = "messageinfo_crc32_map.json"


def id_map_path() -> str:
    return user_config_path(MAP_FILENAME)


class MessageInfoIdMap:
    def __init__(self, path: str | None = None):
        self.path = path or id_map_path()
        self.ids: dict[str, list[str]] = {}

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.ids = {}
            return

        raw_ids = data.get("ids", {}) if isinstance(data, dict) else {}
        result: dict[str, list[str]] = {}
        if isinstance(raw_ids, dict):
            for raw_crc, raw_values in raw_ids.items():
                crc = _normalise_crc_key(raw_crc)
                if crc is None:
                    continue
                values = raw_values if isinstance(raw_values, list) else [raw_values]
                clean_values = []
                seen = set()
                for value in values:
                    if not isinstance(value, str):
                        continue
                    value = value.strip()
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    clean_values.append(value)
                if clean_values:
                    result[crc] = clean_values
        self.ids = result

    def save(self) -> None:
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            "version": MAP_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "ids": dict(sorted(self.ids.items())),
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def add_string(self, string_id: str, *, save: bool = True) -> tuple[int, bool]:
        string_id = (string_id or "").strip()
        if not string_id:
            return 0, False
        crc = crc32_of(string_id)
        changed = self.add_crc_string(crc, string_id, save=False)
        if changed and save:
            self.save()
        return crc, changed

    def add_crc_string(self, crc: int, string_id: str, *, save: bool = True) -> bool:
        string_id = (string_id or "").strip()
        if not string_id:
            return False
        key = f"{crc & 0xFFFFFFFF:08X}"
        values = self.ids.setdefault(key, [])
        if string_id in values:
            return False
        values.append(string_id)
        values.sort()
        if save:
            self.save()
        return True

    def merge_strings(self, string_ids) -> int:
        changed = 0
        for string_id in string_ids:
            _crc, did_change = self.add_string(string_id, save=False)
            if did_change:
                changed += 1
        if changed:
            self.save()
        return changed

    def resolve(self, crc: int) -> list[str]:
        return list(self.ids.get(f"{crc & 0xFFFFFFFF:08X}", ()))

    def display(self, crc: int) -> str:
        values = self.resolve(crc)
        if not values:
            return ""
        if len(values) == 1:
            return values[0]
        return f"{values[0]} (+{len(values) - 1})"

    def count(self) -> int:
        return sum(len(values) for values in self.ids.values())

    def matched_entries(self, entries: list[dict]) -> int:
        return sum(1 for entry in entries if self.resolve(int(entry.get("crc32_id", 0))))


def _normalise_crc_key(value) -> str | None:
    if isinstance(value, int):
        return f"{value & 0xFFFFFFFF:08X}"
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if text.startswith("0X"):
        text = text[2:]
    if len(text) != 8:
        return None
    try:
        int(text, 16)
    except ValueError:
        return None
    return text

import json
import os
from datetime import datetime, timezone

from core.runtime_paths import app_path, user_config_path
from parsers.messageinfo_parser import crc32_of


MAP_VERSION = 1
MAP_FILENAME = "messageinfo_crc32_map.json"
HASHLIST_FILENAME = "messageInfo_hashlist.bin"


def id_map_path() -> str:
    return user_config_path(MAP_FILENAME)


class MessageInfoIdMap:
    def __init__(self, path: str | None = None):
        self.path = path or id_map_path()
        self.ids: dict[str, list[str]] = {}

    def load(self) -> None:
        self.ids = {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}

        result: dict[str, list[str]] = {}
        self._merge_json_ids(data, result)
        self.ids = result
        self.load_hashlist()

    def load_hashlist(self, path: str | None = None) -> int:
        paths = [path] if path else _default_hashlist_paths()
        for candidate in paths:
            try:
                with open(candidate, "rb") as fh:
                    payload = fh.read()
            except OSError:
                continue
            return self._merge_hashlist_payload(payload)
        return 0

    def _merge_json_ids(self, data, result: dict[str, list[str]]) -> None:
        raw_ids = data.get("ids", {}) if isinstance(data, dict) else {}
        if not isinstance(raw_ids, dict):
            return

        for raw_crc, raw_values in raw_ids.items():
            crc = _normalise_crc_key(raw_crc)
            if crc is None:
                continue
            values = raw_values if isinstance(raw_values, list) else [raw_values]
            for value in values:
                if not isinstance(value, str):
                    continue
                self._add_crc_key_string(result, crc, value)

    def _merge_hashlist_payload(self, payload: bytes) -> int:
        changed = 0
        parts = payload.split(b"\x00")
        part_count = len(parts) - 1 if parts and parts[-1] == b"" else len(parts)
        pair_count = part_count // 2
        for index in range(pair_count):
            raw_crc = _decode_hashlist_part(parts[index * 2], ascii_only=True)
            string_id = _decode_hashlist_part(parts[index * 2 + 1])
            crc = _normalise_crc_key(raw_crc)
            if crc is None or not string_id:
                continue
            if self._add_crc_key_string(self.ids, crc, string_id):
                changed += 1
        return changed

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
        key = f"{crc & 0xFFFFFFFF:08X}"
        changed = self._add_crc_key_string(self.ids, key, string_id)
        if changed and save:
            self.save()
        return changed

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

    @staticmethod
    def _add_crc_key_string(target: dict[str, list[str]], key: str, string_id: str) -> bool:
        string_id = (string_id or "").strip()
        if not string_id:
            return False
        values = target.setdefault(key, [])
        if string_id in values:
            return False
        values.append(string_id)
        values.sort()
        return True


def _default_hashlist_paths() -> list[str]:
    paths = []
    seen = set()
    for path in (
        user_config_path(HASHLIST_FILENAME),
        app_path("resources", "data", HASHLIST_FILENAME),
    ):
        norm = os.path.normcase(os.path.abspath(path))
        if norm not in seen:
            seen.add(norm)
            paths.append(path)
    return paths


def _decode_hashlist_part(value: bytes, *, ascii_only: bool = False) -> str:
    encoding = "ascii" if ascii_only else "utf-8"
    return value.decode(encoding, errors="ignore").strip()


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

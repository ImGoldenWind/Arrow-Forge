"""Read-only message references shared by parameter editors.

The CRC map recovers string IDs; localized content comes only from the user's
messageInfo files. All aliases remain visible instead of guessing a collision.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from core.messageinfo_id_map import MessageInfoIdMap, id_map_path, legacy_id_map_path, MAP_FILENAME
from core.movelist_text import MoveListText
from core.runtime_paths import app_path
from parsers.messageinfo_parser import crc32_of


@lru_cache(maxsize=4)
def _id_map(paths_and_stamps):
    result = MessageInfoIdMap(paths_and_stamps[0][0])
    result.load()
    for path, _stamp, _size in paths_and_stamps[1:]:
        other = MessageInfoIdMap(path)
        other.load()
        for key, values in other.ids.items():
            for value in values:
                result.add_crc_string(int(key, 16), value, save=False)
    return result


def message_id_map():
    candidates = dict.fromkeys((id_map_path(), app_path("resources", "data", MAP_FILENAME), legacy_id_map_path()))
    signature = []
    for path in candidates:
        try:
            stat = Path(path).stat()
            signature.append((path, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((path, 0, 0))
    return _id_map(tuple(signature))


@dataclass(frozen=True)
class MessageReference:
    crc: int
    ids: tuple[str, ...]
    text: str
    source: str

    def description(self):
        return '\n'.join(filter(None, ('\n'.join(self.ids),
                                        f'[{self.source}] {self.text}' if self.text else '')))


class MessageText(MoveListText):
    def resolve(self, value, *, crc=False):
        if crc:
            if isinstance(value, int):
                ident = value & 0xFFFFFFFF
            elif re.fullmatch(r'(?:0[xX])?[0-9a-fA-F]{8}', str(value)):
                ident = int(str(value), 16)
            else:
                return None
            ids = tuple(message_id_map().resolve(ident))
        else:
            if not isinstance(value, str) or not value:
                return None
            ident = crc32_of(value)
            aliases = message_id_map().resolve(ident)
            ids = tuple(dict.fromkeys((value, *aliases)))
        text, source = self.text(ident)
        if not text and (not crc or not ids):
            return None
        return MessageReference(ident, ids, text, source)

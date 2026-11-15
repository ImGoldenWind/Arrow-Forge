"""Lossless TrophyParam editing state, independent of Qt and PC achievements.

IDs and values are opaque u32 words. Original comparisons follow record object
identity, never the (possibly duplicated/edited) file ID or the current ordinal.
"""
import copy
from collections import Counter

UINT32_MAX = 0xFFFFFFFF
FIELDS = ('trophy_id', 'requirement_value')


def uint32(text):
    text = str(text).strip()
    if not text or not text.isascii() or not text.isdecimal():
        raise ValueError('An unsigned decimal integer is required.')
    value = int(text)
    if value > UINT32_MAX:
        raise ValueError('The value does not fit in u32 storage.')
    return value


class TrophySession:
    def __init__(self, result):
        self.result = result
        # Retain objects to prevent identity reuse after deleting a record.
        self._originals = {id(entry): (entry, copy.deepcopy(entry))
                           for entry in result['entries']}
        self.mark_saved()

    def original(self, entry):
        pair = self._originals.get(id(entry))
        return pair[1] if pair is not None and pair[0] is entry else None

    def status(self, entry):
        original = self.original(entry)
        if original is None:
            return 'new'
        return 'modified' if any(entry[k] != original[k] for k in FIELDS) else 'unchanged'

    def mark_saved(self):
        self._saved = copy.deepcopy(self.result)

    def dirty(self):
        return self.result != self._saved

    def duplicate_ids(self):
        return {key for key, count in Counter(e['trophy_id'] for e in self.result['entries']).items()
                if count > 1}

    def next_id(self):
        used = {e['trophy_id'] for e in self.result['entries']}
        candidate = 0
        while candidate in used:
            candidate += 1
        if candidate > UINT32_MAX:
            raise ValueError('No unused u32 ID remains.')
        return candidate

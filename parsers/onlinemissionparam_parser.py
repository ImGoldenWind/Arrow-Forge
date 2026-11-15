"""OnlineMissionParam.bin.xfbin parser / writer.

Confirmed retail layout inside the nuccChunkBinary payload:
  [0-3]   uint32 BE  inner size
  [4-7]   uint32 LE  version
  [8-11]  uint32 LE  entry count
  [12-19] uint64 LE  first_ptr (= 8 in the sample)
  [20+]   entries * 104 bytes, followed by an ASCII string pool

Each entry is 0x68 bytes. Pointer fields are self-relative 64-bit pointers
from the pointer field itself to a null-terminated ASCII string.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 104
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000
SIGNED_FIELDS = {"reward_value"}

STRING_FIELDS = (
    ("character_id", 0x18),
    ("opponent_character_id", 0x20),
    ("stage_id", 0x30),
    ("title_key", 0x38),
    ("condition_id", 0x48),
    ("reward_card_id", 0x58),
    ("banner_id", 0x60),
)

NUMERIC_FIELDS = (
    ("group_id", 0x00),
    ("mission_id", 0x04),
    ("flag_08", 0x08),
    ("mission_type", 0x0C),
    ("subtype_id", 0x10),
    ("raw_14", 0x14),
    ("objective_value", 0x28),
    ("raw_2c", 0x2C),
    ("display_slot", 0x40),
    ("raw_44", 0x44),
    ("reward_value", 0x50),
    ("reward_type", 0x54),
)


# Shared NUCC framing handles named chunks, signed relative pointers, opaque
# bytes, in-place edits and atomic output consistently with other editors.
from parsers.relative_table import RelativeTable
_table = RelativeTable('OnlineMissionParam', ENTRY_SIZE,
    tuple((offset, key) for key, offset in STRING_FIELDS),
    tuple((offset, key, 'i' if key in SIGNED_FIELDS else 'I') for key, offset in NUMERIC_FIELDS))
_find_binary_chunk = _table.find_chunk


def parse_onlinemissionparam_xfbin(filepath):
    raw, version, entries = _table.parse(filepath)
    header, size = _table.find_chunk(raw)
    _, _, notes, _, _ = _table.parse_payload(raw[header + 12:header + 12 + size])
    for index, entry in enumerate(entries):
        entry['index'] = index
    return raw, dict(version=version, notes=notes, entries=entries)


def make_default_entry(source: dict | None = None) -> dict:
    if source is not None:
        entry = copy.deepcopy(source)
        entry.pop("index", None)
        entry.pop("_offset", None)
        return entry

    return {
        "group_id": 0,
        "mission_id": 0,
        "flag_08": 0,
        "mission_type": 6,
        "subtype_id": 0,
        "raw_14": 0,
        "character_id": "",
        "opponent_character_id": "",
        "objective_value": 1,
        "raw_2c": 0,
        "stage_id": "",
        "title_key": "online_mission_t_new",
        "display_slot": 0,
        "raw_44": 0,
        "condition_id": "",
        "reward_value": 0,
        "reward_type": 6,
        "reward_card_id": "",
        "banner_id": "",
    }


def _compatible_entries(entries):
    result = []
    for entry in entries:
        row = dict(entry)
        value = row.get('reward_value', 0)
        if 0x80000000 <= value <= 0xFFFFFFFF:
            row['reward_value'] = value - 0x100000000
        result.append(row)
    return result


def _build_inner(version, notes, entries):
    return _table.build(version, _compatible_entries(entries), bytes(notes or b''))


def save_onlinemissionparam_xfbin(filepath, original_data, result):
    _table.save(filepath, original_data, result.get('version', DEFAULT_VERSION),
                _compatible_entries(result['entries']))

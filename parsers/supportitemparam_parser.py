"""SupportItemParam.bin.xfbin parser / writer.

Confirmed retail layout:
  [0-3]   uint32 BE  inner size
  [4-7]   uint32 LE  version
  [8-11]  uint32 LE  entry count
  [12-19] uint64 LE  first_ptr (= 8 in the sample)
  [20+]   entries * 152 bytes, then per-entry blob/string pool

Each entry contains raw numeric fields, one self-relative pointer to an
opaque pre-text blob, and four self-relative ASCII text-key pointers.
The file does not label gameplay meanings for the numeric fields.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 152
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000

BLOB_POINTER_OFFSET = 0x08
TEXT_POINTER_FIELDS = (
    ("story_title_key", 0x28),
    ("story_hint_key", 0x30),
    ("campaign_title_key", 0x38),
    ("campaign_hint_key", 0x40),
)
UINT_FIELDS = (
    ("support_id", 0x00),
    ("reserved_04", 0x04),
    ("shop_marker", 0x10),
    ("price", 0x14),
    ("tier_or_category", 0x18),
    ("enabled_flag", 0x1C),
    ("display_order", 0x20),
    ("reserved_24", 0x24),
    ("effect_type", 0x48),
    ("raw_58", 0x58),
    ("raw_5c", 0x5C),
    ("target_group", 0x60),
    ("raw_64", 0x64),
    ("raw_68", 0x68),
    ("raw_6c", 0x6C),
    ("raw_70", 0x70),
    ("raw_74", 0x74),
    ("raw_78", 0x78),
    ("raw_7c", 0x7C),
    ("raw_80", 0x80),
    ("raw_84", 0x84),
    ("raw_88", 0x88),
    ("raw_8c", 0x8C),
    ("empty_slot_marker", 0x90),
    ("unlock_or_story_flag", 0x94),
)
FLOAT_FIELDS = (
    ("effect_value_1", 0x4C),
    ("effect_value_2", 0x50),
    ("effect_value_3", 0x54),
)


def _find_binary_chunk(data: bytes | bytearray) -> tuple[int, int]:
    if len(data) < 28 or data[:4] != b"NUCC":
        raise ValueError("Not a NUCC/XFBIN file.")

    chunk_table_size = struct.unpack_from(">I", data, 16)[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    best_off = -1
    best_size = 0
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        type_idx = struct.unpack_from(">I", data, offset + 4)[0]
        if type_idx == 1 and size >= INNER_SIZE_FIELD + HEADER_SIZE and size > best_size:
            best_off = offset
            best_size = size

        next_off = offset + 12 + (size if size else 0)
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    if best_off == -1:
        raise ValueError("Could not locate nuccChunkBinary in SupportItemParam XFBIN.")
    return best_off, best_size


def _read_cstr(data: bytes | bytearray, offset: int, limit: int) -> str:
    if offset <= 0 or offset >= limit:
        return ""
    end = data.find(b"\x00", offset, limit)
    if end < 0:
        end = limit
    return data[offset:end].decode("ascii", errors="replace")


def _read_rel_string(data: bytes | bytearray, field_abs: int, ptr: int, limit: int) -> str:
    if not ptr:
        return ""
    return _read_cstr(data, field_abs + ptr, limit)


def _read_rel_target(field_abs: int, ptr: int, limit: int) -> int:
    if not ptr:
        return 0
    target = field_abs + ptr
    return target if 0 < target < limit else 0


def parse_supportitemparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    chunk_end = payload_off + chunk_size
    param_off = payload_off + INNER_SIZE_FIELD

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid SupportItemParam inner size.")

    version = struct.unpack_from("<I", data, param_off)[0]
    count = struct.unpack_from("<I", data, param_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, param_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid SupportItemParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = param_off + HEADER_SIZE
    entries_base = param_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("SupportItemParam entry table exceeds binary chunk size.")

    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        entry: dict = {}
        for key, rel_off in UINT_FIELDS:
            entry[key] = struct.unpack_from("<I", data, base + rel_off)[0]
        for key, rel_off in FLOAT_FIELDS:
            entry[key] = struct.unpack_from("<f", data, base + rel_off)[0]

        string_targets = []
        for key, rel_off in TEXT_POINTER_FIELDS:
            ptr = struct.unpack_from("<Q", data, base + rel_off)[0]
            target = _read_rel_target(base + rel_off, ptr, chunk_end)
            if target:
                string_targets.append(target)
            entry[key] = _read_rel_string(data, base + rel_off, ptr, chunk_end)

        blob_ptr = struct.unpack_from("<Q", data, base + BLOB_POINTER_OFFSET)[0]
        blob_target = _read_rel_target(base + BLOB_POINTER_OFFSET, blob_ptr, chunk_end)
        first_string = min(string_targets) if string_targets else 0
        if blob_target and first_string and blob_target <= first_string:
            entry["pre_text_blob"] = bytes(data[blob_target:first_string])
        elif blob_target:
            entry["pre_text_blob"] = b""
        else:
            entry["pre_text_blob"] = b""
        entries.append(entry)

    return data, {
        "version": version,
        "notes": bytes(data[notes_off:notes_off + notes_len]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None) -> dict:
    if source is not None:
        return copy.deepcopy(source)
    return {
        "support_id": 0,
        "reserved_04": 0,
        "shop_marker": 99,
        "price": 500,
        "tier_or_category": 1,
        "enabled_flag": 1,
        "display_order": 0,
        "reserved_24": 0,
        "story_title_key": "campaign_support_t_new",
        "story_hint_key": "story_support_h_new",
        "campaign_title_key": "campaign_support_t_new",
        "campaign_hint_key": "campaign_support_h_new",
        "pre_text_blob": b"",
        "effect_type": 0,
        "effect_value_1": 0.0,
        "effect_value_2": 0.0,
        "effect_value_3": 0.0,
        "raw_58": 0,
        "raw_5c": 0,
        "target_group": 0,
        "raw_64": 0,
        "raw_68": 0,
        "raw_6c": 0,
        "raw_70": 0,
        "raw_74": 0,
        "raw_78": 0,
        "raw_7c": 0,
        "raw_80": 0,
        "raw_84": 0,
        "raw_88": 0,
        "raw_8c": 0,
        "empty_slot_marker": 0,
        "unlock_or_story_flag": 0,
    }


def _align4(pool: bytearray) -> None:
    rem = len(pool) % 4
    if rem:
        pool.extend(b"\x00" * (4 - rem))


def _add_string(pool: bytearray, text: str) -> int:
    _align4(pool)
    offset = len(pool)
    pool.extend(text.encode("ascii", errors="replace") + b"\x00")
    while (len(pool) - offset) % 8:
        pool.extend(b"\x00")
    return offset


def _build_inner(version: int, notes: bytes, entries: list[dict]) -> bytes:
    notes = bytes(notes or b"")
    count = len(entries)
    first_ptr = 8 + len(notes)
    entries_base = 8 + first_ptr
    pool_base = entries_base + count * ENTRY_SIZE

    pool = bytearray()
    pool_offsets: list[dict[str, int | None]] = []
    for entry in entries:
        offsets: dict[str, int | None] = {}
        blob = bytes(entry.get("pre_text_blob", b"") or b"")
        if blob:
            _align4(pool)
            offsets["pre_text_blob"] = len(pool)
            pool.extend(blob)
            _align4(pool)
        else:
            offsets["pre_text_blob"] = None

        for key, _rel_off in TEXT_POINTER_FIELDS:
            text = str(entry.get(key, ""))
            offsets[key] = _add_string(pool, text) if text else None
        pool_offsets.append(offsets)

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", first_ptr)
    buf += notes

    for idx, entry in enumerate(entries):
        entry_base = entries_base + idx * ENTRY_SIZE
        row = bytearray(ENTRY_SIZE)
        for key, rel_off in UINT_FIELDS:
            struct.pack_into("<I", row, rel_off, int(entry.get(key, 0)) & 0xFFFFFFFF)
        for key, rel_off in FLOAT_FIELDS:
            struct.pack_into("<f", row, rel_off, float(entry.get(key, 0.0)))

        blob_off = pool_offsets[idx]["pre_text_blob"]
        blob_ptr = 0 if blob_off is None else pool_base + int(blob_off) - (entry_base + BLOB_POINTER_OFFSET)
        struct.pack_into("<Q", row, BLOB_POINTER_OFFSET, blob_ptr & 0xFFFFFFFFFFFFFFFF)

        for key, rel_off in TEXT_POINTER_FIELDS:
            string_off = pool_offsets[idx][key]
            ptr = 0 if string_off is None else pool_base + int(string_off) - (entry_base + rel_off)
            struct.pack_into("<Q", row, rel_off, ptr & 0xFFFFFFFFFFFFFFFF)
        buf += row

    buf += pool
    _align4(buf)
    return bytes(buf)


def save_supportitemparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", DEFAULT_VERSION)),
        bytes(result.get("notes", b"")),
        list(result.get("entries", [])),
    )
    payload = struct.pack(">I", len(inner)) + inner
    _align4(payload)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)
    prefix = bytes(original_data[:chunk_hdr_off])
    chunk_hdr = bytearray(original_data[chunk_hdr_off:chunk_hdr_off + 12])
    struct.pack_into(">I", chunk_hdr, 0, len(payload))

    orig_payload_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(original_data[orig_payload_end:])

    with open(filepath, "wb") as fh:
        fh.write(prefix + bytes(chunk_hdr) + payload + trailing)

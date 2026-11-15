"""Battle reward XFBIN parser / writer.

ArcadeRewardParam.bin.xfbin layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  - inner_size (bytes after this field)
  [4-7]   uint32 LE  - version    (1000 in the sample)
  [8-11]  uint32 LE  - entry count (35 in the sample)
  [12-19] uint64 LE  - first_ptr, from this field to Entries (= 8)
  [20+]   optional notes bytes, then entries

Each entry is 40 bytes and uses a self-relative string pointer:
  +0   uint64 LE - pointer to reward_id string
  +8   uint32 LE - difficulty_index
  +12..+28 five uint32 LE - required clear counts for ranks S, A, B, C, D
  +32  int32 LE - GP reward_value (native grant treats the word as signed)
  +36  uint32 LE - padding_24 (skipped by native loader)

CumulativeRewardParam.bin.xfbin uses the same header, but entries are 24 bytes:
  +0   uint32 LE - reward_index / slot
  +4   uint32 LE - reward_group
  +8   uint32 LE - threshold / cumulative value
  +12  uint32 LE - reward_type
  +16  uint64 LE - pointer to reward_id string, self-relative from this field

Strings are null-terminated ASCII and 8-byte aligned.
"""

from __future__ import annotations

import copy
import os
import struct


ARCADE_ENTRY_SIZE = 40
CUMULATIVE_ENTRY_SIZE = 24
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000
ARCADE_RANK_FIELDS = tuple(f"rank_{rank}_count" for rank in "sabcd")
TYPE_ARCADE = "arcade"
TYPE_CUMULATIVE = "cumulative"

_LAYOUTS = {
    TYPE_ARCADE: {
        "entry_size": ARCADE_ENTRY_SIZE,
        "ptr_field_offset": 0,
        "preferred_names": ("arcaderewardparam",),
    },
    TYPE_CUMULATIVE: {
        "entry_size": CUMULATIVE_ENTRY_SIZE,
        "ptr_field_offset": 16,
        "preferred_names": ("cumulativerewardparam",),
    },
}


def _read_cstr(data: bytes | bytearray, off: int) -> str:
    if off >= len(data):
        return ""
    try:
        end = data.index(b"\x00", off)
        raw = data[off:end]
    except ValueError:
        raw = data[off:]
    return raw.decode("ascii", errors="replace")


def _find_binary_chunk(data: bytes | bytearray) -> tuple[int, int]:
    if len(data) < 28 or data[:4] != b"NUCC":
        raise ValueError("Not a NUCC/XFBIN file.")

    table_size = struct.unpack_from(">I", data, 16)[0]
    offset = 28 + table_size
    if offset % 4:
        offset += 4 - offset % 4

    best_off = -1
    best_size = 0
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]
        map_idx = struct.unpack_from(">I", data, offset + 4)[0]
        if map_idx == 1 and size >= INNER_SIZE_FIELD + HEADER_SIZE and size > best_size:
            best_off = offset
            best_size = size

        next_off = offset + 12 + (size if size else 0)
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    if best_off < 0:
        raise ValueError("Could not locate nuccChunkBinary in Battle Rewards XFBIN.")
    return best_off, best_size


def _common_header(data: bytes | bytearray) -> tuple[int, int, int, int, int, int, int, int]:
    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    body_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid Battle Rewards inner size.")

    version = struct.unpack_from("<I", data, body_off)[0]
    count = struct.unpack_from("<I", data, body_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, body_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid Battle Rewards header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = body_off + HEADER_SIZE
    entries_base = body_off + 8 + first_ptr
    return chunk_hdr_off, chunk_size, body_off, chunk_end, version, count, notes_off, entries_base


def _is_printable_ascii_z(data: bytes | bytearray, off: int, chunk_end: int) -> bool:
    if off <= 0 or off >= chunk_end:
        return False
    end = off
    while end < chunk_end and data[end] != 0:
        byte = data[end]
        if byte < 0x20 or byte > 0x7E:
            return False
        end += 1
    return end < chunk_end and end > off


def _score_layout(data: bytes | bytearray, entries_base: int, chunk_end: int, count: int, param_type: str) -> int:
    layout = _LAYOUTS[param_type]
    entry_size = layout["entry_size"]
    ptr_field_offset = layout["ptr_field_offset"]
    entries_end = entries_base + count * entry_size
    if count < 0 or entries_end > chunk_end:
        return -1

    valid = 0
    for idx in range(count):
        base = entries_base + idx * entry_size
        ptr_off = base + ptr_field_offset
        if ptr_off + 8 > entries_end:
            return -1
        ptr = struct.unpack_from("<Q", data, ptr_off)[0]
        if ptr == 0:
            continue
        string_off = ptr_off + ptr
        if string_off >= entries_end and _is_printable_ascii_z(data, string_off, chunk_end):
            valid += 1
    return valid


def _guess_param_type(filepath: str, data: bytes | bytearray, entries_base: int, chunk_end: int, count: int) -> str:
    name = os.path.basename(filepath).lower()
    for param_type, layout in _LAYOUTS.items():
        if any(marker in name for marker in layout["preferred_names"]):
            return param_type

    scores = {
        param_type: _score_layout(data, entries_base, chunk_end, count, param_type)
        for param_type in _LAYOUTS
    }
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score < 0:
        raise ValueError("Could not detect Battle Rewards entry layout.")
    return best_type


def parse_arcaderewardparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    _chunk_hdr_off, _chunk_size, body_off, chunk_end, version, count, notes_off, entries_base = _common_header(data)
    param_type = _guess_param_type(filepath, data, entries_base, chunk_end, count)
    entry_size = _LAYOUTS[param_type]["entry_size"]
    ptr_field_offset = _LAYOUTS[param_type]["ptr_field_offset"]
    entries_end = entries_base + count * entry_size
    if entries_end > chunk_end:
        raise ValueError("Battle Rewards entry table exceeds binary chunk size.")

    first_ptr = struct.unpack_from("<Q", data, body_off + 8)[0]
    notes_len = first_ptr - 8

    entries = []
    for idx in range(count):
        base = entries_base + idx * entry_size
        if param_type == TYPE_CUMULATIVE:
            reward_index, reward_group, threshold, reward_type, ptr = struct.unpack_from("<IIIIQ", data, base)
            reward_id = _read_cstr(data, base + ptr_field_offset + ptr) if ptr else ""
            entries.append({
                "reward_id": reward_id,
                "reward_index": reward_index,
                "reward_group": reward_group,
                "threshold": threshold,
                "reward_type": reward_type,
            })
        else:
            ptr, difficulty_index, *values = struct.unpack_from(
                "<Q8I",
                data,
                base,
            )
            reward_id = _read_cstr(data, base + ptr) if ptr else ""
            entries.append({
                "reward_id": reward_id,
                "difficulty_index": difficulty_index,
                **dict(zip(ARCADE_RANK_FIELDS, values[:5])),
                "reward_value": struct.unpack_from("<i", data, base + 0x20)[0],
                "padding_24": values[6],
            })

    return data, {
        "param_type": param_type,
        "version": version,
        "notes": bytes(data[notes_off:notes_off + notes_len]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None, param_type: str = TYPE_ARCADE) -> dict:
    if source:
        return copy.deepcopy(source)
    if param_type == TYPE_CUMULATIVE:
        return {
            "reward_id": "PLCARD_TITLE_209",
            "reward_index": 0,
            "reward_group": 2,
            "threshold": 10,
            "reward_type": 4,
        }
    return {
        "reward_id": "NORMAL_1",
        "difficulty_index": 2,
        **dict(zip(ARCADE_RANK_FIELDS, (1, 0, 0, 0, 0))),
        "reward_value": 0,
        "padding_24": 0,
    }


def _pad8(pool: bytearray, text: str) -> int:
    off = len(pool)
    pool.extend(text.encode("ascii", errors="replace") + b"\x00")
    rem = len(pool) % 8
    if rem:
        pool.extend(b"\x00" * (8 - rem))
    return off


def rank_requirements(entry: dict) -> tuple[int, ...]:
    """Five independent u32 counters; accept older exported dictionaries too."""
    first_pair = int(entry.get("reserved_1", 0))
    second_pair = int(entry.get("reserved_2", 0))
    legacy = (int(entry.get("battle_step", 0)), first_pair & 0xFFFFFFFF,
              first_pair >> 32, second_pair & 0xFFFFFFFF, second_pair >> 32)
    return tuple(int(entry.get(key, fallback)) for key, fallback in zip(ARCADE_RANK_FIELDS, legacy))


def arcade_gp_delta(entry: dict) -> int:
    """Normalize former unsigned dictionaries to the signed native GP delta."""
    value = int(entry.get("reward_value", 0)) & 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def _build_inner(version: int, notes: bytes, entries: list[dict], param_type: str) -> bytes:
    layout = _LAYOUTS.get(param_type, _LAYOUTS[TYPE_ARCADE])
    count = len(entries)
    first_ptr = 8 + len(notes)
    entries_base = 8 + first_ptr
    entry_size = layout["entry_size"]
    ptr_field_offset = layout["ptr_field_offset"]
    pool_base = entries_base + count * entry_size

    pool = bytearray()
    string_offsets = []
    for entry in entries:
        string_offsets.append(_pad8(pool, str(entry.get("reward_id", ""))))

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", first_ptr)
    buf += notes

    for idx, entry in enumerate(entries):
        entry_base = entries_base + idx * entry_size
        ptr = pool_base + string_offsets[idx] - (entry_base + ptr_field_offset)
        if param_type == TYPE_CUMULATIVE:
            buf += struct.pack(
                "<IIIIQ",
                int(entry.get("reward_index", 0)) & 0xFFFFFFFF,
                int(entry.get("reward_group", 0)) & 0xFFFFFFFF,
                int(entry.get("threshold", 0)) & 0xFFFFFFFF,
                int(entry.get("reward_type", 0)) & 0xFFFFFFFF,
                ptr,
            )
        else:
            buf += struct.pack(
                "<Q8I",
                ptr,
                int(entry.get("difficulty_index", 0)) & 0xFFFFFFFF,
                *(value & 0xFFFFFFFF for value in rank_requirements(entry)),
                int(entry.get("reward_value", 0)) & 0xFFFFFFFF,
                int(entry.get("padding_24", 0)) & 0xFFFFFFFF,
            )

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_arcaderewardparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", DEFAULT_VERSION)),
        bytes(result.get("notes", b"")),
        list(result.get("entries", [])),
        str(result.get("param_type", TYPE_ARCADE)),
    )
    payload = struct.pack(">I", len(inner)) + inner
    if len(payload) % 4:
        payload += b"\x00" * (4 - len(payload) % 4)

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

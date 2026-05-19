"""CommandListParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  - inner_size (bytes after this field)
  [4-7]   uint32 LE  - version
  [8-11]  uint32 LE  - entry count
  [12-19] uint64 LE  - first_ptr, from the first_ptr field to Entries
  [20+]   optional notes bytes, then entries

Each entry is 72 bytes and uses self-relative string pointers:
  +0   uint64 LE  - character id string pointer
  +8   uint64 LE  - move type
  +16  uint64 LE  - move name text key pointer
  +24  uint64 LE  - command/detail text key pointer
  +32  uint64 LE  - command input text key pointer
  +40  uint32 LE  - unk5
  +44  uint32 LE  - unk6
  +48  uint32 LE  - unk7
  +52  uint32 LE  - unk8
  +56  uint32 LE  - unk9
  +60  uint32 LE  - unk10
  +64  uint32 LE  - commandListNum / order value
  +68  int32  LE  - unk12

Strings are null-terminated ASCII and 8-byte aligned in retail files.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 72
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
TYPE_DISABLED = 0xFFFFFFFF

TYPE_NAMES = {
    0: "UNK",
    1: "SKL",
    2: "HHA",
    3: "GHA",
    5: "BTLCMD_TH",
    6: "BTLCMD",
    7: "SKL_02",
    TYPE_DISABLED: "DISABLED",
}

STRING_FIELDS = (
    ("char_id", 0),
    ("name_key", 16),
    ("detail_key", 24),
    ("input_key", 32),
)

UINT_FIELDS = ("unk5", "unk6", "unk7", "unk8", "unk9", "unk10", "command_list_num")


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
        raise ValueError("Could not locate nuccChunkBinary in CommandListParam XFBIN.")
    return best_off, best_size


def _read_cstr(data: bytes | bytearray, off: int, limit: int) -> str:
    if off < 0 or off >= limit:
        return ""
    try:
        end = data.index(b"\x00", off, limit)
    except ValueError:
        end = limit
    return bytes(data[off:end]).decode("ascii", errors="replace")


def _entry_uses_self_empty_pointers(entry: dict) -> bool:
    return (
        int(entry.get("move_type", 0)) == TYPE_DISABLED
        and not entry.get("char_id", "")
        and not entry.get("name_key", "")
        and not entry.get("detail_key", "")
        and not entry.get("input_key", "")
    )


def parse_commandlistparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    command_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid CommandListParam inner size.")

    version = struct.unpack_from("<I", data, command_off)[0]
    count = struct.unpack_from("<I", data, command_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, command_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid CommandListParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = command_off + HEADER_SIZE
    entries_base = command_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("CommandListParam entry table exceeds binary chunk size.")

    notes = bytes(data[notes_off:notes_off + notes_len])
    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        ptrs = {
            key: struct.unpack_from("<Q", data, base + field_off)[0]
            for key, field_off in STRING_FIELDS
        }
        strings = {
            key: _read_cstr(data, base + field_off + ptr, chunk_end)
            for key, field_off in STRING_FIELDS
            for ptr in (ptrs[key],)
        }
        move_type = struct.unpack_from("<Q", data, base + 8)[0]
        values = struct.unpack_from("<IIIIIIIi", data, base + 40)
        entry = {
            "char_id": strings["char_id"],
            "move_type": move_type,
            "name_key": strings["name_key"],
            "detail_key": strings["detail_key"],
            "input_key": strings["input_key"],
            "unk5": values[0],
            "unk6": values[1],
            "unk7": values[2],
            "unk8": values[3],
            "unk9": values[4],
            "unk10": values[5],
            "command_list_num": values[6],
            "unk12": values[7],
            "_self_empty_pointers": all(ptr == 0 for ptr in ptrs.values()),
        }
        entries.append(entry)

    return data, {
        "version": version,
        "notes": notes,
        "entries": entries,
    }


def make_default_entry(source: dict | None = None) -> dict:
    if source:
        entry = copy.deepcopy(source)
        entry.pop("_self_empty_pointers", None)
        return entry
    return {
        "char_id": "newchr",
        "move_type": 6,
        "name_key": "new_btlcmd_name",
        "detail_key": "new_btlcmd",
        "input_key": "new_command",
        "unk5": 4,
        "unk6": 0,
        "unk7": 0,
        "unk8": 0,
        "unk9": 0,
        "unk10": 1,
        "command_list_num": 0,
        "unk12": -1,
    }


def _pad_string(pool: bytearray, text: str) -> int:
    off = len(pool)
    pool.extend(str(text).encode("ascii", errors="replace") + b"\x00")
    rem = len(pool) % 8
    if rem:
        pool.extend(b"\x00" * (8 - rem))
    return off


def _build_inner(version: int, notes: bytes, entries: list[dict]) -> bytes:
    count = len(entries)
    first_ptr = 8 + len(notes)
    entries_base = 8 + first_ptr
    pool_base = entries_base + count * ENTRY_SIZE

    pool = bytearray()
    offsets: list[dict[str, int | None]] = []
    for entry in entries:
        if entry.get("_self_empty_pointers") and _entry_uses_self_empty_pointers(entry):
            offsets.append({key: None for key, _field_off in STRING_FIELDS})
            continue
        offsets.append({key: _pad_string(pool, str(entry.get(key, ""))) for key, _field_off in STRING_FIELDS})

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", first_ptr)
    buf += notes

    for idx, entry in enumerate(entries):
        entry_base = entries_base + idx * ENTRY_SIZE
        entry_buf = bytearray(ENTRY_SIZE)
        for key, field_off in STRING_FIELDS:
            field_abs = entry_base + field_off
            pool_off = offsets[idx][key]
            ptr = 0 if pool_off is None else pool_base + int(pool_off) - field_abs
            struct.pack_into("<Q", entry_buf, field_off, ptr)

        struct.pack_into("<Q", entry_buf, 8, int(entry.get("move_type", 0)) & 0xFFFFFFFFFFFFFFFF)
        values = [int(entry.get(key, 0)) & 0xFFFFFFFF for key in UINT_FIELDS]
        struct.pack_into("<IIIIIII", entry_buf, 40, *values)
        struct.pack_into("<i", entry_buf, 68, int(entry.get("unk12", 0)))
        buf += entry_buf

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_commandlistparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", 1000)),
        bytes(result.get("notes", b"")),
        list(result.get("entries", [])),
    )
    payload = struct.pack(">I", len(inner)) + inner
    if len(payload) % 4:
        payload += b"\x00" * (4 - len(payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)
    chunk_hdr = bytearray(original_data[chunk_hdr_off:chunk_hdr_off + 12])
    struct.pack_into(">I", chunk_hdr, 0, len(payload))

    orig_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_end % 4:
        orig_end += 4 - orig_end % 4

    with open(filepath, "wb") as fh:
        fh.write(bytes(original_data[:chunk_hdr_off]) + bytes(chunk_hdr) + payload + bytes(original_data[orig_end:]))

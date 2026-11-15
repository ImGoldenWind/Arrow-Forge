"""BattleResultParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  - inner_size (bytes after this field)
  [4-7]   uint32 LE  - version    (1000 in the sample)
  [8-11]  uint32 LE  - entry count
  [12-19] uint64 LE  - first_ptr  (= 8, no notes section)
  [20+]   entries * 32 bytes

Each entry (32 bytes):
  +0   uint64 LE  - self-relative pointer to result_id string
  +8   int32 LE   - value_1 (native comparisons/arithmetic are signed)
  +12  int32 LE   - value_2
  +16  int32 LE   - value_3
  +20  int32 LE   - value_4
  +24  int32 LE   - value_5
  +28  uint32 LE  - reserved

Strings are null-terminated ASCII and 8-byte aligned.
"""

from __future__ import annotations

import struct


ENTRY_SIZE = 32
HEADER_SIZE = 16
_INNER_SIZE_FIELD = 4


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
    """Return (chunk_header_offset, chunk_size) for the main binary chunk."""
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

        if type_idx == 1 and size >= _INNER_SIZE_FIELD + HEADER_SIZE and size > best_size:
            best_off = offset
            best_size = size

        next_off = offset + 12 + (size if size else 0)
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    if best_off == -1:
        raise ValueError("Could not locate nuccChunkBinary in BattleResultParam XFBIN.")

    return best_off, best_size


def parse_battleresultparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse BattleResultParam.bin.xfbin.

    Returns (raw_xfbin_data, version, entries).  Each entry exposes the result
    id string, five editable integer values, and the final reserved u32.
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    spm_off = payload_off + _INNER_SIZE_FIELD

    version = struct.unpack_from("<I", data, spm_off)[0]
    count = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8
    if notes_len < 0:
        raise ValueError("Invalid BattleResultParam header: first_ptr is smaller than 8.")

    entries_base = spm_off + HEADER_SIZE + notes_len
    if entries_base + count * ENTRY_SIZE > len(data):
        raise ValueError("BattleResultParam entry table exceeds file size.")

    entries: list[dict] = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        ptr = struct.unpack_from("<Q", data, base)[0]
        result_id = _read_cstr(data, base + ptr) if ptr else ""
        values = list(struct.unpack_from("<5i", data, base + 8))
        reserved = struct.unpack_from("<I", data, base + 28)[0]
        entries.append({
            "result_id": result_id,
            "values": values,
            "reserved": reserved,
        })

    return data, version, entries


def make_default_entry() -> dict:
    return {
        "result_id": "ID_NEW_RESULT",
        "values": [0, 0, 0, 0, 0],
        "reserved": 0,
    }


def signed_value(value: int) -> int:
    """Accept old unsigned dictionary bit patterns as well as native i32 values."""
    value = int(value)
    if 0x80000000 <= value <= 0xFFFFFFFF:
        value -= 0x100000000
    if not -0x80000000 <= value <= 0x7FFFFFFF:
        raise ValueError(f"Result value is outside the signed 32-bit range: {value}")
    return value


def _pad8(pool: bytearray, text: str) -> int:
    off = len(pool)
    pool.extend(text.encode("ascii", errors="replace") + b"\x00")
    rem = len(pool) % 8
    if rem:
        pool.extend(b"\x00" * (8 - rem))
    return off


def _build_binary(version: int, entries: list[dict]) -> bytes:
    count = len(entries)
    pool = bytearray()
    string_offsets = []
    for entry in entries:
        string_offsets.append(_pad8(pool, str(entry.get("result_id", ""))))

    pool_abs = _INNER_SIZE_FIELD + HEADER_SIZE + count * ENTRY_SIZE
    buf = bytearray()
    buf += struct.pack("<I", int(version))
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)

    for idx, entry in enumerate(entries):
        entry_abs = _INNER_SIZE_FIELD + HEADER_SIZE + idx * ENTRY_SIZE
        ptr = pool_abs + string_offsets[idx] - entry_abs
        values = list(entry.get("values", []))[:5]
        values += [0] * (5 - len(values))
        reserved = int(entry.get("reserved", 0))

        buf += struct.pack("<Q", ptr)
        buf += struct.pack("<5i", *(signed_value(value) for value in values))
        buf += struct.pack("<I", reserved & 0xFFFFFFFF)

    buf += pool
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_battleresultparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with edited BattleResultParam data."""
    new_inner = _build_binary(version, entries)
    new_payload = struct.pack(">I", len(new_inner)) + new_inner
    if len(new_payload) % 4:
        new_payload += b"\x00" * (4 - len(new_payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)
    prefix = bytes(original_data[:chunk_hdr_off])
    chunk_hdr = bytearray(original_data[chunk_hdr_off:chunk_hdr_off + 12])
    struct.pack_into(">I", chunk_hdr, 0, len(new_payload))

    orig_payload_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(original_data[orig_payload_end:])

    with open(filepath, "wb") as fh:
        fh.write(prefix + bytes(chunk_hdr) + new_payload + trailing)

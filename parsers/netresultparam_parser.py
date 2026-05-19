"""NetResultParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload):
  [0-3]   uint32 BE  - inner_size (bytes after this field)
  [4-7]   uint32 LE  - version    (1000 in the sample)
  [8-11]  uint32 LE  - entry count (206 in the sample)
  [12-19] uint64 LE  - first_ptr, from this field to the first entry (= 8)
  [20+]   optional notes bytes, then entries

Each entry is 8 bytes:
  +0 int32  LE - signed threshold / delta value
  +4 uint32 LE - result value or rate

The retail sample has no strings. Entries 0-4 are standalone values with
threshold 0; entries 5+ form a signed threshold table from +999999 to -999999.
"""

from __future__ import annotations

import copy
import struct


ENTRY_SIZE = 8
HEADER_SIZE = 16
INNER_SIZE_FIELD = 4
DEFAULT_VERSION = 1000


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
        raise ValueError("Could not locate nuccChunkBinary in NetResultParam XFBIN.")
    return best_off, best_size


def parse_netresultparam_xfbin(filepath: str) -> tuple[bytearray, dict]:
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12
    net_off = payload_off + INNER_SIZE_FIELD
    chunk_end = payload_off + chunk_size

    inner_size = struct.unpack_from(">I", data, payload_off)[0]
    if inner_size + INNER_SIZE_FIELD > chunk_size:
        raise ValueError("Invalid NetResultParam inner size.")

    version = struct.unpack_from("<I", data, net_off)[0]
    count = struct.unpack_from("<I", data, net_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, net_off + 8)[0]
    if first_ptr < 8:
        raise ValueError("Invalid NetResultParam header: first_ptr is smaller than 8.")

    notes_len = first_ptr - 8
    notes_off = net_off + HEADER_SIZE
    entries_base = net_off + 8 + first_ptr
    entries_end = entries_base + count * ENTRY_SIZE
    if entries_end > chunk_end:
        raise ValueError("NetResultParam entry table exceeds binary chunk size.")

    entries = []
    for idx in range(count):
        base = entries_base + idx * ENTRY_SIZE
        threshold, value = struct.unpack_from("<iI", data, base)
        entries.append({
            "threshold": threshold,
            "value": value,
        })

    return data, {
        "version": version,
        "notes": bytes(data[notes_off:notes_off + notes_len]),
        "entries": entries,
    }


def make_default_entry(source: dict | None = None) -> dict:
    if source:
        return copy.deepcopy(source)
    return {
        "threshold": 0,
        "value": 0,
    }


def _build_inner(version: int, notes: bytes, entries: list[dict]) -> bytes:
    first_ptr = 8 + len(notes)

    buf = bytearray()
    buf += struct.pack("<I", int(version) & 0xFFFFFFFF)
    buf += struct.pack("<I", len(entries))
    buf += struct.pack("<Q", first_ptr)
    buf += notes

    for entry in entries:
        buf += struct.pack(
            "<iI",
            int(entry.get("threshold", 0)),
            int(entry.get("value", 0)) & 0xFFFFFFFF,
        )

    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)
    return bytes(buf)


def save_netresultparam_xfbin(filepath: str, original_data: bytearray, result: dict) -> None:
    inner = _build_inner(
        int(result.get("version", DEFAULT_VERSION)),
        bytes(result.get("notes", b"")),
        list(result.get("entries", [])),
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

"""parsers/speaking_parser.py  –  SpeakingLineParam.bin.xfbin parser / writer.

Binary layout (inside the XFBIN binary chunk):
  [0]      uint32 BE  – inner size (all bytes that follow)
  [4]      uint32 LE  – version  (typically 1000)
  [8]      uint32 LE  – entry count
  [12]     uint64 LE  – first_pointer  (= 8 → 0 bytes of notes)
  [20]     notes[first_pointer - 8]
  [20+]    entries × 40 bytes each
           +0  uint32  interaction_type  (0=Unknown, 1=BattleStart, 2=RoundWin, 3=BattleWin)
           +4  uint32  is_round_win      (Bool 0/1)
           +8  uint64  ptr  → char1  string
           +16 uint64  ptr  → char2  string
           +24 uint64  ptr  → dialogue1 string
           +32 uint64  ptr  → dialogue2 string
  String pool follows all entries.

Pointer resolution:
  field_offset = entry_base + 8 + ptr_index * 8
  string_offset = field_offset + ptr_value
"""

import struct


# constants

INTERACTION_NAMES = {0: "Unknown", 1: "Battle Start", 2: "Round Win", 3: "Battle Win"}
INTERACTION_VALUES = {"Unknown": 0, "Battle Start": 1, "Round Win": 2, "Battle Win": 3}
INTERACTION_KEYS = [0, 1, 2, 3]

ENTRY_SIZE = 40   # bytes per entry record
HEADER_SIZE = 16  # version(4) + count(4) + first_pointer(8)


# helpers

def _read_cstr(data: bytes | bytearray, off: int) -> str:
    """Read null-terminated UTF-8 string at *off*."""
    if off >= len(data):
        return ""
    try:
        end = data.index(b"\x00", off)
        return data[off:end].decode("utf-8", errors="replace")
    except ValueError:
        return data[off:].decode("utf-8", errors="replace")


def _find_binary_chunk(data: bytes | bytearray):
    """
    Return (chunk_header_offset, chunk_size) for the first nuccChunkBinary.
    The chunk header is 12 bytes: size(4 BE), type_idx(2 BE), path_idx(2 BE), flags(4 BE).
    chunk_size is the value stored in the 4-byte field (bytes of chunk payload).
    """
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset: offset + 4])[0]
        type_idx = struct.unpack(">H", data[offset + 4: offset + 6])[0]
        if size > 0 and type_idx == 1:          # nuccChunkBinary is always type index 1
            return offset, size
        # also accept any large chunk as the binary chunk
        if size > 512:
            return offset, size
        next_off = offset + 12 + size
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    raise ValueError("Could not locate nuccChunkBinary in XFBIN file.")


# public API

def parse_speaking_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """
    Parse SpeakingLineParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        interaction_type  int   0-3
        is_round_win      int   0 or 1
        char1             str
        char2             str
        dialogue1         str
        dialogue2         str
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12   # start of chunk payload

    # The payload starts with a 4-byte BE inner size, then the SpeakingLineParam struct
    spm_off = payload_off + 4          # SpeakingLineParam struct starts here

    version = struct.unpack_from("<I", data, spm_off)[0]
    count   = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8

    entries_base = spm_off + HEADER_SIZE + notes_len

    entries: list[dict] = []
    for i in range(count):
        e_off = entries_base + i * ENTRY_SIZE
        interaction = struct.unpack_from("<I", data, e_off)[0]
        is_rw       = struct.unpack_from("<I", data, e_off + 4)[0]

        def _str(ptr_idx: int) -> str:
            field_off = e_off + 8 + ptr_idx * 8
            ptr_val   = struct.unpack_from("<Q", data, field_off)[0]
            return _read_cstr(data, field_off + ptr_val)

        entries.append({
            "interaction_type": int(interaction),
            "is_round_win":     int(is_rw),
            "char1":     _str(0),
            "char2":     _str(1),
            "dialogue1": _str(2),
            "dialogue2": _str(3),
        })

    return data, version, entries


def _build_spm_binary(version: int, entries: list[dict]) -> bytes:
    """
    Build the SpeakingLineParam binary (WITHOUT the leading 4-byte BE size).

    Layout:
      version(4) count(4) first_ptr(8)   ← 16 bytes header
      entries × 40 bytes
      string pool (null-terminated strings, may be deduplicated)
    """
    count = len(entries)

    # 1. Build string pool with deduplication
    pool_bytes = bytearray()
    pool_map: dict[str, int] = {}   # string → byte offset in pool

    def pool_add(s: str) -> int:
        if s not in pool_map:
            pool_map[s] = len(pool_bytes)
            pool_bytes.extend(s.encode("utf-8") + b"\x00")
        return pool_map[s]

    # Collect pool offsets for all entries first pass
    string_offsets: list[tuple[int, int, int, int]] = []
    for e in entries:
        o1 = pool_add(e["char1"])
        o2 = pool_add(e["char2"])
        o3 = pool_add(e["dialogue1"])
        o4 = pool_add(e["dialogue2"])
        string_offsets.append((o1, o2, o3, o4))

    # 2. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)      # version
    buf += struct.pack("<I", count)        # count
    buf += struct.pack("<Q", 8)            # first_pointer = 8 (no notes)

    # String pool starts right after all entry records
    pool_start = HEADER_SIZE + count * ENTRY_SIZE

    for i, (e, (o1, o2, o3, o4)) in enumerate(zip(entries, string_offsets)):
        entry_start = HEADER_SIZE + i * ENTRY_SIZE

        buf += struct.pack("<I", e["interaction_type"])
        buf += struct.pack("<I", e["is_round_win"])

        # ptr_n = (pool_start + pool_offset) - ptr_field_offset
        # ptr_field_offset = entry_start + 8 + n*8  (relative to start of spm binary)
        for n, pool_off in enumerate((o1, o2, o3, o4)):
            field_off = entry_start + 8 + n * 8
            ptr_val   = (pool_start + pool_off) - field_off
            buf += struct.pack("<Q", ptr_val)

    buf += pool_bytes

    # Pad to 4-byte alignment
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_speaking_xfbin(filepath: str, original_data: bytearray,
                        version: int, entries: list[dict]) -> None:
    """
    Rebuild the XFBIN file with updated SpeakingLineParam data and write to *filepath*.

    The XFBIN structure is:
      [0..27]    XFBIN header (28 bytes)
      [28..247]  chunk table (220 bytes, fixed)
      [248..271] two null chunks (12 bytes each, fixed)
      [272..283] binary chunk header (12 bytes)  ← chunk size updated here
      [284..]    binary chunk payload             ← rebuilt here
      [last 20]  page/index trailing chunk        ← kept intact
    """
    new_spm = _build_spm_binary(version, entries)

    # Inner size field (BE uint32) = len(new_spm)
    inner_size = len(new_spm)
    new_payload = struct.pack(">I", inner_size) + new_spm
    new_chunk_size = len(new_payload)

    # Locate binary chunk header in original data
    chunk_hdr_off, _orig_chunk_size = _find_binary_chunk(original_data)

    # Everything before the binary chunk header (header + table + two null chunks)
    prefix = bytes(original_data[:chunk_hdr_off])

    # Binary chunk header with updated size (first 4 bytes are BE size)
    orig_hdr = bytearray(original_data[chunk_hdr_off: chunk_hdr_off + 12])
    struct.pack_into(">I", orig_hdr, 0, new_chunk_size)
    new_hdr = bytes(orig_hdr)

    # Trailing chunk(s) that follow the original binary chunk payload
    orig_payload_end = chunk_hdr_off + 12 + _orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(original_data[orig_payload_end:])

    # Pad new_payload to 4-byte boundary before the trailing chunk
    if len(new_payload) % 4:
        new_payload += b"\x00" * (4 - len(new_payload) % 4)

    result = prefix + new_hdr + new_payload + trailing

    with open(filepath, "wb") as fh:
        fh.write(result)

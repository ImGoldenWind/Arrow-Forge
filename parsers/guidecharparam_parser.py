"""parsers/guidecharparam_parser.py  –  GuideCharParam.bin.xfbin parser / writer.

Binary layout (inside the XFBIN binary chunk payload):
  [0-3]   uint32 BE  – inner size (bytes that follow)
  [4-7]   uint32 LE  – version  (1000)
  [8-11]  uint32 LE  – entry count  (110 in retail)
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes section)
  [20+]   entries × 96 bytes each

Each entry (96 bytes, 12 little-endian uint64 string pointers):
  +0   uint64  – ptr → event      (game event identifier, e.g. "GUIDE_MODESEL_IN")
  +8   uint64  – ptr → character  (guide character name,  e.g. "guide_chara_speedwagon")
  +16  uint64  – ptr → msg[0].name    (character name ID, e.g. "c_name_1spw01")
  +24  uint64  – ptr → msg[0].string  (message/animation ID, e.g. "modeselect_g000")
  +32  uint64  – ptr → msg[1].name
  +40  uint64  – ptr → msg[1].string
  +48  uint64  – ptr → msg[2].name
  +56  uint64  – ptr → msg[2].string
  +64  uint64  – ptr → msg[3].name
  +72  uint64  – ptr → msg[3].string
  +80  uint64  – ptr → msg[4].name     (5th slot is usually empty)
  +88  uint64  – ptr → msg[4].string
= 96 bytes per entry

String pool: null-terminated UTF-8, each string padded to 8-byte boundary.

Pointer resolution:
  string is at absolute file offset:  ptr_field_offset + pointer_value
  where ptr_field_offset = file offset of the uint64 pointer field itself.

Note from 010 Editor template: the 5th message slot (msg[4]) is always empty
in vanilla data — adding real data there reportedly has no effect in-game.
"""

import struct

ENTRY_SIZE    = 96     # 12 × uint64 pointers
HEADER_SIZE   = 16    # version(4) + count(4) + first_ptr(8)
_INNER_SZ_FLD = 4     # leading BE uint32 in payload

# All string field offsets within each 96-byte entry
_STR_FIELDS: list[tuple[int, str]] = [
    (0,  "event"),
    (8,  "character"),
    (16, "msg0_name"),
    (24, "msg0_string"),
    (32, "msg1_name"),
    (40, "msg1_string"),
    (48, "msg2_name"),
    (56, "msg2_string"),
    (64, "msg3_name"),
    (72, "msg3_string"),
    (80, "msg4_name"),
    (88, "msg4_string"),
]

_STR_KEYS = [k for _, k in _STR_FIELDS]

# Known guide characters (retail set)
KNOWN_CHARACTERS = [
    "guide_chara_speedwagon",
    "guide_chara_polnareff",
    "guide_chara_messina",
    "guide_chara_melone",
    "guide_chara_abbacchio",
    "guide_chara_emporio",
    "guide_chara_wangchen",
    "guide_chara_boingo",
    "guide_chara_derbyd",
    "guide_chara_derbyt",
    "guide_chara_giatcho",
    "guide_chara_ringo",
]


# Helpers

def _read_cstr(data: bytes | bytearray, off: int) -> str:
    if off >= len(data):
        return ""
    try:
        end = data.index(b"\x00", off)
        raw = data[off:end]
    except ValueError:
        raw = data[off:]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


def _find_binary_chunk(data: bytes | bytearray) -> tuple[int, int]:
    """Return (chunk_header_offset, chunk_size) for the nuccChunkBinary."""
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    while offset + 12 <= len(data):
        size     = struct.unpack(">I", data[offset:     offset + 4])[0]
        type_idx = struct.unpack(">H", data[offset + 4: offset + 6])[0]
        if size > 0 and (type_idx == 1 or size > 512):
            return offset, size
        next_off = offset + 12 + size
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    raise ValueError("Could not locate nuccChunkBinary in XFBIN file.")


# Public API

def parse_guidecharparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse GuideCharParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        event       str  – game event identifier (e.g. "GUIDE_MODESEL_IN")
        character   str  – guide character (e.g. "guide_chara_speedwagon")
        msg0_name   str  – character name ID for message slot 0
        msg0_string str  – animation/message ID for slot 0
        msg1_name   str  – character name ID for slot 1
        msg1_string str  – animation/message ID for slot 1
        msg2_name   str  – character name ID for slot 2
        msg2_string str  – animation/message ID for slot 2
        msg3_name   str  – character name ID for slot 3
        msg3_string str  – animation/message ID for slot 3
        msg4_name   str  – character name ID for slot 4 (usually empty)
        msg4_string str  – animation/message ID for slot 4 (usually empty)
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12

    spm_off = payload_off + _INNER_SZ_FLD

    version   = struct.unpack_from("<I", data, spm_off)[0]
    count     = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8

    entries_base = spm_off + HEADER_SIZE + notes_len

    entries: list[dict] = []
    for i in range(count):
        base = entries_base + i * ENTRY_SIZE

        def _str(field_off: int, _base=base) -> str:
            abs_field = _base + field_off
            ptr = struct.unpack_from("<Q", data, abs_field)[0]
            return _read_cstr(data, abs_field + ptr)

        e: dict = {}
        for off, key in _STR_FIELDS:
            e[key] = _str(off)
        entries.append(e)

    return data, version, entries


def make_default_entry(index: int = 0) -> dict:
    """Return a blank GuideCharParam entry with safe defaults."""
    return {
        "event":      f"GUIDE_NEW_EVENT_{index:03d}",
        "character":  "guide_chara_speedwagon",
        "msg0_name":  "c_name_1spw01",
        "msg0_string": "",
        "msg1_name":  "c_name_1spw01",
        "msg1_string": "",
        "msg2_name":  "c_name_1spw01",
        "msg2_string": "",
        "msg3_name":  "c_name_1spw01",
        "msg3_string": "",
        "msg4_name":  "",
        "msg4_string": "",
    }


def _build_guidecharparam_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner GuideCharParam binary (WITHOUT the leading 4-byte BE inner_size).

    Layout:
      version(4) count(4) first_ptr(8)   ← HEADER_SIZE = 16
      entries × ENTRY_SIZE               ← 96 bytes each
      string pool (null-terminated UTF-8, padded to 8-byte boundary each)
    """
    count = len(entries)

    # 1. Build string pool
    pool: bytearray = bytearray()
    pool_map: dict[str, int] = {}

    def _pool_add(s: str) -> int:
        if s not in pool_map:
            pool_map[s] = len(pool)
            encoded = s.encode("utf-8") + b"\x00"
            pool.extend(encoded)
            pad = (8 - len(pool) % 8) % 8
            if pad:
                pool.extend(b"\x00" * pad)
        return pool_map[s]

    # Pre-compute all string pool offsets per entry
    str_offsets: list[dict[str, int]] = []
    for e in entries:
        offsets = {k: _pool_add(e.get(k, "")) for k in _STR_KEYS}
        str_offsets.append(offsets)

    # Pool starts right after: _INNER_SZ_FLD + HEADER_SIZE + count*ENTRY_SIZE
    pool_tmpl_off = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 2. Assemble binary
    buf = bytearray()

    # Header (version + count + first_ptr)
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)   # first_ptr = 8 (no notes section)

    for i, (e, soff) in enumerate(zip(entries, str_offsets)):
        entry_tmpl = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE

        def _ptr(field_off: int, key: str, _et=entry_tmpl, _soff=soff) -> int:
            """Compute relative pointer from this field to the string in the pool."""
            return pool_tmpl_off + _soff[key] - (_et + field_off)

        for off, key in _STR_FIELDS:
            buf += struct.pack("<Q", _ptr(off, key))

    buf += pool

    # Pad to 4-byte boundary
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_guidecharparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated GuideCharParam data and write to filepath."""
    new_inner   = _build_guidecharparam_binary(version, entries)
    inner_size  = len(new_inner)
    new_payload = struct.pack(">I", inner_size) + new_inner

    # Pad to 4-byte boundary
    if len(new_payload) % 4:
        new_payload += b"\x00" * (4 - len(new_payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)

    prefix   = bytes(original_data[:chunk_hdr_off])

    orig_hdr = bytearray(original_data[chunk_hdr_off: chunk_hdr_off + 12])
    struct.pack_into(">I", orig_hdr, 0, len(new_payload))
    new_hdr  = bytes(orig_hdr)

    orig_payload_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(original_data[orig_payload_end:])

    with open(filepath, "wb") as fh:
        fh.write(prefix + new_hdr + new_payload + trailing)

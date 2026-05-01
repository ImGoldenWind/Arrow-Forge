"""parsers/messageinfo_parser.py  –  messageInfo.bin.xfbin parser / writer.

Binary layout (inside the XFBIN binary chunk payload):
  [0]      uint32 BE  – inner size (bytes that follow)
  [4]      uint32 LE  – version  (typically 1001)
  [8]      uint32 LE  – entry count
  [12]     uint64 LE  – first_pointer  (= 8 → no notes)
  [20]     notes[first_pointer - 8]
  [20+]    entries × 40 bytes each
           +0   uint32 BE  – crc32_id  (CRC32 hash identifier)
           +4   uint32 LE  – unk1      (always 0)
           +8   uint32 LE  – unk2      (always 0)
           +12  uint32 LE  – unk3      (always 0)
           +16  uint64 LE  – pointer   → message string (relative to pointer field)
           +24  uint32 BE  – ref_crc32 (CRC32 of referenced entry when is_ref=1)
           +28  int16  LE  – is_ref    (-1 = normal entry, 1 = reference)
           +30  int16  LE  – char_id   (-1 for ref, 0–73 for characters)
           +32  int16  LE  – cue_id    (-1 for ref, sound cue index)
           +34  int16  LE  – unk6      (always -1)
           +36  uint32 LE  – unk7      (always 0)
  String pool (null-terminated UTF-8 strings, each padded to 8-byte boundary).

Pointer resolution (matches 010 Editor template logic):
  template_ptr_field = 4 + 16 + notes_len + i*40 + 16
  str_off_in_file    = payload_off + template_ptr_field + pointer_value

  i.e.:  FSeek(Pos - 8 + Pointer)  where Pos = FTell() after reading the 8-byte pointer
      →  FSeek(template_ptr_field + pointer_value)
"""

import struct
import zlib


# constants

ENTRY_SIZE   = 40   # bytes per entry record
HEADER_SIZE  = 16   # version(4) + count(4) + first_pointer(8)
_INNER_SIZE_FIELD = 4  # leading BE uint32 in payload


# helpers

def _read_cstr(data: bytes | bytearray, off: int) -> str:
    """Read null-terminated UTF-8 string at *off*."""
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


def _find_binary_chunk(data: bytes | bytearray):
    """
    Return (chunk_header_offset, chunk_size) for the first non-null chunk.
    Chunk header: size(4 BE), type_idx(2 BE), path_idx(2 BE), flags(4 BE).
    """
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset: offset + 4])[0]
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


def crc32_of(key: str) -> int:
    """Compute CRC32 of a UTF-8 encoded string (unsigned 32-bit)."""
    return zlib.crc32(key.encode("utf-8")) & 0xFFFFFFFF


# public API

def parse_messageinfo_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """
    Parse messageInfo.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict has keys:
        crc32_id   int  – 32-bit hash ID (big-endian in file)
        unk1       int  – always 0
        unk2       int  – always 0
        unk3       int  – always 0
        message    str  – localised message text
        ref_crc32  int  – CRC32 of target entry (when is_ref=1), else 0
        is_ref     int  – -1 = normal, 1 = reference alias
        char_id    int  – character index (0–73) or -1
        cue_id     int  – voice cue index or -1
        unk6       int  – always -1
        unk7       int  – always 0
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12

    # Payload: 4-byte BE inner_size, then binary struct
    spm_off = payload_off + _INNER_SIZE_FIELD

    version   = struct.unpack_from("<I", data, spm_off)[0]
    count     = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8

    entries_base = spm_off + HEADER_SIZE + notes_len

    entries: list[dict] = []
    for i in range(count):
        e_off = entries_base + i * ENTRY_SIZE

        crc32_id = struct.unpack_from(">I", data, e_off)[0]
        unk1     = struct.unpack_from("<I", data, e_off + 4)[0]
        unk2     = struct.unpack_from("<I", data, e_off + 8)[0]
        unk3     = struct.unpack_from("<I", data, e_off + 12)[0]
        pointer  = struct.unpack_from("<Q", data, e_off + 16)[0]

        # template offset of this entry's pointer field:
        #   _INNER_SIZE_FIELD(4) + HEADER_SIZE(16) + notes_len + i*40 + 16
        tmpl_ptr_field = _INNER_SIZE_FIELD + HEADER_SIZE + notes_len + i * ENTRY_SIZE + 16
        str_abs = payload_off + tmpl_ptr_field + pointer
        message = _read_cstr(data, str_abs)

        ref_crc32 = struct.unpack_from(">I", data, e_off + 24)[0]
        is_ref    = struct.unpack_from("<h", data, e_off + 28)[0]
        char_id   = struct.unpack_from("<h", data, e_off + 30)[0]
        cue_id    = struct.unpack_from("<h", data, e_off + 32)[0]
        unk6      = struct.unpack_from("<h", data, e_off + 34)[0]
        unk7      = struct.unpack_from("<I", data, e_off + 36)[0]

        entries.append({
            "crc32_id":  crc32_id,
            "unk1":      unk1,
            "unk2":      unk2,
            "unk3":      unk3,
            "message":   message,
            "ref_crc32": ref_crc32,
            "is_ref":    is_ref,
            "char_id":   char_id,
            "cue_id":    cue_id,
            "unk6":      unk6,
            "unk7":      unk7,
        })

    return data, version, entries


def _build_messageinfo_binary(version: int, entries: list[dict]) -> bytes:
    """
    Build the inner messageInfo binary (WITHOUT the leading 4-byte BE inner_size).

    Layout:
      version(4) count(4) first_ptr(8)          ← HEADER_SIZE = 16 bytes
      entries × ENTRY_SIZE bytes
      string pool (null-terminated UTF-8, each padded to 8-byte boundary)
    """
    count = len(entries)

    # 1. Build string pool
    pool_bytes: bytearray = bytearray()
    pool_map: dict[str, int] = {}   # string → byte offset in pool

    def _pool_add(s: str) -> int:
        if s not in pool_map:
            pool_map[s] = len(pool_bytes)
            encoded = s.encode("utf-8") + b"\x00"
            pool_bytes.extend(encoded)
            # Pad each string to 8-byte boundary (matches original file format)
            pad = (8 - len(pool_bytes) % 8) % 8
            if pad:
                pool_bytes.extend(b"\x00" * pad)
        return pool_map[s]

    pool_offsets: list[int] = [_pool_add(e["message"]) for e in entries]

    # 2. Compute template offsets
    # Template offset of string pool start (includes leading inner_size field)
    pool_tmpl_off = _INNER_SIZE_FIELD + HEADER_SIZE + count * ENTRY_SIZE

    # 3. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)   # version
    buf += struct.pack("<I", count)     # count
    buf += struct.pack("<Q", 8)         # first_pointer = 8 (no notes)

    # Entries
    for i, (e, pool_off) in enumerate(zip(entries, pool_offsets)):
        # Template offset of this entry's pointer field
        ptr_field_tmpl_off = _INNER_SIZE_FIELD + HEADER_SIZE + i * ENTRY_SIZE + 16
        ptr_val = pool_tmpl_off + pool_off - ptr_field_tmpl_off

        buf += struct.pack(">I", e["crc32_id"] & 0xFFFFFFFF)  # BE
        buf += struct.pack("<I", e["unk1"])
        buf += struct.pack("<I", e["unk2"])
        buf += struct.pack("<I", e["unk3"])
        buf += struct.pack("<Q", ptr_val)
        buf += struct.pack(">I", e["ref_crc32"] & 0xFFFFFFFF)  # BE
        buf += struct.pack("<h", e["is_ref"])
        buf += struct.pack("<h", e["char_id"])
        buf += struct.pack("<h", e["cue_id"])
        buf += struct.pack("<h", e["unk6"])
        buf += struct.pack("<I", e["unk7"])

    buf += pool_bytes

    # Pad to 4-byte alignment
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_messageinfo_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """
    Rebuild the XFBIN file with updated messageInfo data and write to *filepath*.
    """
    new_inner = _build_messageinfo_binary(version, entries)
    inner_size = len(new_inner)
    new_payload = struct.pack(">I", inner_size) + new_inner
    new_chunk_size = len(new_payload)

    # Pad payload to 4-byte boundary
    if len(new_payload) % 4:
        new_payload += b"\x00" * (4 - len(new_payload) % 4)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)

    # Prefix: everything before the binary chunk header
    prefix = bytes(original_data[:chunk_hdr_off])

    # Binary chunk header with updated size
    orig_hdr = bytearray(original_data[chunk_hdr_off: chunk_hdr_off + 12])
    struct.pack_into(">I", orig_hdr, 0, new_chunk_size)
    new_hdr = bytes(orig_hdr)

    # Trailing data after original binary chunk payload
    orig_payload_end = chunk_hdr_off + 12 + orig_chunk_size
    if orig_payload_end % 4:
        orig_payload_end += 4 - orig_payload_end % 4
    trailing = bytes(original_data[orig_payload_end:])

    result = prefix + new_hdr + new_payload + trailing

    with open(filepath, "wb") as fh:
        fh.write(result)

"""parsers/dictionaryparam_parser.py  –  DictionaryParam.bin.xfbin parser / writer.

Binary layout (inside the XFBIN binary chunk payload):
  [0]      uint32 BE  – inner size (bytes that follow)
  [4]      uint32 LE  – version  (typically 1000)
  [8]      uint32 LE  – entry count
  [12]     uint64 LE  – first_pointer  (= 8 → no notes)
  [20+]    entries × 168 bytes each

Each entry (168 bytes, all little-endian unless noted):
  +0    uint64  – pointer → char_id string  (str at ptr_field + pointer_value)
  +8    uint64  – pointer → panel string
  +16   uint64  – pointer → title string
  +24   uint64  – pointer → header string
  +32   uint32  – flag1   (JoJo part / category flag)
  +36   uint32  – flag2
  +40   uint32  – flag3
  +44   uint32  – flag4
  +48   uint32  – flag5
  +52   uint32  – flag6
  +56   uint32  – flag7
  +60   uint32  – flag8   (comment: "1 for patch230 latest version?")
  +64   uint32  – pad1    (always 0)
  +68   uint32  – pad2    (always 0)
  +72   uint32  – pad3    (always 0)
  +76   uint32  – pad4    (always 0)
  +80   uint32  – flag13
  +84   uint32  – flag14
  +88   uint32  – flag15
  +92   uint32  – pad5    (always 0)
  +96   uint32  – pad6    (always 0)
  +100  uint32  – pad7    (always 0)
  +104  uint32  – flag19
  +108  uint32  – pad8    (always 0)
  +112  uint64  – pointer → dmy string
  +120  uint32  – dlc_id
  +124  uint32  – patch
  +128  uint32  – no_panel  (4 = missing panel, 0 = has panel)
  +132  uint32  – const1    (always 1)
  +136  uint32  – padding   (always 0xFFFFFFFF)
  +140  uint32  – res1..res5  (always 0) × 5  (+140,+144,+148,+152,+156)
  +160  uint64  – index

String pool: null-terminated UTF-8, each padded to 8-byte boundary.

Pointer resolution:
  string is at absolute file offset:  ptr_field_offset + pointer_value
  where ptr_field_offset = file offset of the uint64 pointer field itself
"""

import struct

ENTRY_SIZE    = 168
HEADER_SIZE   = 16    # version(4) + count(4) + first_pointer(8)
_INNER_SZ_FLD = 4     # leading BE uint32 in payload


# helpers

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


def _find_binary_chunk(data: bytes | bytearray):
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


# public API

def parse_dictionaryparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """
    Parse DictionaryParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict:
        char_id   str  – dictionary lookup key  (e.g. "DIC_ID_DMY_1")
        panel     str  – ASB mode panel unlock  (e.g. "PANEL_13_08")
        title     str  – title text-key         (e.g. "dictionary_t001")
        header    str  – header text-key        (e.g. "dictionary_h001")
        flag1..flag8 int  – part/category flags
        pad1..pad4   int  – always 0
        flag13..flag15 int
        pad5..pad7   int  – always 0
        flag19       int
        pad8         int  – always 0
        dmy       str  – dummy string           (e.g. "dmy01")
        dlc_id    int  – DLC package id
        patch     int  – game version when added
        no_panel  int  – 4 = no panel/not unlockable, 0 = normal
        const1    int  – always 1
        padding   int  – always 0xFFFFFFFF
        res1..res5 int – always 0
        index     int  – sort/display index
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

        # String pointers (absolute file offsets)
        def _str(field_off: int) -> str:
            abs_field = base + field_off
            ptr = struct.unpack_from("<Q", data, abs_field)[0]
            return _read_cstr(data, abs_field + ptr)

        e: dict = {
            "char_id":  _str(0),
            "panel":    _str(8),
            "title":    _str(16),
            "header":   _str(24),
            # flags / padding
            "flag1":    struct.unpack_from("<I", data, base + 32)[0],
            "flag2":    struct.unpack_from("<I", data, base + 36)[0],
            "flag3":    struct.unpack_from("<I", data, base + 40)[0],
            "flag4":    struct.unpack_from("<I", data, base + 44)[0],
            "flag5":    struct.unpack_from("<I", data, base + 48)[0],
            "flag6":    struct.unpack_from("<I", data, base + 52)[0],
            "flag7":    struct.unpack_from("<I", data, base + 56)[0],
            "flag8":    struct.unpack_from("<I", data, base + 60)[0],
            "pad1":     struct.unpack_from("<I", data, base + 64)[0],
            "pad2":     struct.unpack_from("<I", data, base + 68)[0],
            "pad3":     struct.unpack_from("<I", data, base + 72)[0],
            "pad4":     struct.unpack_from("<I", data, base + 76)[0],
            "flag13":   struct.unpack_from("<I", data, base + 80)[0],
            "flag14":   struct.unpack_from("<I", data, base + 84)[0],
            "flag15":   struct.unpack_from("<I", data, base + 88)[0],
            "pad5":     struct.unpack_from("<I", data, base + 92)[0],
            "pad6":     struct.unpack_from("<I", data, base + 96)[0],
            "pad7":     struct.unpack_from("<I", data, base + 100)[0],
            "flag19":   struct.unpack_from("<I", data, base + 104)[0],
            "pad8":     struct.unpack_from("<I", data, base + 108)[0],
            # dmy string pointer
            "dmy":      _str(112),
            # trailing fields
            "dlc_id":   struct.unpack_from("<I", data, base + 120)[0],
            "patch":    struct.unpack_from("<I", data, base + 124)[0],
            "no_panel": struct.unpack_from("<I", data, base + 128)[0],
            "const1":   struct.unpack_from("<I", data, base + 132)[0],
            "padding":  struct.unpack_from("<I", data, base + 136)[0],
            "res1":     struct.unpack_from("<I", data, base + 140)[0],
            "res2":     struct.unpack_from("<I", data, base + 144)[0],
            "res3":     struct.unpack_from("<I", data, base + 148)[0],
            "res4":     struct.unpack_from("<I", data, base + 152)[0],
            "res5":     struct.unpack_from("<I", data, base + 156)[0],
            "index":    struct.unpack_from("<Q", data, base + 160)[0],
        }
        entries.append(e)

    return data, version, entries


def make_default_entry(index: int = 0) -> dict:
    """Return a blank DictionaryParam entry with safe defaults."""
    return {
        "char_id":  f"DIC_ID_DMY_{index + 1}",
        "panel":    "",
        "title":    f"dictionary_t{index + 1:03d}",
        "header":   f"dictionary_h{index + 1:03d}",
        "flag1":    0, "flag2":  0, "flag3":  0, "flag4":  0,
        "flag5":    0, "flag6":  0, "flag7":  0, "flag8":  0,
        "pad1":     0, "pad2":   0, "pad3":   0, "pad4":   0,
        "flag13":   0, "flag14": 0, "flag15": 0,
        "pad5":     0, "pad6":   0, "pad7":   0,
        "flag19":   0, "pad8":   0,
        "dmy":      "dmy01",
        "dlc_id":   0,
        "patch":    0,
        "no_panel": 4,      # 4 = no panel (safe default for new entries)
        "const1":   1,
        "padding":  0xFFFFFFFF,
        "res1":     0, "res2": 0, "res3": 0, "res4": 0, "res5": 0,
        "index":    index,
    }


def _build_dictionaryparam_binary(version: int, entries: list[dict]) -> bytes:
    """
    Build the inner DictionaryParam binary (WITHOUT the leading 4-byte BE inner_size).

    Layout:
      version(4) count(4) first_ptr(8)   ← HEADER_SIZE = 16
      entries × ENTRY_SIZE
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

    # Pre-build all pool offsets; collect per-entry [char_id, panel, title, header, dmy]
    str_offsets: list[tuple[int, int, int, int, int]] = []
    for e in entries:
        str_offsets.append((
            _pool_add(e["char_id"]),
            _pool_add(e["panel"]),
            _pool_add(e["title"]),
            _pool_add(e["header"]),
            _pool_add(e["dmy"]),
        ))

    # 2. Compute template offsets
    # The pool starts right after: _INNER_SZ_FLD(4) + HEADER_SIZE(16) + count*ENTRY_SIZE
    pool_tmpl_off = _INNER_SZ_FLD + HEADER_SIZE + count * ENTRY_SIZE

    # 3. Assemble binary
    buf = bytearray()

    # Header
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)          # first_pointer = 8 (no notes)

    for i, (e, (off_ci, off_pn, off_ti, off_hd, off_dm)) in enumerate(
        zip(entries, str_offsets)
    ):
        # Template offset of each of the 5 pointer fields within the entry
        entry_tmpl = _INNER_SZ_FLD + HEADER_SIZE + i * ENTRY_SIZE

        def _ptr(field_off: int, pool_off: int) -> int:
            ptr_tmpl = entry_tmpl + field_off
            return pool_tmpl_off + pool_off - ptr_tmpl

        buf += struct.pack("<Q", _ptr(0,   off_ci))
        buf += struct.pack("<Q", _ptr(8,   off_pn))
        buf += struct.pack("<Q", _ptr(16,  off_ti))
        buf += struct.pack("<Q", _ptr(24,  off_hd))

        buf += struct.pack("<I", e["flag1"])
        buf += struct.pack("<I", e["flag2"])
        buf += struct.pack("<I", e["flag3"])
        buf += struct.pack("<I", e["flag4"])
        buf += struct.pack("<I", e["flag5"])
        buf += struct.pack("<I", e["flag6"])
        buf += struct.pack("<I", e["flag7"])
        buf += struct.pack("<I", e["flag8"])
        buf += struct.pack("<I", e["pad1"])
        buf += struct.pack("<I", e["pad2"])
        buf += struct.pack("<I", e["pad3"])
        buf += struct.pack("<I", e["pad4"])
        buf += struct.pack("<I", e["flag13"])
        buf += struct.pack("<I", e["flag14"])
        buf += struct.pack("<I", e["flag15"])
        buf += struct.pack("<I", e["pad5"])
        buf += struct.pack("<I", e["pad6"])
        buf += struct.pack("<I", e["pad7"])
        buf += struct.pack("<I", e["flag19"])
        buf += struct.pack("<I", e["pad8"])

        buf += struct.pack("<Q", _ptr(112, off_dm))

        buf += struct.pack("<I", e["dlc_id"])
        buf += struct.pack("<I", e["patch"])
        buf += struct.pack("<I", e["no_panel"])
        buf += struct.pack("<I", e["const1"])
        buf += struct.pack("<I", e["padding"] & 0xFFFFFFFF)
        buf += struct.pack("<I", e["res1"])
        buf += struct.pack("<I", e["res2"])
        buf += struct.pack("<I", e["res3"])
        buf += struct.pack("<I", e["res4"])
        buf += struct.pack("<I", e["res5"])
        buf += struct.pack("<Q", e["index"])

    buf += pool

    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_dictionaryparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated DictionaryParam data and write to filepath."""
    new_inner    = _build_dictionaryparam_binary(version, entries)
    inner_size   = len(new_inner)
    new_payload  = struct.pack(">I", inner_size) + new_inner

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

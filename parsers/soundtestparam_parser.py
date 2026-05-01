"""parsers/soundtestparam_parser.py  –  SoundTestParam.bin.xfbin parser / writer.

Binary layout (nuccChunkBinary payload, total 1586 entries in retail):

  [0-3]   uint32 BE  – inner_size  (bytes after this field)
  [4-7]   uint32 LE  – version     (1000)
  [8-11]  uint32 LE  – entry count
  [12-19] uint64 LE  – first_ptr   (= 8 → no notes section)
  [20+]   entries × 80 bytes each
  [...]   string pool (null-terminated, 8-byte aligned per string)

Each entry (80 bytes):
  +0   uint64 LE  – relative ptr → BGM_ID       string  (e.g. "ST_BGM_000")
  +8   uint64 LE  – relative ptr → unk1          string  (always empty in retail)
  +16  uint64 LE  – relative ptr → unk2          string  (always empty in retail)
  +24  uint64 LE  – relative ptr → CharaCode     string  (e.g. "dmy01", "1jnt01")
  +32  uint64 LE  – relative ptr → unk3          string  (always empty in retail)
  +40  uint32 LE  – UnlockCondition  (1=default, 4=shop, 6=char-specific)
  +44  uint32 LE  – MenuIndex        (always 1 in retail)
  +48  uint64 LE  – Price            (50 or 1000)
  +56  uint64 LE  – relative ptr → SoundString1  (e.g. "sound_bgm_t000")
  +64  uint64 LE  – relative ptr → SoundString2  (e.g. "sound_bgm_h000")
  +72  uint64 LE  – Index            (sound track index number)

Pointer convention:
  string_abs = field_abs_offset + pointer_value
  Empty string: ptr = 0 (field's own first byte is 0x00 → empty).
"""

import struct

ENTRY_SIZE   = 80
HEADER_SIZE  = 16   # version(4) + count(4) + first_ptr(8)
_INNER_SZ    =  4   # leading BE uint32 in payload


# Low-level helpers

def _read_cstr(data: bytes | bytearray, off: int) -> str:
    if off >= len(data):
        return ""
    try:
        end = data.index(b"\x00", off)
        return data[off:end].decode("ascii", errors="replace")
    except ValueError:
        return data[off:].decode("ascii", errors="replace")


def _find_binary_chunk(data: bytes | bytearray) -> tuple[int, int]:
    """Return (chunk_hdr_offset, chunk_data_size) for the main nuccChunkBinary."""
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    best_off  = -1
    best_size = 0

    while offset + 12 <= len(data):
        size     = struct.unpack(">I", data[offset:offset + 4])[0]
        type_idx = struct.unpack(">I", data[offset + 4:offset + 8])[0]

        if type_idx == 1 and size > best_size:
            best_off  = offset
            best_size = size

        if size == 0:
            next_off = offset + 12
        else:
            next_off = offset + 12 + size
        if next_off % 4:
            next_off += 4 - next_off % 4
        if next_off <= offset:
            break
        offset = next_off

    if best_off == -1:
        # Fallback: just pick the largest chunk
        offset = 28 + chunk_table_size
        while offset + 12 <= len(data):
            size = struct.unpack(">I", data[offset:offset + 4])[0]
            if size > best_size:
                best_off  = offset
                best_size = size
            next_off = offset + 12 + (size if size else 0)
            if next_off % 4:
                next_off += 4 - next_off % 4
            if next_off <= offset:
                break
            offset = next_off

    if best_off == -1:
        raise ValueError("Could not locate nuccChunkBinary in SoundTestParam XFBIN.")

    return best_off, best_size


def _ptr_read(data: bytearray, field_abs: int, printable_only: bool = False) -> str:
    """Read a relative pointer at field_abs and return the string it points to.

    If printable_only=True, returns "" for any string that contains
    non-printable / non-ASCII characters (used for unk1/unk2/unk3 fields
    which are uninitialized in the retail file and may read garbage bytes).
    """
    ptr = struct.unpack_from("<Q", data, field_abs)[0]
    if ptr == 0:
        return ""
    target = field_abs + ptr
    if target >= len(data):
        return ""
    s = _read_cstr(data, target)
    if printable_only:
        # Discard if the string contains replacement chars or non-printable bytes
        if any(ord(c) < 0x20 or ord(c) > 0x7E for c in s):
            return ""
    return s


# Public API

def parse_soundtestparam_xfbin(filepath: str) -> tuple[bytearray, int, list[dict]]:
    """Parse SoundTestParam.bin.xfbin.

    Returns:
        (raw_xfbin_data, version, entries)

    Each entry dict:
        bgm_id       str  – sound ID tag       (e.g. "ST_BGM_000")
        unk1         str  – reserved string 1  (usually "")
        unk2         str  – reserved string 2  (usually "")
        chara_code   str  – character code     (e.g. "dmy01", "1jnt01")
        unk3         str  – reserved string 3  (usually "")
        unlock_cond  int  – unlock condition   (1/4/6)
        menu_index   int  – menu display index (always 1)
        price        int  – shop price         (50 / 1000)
        sound_str1   str  – audio cue: title   (e.g. "sound_bgm_t000")
        sound_str2   str  – audio cue: hover   (e.g. "sound_bgm_h000")
        index        int  – numerical index    (e.g. 0, 7, 79 …)
    """
    with open(filepath, "rb") as fh:
        data = bytearray(fh.read())

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    payload_off = chunk_hdr_off + 12

    spm_off   = payload_off + _INNER_SZ
    version   = struct.unpack_from("<I", data, spm_off)[0]
    count     = struct.unpack_from("<I", data, spm_off + 4)[0]
    first_ptr = struct.unpack_from("<Q", data, spm_off + 8)[0]
    notes_len = first_ptr - 8  # bytes between header and entries (= 0 normally)

    entries_base = spm_off + HEADER_SIZE + notes_len

    entries: list[dict] = []
    for i in range(count):
        base = entries_base + i * ENTRY_SIZE

        bgm_id     = _ptr_read(data, base +  0)
        unk1       = _ptr_read(data, base +  8, printable_only=True)
        unk2       = _ptr_read(data, base + 16, printable_only=True)
        chara_code = _ptr_read(data, base + 24)
        unk3       = _ptr_read(data, base + 32, printable_only=True)
        unlock_c   = struct.unpack_from("<I", data, base + 40)[0]
        menu_idx   = struct.unpack_from("<I", data, base + 44)[0]
        price      = struct.unpack_from("<Q", data, base + 48)[0]
        ss1        = _ptr_read(data, base + 56)
        ss2        = _ptr_read(data, base + 64)
        idx        = struct.unpack_from("<Q", data, base + 72)[0]

        entries.append({
            "bgm_id":      bgm_id,
            "unk1":        unk1,
            "unk2":        unk2,
            "chara_code":  chara_code,
            "unk3":        unk3,
            "unlock_cond": unlock_c,
            "menu_index":  menu_idx,
            "price":       price,
            "sound_str1":  ss1,
            "sound_str2":  ss2,
            "index":       idx,
        })

    return data, version, entries


def make_default_entry() -> dict:
    """Return a blank entry with sensible defaults."""
    return {
        "bgm_id":      "ST_BGM_NEW",
        "unk1":        "",
        "unk2":        "",
        "chara_code":  "dmy01",
        "unk3":        "",
        "unlock_cond": 1,
        "menu_index":  1,
        "price":       1000,
        "sound_str1":  "",
        "sound_str2":  "",
        "index":       0,
    }


# Binary builder

def _pad8(buf: bytearray, s: str) -> int:
    """Append null-terminated string padded to 8-byte boundary to buf.
    Returns offset of this string within buf before appending."""
    off = len(buf)
    encoded = s.encode("ascii", errors="replace") + b"\x00"
    buf.extend(encoded)
    rem = len(buf) % 8
    if rem:
        buf.extend(b"\x00" * (8 - rem))
    return off


def _build_binary(version: int, entries: list[dict]) -> bytes:
    """Build the inner binary payload (without the 4-byte BE inner_size field).

    Layout:
      version(4) count(4) first_ptr(8)       ← HEADER_SIZE = 16
      entries × ENTRY_SIZE                   ← 80 bytes each
      string pool (null-term, 8-byte aligned per string, per entry)
    """
    count = len(entries)

    # 1. Build string pool + collect per-field pool offsets
    # pool_abs = absolute offset of pool start inside the FULL payload
    # (including the 4-byte inner_size field that comes before this binary)
    pool_abs = _INNER_SZ + HEADER_SIZE + count * ENTRY_SIZE

    pool: bytearray = bytearray()

    # For each entry, store (off0, off1, off2, off3, off4, off5, off6) = pool offsets
    # for (bgm_id, unk1, unk2, chara_code, unk3, ss1, ss2).
    # -1 means "empty string → write ptr=0"
    offsets: list[tuple] = []

    for e in entries:
        fields = [
            e.get("bgm_id",     ""),
            e.get("unk1",       ""),
            e.get("unk2",       ""),
            e.get("chara_code", ""),
            e.get("unk3",       ""),
            e.get("sound_str1", ""),
            e.get("sound_str2", ""),
        ]
        entry_offs = []
        for s in fields:
            if s:
                entry_offs.append(_pad8(pool, s))
            else:
                entry_offs.append(-1)  # empty → ptr=0
        offsets.append(tuple(entry_offs))

    # 2. Assemble header + entries
    buf = bytearray()
    buf += struct.pack("<I", version)
    buf += struct.pack("<I", count)
    buf += struct.pack("<Q", 8)   # first_ptr = 8 (no notes)

    _FIELD_OFFSETS = (0, 8, 16, 24, 32, 56, 64)  # within entry

    for i, e in enumerate(entries):
        entry_abs = _INNER_SZ + HEADER_SIZE + i * ENTRY_SIZE  # abs in payload+inner_sz

        part = bytearray(ENTRY_SIZE)

        for fi, (foff, pool_off) in enumerate(zip(_FIELD_OFFSETS, offsets[i])):
            if pool_off == -1:
                ptr = 0  # empty string: self-referential null
            else:
                field_abs = entry_abs + foff
                ptr = (pool_abs + pool_off) - field_abs
            struct.pack_into("<Q", part, foff, ptr)

        struct.pack_into("<I", part, 40, int(e.get("unlock_cond", 1)))
        struct.pack_into("<I", part, 44, int(e.get("menu_index",  1)))
        struct.pack_into("<Q", part, 48, int(e.get("price",    1000)))
        struct.pack_into("<Q", part, 72, int(e.get("index",       0)))

        buf += part

    buf += pool

    # Pad to 4-byte boundary
    if len(buf) % 4:
        buf += b"\x00" * (4 - len(buf) % 4)

    return bytes(buf)


def save_soundtestparam_xfbin(
    filepath: str,
    original_data: bytearray,
    version: int,
    entries: list[dict],
) -> None:
    """Rebuild the XFBIN with updated Sound Test entries and write to filepath."""
    new_inner   = _build_binary(version, entries)
    inner_size  = len(new_inner)
    new_payload = struct.pack(">I", inner_size) + new_inner

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

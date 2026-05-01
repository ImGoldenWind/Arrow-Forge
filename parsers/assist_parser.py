"""parsers/assist_parser.py  –  Parser for SupportCharaParam.bin.xfbin.

Binary layout (little-endian, all u32/i32 unless noted):

  [XFBIN prefix]    XFBIN index/header + null/page/index chunks (preserved)
  [chunk header]    12 bytes  (chunk_size BE, type_idx BE, name_idx BE)
  [payload_off+0]   uint32 BE – inner_size  (bytes that follow)
  [payload_off+4]   uint32 LE – type_id
  [payload_off+8]   uint32 LE – entry_count
  [payload_off+12]  uint32 LE – unk8
  [payload_off+16]  uint32 LE – unk0
  [payload_off+20]  N entries × 144 bytes (spm_off = payload_off + 4)
  [after entries]   N char-name slots × 8 bytes (null-padded ASCII)
  [end]             Footer 20 bytes (preserved)

Entry structure (144 = 0x90 bytes, all LE i32):
  +0x00  char_name_ptr  self-relative pointer to char name (auto-recalculated on save)
  +0x04  _pad0          always 0
  +0x08  assault_stocks    Assault Stocks
  +0x0C  reversal_stocks   Reversal Stocks
  +0x10  assault_xpos      Assault Entrance X Position
  +0x14  assault_ypos      Assault Entrance Y Position
  +0x18  assault_xmom      Assault Entrance X Momentum
  +0x1C  reversal_xpos     Reversal Entrance X Position
  +0x20  reversal_ypos     Reversal Entrance Y Position
  +0x24  reversal_xmom     Reversal Entrance X Momentum
  +0x28  stand_act_id      Assault Stand Act ID
  +0x2C  stand_act_kind    Assault Stand Act Kind
  +0x30  user_act_id       Assault User Act ID
  +0x34  user_act_button   Assault User Act Button
  +0x38  add_presses       Assault Add Presses
  +0x3C  assault_unk       Assault Unknown
  +0x40  reversal_unk[0]   Reversal Info Unknown 0
  +0x44  reversal_unk[1]   Reversal Info Unknown 1
  +0x48  reversal_unk[2]   Reversal Info Unknown 2
  +0x4C  reversal_unk[3]   Reversal Info Unknown 3
  +0x50  reversal_unk[4]   Reversal Info Unknown 4
  +0x54  reversal_unk[5]   Reversal Info Unknown 5
  -- Cooldown section (3 interleaved sets × 4 tiers) --
  +0x58  def_cooldown_1    Default Cooldown tier 1
  +0x5C  short_cooldown_1  Short Cooldown tier 1
  +0x60  long_cooldown_1   Long/Reversal Cooldown tier 1
  +0x64  def_cooldown_2    Default Cooldown tier 2
  +0x68  short_cooldown_2  Short Cooldown tier 2
  +0x6C  long_cooldown_2   Long/Reversal Cooldown tier 2
  +0x70  def_cooldown_3    Default Cooldown tier 3
  +0x74  short_cooldown_3  Short Cooldown tier 3
  +0x78  long_cooldown_3   Long/Reversal Cooldown tier 3
  +0x7C  def_cooldown_4    Default Cooldown tier 4
  +0x80  short_cooldown_4  Short Cooldown tier 4
  +0x84  long_cooldown_4   Long/Reversal Cooldown tier 4
  +0x88  _unk              Unknown (hidden, preserved on save)
  +0x8C  assist_type       Assist Type
"""

import struct

# Layout constants

BINARY_HDR_LEN  = 16       # type_id + entry_count + unk8 + unk0
ENTRY_SIZE      = 144      # 0x90
CHAR_SLOT_SIZE  = 8
FOOTER_SIZE     = 20

# Editable field indices (inside the 36-field entry, field index = offset/4)
_EDITABLE = [
    2, 3,               # Assault/Reversal Stocks
    4, 5, 6,            # Assault Entrance XPos, YPos, X Momentum
    7, 8, 9,            # Reversal Entrance XPos, YPos, X Momentum
    10, 11, 12, 13, 14, 15,  # Assault Info
    16, 17, 18, 19, 20, 21,  # Reversal Info (6 unknowns)
    22, 23, 24,         # Cooldown tier 1: Def, Short, Long
    25, 26, 27,         # Cooldown tier 2: Def, Short, Long
    28, 29, 30,         # Cooldown tier 3: Def, Short, Long
    31, 32, 33,         # Cooldown tier 4: Def, Short, Long
    35,                 # Assist Type (field 34 = unk, skipped)
]

FIELD_NAMES = {
    2:  "Assault Stocks",
    3:  "Reversal Stocks",
    4:  "Assault XPos",
    5:  "Assault YPos",
    6:  "Assault X Mom",
    7:  "Reversal XPos",
    8:  "Reversal YPos",
    9:  "Reversal X Mom",
    10: "Stand Act ID",
    11: "Stand Act Kind",
    12: "User Act ID",
    13: "User Act Button",
    14: "Add Presses",
    15: "Assault Unk",
    16: "Rev Unk 0",
    17: "Rev Unk 1",
    18: "Rev Unk 2",
    19: "Rev Unk 3",
    20: "Rev Unk 4",
    21: "Rev Unk 5",
    22: "Def CD 1",
    23: "Short CD 1",
    24: "Long CD 1",
    25: "Def CD 2",
    26: "Short CD 2",
    27: "Long CD 2",
    28: "Def CD 3",
    29: "Short CD 3",
    30: "Long CD 3",
    31: "Def CD 4",
    32: "Short CD 4",
    33: "Long CD 4",
    35: "Assist Type",
}

FIELD_TOOLTIPS = {
    2:  "+0x08 Assault Stocks. Values: 1, 2, 3",
    3:  "+0x0C Reversal Stocks. Values: 1, 2",
    4:  "+0x10 Assault Entrance X Position (signed)",
    5:  "+0x14 Assault Entrance Y Position (signed)",
    6:  "+0x18 Assault Entrance X Momentum (signed)",
    7:  "+0x1C Reversal Entrance X Position (signed)",
    8:  "+0x20 Reversal Entrance Y Position (signed)",
    9:  "+0x24 Reversal Entrance X Momentum (signed)",
    10: "+0x28 Assault Stand Act ID",
    11: "+0x2C Assault Stand Act Kind",
    12: "+0x30 Assault User Act ID",
    13: "+0x34 Assault User Act Button",
    14: "+0x38 Assault Add Presses",
    15: "+0x3C Assault Unknown",
    16: "+0x40 Reversal Info Unknown 0",
    17: "+0x44 Reversal Info Unknown 1",
    18: "+0x48 Reversal Info Unknown 2",
    19: "+0x4C Reversal Info Unknown 3",
    20: "+0x50 Reversal Info Unknown 4",
    21: "+0x54 Reversal Info Unknown 5",
    22: "+0x58 Default Cooldown tier 1",
    23: "+0x5C Short Cooldown tier 1",
    24: "+0x60 Long/Reversal Cooldown tier 1",
    25: "+0x64 Default Cooldown tier 2",
    26: "+0x68 Short Cooldown tier 2",
    27: "+0x6C Long/Reversal Cooldown tier 2",
    28: "+0x70 Default Cooldown tier 3",
    29: "+0x74 Short Cooldown tier 3",
    30: "+0x78 Long/Reversal Cooldown tier 3",
    31: "+0x7C Default Cooldown tier 4",
    32: "+0x80 Short Cooldown tier 4",
    33: "+0x84 Long/Reversal Cooldown tier 4",
    35: "+0x8C Assist Type",
}


# Chunk locator

def _find_binary_chunk(data):
    """Return (chunk_header_offset, chunk_data_size) for nuccChunkBinary.

    Uses the largest-chunk heuristic: the binary data chunk is always the
    largest non-trivial chunk in the file.
    """
    chunk_table_size = struct.unpack(">I", data[16:20])[0]
    offset = 28 + chunk_table_size
    if offset % 4:
        offset += 4 - offset % 4

    best_off  = -1
    best_size = 0

    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset: offset + 4])[0]
        if size >= 20 and size > best_size:
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
        raise ValueError("Could not locate nuccChunkBinary in SupportCharaParam XFBIN.")

    return best_off, best_size


# Parser

def parse_assist_xfbin(filepath):
    """Load SupportCharaParam.bin.xfbin.

    Returns (raw_bytearray, entries) where entries is a list of dicts::

        {
          'char_id': '1jnt01',
          'f2': 1,   # assault_stocks
          'f3': 2,   # reversal_stocks
          'f4': -200, ...
          'f34': 0,  # hidden unk (preserved on save)
          'f35': 5,
        }
    """
    with open(filepath, 'rb') as fh:
        data = bytearray(fh.read())

    if data[:4] != b'NUCC':
        raise ValueError("Not a valid NUCC XFBIN file")

    chunk_hdr_off, _chunk_size = _find_binary_chunk(data)
    # payload_off: start of inner_size field (4 bytes BE) before the data
    payload_off = chunk_hdr_off + 12
    # spm_off: start of the actual binary data (type_id, entry_count, …)
    spm_off = payload_off + 4

    entry_count = struct.unpack_from('<i', data, spm_off + 4)[0]
    if entry_count < 0 or entry_count > 10000:
        raise ValueError(f"Implausible entry count: {entry_count}")

    # Character names are in a fixed-size slot table after all entries
    char_table_off = spm_off + BINARY_HDR_LEN + entry_count * ENTRY_SIZE

    char_names = []
    for i in range(entry_count):
        slot = data[char_table_off + i * CHAR_SLOT_SIZE:
                    char_table_off + i * CHAR_SLOT_SIZE + CHAR_SLOT_SIZE]
        char_names.append(slot.rstrip(b'\x00').decode('ascii', errors='replace'))

    entries = []
    for i in range(entry_count):
        base = spm_off + BINARY_HDR_LEN + i * ENTRY_SIZE
        entry = {'char_id': char_names[i]}
        for fi in _EDITABLE:
            entry[f'f{fi}'] = struct.unpack_from('<i', data, base + fi * 4)[0]
        # Read hidden field 34 so we can round-trip it unchanged
        entry['f34'] = struct.unpack_from('<i', data, base + 34 * 4)[0]
        entries.append(entry)

    return data, entries


# Default entry factory

def make_default_entry(char_id=''):
    """Return a blank assist entry with sensible defaults."""
    entry = {'char_id': char_id, 'f34': 0}
    for fi in _EDITABLE:
        entry[f'f{fi}'] = 0
    entry['f2'] = 1   # assault_stocks
    entry['f3'] = 1   # reversal_stocks
    return entry


# Serialiser

def save_assist_xfbin(filepath, original_data, entries):
    """Rebuild SupportCharaParam.bin.xfbin with the given entries and write it.

    Supports adding and removing entries (entry count is no longer fixed).
    The XFBIN prefix, chunk header type/name indices, and the 20-byte footer
    are all preserved from *original_data*.  The chunk size field and
    entry_count are updated automatically.
    """
    n = len(entries)

    chunk_hdr_off, orig_chunk_size = _find_binary_chunk(original_data)
    payload_off = chunk_hdr_off + 12   # inner_size field (BE u32)
    spm_off     = payload_off + 4      # actual binary data

    # Preserve the three constant fields from the binary header
    type_id = struct.unpack_from('<i', original_data, spm_off)[0]
    unk8    = struct.unpack_from('<i', original_data, spm_off + 8)[0]
    unk0    = struct.unpack_from('<i', original_data, spm_off + 12)[0]

    # Read footer from the end of the original chunk data
    orig_chunk_end = chunk_hdr_off + 12 + orig_chunk_size
    footer = bytes(original_data[orig_chunk_end - FOOTER_SIZE: orig_chunk_end])

    # Build inner binary

    inner = bytearray()

    # Binary header (16 bytes)
    inner += struct.pack('<i', type_id)
    inner += struct.pack('<i', n)
    inner += struct.pack('<i', unk8)
    inner += struct.pack('<i', unk0)

    # Entry blocks (144 bytes each)
    # char_name_ptr for entry i with N total entries:
    #   name slot i is at:  binary_hdr(16) + N*144 + i*8  (relative to spm_off)
    #   field[0] is at:     binary_hdr(16) + i*144 + 0    (relative to spm_off)
    #   ptr = N*144 + i*8 - i*144 = N*144 - i*136
    for i, entry in enumerate(entries):
        entry_buf = bytearray(ENTRY_SIZE)
        char_name_ptr = n * ENTRY_SIZE - i * (ENTRY_SIZE - CHAR_SLOT_SIZE)
        struct.pack_into('<i', entry_buf, 0,        char_name_ptr)
        struct.pack_into('<i', entry_buf, 4,        0)              # pad0
        for fi in _EDITABLE:
            struct.pack_into('<i', entry_buf, fi * 4, int(entry[f'f{fi}']))
        struct.pack_into('<i', entry_buf, 34 * 4,  int(entry.get('f34', 0)))
        inner += entry_buf

    # Char name table (8 bytes per slot, null-padded ASCII)
    for entry in entries:
        cid = entry['char_id']
        raw = cid.encode('ascii', errors='replace')[:CHAR_SLOT_SIZE]
        inner += raw + b'\x00' * (CHAR_SLOT_SIZE - len(raw))

    # Footer
    inner += footer

    # Pad inner to 4-byte boundary
    if len(inner) % 4:
        inner += b'\x00' * (4 - len(inner) % 4)

    # Assemble final file

    inner_size  = len(inner)
    new_payload = struct.pack('>I', inner_size) + bytes(inner)
    if len(new_payload) % 4:
        new_payload += b'\x00' * (4 - len(new_payload) % 4)

    prefix   = bytes(original_data[:chunk_hdr_off])
    orig_hdr = bytearray(original_data[chunk_hdr_off: chunk_hdr_off + 12])
    struct.pack_into('>I', orig_hdr, 0, len(new_payload))
    new_hdr  = bytes(orig_hdr)

    # Everything after the original chunk (padding included)
    if orig_chunk_end % 4:
        orig_chunk_end += 4 - orig_chunk_end % 4
    trailing = bytes(original_data[orig_chunk_end:])

    with open(filepath, 'wb') as fh:
        fh.write(prefix + new_hdr + new_payload + trailing)

"""
NUS3BANK / XFBIN Audio parser & writer

Supports XFBIN containers used in All Star Battle R that hold NUS3BANK
sound banks (battle.xfbin, gimmick.xfbin, character xfbin banks, …).

XFBIN structure
  [0:4]   'NUCC' magic
  [4:28]  header (version, table sizes, chunk count, all big-endian)
  ...string / path / name tables...
  Chunks:  each chunk is immediately preceded by a 12-byte descriptor:
    [desc+0:+4]   version / flags  (BE u32)
    [desc+4:+8]   type/path info   (BE)
    [desc+8:+12]  chunk_data_size  (BE u32)  ← NUS3BANK blob size
  And 4 bytes further back in the chunk-map there is another field:
    [desc-4:desc]  chunk_data_size + 4  (BE u32)

NUS3BANK blob
  [0:4]   'NUS3' magic
  [4:8]   file_size (LE u32) = chunk_data_size - 8
  Sections (see SECTION_* constants):
    Each section: tag(4 or 8 bytes) + size(4 bytes LE) + data

  BANKTOC  – table of contents (8-byte tag 'BANKTOC ')
  PROP     – project properties
  BINF     – bank info (bank name string)
  GRP      – sound groups (complex, preserved verbatim)
  DTON     – data-tone references (preserved verbatim)
  TONE     – array of tone entries (see ToneEntry)
  JUNK     – padding
  PACK     – concatenated BNSF audio blobs, one per tone

TONE entry  (variable size, always 4-byte aligned)
  [0:4]    flags (LE u32, usually 0)
  [4:12]   type_id (8 bytes, constant per bank)
  [12]     name_len (u8, includes null terminator)
  [13 : 13+name_len]  name string (null-terminated)
  padded to next 4-byte boundary  ← params start here
  params (224 bytes):
    rel+0x08  pack_offset  u32 LE  (offset into PACK section data)
    rel+0x0C  pack_size    u32 LE  (byte size of this tone's BNSF)
    rel+0x1C  volume       f32     (1.0 = 100 %)
    rel+0x20  pitch        f32     (1.0 = no shift)
    rel+0x24  pan_3d       f32     (degrees, -90 default)
    rel+0x2C  send_level   f32     (1.0 default)
    rel+0x5C  track_count  u32     (1 for mono)
    rel+0x60  pan_2d       f32
    rel+0x78  sample_rate  u32     (48000)
    rel+0x7C  channel_count u32    (1)
    rel+0x80  total_samples u32
    rel+0x94  loop_start   u32     (0xFFFFFFFF = no loop)
    rel+0x9C  loop_end     u32     (0xFFFFFFFF = no loop)

BNSF audio blob  (big-endian fields inside)
  [0:4]   'BNSF' magic
  [4:8]   unk_field (BE u32)
  [8:12]  codec tag 'IS14'
  sfmt section:  'sfmt'(4) + size_BE(4) + channels_BE(4) + samplerate_BE(4)
                 + total_samples_BE(4) + unk(4) + unk(4)   → 28 bytes total
  sdat section:  'sdat'(4) + size_BE(4) + audio_data
"""

import struct

# Constants

NUS3_MAGIC  = b'NUS3'
NUCC_MAGIC  = b'NUCC'
BNSF_MAGIC  = b'BNSF'
IS14_TAG    = b'IS14'
SFMT_TAG    = b'sfmt'
SDAT_TAG    = b'sdat'

BANKTOC_TAG = b'BANKTOC '   # 8-byte tag
PROP_TAG    = b'PROP'
BINF_TAG    = b'BINF'
GRP_TAG     = b'GRP '
DTON_TAG    = b'DTON'
TONE_TAG    = b'TONE'
JUNK_TAG    = b'JUNK'
PACK_TAG    = b'PACK'

SECTION_ORDER = [PROP_TAG, BINF_TAG, GRP_TAG, DTON_TAG,
                 TONE_TAG, JUNK_TAG, PACK_TAG]

# PACK alignment between consecutive BNSF blobs (game expects 16-byte)
PACK_ALIGN  = 16

# Usual size of the 'params' block appended after the padded name. Some
# character PL banks use a compact 220-byte variant where later fields are
# shifted back by 4 bytes.
PARAMS_SIZE = 224
COMPACT_PARAMS_SIZE = 220
_MIN_AUDIO_PARAMS_SIZE = 0x9C

# Offsets within the params block (relative to params_start)
_P_PACK_OFFSET   = 0x08
_P_PACK_SIZE     = 0x0C
_P_VOLUME        = 0x1C
_P_PITCH         = 0x20
_P_PAN_3D        = 0x24
_P_SEND_LEVEL    = 0x2C
_P_TRACK_COUNT   = 0x5C
_P_PAN_2D        = 0x60
_P_SAMPLE_RATE   = 0x78
_P_CHANNEL_COUNT = 0x7C
_P_TOTAL_SAMPLES = 0x80
_P_LOOP_START    = 0x94
_P_LOOP_END      = 0x9C
_COMPACT_OFFSET_SHIFT_AT = _P_TRACK_COUNT


# Low-level helpers

def _u32le(d, o): return struct.unpack_from('<I', d, o)[0]
def _u32be(d, o): return struct.unpack_from('>I', d, o)[0]
def _f32le(d, o): return struct.unpack_from('<f', d, o)[0]
def _wu32le(d, o, v): struct.pack_into('<I', d, o, int(v & 0xFFFFFFFF))
def _wu32be(d, o, v): struct.pack_into('>I', d, o, int(v & 0xFFFFFFFF))
def _wf32le(d, o, v): struct.pack_into('<f', d, o, float(v))

def _align_up(n, align):
    return n if n % align == 0 else n + (align - n % align)


def _param_offset(params_size: int, off: int) -> int:
    """Return the on-disk offset for a TONE field in the current layout."""
    if params_size < PARAMS_SIZE and off >= _COMPACT_OFFSET_SHIFT_AT:
        return off - 4
    return off


def _read_param_u32(raw: bytes, ps: int, params_size: int,
                    off: int, default: int = 0) -> int:
    real = _param_offset(params_size, off)
    if real < 0 or real + 4 > params_size:
        return default
    return _u32le(raw, ps + real)


def _read_param_f32(raw: bytes, ps: int, params_size: int,
                    off: int, default: float = 0.0) -> float:
    real = _param_offset(params_size, off)
    if real < 0 or real + 4 > params_size:
        return default
    return _f32le(raw, ps + real)


def _write_param_u32(buf: bytearray, ps: int, params_size: int,
                     off: int, value: int) -> None:
    real = _param_offset(params_size, off)
    if real >= 0 and real + 4 <= params_size:
        _wu32le(buf, ps + real, value)


def _write_param_f32(buf: bytearray, ps: int, params_size: int,
                     off: int, value: float) -> None:
    real = _param_offset(params_size, off)
    if real >= 0 and real + 4 <= params_size:
        _wf32le(buf, ps + real, value)


# BNSF helpers

def parse_bnsf_meta(blob: bytes) -> dict:
    """Extract metadata from a raw BNSF blob.

    Returns a dict with keys: sample_rate, channel_count, total_samples,
    sdat_size, codec.  Returns None if not a valid BNSF.
    """
    if len(blob) < 48 or blob[0:4] != BNSF_MAGIC:
        return None
    codec = blob[8:12]

    sections = {}
    pos = 12
    while pos + 8 <= len(blob):
        tag = blob[pos:pos + 4]
        size = _u32be(blob, pos + 4)
        data_off = pos + 8
        data_end = data_off + size
        if not tag.strip(b'\x00 '):
            break
        if data_end > len(blob):
            break
        sections[tag] = blob[data_off:data_end]
        pos = _align_up(data_end, 4)

    sfmt = sections.get(SFMT_TAG)
    sdat = sections.get(SDAT_TAG)
    if sfmt is None or sdat is None:
        return None
    if len(sfmt) < 20:
        return None
    channels      = _u32be(sfmt, 0)
    sample_rate   = _u32be(sfmt, 4)
    total_samples = _u32be(sfmt, 8)
    sdat_size     = len(sdat)
    return {
        'sample_rate':   sample_rate,
        'channel_count': channels,
        'total_samples': total_samples,
        'sdat_size':     sdat_size,
        'codec':         codec.decode('ascii', errors='replace'),
    }


def build_bnsf(audio_data: bytes, sample_rate: int, channels: int,
               total_samples: int, unk_field: int = 0x0910) -> bytes:
    """Build a minimal IS14 BNSF blob wrapping raw IS14 audio_data."""
    sdat_size  = len(audio_data)
    sfmt_size  = 20
    # Header: BNSF(4) + unk(4) + IS14(4) + sfmt hdr(8) + sfmt data(20) + sdat hdr(8)
    hdr = bytearray(4 + 4 + 4 + 8 + sfmt_size + 8)
    hdr[0:4]  = BNSF_MAGIC
    struct.pack_into('>I', hdr, 4,  unk_field)
    hdr[8:12] = IS14_TAG
    hdr[12:16] = SFMT_TAG
    struct.pack_into('>I', hdr, 16, sfmt_size)
    struct.pack_into('>I', hdr, 20, channels)
    struct.pack_into('>I', hdr, 24, sample_rate)
    struct.pack_into('>I', hdr, 28, total_samples)
    struct.pack_into('>I', hdr, 32, 0)  # unk
    struct.pack_into('>I', hdr, 36, 0)  # unk
    sdat_off = 40
    hdr[sdat_off:sdat_off + 4] = SDAT_TAG
    struct.pack_into('>I', hdr, sdat_off + 4, sdat_size)
    return bytes(hdr) + audio_data


# TONE entry

class ToneEntry:
    """Represents a single sound tone inside a NUS3BANK."""
    __slots__ = (
        'name', 'flags', 'type_id',
        'pack_offset', 'pack_size',
        'volume', 'pitch', 'pan_3d', 'pan_2d', 'send_level',
        'track_count', 'sample_rate', 'channel_count', 'total_samples',
        'loop_start', 'loop_end',
        '_raw_params',   # params blob (editable fields patched on write)
        '_params_size',  # standard 224-byte or compact 220-byte TONE params
        '_bnsf_blob',    # raw BNSF bytes, or None if not yet extracted
    )

    def __init__(self):
        self.name          = ''
        self.flags         = 0
        self.type_id       = b'\xff\xff\x27\x84\x1f\x98\x0c\x00'
        self.pack_offset   = 0
        self.pack_size     = 0
        self.volume        = 1.0
        self.pitch         = 1.0
        self.pan_3d        = -90.0
        self.pan_2d        = -90.0
        self.send_level    = 1.0
        self.track_count   = 1
        self.sample_rate   = 48000
        self.channel_count = 1
        self.total_samples = 0
        self.loop_start    = 0xFFFFFFFF
        self.loop_end      = 0xFFFFFFFF
        self._raw_params   = bytearray(PARAMS_SIZE)
        self._params_size  = PARAMS_SIZE
        self._bnsf_blob    = None

    # computed properties

    @property
    def duration_sec(self) -> float:
        if self.sample_rate > 0:
            return self.total_samples / self.sample_rate
        return 0.0

    @property
    def looping(self) -> bool:
        return self.loop_start != 0xFFFFFFFF

    # serialise

    def _build_entry_bytes(self) -> bytes:
        """Serialise this ToneEntry to its on-disk binary form."""
        name_b = self.name.encode('ascii', errors='replace')
        name_len = len(name_b) + 1          # include null terminator
        raw_name = name_b + b'\x00'

        # Fixed header: flags(4) + type_id(8) + len_byte(1) + name
        before_pad = 4 + 8 + 1 + name_len   # 13 + name_len
        params_start = _align_up(before_pad, 4)
        params_size  = max(_MIN_AUDIO_PARAMS_SIZE, getattr(self, '_params_size', PARAMS_SIZE))
        entry_size   = params_start + params_size

        buf = bytearray(entry_size)
        _wu32le(buf, 0, self.flags)
        buf[4:12] = self.type_id[:8].ljust(8, b'\x00')
        buf[12]   = name_len & 0xFF
        buf[13:13 + len(raw_name)] = raw_name

        # Copy the preserved raw params, then patch editable fields
        ps = params_start
        raw_params = bytes(self._raw_params[:params_size]).ljust(params_size, b'\x00')
        buf[ps:ps + params_size] = raw_params

        _write_param_u32(buf, ps, params_size, _P_PACK_OFFSET,   self.pack_offset)
        _write_param_u32(buf, ps, params_size, _P_PACK_SIZE,     self.pack_size)
        _write_param_f32(buf, ps, params_size, _P_VOLUME,        self.volume)
        _write_param_f32(buf, ps, params_size, _P_PITCH,         self.pitch)
        _write_param_f32(buf, ps, params_size, _P_PAN_3D,        self.pan_3d)
        _write_param_f32(buf, ps, params_size, _P_SEND_LEVEL,    self.send_level)
        _write_param_u32(buf, ps, params_size, _P_TRACK_COUNT,   self.track_count)
        _write_param_f32(buf, ps, params_size, _P_PAN_2D,        self.pan_2d)
        _write_param_u32(buf, ps, params_size, _P_SAMPLE_RATE,   self.sample_rate)
        _write_param_u32(buf, ps, params_size, _P_CHANNEL_COUNT, self.channel_count)
        _write_param_u32(buf, ps, params_size, _P_TOTAL_SAMPLES, self.total_samples)
        _write_param_u32(buf, ps, params_size, _P_LOOP_START,    self.loop_start)
        _write_param_u32(buf, ps, params_size, _P_LOOP_END,      self.loop_end)

        return bytes(buf)


# Bank

class Nus3Bank:
    """In-memory representation of one NUS3BANK inside an XFBIN."""
    __slots__ = (
        'name',           # e.g. "battle"
        'tones',          # list[ToneEntry]
        '_tone_records',  # list[ToneEntry | bytes] preserving non-audio entries
        '_sections',      # dict: tag_bytes -> raw_section_data (preserved verbatim)
        '_tone_type_id',  # 8-byte identifier common to all tones in this bank
        '_tone_param_size',# params size to use when adding new tones
        '_nus3_off',      # byte offset of NUS3 magic in the XFBIN file
        '_xfbin_desc_off',# byte offset of the 12-byte chunk descriptor
    )

    def __init__(self):
        self.name          = ''
        self.tones         = []
        self._tone_records = []
        self._sections     = {}
        self._tone_type_id = b'\xff\xff\x27\x84\x1f\x98\x0c\x00'
        self._tone_param_size = PARAMS_SIZE
        self._nus3_off     = -1
        self._xfbin_desc_off = -1


# Parsing

def _parse_section(data: bytes, pos: int) -> tuple:
    """Parse one NUS3BANK section starting at *pos*.

    Returns (tag, section_data_bytes, next_pos).
    BANKTOC has an 8-byte tag; all others have a 4-byte tag.
    """
    tag4 = data[pos:pos + 4]
    if tag4 == b'BANK':
        tag      = data[pos:pos + 8]
        size     = _u32le(data, pos + 8)
        data_off = pos + 12
    else:
        tag      = tag4
        size     = _u32le(data, pos + 4)
        data_off = pos + 8
    return tag, data[data_off:data_off + size], data_off + size


def _parse_tone_section(tone_data: bytes) -> tuple:
    """Parse the raw TONE section data.

    Returns (audio_tones, all_records). all_records preserves non-audio TONE
    entries as raw bytes so saving an edited bank does not drop placeholders or
    cue-only records.
    """
    if len(tone_data) < 8:
        return [], []

    count         = _u32le(tone_data, 0)
    data_block_off= _u32le(tone_data, 4)   # offset to first entry, relative to tone_data

    # Build offset → end_offset table (271 entries × 8 bytes from offset 8)
    entry_ends = []
    for i in range(max(0, count - 1)):
        tbl_off  = 8 + i * 8
        if tbl_off + 8 > len(tone_data):
            break
        end_rel  = _u32le(tone_data, tbl_off + 4)  # end of this entry (rel to tone_data)
        entry_ends.append(end_rel)
    if count:
        entry_ends.append(len(tone_data))

    tones = []
    records = []
    entry_start = data_block_off
    for i, entry_end in enumerate(entry_ends):
        if entry_end > len(tone_data):
            break
        raw = tone_data[entry_start:entry_end]
        t   = _parse_tone_entry(raw)
        if t:
            tones.append(t)
            records.append(t)
        else:
            records.append(bytes(raw))
        entry_start = entry_end

    return tones, records


def _parse_tone_entry(raw: bytes) -> ToneEntry:
    """Parse a single variable-length tone entry buffer."""
    if len(raw) < 14:
        return None

    t          = ToneEntry()
    t.flags    = _u32le(raw, 0)
    t.type_id  = raw[4:12]

    name_len   = raw[12]
    name_bytes = raw[13:13 + name_len]
    t.name     = name_bytes.rstrip(b'\x00').decode('ascii', errors='replace')

    before_pad  = 13 + name_len
    params_start = _align_up(before_pad, 4)
    params_size = len(raw) - params_start
    if params_size < _MIN_AUDIO_PARAMS_SIZE:
        return None

    ps = params_start
    t._params_size   = params_size
    t._raw_params    = bytearray(raw[ps:ps + params_size])

    t.pack_offset    = _read_param_u32(raw, ps, params_size, _P_PACK_OFFSET)
    t.pack_size      = _read_param_u32(raw, ps, params_size, _P_PACK_SIZE)
    if t.pack_size <= 0:
        return None
    t.volume         = _read_param_f32(raw, ps, params_size, _P_VOLUME, 1.0)
    t.pitch          = _read_param_f32(raw, ps, params_size, _P_PITCH, 1.0)
    t.pan_3d         = _read_param_f32(raw, ps, params_size, _P_PAN_3D, -90.0)
    t.send_level     = _read_param_f32(raw, ps, params_size, _P_SEND_LEVEL, 1.0)
    t.track_count    = _read_param_u32(raw, ps, params_size, _P_TRACK_COUNT, 1)
    t.pan_2d         = _read_param_f32(raw, ps, params_size, _P_PAN_2D, -90.0)
    t.sample_rate    = _read_param_u32(raw, ps, params_size, _P_SAMPLE_RATE, 48000)
    t.channel_count  = _read_param_u32(raw, ps, params_size, _P_CHANNEL_COUNT, 1)
    t.total_samples  = _read_param_u32(raw, ps, params_size, _P_TOTAL_SAMPLES)
    t.loop_start     = _read_param_u32(raw, ps, params_size, _P_LOOP_START, 0xFFFFFFFF)
    t.loop_end       = _read_param_u32(raw, ps, params_size, _P_LOOP_END, 0xFFFFFFFF)

    return t


def _extract_bnsf_blobs(pack_data: bytes, tones: list) -> None:
    """Populate tone._bnsf_blob from the PACK section data."""
    for t in tones:
        off = t.pack_offset
        sz  = t.pack_size
        if off + sz <= len(pack_data):
            t._bnsf_blob = bytes(pack_data[off:off + sz])
        else:
            # Fallback: span from pack_offset to the natural BNSF boundary
            if off < len(pack_data) and pack_data[off:off + 4] == BNSF_MAGIC:
                # Try to read size from BNSF directly
                sfmt_off = 12
                if len(pack_data) > off + sfmt_off + 8:
                    sfmt_size = _u32be(pack_data, off + sfmt_off + 4)
                    sdat_hdr  = off + sfmt_off + 4 + sfmt_size + 4
                    if len(pack_data) > sdat_hdr + 4:
                        sdat_size = _u32be(pack_data, sdat_hdr)
                        bnsf_end  = sdat_hdr + 4 + sdat_size
                        t._bnsf_blob = bytes(pack_data[off:bnsf_end])
                        t.pack_size  = len(t._bnsf_blob)
        meta = parse_bnsf_meta(t._bnsf_blob) if t._bnsf_blob else None
        if meta:
            t.sample_rate   = meta['sample_rate']
            t.channel_count = meta['channel_count']
            t.total_samples = meta['total_samples']


def _parse_nus3bank(data: bytes, nus3_off: int) -> Nus3Bank:
    """Parse a NUS3BANK blob starting at *nus3_off* in *data*."""
    bank = Nus3Bank()
    bank._nus3_off = nus3_off

    pos = nus3_off + 8   # skip 'NUS3' + size

    # Walk all sections
    pack_data   = None
    tone_raw    = None
    banktoc_raw = None
    end_pos     = nus3_off + 8 + _u32le(data, nus3_off + 4)

    while pos < end_pos and pos < len(data) - 4:
        tag, sec_data, next_pos = _parse_section(data, pos)
        tag_stripped = tag.rstrip(b' ')

        if tag_stripped == b'BANKTOC':
            banktoc_raw = sec_data
        elif tag_stripped == TONE_TAG:
            tone_raw    = sec_data
        elif tag_stripped == PACK_TAG:
            pack_data   = sec_data
        elif tag_stripped == BINF_TAG:
            # Extract bank name (1-byte length, then string)
            if len(sec_data) >= 9:
                name_len = sec_data[8] if len(sec_data) > 8 else 0
                bank.name = sec_data[9:9 + name_len].rstrip(b'\x00').decode(
                    'ascii', errors='replace')
        bank._sections[tag] = sec_data
        pos = next_pos

    if tone_raw:
        bank.tones, bank._tone_records = _parse_tone_section(tone_raw)
        # Capture the common type_id from the first tone
        if bank.tones:
            bank._tone_type_id = bank.tones[0].type_id
            bank._tone_param_size = bank.tones[0]._params_size

    if pack_data and bank.tones:
        _extract_bnsf_blobs(pack_data, bank.tones)

    return bank


def parse_xfbin_audio(filepath: str) -> tuple:
    """Parse an XFBIN file and return (raw_data: bytearray, banks: list[Nus3Bank]).

    Locates all NUS3BANK chunks by scanning for 'NUS3' magic.
    Each found bank is fully parsed (TONE + PACK sections).
    """
    with open(filepath, 'rb') as f:
        raw = bytearray(f.read())

    banks = []
    search_from = 0
    while True:
        pos = raw.find(NUS3_MAGIC, search_from)
        if pos < 0:
            break
        # Verify it's a real NUS3BANK by checking the file size makes sense
        if pos + 8 <= len(raw):
            internal_size = _u32le(raw, pos + 4)
            if internal_size > 0 and pos + 8 + internal_size <= len(raw) + 16:
                bank = _parse_nus3bank(bytes(raw), pos)
                if bank.tones:   # only include banks that have audio
                    bank._xfbin_desc_off = pos - 12 if pos >= 12 else -1
                    banks.append(bank)
        search_from = pos + 4

    return raw, banks


# Building

def _build_tone_section(tones: list, orig_tone_data: bytes, records: list = None) -> bytes:
    """Rebuild the TONE section data with updated tone entries.

    The global header (count, data_block_off) and the offset table are
    recalculated; each entry is rebuilt from its ToneEntry fields.
    """
    records = records or tones
    count = len(records)
    if count == 0:
        return orig_tone_data   # fallback

    # Build entry bytes and compute cumulative offsets
    entry_blobs = [
        r._build_entry_bytes() if isinstance(r, ToneEntry) else bytes(r)
        for r in records
    ]
    sizes       = [len(b) for b in entry_blobs]

    # Header: count(4) + data_block_off(4) + offset_table((count - 1) * 8)
    header_size  = 4 + count * 8
    data_block_off = header_size   # entries immediately follow the table

    buf = bytearray(header_size + sum(sizes))
    _wu32le(buf, 0, count)
    _wu32le(buf, 4, data_block_off)

    cum = data_block_off
    for i, sz in enumerate(sizes[:-1]):
        tbl_off = 8 + i * 8
        _wu32le(buf, tbl_off,     sz)                  # entry stride / size
        cum += sz
        _wu32le(buf, tbl_off + 4, cum)                 # cumulative end offset

    pos = header_size
    for blob in entry_blobs:
        buf[pos:pos + len(blob)] = blob
        pos += len(blob)

    return bytes(buf)


def _build_pack_section(tones: list, orig_pack: bytes = None) -> tuple:
    """Rebuild the PACK section and update pack_offset/pack_size in each tone.

    Returns the new PACK data bytes.
    """
    if orig_pack is not None:
        unchanged = True
        for t in tones:
            blob = t._bnsf_blob or b''
            if not blob or t.pack_offset + t.pack_size > len(orig_pack):
                unchanged = False
                break
            if bytes(orig_pack[t.pack_offset:t.pack_offset + t.pack_size]) != blob:
                unchanged = False
                break
        if unchanged:
            return bytes(orig_pack)

    parts = []
    offset = 0
    for t in tones:
        blob = t._bnsf_blob or b''
        # Update tone's pack reference before building entry bytes
        t.pack_offset = offset
        t.pack_size   = len(blob)
        parts.append(blob)
        offset += len(blob)
        # Align to PACK_ALIGN
        aligned = _align_up(offset, PACK_ALIGN)
        if aligned > offset:
            parts.append(b'\x00' * (aligned - offset))
            offset = aligned

    return b''.join(parts)


def _build_nus3bank(bank: Nus3Bank) -> bytes:
    """Rebuild an entire NUS3BANK blob from a Nus3Bank object."""
    # Rebuild PACK first (updates pack_offset / pack_size in tones)
    new_pack = _build_pack_section(bank.tones, bank._sections.get(PACK_TAG))

    # Rebuild TONE section
    orig_tone = bank._sections.get(TONE_TAG, b'')
    new_tone  = _build_tone_section(
        bank.tones, orig_tone, getattr(bank, '_tone_records', None))

    # Update JUNK (preserve original, typically 8 bytes of zeros)
    junk_data = bank._sections.get(JUNK_TAG, b'\x00' * 8)

    # Rebuild BANKTOC: count(4) + 7×(tag(4)+size(4)) = 60 bytes
    # Sections: PROP, BINF, GRP, DTON, TONE, JUNK, PACK
    section_data = {
        PROP_TAG: bank._sections.get(PROP_TAG, b''),
        BINF_TAG: bank._sections.get(BINF_TAG, b''),
        GRP_TAG:  bank._sections.get(GRP_TAG,  b''),
        DTON_TAG: bank._sections.get(DTON_TAG, b''),
        TONE_TAG: new_tone,
        JUNK_TAG: junk_data,
        PACK_TAG: new_pack,
    }
    toc_count = len(SECTION_ORDER)
    toc_data  = struct.pack('<I', toc_count)
    for tag in SECTION_ORDER:
        toc_data += tag + struct.pack('<I', len(section_data[tag]))

    # Assemble all sections in order
    body = bytearray()

    def _add_section(tag, data_bytes):
        if tag == BANKTOC_TAG:
            body.extend(BANKTOC_TAG)
            body.extend(struct.pack('<I', len(data_bytes)))
        else:
            body.extend(tag)
            body.extend(struct.pack('<I', len(data_bytes)))
        body.extend(data_bytes)

    _add_section(BANKTOC_TAG, toc_data)
    for tag in SECTION_ORDER:
        _add_section(tag, section_data[tag])

    # NUS3 header
    internal_size = len(body)
    header = NUS3_MAGIC + struct.pack('<I', internal_size)

    return header + bytes(body)


# Saving

def save_xfbin_audio(filepath: str, raw: bytearray, banks: list) -> None:
    """Rebuild the XFBIN with modified NUS3BANK blobs and write to *filepath*.

    Strategy:
    1. Sort banks by their original offset.
    2. Walk through the original file, replacing each NUS3BANK chunk in-place.
       If a bank grew, subsequent data is shifted; size fields are updated.
    """
    result  = bytearray()
    src_pos = 0

    # Sort by original offset so we process in file order
    sorted_banks = sorted(banks, key=lambda b: b._nus3_off)

    for bank in sorted_banks:
        nus3_off = bank._nus3_off
        if nus3_off < 0:
            continue

        # Original chunk size (everything from NUS3 magic to end of blob)
        orig_internal = _u32le(raw, nus3_off + 4)
        orig_chunk_sz = orig_internal + 8

        # Copy everything before this NUS3BANK (including its 12-byte descriptor)
        result.extend(raw[src_pos:nus3_off])
        src_pos = nus3_off + orig_chunk_sz

        # Build the new NUS3BANK blob
        new_blob     = _build_nus3bank(bank)
        new_chunk_sz = len(new_blob)

        result.extend(new_blob)

        # Patch the size fields in the descriptor (they sit in what we already copied)
        # descriptor is at result[-new_chunk_sz - 12 : -new_chunk_sz]
        desc_start = len(result) - new_chunk_sz - 12
        if desc_start >= 0:
            # desc+8 = exact chunk size (BE u32)
            struct.pack_into('>I', result, desc_start + 8, new_chunk_sz)
            # desc-4 = chunk size + 4 (BE u32)
            size_plus4_off = desc_start - 4
            if size_plus4_off >= 0:
                struct.pack_into('>I', result, size_plus4_off, new_chunk_sz + 4)

    # Append any remaining data after the last NUS3BANK
    if src_pos < len(raw):
        result.extend(raw[src_pos:])

    with open(filepath, 'wb') as f:
        f.write(result)


# Convenience

def get_tone_bnsf(tone: ToneEntry) -> bytes:
    """Return the raw BNSF bytes for this tone, or None."""
    return tone._bnsf_blob


def set_tone_bnsf(tone: ToneEntry, bnsf_bytes: bytes) -> None:
    """Replace this tone's audio data with new BNSF bytes.

    Also refreshes sample_rate / channel_count / total_samples from the
    new BNSF header so the TONE entry reflects the actual audio.
    """
    tone._bnsf_blob = bnsf_bytes
    tone.pack_size  = len(bnsf_bytes)
    meta = parse_bnsf_meta(bnsf_bytes)
    if meta:
        tone.sample_rate   = meta['sample_rate']
        tone.channel_count = meta['channel_count']
        tone.total_samples = meta['total_samples']

"""Preserving NUS3BANK stream records inside ASBR XFBIN containers.

Optional TONE fields are walked from native flag words and array lengths
(RVA B23D60), never inferred from the total record size. The legacy public
attribute names volume/pitch/pan_3d/track_count/pan_2d/loop_start/loop_end are
retained for compatibility; they are NOT source gain/pitch/pan/loop operands.
Source gain_db/pan_degrees/pitch_cents are at flags0 bits 2/3/4. Stream loops
belong to BNSF or RIFF headers (core.xfbin_audio_tools).

Unmodified entry bytes, names, section order, opaque records and PACK bytes
are retained. Replaced audio is appended so opaque native offsets survive.
XFBIN descriptors are patched only at validated embedded-bank boundaries.
"""

import struct
import os
import tempfile

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

# Common observed sizes; parsed optional-field offsets use flags and counts.
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
    """Siren BNSF header; loop end on disk is inclusive."""
    if len(blob) < 48 or blob[:4] != BNSF_MAGIC or blob[8:12] not in (b'IS14', b'IS22'):
        return None
    if _u32be(blob, 4) + (0 if blob[8:12] == b'IS22' else 8) != len(blob):
        return None
    sections = {}
    pos = 12
    while pos < len(blob):
        if pos + 8 > len(blob):
            return None
        tag, size = blob[pos:pos + 4], _u32be(blob, pos + 4)
        end = pos + 8 + size
        if end > len(blob):
            return None
        sections[tag] = (pos, memoryview(blob)[pos + 8:end])
        pos = end + (size & 1)
    if SFMT_TAG not in sections or SDAT_TAG not in sections:
        return None
    sfmt = sections[SFMT_TAG][1]
    if len(sfmt) < 20:
        return None
    flags, channels, rate, samples, adjust, block_size, block_samples = struct.unpack_from('>HHIIIHH', sfmt)
    if channels not in (1, 2) or not rate or not samples or not block_size or not block_samples or adjust >= block_samples:
        return None
    payload_size = len(sections[SDAT_TAG][1])
    if payload_size % block_size or block_size % channels or payload_size // block_size * block_samples < samples:
        return None
    loop = sections.get(b'loop')
    start, end = (None, None)
    if loop:
        if len(loop[1]) < 8:
            return None
        start, end = struct.unpack_from('>II', loop[1])
        start, end = start + adjust, end + 1
    return dict(sample_rate=rate, channel_count=channels, total_samples=samples,
                sdat_size=len(sections[SDAT_TAG][1]), codec=blob[8:12].decode('ascii'),
                flags=flags, block_size=block_size, block_samples=block_samples,
                loop_start=start, loop_end=end, loop_adjust=adjust)


def build_bnsf(audio_data, sample_rate, channels, total_samples, *, block_size, block_samples):
    """Wrap already encoded Siren14 frames. This function does not encode PCM."""
    if channels not in (1, 2) or not block_size or not block_samples or len(audio_data) % block_size:
        raise ValueError('Invalid Siren14 frame layout')
    body = b'IS14sfmt' + struct.pack('>IHHIIIHH', 20, 0, channels, sample_rate, total_samples, 0, block_size, block_samples)
    body += b'sdat' + struct.pack('>I', len(audio_data)) + audio_data
    return BNSF_MAGIC + struct.pack('>I', len(body)) + body


# TONE entry

class ToneEntry:
    """Represents a single sound tone inside a NUS3BANK."""
    __slots__ = (
        'name', 'flags', 'type_id',
        'pack_offset', 'pack_size',
        'gain_db', 'pan_degrees', 'pitch_cents',
        'volume', 'pitch', 'pan_3d', 'pan_2d', 'send_level',
        'track_count', 'sample_rate', 'channel_count', 'total_samples',
        'loop_start', 'loop_end',
        '_raw_params',   # params blob (editable fields patched on write)
        '_params_size',  # standard 224-byte or compact 220-byte TONE params
        '_raw_entry', '_source_values', '_field_offsets',
        '_bnsf_blob',    # raw BNSF bytes, or None if not yet extracted
    )

    def __init__(self):
        self.name          = ''
        self.flags         = 0
        self.type_id       = b'\xff\xff\x27\x84\x1f\x98\x0c\x00'
        self.pack_offset   = 0
        self.pack_size     = 0
        self.gain_db = 0.0
        self.pan_degrees = 0.0
        self.pitch_cents = 0.0
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
        self._raw_entry = None
        self._source_values = None
        self._field_offsets = {}

    # computed properties

    @property
    def duration_sec(self) -> float:
        if self.sample_rate > 0:
            return self.total_samples / self.sample_rate
        return 0.0

    @property
    def looping(self) -> bool:
        from core.xfbin_audio_tools import stream_loop
        return stream_loop(self._bnsf_blob or b'') is not None

    # serialise

    def _build_entry_bytes(self) -> bytes:
        """Serialise this ToneEntry to its on-disk binary form."""
        name_b = self.name.encode('ascii', errors='strict') if not self._source_values or self.name != self._source_values['name'] else None
        if name_b is not None and (len(name_b) > 253 or b'\0' in name_b):
            raise ValueError('Tone names require at most 253 ASCII bytes without NUL.')
        params_size = self._params_size
        if self._raw_entry and self.name == self._source_values['name']:
            buf = bytearray(self._raw_entry)
            ps = len(buf) - params_size
        else:
            name_len = len(name_b) + 1
            ps = _align_up(13 + name_len, 4)
            buf = bytearray(ps + params_size)
            _wu32le(buf, 0, self.flags)
            buf[4:12] = self.type_id[:8].ljust(8, b'\0')
            buf[12] = name_len
            buf[13:13 + name_len] = name_b + b'\0'
            buf[ps:] = bytes(self._raw_params[:params_size]).ljust(params_size, b'\0')
        _wu32le(buf, 0, self.flags)
        buf[4:12] = self.type_id[:8].ljust(8, b'\0')
        for name, off, writer in TONE_FIELDS:
            value = getattr(self, name)
            source = self._source_values.get(name) if self._source_values else None
            unchanged = value == source or (isinstance(value, float) and isinstance(source, float) and value != value and source != source)
            if not unchanged:
                real = self._field_offsets.get(name, _param_offset(params_size, off))
                if real + 4 > params_size:
                    raise ValueError('TONE field exceeds its native layout')
                struct.pack_into('<I' if writer is _write_param_u32 else '<f', buf, ps + real, value)

        return bytes(buf)


TONE_FIELDS = (
    ('gain_db', 0x10, _write_param_f32), ('pan_degrees', 0x14, _write_param_f32),
    ('pitch_cents', 0x18, _write_param_f32),
    ('pack_offset', _P_PACK_OFFSET, _write_param_u32), ('pack_size', _P_PACK_SIZE, _write_param_u32),
    ('volume', _P_VOLUME, _write_param_f32), ('pitch', _P_PITCH, _write_param_f32),
    ('pan_3d', _P_PAN_3D, _write_param_f32), ('send_level', _P_SEND_LEVEL, _write_param_f32),
    ('track_count', _P_TRACK_COUNT, _write_param_u32), ('pan_2d', _P_PAN_2D, _write_param_f32),
    ('sample_rate', _P_SAMPLE_RATE, _write_param_u32), ('channel_count', _P_CHANNEL_COUNT, _write_param_u32),
    ('total_samples', _P_TOTAL_SAMPLES, _write_param_u32), ('loop_start', _P_LOOP_START, _write_param_u32),
    ('loop_end', _P_LOOP_END, _write_param_u32),
)


# Bank

class Nus3Bank:
    """In-memory representation of one NUS3BANK inside an XFBIN."""
    __slots__ = (
        '_original_blob',
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
        self._original_blob = None
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
    if pos < 0 or pos + 8 > len(data):
        raise ValueError('Truncated NUS3 section header')
    tag4 = data[pos:pos + 4]
    if tag4 == b'BANK':
        tag      = data[pos:pos + 8]
        size     = _u32le(data, pos + 8)
        data_off = pos + 12
    else:
        tag      = tag4
        size     = _u32le(data, pos + 4)
        data_off = pos + 8
    if data_off + size > len(data):
        raise ValueError('NUS3 section exceeds bank bounds')
    return tag, data[data_off:data_off + size], data_off + size


def _parse_tone_section(tone_data: bytes) -> tuple:
    """Parse the raw TONE section data.

    Returns (audio_tones, all_records). all_records preserves non-audio TONE
    entries as raw bytes so saving an edited bank does not drop placeholders or
    cue-only records.
    """
    if len(tone_data) < 4:
        raise ValueError('Truncated TONE table')
    count = _u32le(tone_data, 0)
    table_end = 4 + 8 * count
    if table_end > len(tone_data):
        raise ValueError('TONE count exceeds section bounds')
    tones, records = [], []
    for i in range(count):
        off, size = struct.unpack_from('<II', tone_data, 4 + i * 8)
        if i == count - 1 and size == 0:
            size = len(tone_data) - off
        if off < table_end or off + size > len(tone_data):
            raise ValueError('TONE entry exceeds section bounds')
        raw = tone_data[off:off + size]
        tone = _parse_tone_entry(raw)
        records.append(tone if tone else bytes(raw))
        if tone:
            tones.append(tone)
    return tones, records


def _tone_field_offsets(flags_bytes, params):
    """Walk the optional words/arrays consumed by ASBR RVA B23D60.

    Array lengths, not total entry length, determine downstream field offsets.
    Only native two-flag-word stream records with the exposed fields are edited.
    """
    first, second = struct.unpack('<II', flags_bytes)
    if not first & 1 or not first & 0x80000000 or second & 0x80000000:
        raise ValueError('Unsupported TONE flag chain')
    cursor, starts, offsets = 0, {}, {}
    def word(off):
        if off < 0 or off + 4 > len(params):
            raise ValueError('TONE optional field exceeds entry')
        return _u32le(params, off)
    for group, flags in enumerate((first, second)):
        for bit in range(1 if group == 0 else 0, 31):
            if not flags >> bit & 1:
                continue
            starts[group, bit] = cursor
            if group == 0 and bit == 1:
                if word(cursor) != 0:
                    raise ValueError('Not a stream TONE')
                offsets.update(pack_offset=cursor + 8, pack_size=cursor + 12)
                cursor += 8 + word(cursor + 4)
            elif group == 0 and bit in (14, 15, 19):
                cursor += 4 + word(cursor) * (8 if bit == 15 else 4)
            elif group == 1 and bit in (8, 18, 19):
                cursor += 4 + word(cursor) * (8 if bit in (18, 19) else 4)
            else:
                cursor += 4
            if cursor > len(params):
                raise ValueError('Truncated optional TONE data')
    for bit, name in ((2, 'gain_db'), (3, 'pan_degrees'), (4, 'pitch_cents'),
                      (5, 'volume'), (6, 'pitch'), (7, 'pan_3d'), (9, 'send_level')):
        if (0, bit) in starts:
            offsets[name] = starts[0, bit]
    if (0, 15) in starts and word(starts[0, 15]) >= 2:
        offsets['track_count'] = starts[0, 15] + 12
        offsets['pan_2d'] = starts[0, 15] + 16
    for bit, name in ((0, 'sample_rate'), (1, 'channel_count'), (2, 'total_samples'), (15, 'loop_start')):
        if (1, bit) in starts:
            offsets[name] = starts[1, bit]
    if (1, 18) in starts and word(starts[1, 18]):
        offsets['loop_end'] = starts[1, 18] + 4
    return offsets


def _parse_tone_entry(raw: bytes) -> ToneEntry:
    """Parse a single variable-length tone entry buffer."""
    if len(raw) < 14:
        return None

    t          = ToneEntry()
    t.flags    = _u32le(raw, 0)
    t.type_id  = raw[4:12]

    name_len   = raw[12]
    if name_len == 0xff or 13 + name_len > len(raw):
        return None
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

    try:
        offsets = _tone_field_offsets(t.type_id, t._raw_params)
    except (ValueError, struct.error):
        return None  # Unknown optional layouts remain opaque, never guessed by size.
    required = {name for name, _, _ in TONE_FIELDS}
    if not required.issubset(offsets):
        return None
    t._field_offsets = offsets
    for name, _, writer in TONE_FIELDS:
        value = struct.unpack_from('<I' if writer is _write_param_u32 else '<f', t._raw_params, offsets[name])[0]
        setattr(t, name, value)
    if t.pack_size <= 0:
        return None
    t._raw_entry = bytes(raw)
    t._source_values = {name: getattr(t, name) for name, _, _ in TONE_FIELDS}
    t._source_values['name'] = t.name
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


def _parse_nus3bank(data: bytes, nus3_off: int) -> Nus3Bank:
    """Parse a NUS3BANK blob starting at *nus3_off* in *data*."""
    bank = Nus3Bank()
    bank._nus3_off = nus3_off
    bank._original_blob = bytes(data[nus3_off:nus3_off + 8 + _u32le(data, nus3_off + 4)])

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
        if tag in bank._sections:
            raise ValueError('Duplicate NUS3 section; unsupported layout retained on disk')
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

    if raw[:4] != NUCC_MAGIC:
        raise ValueError('Not an XFBIN container')
    banks = []
    search_from = 0
    while True:
        pos = raw.find(NUS3_MAGIC, search_from)
        if pos < 0:
            break
        # Verify it's a real NUS3BANK by checking the file size makes sense
        if pos + 8 <= len(raw):
            internal_size = _u32le(raw, pos + 4)
            if internal_size > 0 and pos + 8 + internal_size <= len(raw) and raw[pos + 8:pos + 16] == BANKTOC_TAG:
                bank = _parse_nus3bank(bytes(raw[pos:pos + 8 + internal_size]), 0)
                bank._nus3_off = pos
                if TONE_TAG in bank._sections and PACK_TAG in bank._sections:
                    bank._xfbin_desc_off = pos - 12 if pos >= 12 else -1
                    banks.append(bank)
        search_from = pos + 8 + internal_size if banks and banks[-1]._nus3_off == pos else pos + 4

    return raw, banks


# Building

def _build_tone_section(tones: list, orig_tone_data: bytes, records: list = None) -> bytes:
    """Rebuild the TONE section data with updated tone entries.

    The global header (count, data_block_off) and the offset table are
    recalculated; each entry is rebuilt from its ToneEntry fields.
    """
    records = tones if records is None else records
    count = len(records)
    if count == 0:
        return orig_tone_data if len(orig_tone_data) >= 4 and _u32le(orig_tone_data, 0) == 0 else struct.pack('<I', 0)

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

    original_count = _u32le(orig_tone_data, 0) if len(orig_tone_data) >= 4 else 0
    zero_last = bool(original_count and _u32le(orig_tone_data, 8 + (original_count - 1) * 8) == 0)
    cum = data_block_off
    for i, size in enumerate(sizes):
        _wu32le(buf, 4 + i * 8, cum)
        _wu32le(buf, 8 + i * 8, 0 if i == count - 1 and zero_last else size)
        cum += size

    pos = header_size
    for blob in entry_blobs:
        buf[pos:pos + len(blob)] = blob
        pos += len(blob)

    return bytes(buf)


def _build_pack_section(tones: list, orig_pack: bytes = None) -> tuple:
    """Rebuild the PACK section and update pack_offset/pack_size in each tone.

    Returns the new PACK data bytes.
    """
    result = bytearray(orig_pack or b'')
    appended = False
    for tone in tones:
        blob = tone._bnsf_blob
        if blob is None:
            raise ValueError('Tone audio is missing; refusing to drop its payload')
        if tone.pack_size == len(blob) and result[tone.pack_offset:tone.pack_offset + tone.pack_size] == blob:
            continue
        result.extend(b'\0' * (_align_up(len(result), PACK_ALIGN) - len(result)))
        tone.pack_offset, tone.pack_size = len(result), len(blob)
        result.extend(blob)
        appended = True
    if appended:
        result.extend(b'\0' * (_align_up(len(result), PACK_ALIGN) - len(result)))
    return bytes(result)


def _build_nus3bank(bank: Nus3Bank) -> bytes:
    """Rebuild an entire NUS3BANK blob from a Nus3Bank object."""
    # Rebuild PACK first (updates pack_offset / pack_size in tones)
    new_pack = _build_pack_section(bank.tones, bank._sections.get(PACK_TAG))

    # Rebuild TONE section
    orig_tone = bank._sections.get(TONE_TAG, b'')
    new_tone  = _build_tone_section(
        bank.tones, orig_tone, getattr(bank, '_tone_records', None))

    section_data = dict(bank._sections)
    section_data[TONE_TAG], section_data[PACK_TAG] = new_tone, new_pack
    order = [tag for tag in section_data if tag != BANKTOC_TAG]
    toc = struct.pack('<I', len(order)) + b''.join(tag + struct.pack('<I', len(section_data[tag])) for tag in order)
    section_data[BANKTOC_TAG] = toc
    body = bytearray()
    for tag in [BANKTOC_TAG] + order:
        content = section_data[tag]
        body += tag + struct.pack('<I', len(content)) + content
    return NUS3_MAGIC + struct.pack('<I', len(body)) + body


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
        if nus3_off < 16 or raw[nus3_off:nus3_off + 4] != NUS3_MAGIC:
            raise ValueError('Invalid embedded-bank boundary')

        # Original chunk size (everything from NUS3 magic to end of blob)
        orig_internal = _u32le(raw, nus3_off + 4)
        orig_chunk_sz = orig_internal + 8
        if _u32be(raw, nus3_off - 4) != orig_chunk_sz or _u32be(raw, nus3_off - 16) != orig_chunk_sz + 4:
            raise ValueError('Unexpected XFBIN audio descriptor; refusing to overwrite neighboring data')

        # Copy everything before this NUS3BANK (including its 12-byte descriptor)
        result.extend(raw[src_pos:nus3_off])
        src_pos = nus3_off + orig_chunk_sz

        # Build the new NUS3BANK blob
        new_blob = _build_nus3bank(bank)
        if bank._original_blob and new_blob == bank._original_blob:
            new_blob = bank._original_blob
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

    path = os.path.abspath(filepath)
    fd, temporary = tempfile.mkstemp(prefix='.xfa-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(result)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return bytes(result)


# Convenience

def get_tone_bnsf(tone: ToneEntry) -> bytes:
    """Return the raw BNSF bytes for this tone, or None."""
    return tone._bnsf_blob


def set_tone_bnsf(tone: ToneEntry, bnsf_bytes: bytes) -> None:
    """Replace this tone's audio data with new BNSF bytes.

    Also refreshes sample_rate / channel_count / total_samples from the
    new BNSF header so the TONE entry reflects the actual audio.
    """
    meta = parse_audio_meta(bnsf_bytes)
    if meta is None:
        raise ValueError("Unsupported or malformed embedded audio")
    tone._bnsf_blob = bnsf_bytes
    tone.pack_size = len(bnsf_bytes)
    if meta:
        tone.sample_rate   = meta['sample_rate']
        tone.channel_count = meta['channel_count']
        tone.total_samples = meta['total_samples']


def parse_audio_meta(blob):
    if blob[:4] == BNSF_MAGIC:
        return parse_bnsf_meta(blob)
    if len(blob) < 12 or blob[:4] != b'RIFF' or blob[8:12] != b'WAVE':
        return None
    end = _u32le(blob, 4) + 8
    if end != len(blob):
        return None
    fmt, data_size, pos = None, None, 12
    while pos < end:
        if pos + 8 > end:
            return None
        size = _u32le(blob, pos + 4)
        if pos + 8 + size > end:
            return None
        tag = blob[pos:pos + 4]
        if tag == b'fmt ' and size >= 16:
            fmt = struct.unpack_from('<HHIIHH', blob, pos + 8)
        elif tag == b'data':
            data_size = size
        pos += 8 + size + (size & 1)
    if fmt is None or not data_size:
        return None
    codec, channels, rate, byte_rate, align, bits = fmt
    if codec != 1 or channels not in (1, 2) or not rate or bits != 16 or align != channels * 2 or data_size % align:
        return None
    return dict(sample_rate=rate, channel_count=channels,
                total_samples=data_size // align, codec='PCM16')

"""
CriWare HCA audio decoder.

Decodes HCA audio streams (found in AWB/ACB containers)
to raw PCM or WAV format.

Supports:
- HCA version 2.x
- Cipher types: 0 (none), 1 (basic), 56 (keyed)
- Mono, stereo (with intensity stereo), and multi-channel
- HFR (High Frequency Reconstruction)
- RVA (Relative Volume Adjustment) reading and editing
"""

import struct
import math
import io
import wave

# Constants

_N = 128  # spectral coefficients per sub-frame
_SUBFRAMES = 8
_SAMPLES_PER_FRAME = _SUBFRAMES * _N  # 1024

# Channel types for stereo handling
_CH_DISCRETE = 0
_CH_STEREO_PRIMARY = 1
_CH_STEREO_SECONDARY = 2

# Pre-computed tables

# CRC-16
_CRC16 = []
for _i in range(256):
    _v = _i << 8
    for _ in range(8):
        _v = ((_v << 1) ^ 0x8005) if (_v & 0x8000) else (_v << 1)
        _v &= 0xFFFF
    _CRC16.append(_v)


def _crc16(data, length=None):
    if length is None:
        length = len(data)
    c = 0
    for i in range(length):
        c = (_CRC16[(c >> 8) ^ data[i]] ^ (c << 8)) & 0xFFFF
    return c


# Cipher tables

# Cipher type 1: basic LFSR scramble (no key required)
def _build_cipher1():
    table = bytearray(256)
    v = 0
    pos = 1
    for i in range(256):
        v = (v * 13 + 11) & 0xFF
        if v != 0 and v != 0xFF:
            table[pos] = v
            pos += 1
    table[0] = 0
    table[255] = 0xFF
    return bytes(table)


_CIPHER1 = _build_cipher1()


# Cipher type 56: key-based encryption (requires key1, key2)
# Key for JoJo's All Star Battle / ASBR: 19700307 (0x00000000012C9A53)
ASBR_KEY1 = 0x012C9A53
ASBR_KEY2 = 0x00000000


def _cipher56_create_row(seed):
    """LCG row generator for cipher 56 (matches CriHcaKey.CreateRandomRow)."""
    xor = (seed >> 4) & 0xF
    mul = ((seed & 1) << 3) | 5
    add = (seed & 0xE) | 1
    row = []
    for _ in range(16):
        xor = (xor * mul + add) & 0xF
        row.append(xor)
    return row


def _build_cipher56(key1=ASBR_KEY1, key2=ASBR_KEY2):
    """Build cipher type 56 decrypt table from two 32-bit key halves."""
    # Combine into 64-bit key and subtract 1
    key_code = ((key2 & 0xFFFFFFFF) << 32) | (key1 & 0xFFFFFFFF)
    key_code = (key_code - 1) & 0xFFFFFFFFFFFFFFFF
    # Extract bytes (little-endian)
    kc = []
    for i in range(8):
        kc.append(key_code & 0xFF)
        key_code >>= 8

    # 16-byte seed (column seeds) — matches reference CriHcaKey.CreateDecryptionTable
    seed = [0] * 16
    seed[0]  = kc[1]
    seed[1]  = (kc[6] ^ kc[1]) & 0xFF
    seed[2]  = (kc[2] ^ kc[3]) & 0xFF
    seed[3]  = kc[2]
    seed[4]  = (kc[1] ^ kc[2]) & 0xFF
    seed[5]  = (kc[3] ^ kc[4]) & 0xFF
    seed[6]  = kc[3]
    seed[7]  = (kc[2] ^ kc[3]) & 0xFF
    seed[8]  = (kc[4] ^ kc[5]) & 0xFF
    seed[9]  = kc[4]
    seed[10] = (kc[3] ^ kc[4]) & 0xFF
    seed[11] = (kc[5] ^ kc[6]) & 0xFF
    seed[12] = kc[5]
    seed[13] = (kc[4] ^ kc[5]) & 0xFF
    seed[14] = (kc[6] ^ kc[1]) & 0xFF
    seed[15] = kc[6]

    # Build 256-byte intermediate table using row/column LCG combination
    row = _cipher56_create_row(kc[0])
    t3 = bytearray(256)
    for r in range(16):
        col = _cipher56_create_row(seed[r])
        hi = row[r] << 4
        for c in range(16):
            t3[16 * r + c] = hi | col[c]

    # Shuffle table (step 17), skip 0x00 and 0xFF entries
    table = bytearray(256)
    x = 0
    out_pos = 1
    for _ in range(256):
        x = (x + 17) & 0xFF
        if t3[x] != 0 and t3[x] != 0xFF:
            table[out_pos] = t3[x]
            out_pos += 1
    table[0] = 0
    table[0xFF] = 0xFF
    return bytes(table)


_CIPHER56 = _build_cipher56()

# Scale factor → floating-point gain (DequantizerScalingTable)
# Reference: sqrt(128) * pow(pow(2, 53.0/128), x - 63)
# = sqrt(128) * pow(2, (53.0/128) * (x - 63))
_GAIN = [0.0] + [
    math.sqrt(128.0) * (2.0 ** ((53.0 / 128.0) * (i - 63))) for i in range(1, 64)
]

# Dequantization step size per resolution (QuantizerStepSize)
# Reference: 1 / (ResolutionMaxValues[x] + 0.5)  where max[x<8]=x, max[x>=8]=(1<<(x-4))-1
def _resolution_max(x):
    if x < 8:
        return x
    return (1 << (x - 4)) - 1

_DEQUANT = [0.0] + [1.0 / (_resolution_max(i) + 0.5) for i in range(1, 16)]

# Spectrum coding: max bits to peek per resolution (QuantizedSpectrumMaxBits)
_SPEC_MAX_BITS = [0, 2, 3, 3, 4, 4, 4, 4, 5, 6, 7, 8, 9, 10, 11, 12]

# VLC decode tables for resolution < 8 (from reference packed tables)
# QuantizedSpectrumBits[res][code] → actual bits consumed
_VLC_BITS = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  # res 0 (unused)
    [1, 1, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  # res 1
    [2, 2, 2, 2, 2, 2, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0],  # res 2
    [2, 2, 3, 3, 3, 3, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0],  # res 3
    [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4],  # res 4
    [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4],  # res 5
    [3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],  # res 6
    [3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],  # res 7
]

# QuantizedSpectrumValue[res][code] → decoded quantized value
_VLC_VALUE = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  # res 0
    [0, 0, 1, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],  # res 1
    [0, 0, 1, 1, -1, -1, 2, -2, 0, 0, 0, 0, 0, 0, 0, 0],  # res 2
    [0, 0, 1, -1, 2, -2, 3, -3, 0, 0, 0, 0, 0, 0, 0, 0],  # res 3
    [0, 0, 1, 1, -1, -1, 2, 2, -2, -2, 3, 3, -3, -3, 4, -4],  # res 4
    [0, 0, 1, 1, -1, -1, 2, 2, -2, -2, 3, -3, 4, -4, 5, -5],  # res 5
    [0, 0, 1, 1, -1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6],  # res 6
    [0, 0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7],  # res 7
]

# Scale-to-resolution curve (from reference packed tables)
_SCALE_TO_RES = [
    15, 14, 14, 14, 14, 14, 14, 13, 13, 13, 13, 13, 13, 12, 12, 12,
    12, 12, 12, 11, 11, 11, 11, 11, 11, 10, 10, 10, 10, 10, 10, 10,
     9,  9,  9,  9,  9,  9,  8,  8,  8,  8,  8,  8,  7,  6,  6,  5,
     4,  4,  4,  3,  3,  3,  2,  2,  2,  2,  1,
]

# ATH base curve (656 entries from reference packed tables)
_ATH_CURVE_FULL = [
    120, 95, 86, 81, 78, 76, 75, 73, 72, 72, 71, 70, 70, 69, 69, 69,
    68, 68, 68, 68, 67, 67, 67, 67, 67, 67, 66, 66, 66, 66, 66, 66,
    66, 66, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 64, 64, 64, 64,
    64, 64, 64, 64, 64, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63,
    63, 63, 63, 62, 62, 62, 62, 62, 62, 61, 61, 61, 61, 61, 61, 61,
    60, 60, 60, 60, 60, 60, 60, 60, 59, 59, 59, 59, 59, 59, 59, 59,
    59, 59, 59, 59, 59, 59, 59, 59, 59, 59, 59, 59, 59, 59, 59, 59,
    59, 59, 59, 59, 59, 59, 59, 59, 60, 60, 60, 60, 60, 60, 60, 60,
    61, 61, 61, 61, 61, 61, 61, 61, 62, 62, 62, 62, 62, 62, 62, 63,
    63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63,
    63, 63, 63, 63, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64, 64,
    64, 64, 64, 64, 64, 64, 64, 64, 64, 65, 65, 65, 65, 65, 65, 65,
    65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65, 65,
    65, 65, 65, 65, 65, 65, 65, 66, 66, 66, 66, 66, 66, 66, 66, 66,
    66, 66, 66, 66, 66, 66, 66, 66, 66, 66, 66, 66, 66, 67, 67, 67,
    67, 67, 67, 67, 67, 67, 67, 67, 67, 67, 67, 67, 67, 67, 68, 68,
    68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 68, 69, 69, 69, 69,
    69, 69, 69, 69, 69, 69, 69, 69, 70, 70, 70, 70, 70, 70, 70, 70,
    70, 70, 71, 71, 71, 71, 71, 71, 71, 71, 71, 71, 72, 72, 72, 72,
    72, 72, 72, 72, 73, 73, 73, 73, 73, 73, 73, 73, 74, 74, 74, 74,
    74, 74, 74, 74, 75, 75, 75, 75, 75, 75, 75, 76, 76, 76, 76, 76,
    76, 77, 77, 77, 77, 77, 77, 78, 78, 78, 78, 78, 78, 79, 79, 79,
    79, 79, 79, 80, 80, 80, 80, 80, 81, 81, 81, 81, 81, 82, 82, 82,
    82, 82, 83, 83, 83, 83, 84, 84, 84, 84, 84, 85, 85, 85, 85, 86,
    86, 86, 86, 87, 87, 87, 87, 87, 88, 88, 88, 89, 89, 89, 89, 90,
    90, 90, 90, 91, 91, 91, 91, 92, 92, 92, 93, 93, 93, 93, 94, 94,
    94, 95, 95, 95, 96, 96, 96, 97, 97, 97, 97, 98, 98, 98, 99, 99,
    99, 100, 100, 100, 101, 101, 102, 102, 102, 103, 103, 103, 104, 104, 104, 105,
    105, 106, 106, 106, 107, 107, 107, 108, 108, 109, 109, 109, 110, 110, 111, 111,
    112, 112, 112, 113, 113, 114, 114, 115, 115, 115, 116, 116, 117, 117, 118, 118,
    119, 119, 120, 120, 120, 121, 121, 122, 122, 123, 123, 124, 124, 125, 125, 126,
    126, 127, 127, 128, 128, 129, 129, 130, 131, 131, 132, 132, 133, 133, 134, 134,
    135, 136, 136, 137, 137, 138, 138, 139, 140, 140, 141, 141, 142, 143, 143, 144,
    144, 145, 146, 146, 147, 148, 148, 149, 149, 150, 151, 151, 152, 153, 153, 154,
    155, 155, 156, 157, 157, 158, 159, 160, 160, 161, 162, 162, 163, 164, 165, 165,
    166, 167, 167, 168, 169, 170, 170, 171, 172, 173, 174, 174, 175, 176, 177, 177,
    178, 179, 180, 181, 182, 182, 183, 184, 185, 186, 186, 187, 188, 189, 190, 191,
    192, 193, 193, 194, 195, 196, 197, 198, 199, 200, 201, 201, 202, 203, 204, 205,
    206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221,
    222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 234, 235, 237, 238,
    239, 240, 241, 242, 243, 244, 245, 247, 248, 249, 250, 251, 252, 253,
]

# IMDCT window (128 entries, from reference packed tables)
# Close to a KBD window with alpha ~3.82
_MDCT_WINDOW = [
    6.905337795615196e-04, 1.976234838366508e-03, 3.673864528536797e-03, 5.724240094423294e-03,
    8.096703328192234e-03, 1.077318191528320e-02, 1.374251767992973e-02, 1.699785701930523e-02,
    2.053526416420937e-02, 2.435290254652500e-02, 2.845051884651184e-02, 3.282909467816353e-02,
    3.749062120914459e-02, 4.243789613246918e-02, 4.767442867159843e-02, 5.320430174469948e-02,
    5.903211236000061e-02, 6.516288220882416e-02, 7.160200923681259e-02, 7.835522294044495e-02,
    8.542849123477936e-02, 9.282802045345306e-02, 1.005601510405540e-01, 1.086313501000404e-01,
    1.170481219887733e-01, 1.258169859647751e-01, 1.349443495273590e-01, 1.444365084171295e-01,
    1.542995125055313e-01, 1.645391285419464e-01, 1.751607209444046e-01, 1.861691623926163e-01,
    1.975687295198441e-01, 2.093629688024521e-01, 2.215546220541000e-01, 2.341454178094864e-01,
    2.471359968185425e-01, 2.605257630348206e-01, 2.743127048015594e-01, 2.884931862354279e-01,
    3.030619323253632e-01, 3.180117309093475e-01, 3.333333432674408e-01, 3.490152955055237e-01,
    3.650438189506531e-01, 3.814027011394501e-01, 3.980731070041656e-01, 4.150335192680359e-01,
    4.322597980499268e-01, 4.497250318527222e-01, 4.673995673656464e-01, 4.852511584758759e-01,
    5.032449364662170e-01, 5.213438272476196e-01, 5.395085215568542e-01, 5.576977729797363e-01,
    5.758689045906067e-01, 5.939780473709106e-01, 6.119805574417114e-01, 6.298314332962036e-01,
    6.474860310554504e-01, 6.649002432823181e-01, 6.820311546325684e-01, 6.988375782966614e-01,
    7.152804136276245e-01, 7.313231229782104e-01, 7.469321489334106e-01, 7.620773315429688e-01,
    7.767318487167358e-01, 7.908728122711182e-01, 8.044812679290771e-01, 8.175420165061951e-01,
    8.300440907478333e-01, 8.419801592826843e-01, 8.533467054367065e-01, 8.641437888145447e-01,
    8.743748068809509e-01, 8.840461969375610e-01, 8.931670784950256e-01, 9.017491340637207e-01,
    9.098061323165894e-01, 9.173536896705627e-01, 9.244089722633362e-01, 9.309903383255005e-01,
    9.371170401573181e-01, 9.428090453147888e-01, 9.480867981910706e-01, 9.529708623886108e-01,
    9.574819207191467e-01, 9.616405367851257e-01, 9.654669165611267e-01, 9.689807891845703e-01,
    9.722015857696533e-01, 9.751479625701904e-01, 9.778379797935486e-01, 9.802890419960022e-01,
    9.825177192687988e-01, 9.845398664474487e-01, 9.863705635070801e-01, 9.880241155624390e-01,
    9.895140528678894e-01, 9.908531904220581e-01, 9.920534491539001e-01, 9.931262731552124e-01,
    9.940820932388306e-01, 9.949309825897217e-01, 9.956821799278259e-01, 9.963443279266357e-01,
    9.969255328178406e-01, 9.974333047866821e-01, 9.978746175765991e-01, 9.982560873031616e-01,
    9.985836744308472e-01, 9.988629221916199e-01, 9.990991353988647e-01, 9.992969632148743e-01,
    9.994609951972961e-01, 9.995952248573303e-01, 9.997034072875977e-01, 9.997891187667847e-01,
    9.998555183410645e-01, 9.999055862426758e-01, 9.999419450759888e-01, 9.999672174453735e-01,
    9.999836087226868e-01, 9.999932646751404e-01, 9.999980330467224e-01, 9.999997615814209e-01,
]

# Intensity ratio table for stereo (15 entries)
_INTENSITY_RATIO = [(28 - i * 2) / 14.0 for i in range(15)]

# Scale conversion table for HFR (128 entries)
_SCALE_CONV = [0.0, 0.0] + [
    2.0 ** ((53.0 / 128.0) * (i - 64)) for i in range(2, 127)
] + [0.0]

# Pre-computed DCT-IV cosine matrix for IMDCT
_DCT4_MATRIX = None   # Python list-of-lists fallback
_DCT4_NP = None       # numpy matrix (if available)
_USE_NUMPY = False
_MDCT_SCALE = math.sqrt(2.0 / _N)

try:
    import numpy as _np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


def _ensure_dct4():
    """Pre-compute the full DCT-IV cosine matrix (128x128) with scale."""
    global _DCT4_MATRIX, _DCT4_NP, _USE_NUMPY
    if _DCT4_MATRIX is not None or _DCT4_NP is not None:
        return
    N = _N
    scale = _MDCT_SCALE

    if _HAS_NUMPY:
        k = _np.arange(N).reshape(N, 1)
        n = _np.arange(N).reshape(1, N)
        _DCT4_NP = (_np.cos(math.pi / N * (k + 0.5) * (n + 0.5)) * scale).astype(_np.float64)
        _USE_NUMPY = True
    else:
        _DCT4_MATRIX = []
        for k in range(N):
            row = [0.0] * N
            for n in range(N):
                row[n] = math.cos(math.pi / N * (k + 0.5) * (n + 0.5)) * scale
            _DCT4_MATRIX.append(row)


# Bit reader

class _BitReader:
    __slots__ = ('_d', '_p', '_end')

    def __init__(self, data, offset=0, size=None):
        self._d = data
        self._p = offset * 8
        self._end = (offset + (size if size is not None else len(data) - offset)) * 8

    @property
    def position(self):
        return self._p

    @position.setter
    def position(self, v):
        self._p = v

    @property
    def remaining(self):
        return self._end - self._p

    def read(self, bits):
        v = 0
        d, p = self._d, self._p
        for _ in range(bits):
            if p < self._end:
                v = (v << 1) | ((d[p >> 3] >> (7 - (p & 7))) & 1)
                p += 1
            else:
                v <<= 1
        self._p = p
        return v

    def peek(self, bits):
        """Read bits without advancing position."""
        old = self._p
        v = self.read(bits)
        self._p = old
        return v

    def read_offset_binary(self, bits):
        """Read offset-binary encoded value with positive bias (for delta decoding)."""
        offset = (1 << (bits - 1)) - 1  # OffsetBias.Positive → -1
        val = self.peek(bits) - offset
        self._p += bits
        return val


# Header parsing

def _unmask4(data, off):
    """Read 4-byte chunk signature, clearing bit 7 on each byte."""
    return bytes(b & 0x7F for b in data[off:off + 4])


def parse_hca_info(data):
    """Parse HCA header → metadata dict."""
    if len(data) < 8:
        raise ValueError("Data too short for HCA")
    sig = _unmask4(data, 0)
    if sig[:3] != b'HCA':
        raise ValueError(f"Not HCA: {sig!r}")

    version = struct.unpack_from('>H', data, 4)[0]
    data_offset = struct.unpack_from('>H', data, 6)[0]

    info = dict(
        version_major=version >> 8, version_minor=version & 0xFF,
        data_offset=data_offset,
        channels=1, sample_rate=44100, frame_count=0,
        mute_header=0, mute_footer=0,
        frame_size=0, min_resolution=0, max_resolution=15,
        track_count=1, channel_config=0,
        total_band_count=128, base_band_count=128,
        stereo_band_count=0, bands_per_hfr_group=0,
        ath_type=0,
        loop_enabled=False, loop_start=0, loop_end=0, loop_count=0,
        cipher_type=0,
        rva_volume=1.0, rva_offset=-1,
    )

    pos = 8
    while pos < data_offset - 2:
        sig = _unmask4(data, pos)
        if sig == b'fmt\x00':
            info['channels'] = data[pos + 4]
            info['sample_rate'] = (data[pos + 5] << 16) | (data[pos + 6] << 8) | data[pos + 7]
            info['frame_count'] = struct.unpack_from('>I', data, pos + 8)[0]
            info['mute_header'] = struct.unpack_from('>H', data, pos + 12)[0]
            info['mute_footer'] = struct.unpack_from('>H', data, pos + 14)[0]
            pos += 16
        elif sig == b'comp':
            info['frame_size'] = struct.unpack_from('>H', data, pos + 4)[0]
            info['min_resolution'] = data[pos + 6]
            info['max_resolution'] = data[pos + 7]
            info['track_count'] = data[pos + 8]
            info['channel_config'] = data[pos + 9]
            info['total_band_count'] = data[pos + 10]
            info['base_band_count'] = data[pos + 11]
            info['stereo_band_count'] = data[pos + 12]
            info['bands_per_hfr_group'] = data[pos + 13]
            pos += 16
        elif sig == b'dec\x00':
            info['frame_size'] = struct.unpack_from('>H', data, pos + 4)[0]
            info['min_resolution'] = data[pos + 6]
            info['max_resolution'] = data[pos + 7]
            info['total_band_count'] = data[pos + 8] + 1
            info['base_band_count'] = data[pos + 9] + 1
            info['track_count'] = data[pos + 10]
            info['channel_config'] = data[pos + 11]
            if info['stereo_band_count'] == 0:
                info['stereo_band_count'] = info['total_band_count'] - info['base_band_count']
            pos += 12
        elif sig == b'vbr\x00':
            pos += 8
        elif sig == b'ath\x00':
            info['ath_type'] = struct.unpack_from('>H', data, pos + 4)[0]
            pos += 6
        elif sig == b'loop':
            info['loop_enabled'] = True
            info['loop_start'] = struct.unpack_from('>I', data, pos + 4)[0]
            info['loop_end'] = struct.unpack_from('>I', data, pos + 8)[0]
            info['loop_count'] = struct.unpack_from('>H', data, pos + 12)[0]
            pos += 16
        elif sig == b'ciph':
            info['cipher_type'] = struct.unpack_from('>H', data, pos + 4)[0]
            pos += 6
        elif sig == b'rva\x00':
            info['rva_volume'] = struct.unpack_from('>f', data, pos + 4)[0]
            info['rva_offset'] = pos + 4
            pos += 8
        elif sig == b'pad\x00':
            break
        else:
            pos += 4  # skip unknown

    # Calculate HFR values
    bphg = info['bands_per_hfr_group']
    if bphg > 0:
        hfr_band = info['total_band_count'] - info['base_band_count'] - info['stereo_band_count']
        info['hfr_band_count'] = hfr_band
        info['hfr_group_count'] = (hfr_band + bphg - 1) // bphg if hfr_band > 0 else 0
    else:
        info['hfr_band_count'] = 0
        info['hfr_group_count'] = 0

    sr = info['sample_rate']
    fc = info['frame_count']
    total = fc * _SAMPLES_PER_FRAME
    actual = max(0, total - info['mute_header'] - info['mute_footer'])
    info['total_samples'] = total
    info['actual_samples'] = actual
    info['duration'] = actual / sr if sr > 0 else 0.0
    if info['frame_size'] > 0 and fc > 0 and total > 0:
        info['bit_rate'] = int(info['frame_size'] * fc * 8 * sr / total)
    else:
        info['bit_rate'] = 0
    return info


# RVA volume editing

def set_hca_volume(data, volume):
    """Set (or insert) RVA volume in HCA data. Returns modified bytes."""
    buf = bytearray(data)
    info = parse_hca_info(data)

    if info['rva_offset'] >= 0:
        struct.pack_into('>f', buf, info['rva_offset'], volume)
    else:
        # Insert rva chunk in padding area
        do = info['data_offset']
        pos = 8
        pad_pos = -1
        while pos < do - 2:
            sig = _unmask4(data, pos)
            if sig == b'pad\x00':
                pad_pos = pos
                break
            sizes = {b'fmt\x00': 16, b'comp': 16, b'dec\x00': 12,
                     b'vbr\x00': 8, b'ath\x00': 6, b'loop': 16,
                     b'ciph': 6, b'rva\x00': 8}
            pos += sizes.get(sig, 4)

        if pad_pos < 0 or (do - 2 - pad_pos) < 12:
            raise ValueError("No space for RVA chunk in header")

        # Write masked "rva\0" + float32 + masked "pad\0"
        buf[pad_pos:pad_pos + 4] = bytes([0x72|0x80, 0x76|0x80, 0x61|0x80, 0x00])
        struct.pack_into('>f', buf, pad_pos + 4, volume)
        buf[pad_pos + 8:pad_pos + 12] = bytes([0x70|0x80, 0x61|0x80, 0x64|0x80, 0x00])

    # Recalculate header CRC
    crc_pos = info['data_offset'] - 2
    crc = _crc16(buf, crc_pos)
    struct.pack_into('>H', buf, crc_pos, crc)
    return bytes(buf)


# ATH curve scaling

def _scale_ath_curve(sample_rate):
    """Scale ATH curve to the given sample rate (reference: 41856 Hz)."""
    ath = [0] * _N
    acc = 0
    curve_len = len(_ATH_CURVE_FULL)
    i = 0
    while i < _N:
        acc += sample_rate
        idx = acc >> 13
        if idx >= curve_len:
            break
        ath[i] = _ATH_CURVE_FULL[idx]
        i += 1
    while i < _N:
        ath[i] = 0xFF
        i += 1
    return ath


# Channel type determination

def _get_channel_types(info):
    """Determine channel types (discrete, stereo primary/secondary)."""
    ch_count = info['channels']
    track_count = info['track_count']
    stereo_band = info['stereo_band_count']

    if stereo_band == 0 or ch_count == 1:
        return [_CH_DISCRETE] * ch_count

    channels_per_track = ch_count // track_count if track_count > 0 else ch_count
    ch_config = info['channel_config']

    type_map = {
        2: [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY],
        3: [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE],
    }

    if channels_per_track in type_map:
        return type_map[channels_per_track]

    if channels_per_track == 4:
        if ch_config != 0:
            return [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE, _CH_DISCRETE]
        else:
            return [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY]

    if channels_per_track == 5:
        if ch_config > 2:
            return [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE, _CH_DISCRETE, _CH_DISCRETE]
        else:
            return [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE, _CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY]

    if channels_per_track == 6:
        return [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE, _CH_DISCRETE, _CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY]

    if channels_per_track == 7:
        return [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE, _CH_DISCRETE, _CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE]

    if channels_per_track == 8:
        return [_CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_DISCRETE, _CH_DISCRETE, _CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY, _CH_STEREO_PRIMARY, _CH_STEREO_SECONDARY]

    return [_CH_DISCRETE] * ch_count


# Frame decoder

class _ChState:
    """Per-channel decoding state."""
    __slots__ = ('ch_type', 'coded_count', 'scales', 'resolution', 'gain',
                 'quantized', 'spectra', 'intensity', 'hfr_scales',
                 'imdct_prev', 'pcm_float', '_sf_delta_bits', '_hfr_group_count')

    def __init__(self, ch_type, base_band, stereo_band):
        self.ch_type = ch_type
        # StereoSecondary channels only code base_band scale factors
        self.coded_count = base_band if ch_type == _CH_STEREO_SECONDARY else (base_band + stereo_band)
        self.scales = [0] * _N
        self.resolution = [0] * _N
        self.gain = [0.0] * _N
        self.quantized = [[0] * _N for _ in range(_SUBFRAMES)]
        self.spectra = [[0.0] * _N for _ in range(_SUBFRAMES)]
        self.intensity = [0] * _SUBFRAMES
        self.hfr_scales = [0] * 8
        self.imdct_prev = [0.0] * _N
        self.pcm_float = [[0.0] * _N for _ in range(_SUBFRAMES)]
        self._sf_delta_bits = 0
        self._hfr_group_count = 0


def _calculate_resolution(scale_factor, noise_level):
    """Calculate resolution from scale factor and noise level (reference formula)."""
    if scale_factor == 0:
        return 0
    curve_pos = noise_level - (5 * scale_factor) // 2 + 2
    curve_pos = max(0, min(58, curve_pos))
    return _SCALE_TO_RES[curve_pos]


def _read_scale_factors(br, ch):
    """Read delta-encoded scale factors."""
    delta_bits = br.read(3)
    ch._sf_delta_bits = delta_bits

    if delta_bits == 0:
        for i in range(_N):
            ch.scales[i] = 0
        return True

    if delta_bits >= 6:
        for i in range(ch.coded_count):
            ch.scales[i] = br.read(6)
        for i in range(ch.coded_count, _N):
            ch.scales[i] = 0
        return True

    # Delta decode
    ch.scales[0] = br.read(6)
    max_delta = 1 << (delta_bits - 1)
    max_value = 63  # (1 << 6) - 1

    for i in range(1, ch.coded_count):
        delta = br.read_offset_binary(delta_bits)
        if delta < max_delta:
            value = ch.scales[i - 1] + delta
            if value < 0 or value > max_value:
                return False
            ch.scales[i] = value
        else:
            ch.scales[i] = br.read(6)

    for i in range(ch.coded_count, _N):
        ch.scales[i] = 0
    return True


def _unpack_frame_header(br, channels, ath_curve):
    """Unpack frame header: sync, noise level, evaluation boundary, scale factors, resolution."""
    sync = br.read(16)
    if sync != 0xFFFF:
        return False

    anl = br.read(9)  # acceptable noise level
    eb = br.read(7)   # evaluation boundary

    for ch in channels:
        if not _read_scale_factors(br, ch):
            return False

        # Calculate resolution per band
        for i in range(eb):
            ch.resolution[i] = _calculate_resolution(
                ch.scales[i], ath_curve[i] + anl - 1)
        for i in range(eb, ch.coded_count):
            ch.resolution[i] = _calculate_resolution(
                ch.scales[i], ath_curve[i] + anl)
        for i in range(ch.coded_count, _N):
            ch.resolution[i] = 0

        # Read intensity (for stereo secondary) or HFR scales (for primary/discrete)
        if ch.ch_type == _CH_STEREO_SECONDARY:
            for sf in range(_SUBFRAMES):
                ch.intensity[sf] = br.read(4)
        elif channels[0]._hfr_group_count > 0:
            for g in range(channels[0]._hfr_group_count):
                ch.hfr_scales[g] = br.read(6)

    return True


def _read_spectral_coefficients(br, channels):
    """Read quantized spectral coefficients for all subframes.

    Uses the exact VLC lookup tables from the reference for res < 8,
    and sign-in-LSB encoding for res >= 8.
    """
    for sf in range(_SUBFRAMES):
        for ch in channels:
            for s in range(ch.coded_count):
                res = ch.resolution[s]
                if res == 0:
                    ch.quantized[sf][s] = 0
                    continue

                bits = _SPEC_MAX_BITS[res]
                code = br.peek(bits)

                if res < 8:
                    # Use exact VLC lookup tables from reference
                    actual_bits = _VLC_BITS[res][code]
                    ch.quantized[sf][s] = _VLC_VALUE[res][code]
                    br.position += actual_bits
                else:
                    # Sign-in-LSB encoding: low bit is sign
                    qc = (code >> 1) * (1 - (code & 1) * 2)
                    if qc == 0:
                        bits -= 1
                    ch.quantized[sf][s] = qc
                    br.position += bits

            # Clear remaining bands
            for s in range(ch.coded_count, _N):
                ch.quantized[sf][s] = 0
                ch.spectra[sf][s] = 0.0


def _dequantize_frame(channels):
    """Calculate gain and dequantize spectral coefficients."""
    for ch in channels:
        # Calculate gain per band
        for i in range(ch.coded_count):
            sf = ch.scales[i]
            res = ch.resolution[i]
            if sf > 0 and res > 0:
                ch.gain[i] = _GAIN[sf] * _DEQUANT[res]
            else:
                ch.gain[i] = 0.0

        # Dequantize spectra
        for sf in range(_SUBFRAMES):
            for s in range(ch.coded_count):
                ch.spectra[sf][s] = ch.quantized[sf][s] * ch.gain[s]


def _reconstruct_hfr(channels, info):
    """Reconstruct high frequencies from lower bands."""
    hfr_group_count = info['hfr_group_count']
    if hfr_group_count == 0:
        return

    total_band = min(info['total_band_count'], 127)
    hfr_start = info['base_band_count'] + info['stereo_band_count']
    hfr_band_count = min(info['hfr_band_count'], total_band - info['hfr_band_count'])
    bands_per_group = info['bands_per_hfr_group']

    for ch in channels:
        if ch.ch_type == _CH_STEREO_SECONDARY:
            continue

        band = 0
        for group in range(hfr_group_count):
            for i in range(bands_per_group):
                if band >= hfr_band_count:
                    break
                high_band = hfr_start + band
                low_band = hfr_start - band - 1
                idx = ch.hfr_scales[group] - ch.scales[low_band] + 64
                idx = max(0, min(127, idx))
                scale = _SCALE_CONV[idx]
                for sf in range(_SUBFRAMES):
                    ch.spectra[sf][high_band] = scale * ch.spectra[sf][low_band]
                band += 1


def _apply_intensity_stereo(channels, info):
    """Apply intensity stereo processing to reconstruct stereo difference."""
    if info['stereo_band_count'] <= 0:
        return

    base = info['base_band_count']
    total = info['total_band_count']

    for c in range(len(channels)):
        if channels[c].ch_type != _CH_STEREO_PRIMARY:
            continue
        if c + 1 >= len(channels):
            continue

        primary = channels[c]
        secondary = channels[c + 1]

        for sf in range(_SUBFRAMES):
            ratio_l = _INTENSITY_RATIO[secondary.intensity[sf]]
            ratio_r = ratio_l - 2.0
            for b in range(base, total):
                secondary.spectra[sf][b] = primary.spectra[sf][b] * ratio_r
                primary.spectra[sf][b] = primary.spectra[sf][b] * ratio_l


def _run_imdct(channels):
    """Run DCT-IV based IMDCT with windowing and overlap-add.

    Uses numpy matrix multiply if available, otherwise pre-computed cosine matrix.
    """
    N = _N
    half = N >> 1  # 64
    win = _MDCT_WINDOW

    for sf in range(_SUBFRAMES):
        for ch in channels:
            spec = ch.spectra[sf]

            if _USE_NUMPY:
                spec_arr = _np.array(spec, dtype=_np.float64)
                dct_arr = _DCT4_NP @ spec_arr
                dct_out = dct_arr.tolist()
            else:
                mat = _DCT4_MATRIX
                dct_out = [0.0] * N
                for k in range(N):
                    row = mat[k]
                    s = 0.0
                    for n in range(N):
                        s += row[n] * spec[n]
                    dct_out[k] = s

            # Windowed overlap-add (matches reference Mdct.RunImdct)
            prev = ch.imdct_prev
            out = ch.pcm_float[sf]
            new_prev = [0.0] * N

            for i in range(half):
                out[i] = win[i] * dct_out[i + half] + prev[i]
                out[i + half] = win[i + half] * (-dct_out[N - 1 - i]) - prev[i + half]
                new_prev[i] = win[N - 1 - i] * (-dct_out[half - i - 1])
                new_prev[i + half] = win[half - i - 1] * dct_out[i]

            ch.imdct_prev = new_prev


# Public decode API

def decode_hca_to_wav(data, volume_override=None):
    """Decode HCA bytes → WAV bytes.

    Args:
        data: raw HCA audio bytes
        volume_override: float, overrides the embedded RVA volume

    Returns:
        Complete WAV file as bytes
    """
    _ensure_dct4()
    info = parse_hca_info(data)

    channels   = info['channels']
    sr         = info['sample_rate']
    fc         = info['frame_count']
    frame_size = info['frame_size']
    data_off   = info['data_offset']
    cipher     = info['cipher_type']
    volume     = volume_override if volume_override is not None else info['rva_volume']

    if cipher == 56:
        ctab = _CIPHER56
    elif cipher == 1:
        ctab = _CIPHER1
    elif cipher == 0:
        ctab = None
    else:
        raise ValueError(f"Unsupported cipher: {cipher}")

    # ATH curve
    use_ath = info['ath_type'] == 1
    ath_curve = _scale_ath_curve(sr) if use_ath else [0] * _N

    # Channel states with proper types
    ch_types = _get_channel_types(info)
    base_band = info['base_band_count']
    stereo_band = info['stereo_band_count']
    states = [_ChState(ch_types[i], base_band, stereo_band) for i in range(channels)]

    # Store HFR group count on first channel for reference during unpacking
    hfr_gc = info['hfr_group_count']
    for st in states:
        st._hfr_group_count = hfr_gc

    all_pcm = [[0.0] * (fc * _SAMPLES_PER_FRAME) for _ in range(channels)]
    inserted = info['mute_header']

    for fi in range(fc):
        off = data_off + fi * frame_size
        end = off + frame_size
        if end > len(data):
            break

        frame = bytearray(data[off:end])

        # Decrypt (only frame_size - 2 bytes, skip CRC)
        if ctab:
            for j in range(frame_size - 2):
                frame[j] = ctab[frame[j]]

        br = _BitReader(frame, 0, frame_size - 2)

        # Unpack frame header (scale factors, resolution, intensity/HFR)
        if not _unpack_frame_header(br, states, ath_curve):
            # Invalid frame: write silence
            continue

        # Read spectral coefficients
        _read_spectral_coefficients(br, states)

        # Dequantize
        _dequantize_frame(states)

        # Restore missing bands
        _reconstruct_hfr(states, info)
        _apply_intensity_stereo(states, info)

        # IMDCT
        _run_imdct(states)

        # PCM float → output buffer with proper sample positioning
        current_sample = fi * _SAMPLES_PER_FRAME - inserted
        for sf in range(_SUBFRAMES):
            src_start = 0
            dst_start = current_sample + sf * _N
            length = _N

            if dst_start < 0:
                src_start = -dst_start
                length -= src_start
                dst_start = 0
            if dst_start + length > info['actual_samples']:
                length = info['actual_samples'] - dst_start
            if length <= 0:
                continue

            for c in range(channels):
                for s in range(length):
                    all_pcm[c][dst_start + s] = states[c].pcm_float[sf][src_start + s]

    # Apply volume
    actual = info['actual_samples']
    if volume != 1.0:
        for ch in range(channels):
            arr = all_pcm[ch]
            for i in range(actual):
                arr[i] *= volume

    # Convert to 16-bit PCM WAV
    n_samples = actual
    pcm = bytearray(n_samples * channels * 2)
    for i in range(n_samples):
        for ch in range(channels):
            v = all_pcm[ch][i]
            # Reference: (int)(sample * (short.MaxValue + 1))
            sample = int(v * 32768.0)
            sample = max(-32768, min(32767, sample))
            struct.pack_into('<h', pcm, (i * channels + ch) * 2, sample)

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(pcm))
    return buf.getvalue()

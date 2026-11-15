"""ASB.acf DSP layouts from the embedded CRI decoder (ASBR.exe A88C78).

Only exact verified payload sizes are decoded. Unknown formats stay opaque.
Names combine native parameter slots with CRI's effect documentation.
"""
from dataclasses import dataclass
import math
import struct


# Native name-to-ID function A88430, not a guessed contemporary SDK enum.
FX_NAMES = {1: 'Reverb', 2: 'Echo', 3: 'Biquad', 4: 'Bandpass', 5: 'Compressor',
            6: 'Delay', 7: 'PitchShifter', 8: '3BandsEQ', 9: 'Chorus', 10: 'Flanger',
            11: 'Distortion', 12: 'AmplitudeAnalyzer', 13: 'Surrounder',
            14: 'I3DL2Reverb', 15: 'MultiTapDelay', 16: 'Limiter', 17: 'Matrix',
            18: '32BandsEQ', 19: 'BusBufferPool', 20: 'MidSide'}


@dataclass(frozen=True)
class DspField:
    name: str
    offset: int
    fmt: str = 'f'
    storage: int = 5
    blob_name: str = 'Parameters'

    def read(self, data):
        return struct.unpack_from('>' + self.fmt, data, self.offset)[0]

    def write(self, data, text):
        try:
            value = float(text) if self.fmt == 'f' else int(text, 16 if text.lower().startswith(('0x', '-0x', '+0x')) else 10)
            if self.fmt == 'f' and not math.isfinite(value):
                raise ValueError
            encoded = struct.pack('>' + self.fmt, value)
        except (ValueError, OverflowError, struct.error) as exc:
            raise ValueError('invalid_float' if self.fmt == 'f' else 'invalid_integer') from exc
        result = bytearray(data)
        result[self.offset:self.offset + len(encoded)] = encoded
        return bytes(result)


_LAYOUTS = {
    # Legacy name 'flags' retained for callers. Native A94768 copies this byte
    # into bus +2368; A94B74 processes an effect only when its state is zero.
    (1, 30): (
        DspField('cutoff_high_hz', 0), DspField('cutoff_low_hz', 4),
        DspField('max_pre_delay_ms', 8), DspField('max_room_size_m', 12),
        DspField('pre_delay_ms', 16), DspField('reverb_time_ms', 20),
        DspField('room_size_m', 24), DspField('reverb_mode', 28, 'B'), DspField('flags', 29, 'B'),
    ),
    (3, 14): (
        DspField('biquad_type', 0, 'B'), DspField('frequency_normalized', 1),
        DspField('gain', 5), DspField('quality', 9), DspField('flags', 13, 'B'),
    ),
    (4, 9): (
        DspField('cutoff_high_normalized', 0), DspField('cutoff_low_normalized', 4), DspField('flags', 8, 'B'),
    ),
    (13, 14): (
        DspField('surround_delay_ms', 0), DspField('surround_gain_db', 4),
        DspField('surround_mode', 8, 'B'), DspField('surround_max_delay_ms', 9), DspField('flags', 13, 'B'),
    ),
}


def dsp_fields(fx_type, data):
    return _LAYOUTS.get((int(fx_type), len(data)), ())

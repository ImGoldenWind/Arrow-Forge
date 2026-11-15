"""Qt-independent PCM analysis and bounded preview storage.

Envelopes preserve extrema of every channel and include the final sample.
They represent decoded audio, not Atom cue/bus processing.
"""
from collections import OrderedDict
from collections.abc import MutableMapping
from dataclasses import dataclass
import io
import math
import wave

import numpy as np


def import_pyaudio():
    """The declared Arrow Forge audio backend, shared by stream editors."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        import pyaudio
    return pyaudio


def scale_wav(data, gain):
    """Apply an RVA audition multiplier to PCM16 with saturation."""
    if not math.isfinite(gain) or gain < 0:
        raise ValueError('Invalid RVA multiplier')
    if gain == 1:
        return data
    with wave.open(io.BytesIO(data), 'rb') as wav:
        params = wav.getparams()
        if wav.getsampwidth() != 2:
            raise ValueError('RVA audition requires PCM16')
        samples = np.frombuffer(wav.readframes(wav.getnframes()), '<i2')
    scaled = np.clip(np.trunc(samples.astype(np.float64) * gain), -32768, 32767).astype('<i2')
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams(params)
        wav.writeframes(scaled.tobytes())
    return output.getvalue()


@dataclass(frozen=True)
class AudioEnvelope:
    low: np.ndarray
    high: np.ndarray
    sample_rate: int
    frames: int
    peak: float
    clipped: int
    bin_size: int

    @property
    def duration(self):
        return self.frames / self.sample_rate

    @property
    def channels(self):
        return self.low.shape[1]


def analyze_wav(data, bins=4096):
    with wave.open(io.BytesIO(data), 'rb') as wav:
        channels, rate, frames, width = (wav.getnchannels(), wav.getframerate(),
                                         wav.getnframes(), wav.getsampwidth())
        pcm = wav.readframes(frames)
    if not frames or not rate or not channels or len(pcm) != frames * channels * width:
        raise ValueError('Empty or truncated PCM stream')
    if width == 1:
        values = (np.frombuffer(pcm, np.uint8).astype(np.float32) - 128) / 128
    elif width in (2, 4):
        values = np.frombuffer(pcm, '<i' + str(width)).astype(np.float32) / (1 << (width * 8 - 1))
    elif width == 3:
        octets = np.frombuffer(pcm, np.uint8).reshape(-1, 3).astype(np.int32)
        numbers = octets[:, 0] | octets[:, 1] << 8 | octets[:, 2] << 16
        numbers = (numbers ^ 0x800000) - 0x800000
        values = numbers.astype(np.float32) / 0x800000
    else:
        raise ValueError('Unsupported PCM sample width')
    values = values.reshape(frames, channels)
    bin_size = max(1, (frames + bins - 1) // bins)
    starts = np.arange(0, frames, bin_size)
    low = np.minimum.reduceat(values, starts, axis=0)
    high = np.maximum.reduceat(values, starts, axis=0)
    low.flags.writeable = high.flags.writeable = False
    return AudioEnvelope(low, high, rate, frames, float(np.max(np.abs(values))),
                         int(np.count_nonzero((values <= -1) | (values >= 1 - 1 / (1 << (width * 8 - 1))))), bin_size)


class AudioCache(MutableMapping):
    """LRU byte budget; a single oversized WAV is used without retaining it."""
    def __init__(self, budget=96 * 1024 * 1024):
        self.budget = budget
        self._items = OrderedDict()
        self.bytes_used = 0

    def __getitem__(self, key):
        value = self._items[key]
        self._items.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self._items:
            del self[key]
        if len(value) > self.budget:
            return
        while self.bytes_used + len(value) > self.budget:
            del self[next(iter(self._items))]
        self._items[key] = value
        self.bytes_used += len(value)

    def __delitem__(self, key):
        self.bytes_used -= len(self._items.pop(key))

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

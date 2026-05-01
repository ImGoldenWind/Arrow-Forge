"""
XFBIN Audio Editor  –  battle.xfbin / NUS3BANK sound editor

Supports XFBIN containers that embed NUS3BANK sound banks (CC2 / ASBR).
Features:
  • Open any .xfbin containing NUS3BANK chunks
  • List all banks and their sound tones (with search)
  • Play back individual sounds (decoded via VGAudioCli → WAV)
  • Export a tone as WAV or as raw BNSF
  • Import & replace audio from any common format (WAV, MP3, FLAC, OGG…)
    – converted to BNSF IS14 via VGAudioCli
  • Edit tone parameters: volume, pitch, pan, loop points
  • Add / delete tones
  • Save the modified XFBIN
"""

import os
import io
import math
import wave
import struct
import threading
import subprocess
import tempfile

from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QScrollArea, QSlider,
    QFileDialog, QMessageBox, QSizePolicy, QComboBox,
    QDoubleSpinBox, QSpinBox, QCheckBox,
    QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPainter, QColor, QPen

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_check, ss_dim_label, ss_file_label, ss_input, ss_panel,
    ss_placeholder, ss_scrollarea, ss_scrollarea_transparent, ss_search,
    ss_section_label, ss_sep, ss_sidebar_btn, ss_slider,
)
from core.skeleton import SkeletonListRow
from core.settings import load_settings, save_settings
from parsers.nus3bank_parser import (
    parse_xfbin_audio, save_xfbin_audio,
    get_tone_bnsf, set_tone_bnsf,
    parse_bnsf_meta, build_bnsf,
    Nus3Bank, ToneEntry, PARAMS_SIZE,
    _align_up,
)
from core.translations import ui_text


# Audio format detection

_AUDIO_MATCHERS = [
    (lambda d: d[:4] == b'RIFF' and d[8:12] == b'WAVE',               '.wav',  'WAV'),
    (lambda d: d[:3] in (b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'), '.mp3', 'MP3'),
    (lambda d: d[:4] == b'fLaC',                                        '.flac', 'FLAC'),
    (lambda d: d[:4] == b'OggS',                                        '.ogg',  'OGG'),
    (lambda d: d[:4] == b'FORM' and d[8:12] in (b'AIFF', b'AIFC'),     '.aiff', 'AIFF'),
    (lambda d: d[:2] == b'\x80\x00',                                    '.adx',  'ADX'),
    (lambda d: d[:4] == b'BNSF',                                        '.bnsf', 'BNSF'),
    (lambda d: d[:3] == b'HCA' or d[:3] == bytes([0xC8,0xC3,0xC1]),    '.hca',  'HCA'),
    (lambda d: len(d) > 8 and d[4:8] == b'ftyp',                       '.m4a',  'M4A'),
]

_AUDIO_OPEN_FILTER = (
    "Audio files (*.wav *.mp3 *.flac *.ogg *.opus *.aiff *.aif *.m4a *.aac "
    "*.bnsf *.hca *.adx *.bin);;All files (*.*)"
)


def _detect_ext(data: bytes) -> str:
    h = data[:16]
    for matcher, ext, _ in _AUDIO_MATCHERS:
        try:
            if matcher(h):
                return ext
        except Exception:
            pass
    raise ValueError(ui_text("xfa_unknown_audio_format", signature=h[:8].hex()))


def _detect_audio_tool() -> dict:
    """Find vgmstream for reading and VGAudio for writing."""
    import sys
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    vgmstream = os.path.join(base, 'tools', 'vgmstream-cli.exe')
    vgaudio = os.path.join(base, 'tools', ui_text("ui_sound_vgaudiocli_exe_2"))
    
    return {
        'decode': vgmstream if os.path.isfile(vgmstream) else vgaudio if os.path.isfile(vgaudio) else '',
        'encode': vgaudio if os.path.isfile(vgaudio) else ''
    }


def _detect_vgaudio() -> str:
    settings = load_settings()
    cli = settings.get('vgaudio_cli_path', '')
    if cli and os.path.isfile(cli):
        return cli
    return _detect_audio_tool().get('encode', '')


def _run_vgaudio(cli: str, in_path: str, out_path: str) -> bytes:
    # Try multiple command-line styles for compatibility with different VGAudioCli versions.
    # Some versions need the explicit `-i` flag (which triggers magic-byte detection rather
    # than relying solely on the file extension).
    cmds = [
        [cli, '-i', in_path, '-o', out_path],   # newer / explicit input flag
        [cli, in_path, '-o', out_path],          # older / positional input
    ]
    last_err = ''
    for cmd in cmds:
        if os.path.isfile(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        res = subprocess.run(cmd, capture_output=True, timeout=90)
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            with open(out_path, 'rb') as f:
                return f.read()
        raw = (res.stderr or res.stdout or b'').decode(errors='replace').strip()
        last_err = ui_text("xfa_vgaudio_exit_code", code=res.returncode, details=raw or ui_text("no_output"))
    raise RuntimeError(last_err)


_IMA_STEP_TABLE = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28,
    31, 34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107,
    118, 130, 143, 157, 173, 190, 209, 230, 253, 279, 307, 337,
    371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963, 1060,
    1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749,
    3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132,
    7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818,
    18500, 20350, 22385, 24623, 27086, 29794, 32767,
]
_IMA_INDEX_TABLE = [-1, -1, -1, -1, 2, 4, 6, 8]

def _run_vgmstream(cli: str, in_path: str, out_path: str) -> bytes:
    cmd = [cli, '-o', out_path, in_path]
    res = subprocess.run(cmd, capture_output=True, timeout=30)
    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        with open(out_path, 'rb') as f:
            return f.read()
    raise RuntimeError(f"vgmstream error: {(res.stderr or b'').decode(errors='replace')}")
            
    err = (res.stderr or res.stdout or b'').decode(errors='replace').strip()
    raise RuntimeError(f"vgmstream error: {err}")

def _decode_is14_python(bnsf_data: bytes) -> bytes:
    """Pure-Python IS14 (CRI IMA ADPCM) decoder for BNSF containers.

    Fallback used when VGAudioCli is unavailable or does not support BNSF.
    Handles mono fully; stereo uses standard 4-byte interleave convention.
    """
    if len(bnsf_data) < 48 or bnsf_data[:4] != b'BNSF':
        raise ValueError(ui_text("ui_xfbin_audio_not_a_valid_bnsf_file"))

    sections = {}
    pos = 12
    while pos + 8 <= len(bnsf_data):
        tag = bnsf_data[pos:pos + 4]
        size = struct.unpack_from(ui_text("ui_char_stats_i"), bnsf_data, pos + 4)[0]
        data_off = pos + 8
        data_end = data_off + size
        if not tag.strip(b'\x00 ') or data_end > len(bnsf_data):
            break
        sections[tag] = bnsf_data[data_off:data_end]
        pos = _align_up(data_end, 4)

    sfmt = sections.get(b'sfmt')
    raw = sections.get(b'sdat')
    if sfmt is None or raw is None or len(sfmt) < 20:
        raise ValueError(ui_text("ui_xfbin_audio_not_a_valid_bnsf_file"))

    channels      = struct.unpack_from(ui_text("ui_char_stats_i"), sfmt, 0)[0]
    sample_rate   = struct.unpack_from(ui_text("ui_char_stats_i"), sfmt, 4)[0]
    total_samples = struct.unpack_from(ui_text("ui_char_stats_i"), sfmt, 8)[0]

    if channels < 1 or channels > 2:
        raise ValueError(f"Unsupported channel count: {channels}")

    # Auto-detect block size: pick smallest standard size that evenly divides raw data
    block_size = 512
    for bs in (512, 256, 1024, 128, 2048):
        if len(raw) % bs == 0:
            block_size = bs
            break

    def _decode_nibble(nib, pred, sidx):
        step = _IMA_STEP_TABLE[sidx]
        diff = step >> 3
        if nib & 4: diff += step
        if nib & 2: diff += step >> 1
        if nib & 1: diff += step >> 2
        pred = (pred - diff) if (nib & 8) else (pred + diff)
        pred = max(-32768, min(32767, pred))
        sidx = max(0, min(88, sidx + _IMA_INDEX_TABLE[nib & 7]))
        return pred, sidx

    out = []
    n_blocks = len(raw) // block_size

    for bi in range(n_blocks):
        blk = raw[bi * block_size : (bi + 1) * block_size]

        if channels == 1:
            pred = struct.unpack_from('<h', blk, 0)[0]
            sidx = max(0, min(88, blk[2]))
            out.append(pred)                           # predictor = first sample
            for byte in blk[4:]:
                pred, sidx = _decode_nibble(byte & 0xF, pred, sidx)
                out.append(pred)
                pred, sidx = _decode_nibble((byte >> 4) & 0xF, pred, sidx)
                out.append(pred)
        else:
            # Stereo: 2×4-byte headers, then 4-byte chunks alternating ch0/ch1
            pred0 = struct.unpack_from('<h', blk, 0)[0]
            sidx0 = max(0, min(88, blk[2]))
            pred1 = struct.unpack_from('<h', blk, 4)[0]
            sidx1 = max(0, min(88, blk[6]))
            ch0 = [pred0]
            ch1 = [pred1]
            pos = 8
            INTERLEAVE = 4
            while pos + INTERLEAVE * 2 <= len(blk):
                for byte in blk[pos : pos + INTERLEAVE]:
                    pred0, sidx0 = _decode_nibble(byte & 0xF, pred0, sidx0)
                    ch0.append(pred0)
                    pred0, sidx0 = _decode_nibble((byte >> 4) & 0xF, pred0, sidx0)
                    ch0.append(pred0)
                pos += INTERLEAVE
                for byte in blk[pos : pos + INTERLEAVE]:
                    pred1, sidx1 = _decode_nibble(byte & 0xF, pred1, sidx1)
                    ch1.append(pred1)
                    pred1, sidx1 = _decode_nibble((byte >> 4) & 0xF, pred1, sidx1)
                    ch1.append(pred1)
                pos += INTERLEAVE
            # Interleave channels: [L0, R0, L1, R1, ...]
            for l, r in zip(ch0, ch1):
                out.append(l)
                out.append(r)

    # Trim to exact sample count
    out = out[: total_samples * channels]

    import array as _array
    pcm = _array.array('h', out).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()



def _decode_bnsf_to_wav(bnsf_data: bytes, cli: str) -> bytes:
    """Decode BNSF using vgmstream/VGAudio when available, otherwise Python IS14."""
    if not cli:
        return _decode_is14_python(bnsf_data)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            in_path = os.path.join(tmp, 'tone.bnsf')
            out_path = os.path.join(tmp, 'tone.wav')
            with open(in_path, 'wb') as f:
                f.write(bnsf_data)
            if 'vgmstream' in cli.lower():
                return _run_vgmstream(cli, in_path, out_path)
            return _run_vgaudio(cli, in_path, out_path)
    except Exception as e:
        if len(bnsf_data) > 0x100 and b'ATRAC9' in bnsf_data[:0x200]:
            raise RuntimeError(f"ATRAC9 decode error: {e}")
        return _decode_is14_python(bnsf_data)


def _encode_audio_to_bnsf(audio_data: bytes, cli: str) -> bytes:
    ext = _detect_ext(audio_data)
    if ext == '.bnsf':
        return audio_data
    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, f'input{ext}')
        out_path = os.path.join(tmp, 'output.bnsf')
        with open(in_path, 'wb') as f:
            f.write(audio_data)
        return _run_vgaudio(cli, in_path, out_path)


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _fmt_dur(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:05.2f}"


def _tone_type_info(type_id: bytes) -> tuple:
    if len(type_id) >= 2:
        t = type_id[:2]
        if t == b'\xff\xff':
            return "PS", P['accent'], P['bg_dark']
        if t == b'\x7f\x00':
            return "RNG", P['secondary'], P['bg_dark']
    return "-", P['mid'], P['text_dim']


def _clear_layout(layout):
    if not layout:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


class WaveformWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self._lines = None
        self.setStyleSheet(f"background-color: {P['bg_card']};")

    def set_waveform(self, lines):
        self._lines = lines
        self.update()

    def clear(self):
        self._lines = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        w, h = self.width(), self.height()
        mid = h // 2
        painter.fillRect(self.rect(), QColor(P['bg_card']))
        painter.setPen(QPen(QColor(P['mid']), 1))
        painter.drawLine(0, mid, w, mid)
        if self._lines:
            painter.setPen(QPen(QColor(P['accent']), 1))
            for x, y_top, y_bot in self._lines:
                if x < w:
                    painter.drawLine(x, y_top, x, y_bot)
        else:
            painter.setPen(QPen(QColor(P['text_dim']), 1))
            fm = painter.fontMetrics()
            txt = "..."
            painter.drawText((w - fm.horizontalAdvance(txt)) // 2, mid + fm.ascent() // 2, txt)
        painter.end()


class RangeSlider(QWidget):
    valueChanged = pyqtSignal(int, int)

    def __init__(self, minimum=0, maximum=100, start=0, end=100, parent=None):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = max(self._min + 1, int(maximum))
        self._start = max(self._min, min(self._max, int(start)))
        self._end = max(self._start, min(self._max, int(end)))
        self._active = None
        self.setMinimumHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def values(self):
        return self._start, self._end

    def setValues(self, start, end):
        start = max(self._min, min(self._max, int(start)))
        end = max(self._min, min(self._max, int(end)))
        if start > end:
            start, end = end, start
        if start != self._start or end != self._end:
            self._start, self._end = start, end
            self.update()
            self.valueChanged.emit(self._start, self._end)

    def _track_rect(self):
        return 10, self.width() - 10

    def _x_from_value(self, value):
        left, right = self._track_rect()
        ratio = (value - self._min) / max(1, self._max - self._min)
        return left + ratio * max(1, right - left)

    def _value_from_x(self, x):
        left, right = self._track_rect()
        ratio = (max(left, min(right, x)) - left) / max(1, right - left)
        return int(round(self._min + ratio * (self._max - self._min)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() // 2
        left, right = self._track_rect()
        sx = self._x_from_value(self._start)
        ex = self._x_from_value(self._end)
        p.setPen(QPen(QColor(P['mid']), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(left), y, int(right), y)
        p.setPen(QPen(QColor(P['accent']), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(sx), y, int(ex), y)
        p.setPen(QPen(QColor(P['border']), 1))
        p.setBrush(QColor(P['accent']))
        p.drawEllipse(int(sx - 7), int(y - 7), 14, 14)
        p.drawEllipse(int(ex - 7), int(y - 7), 14, 14)
        p.end()

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        x = e.position().x()
        sx = self._x_from_value(self._start)
        ex = self._x_from_value(self._end)
        self._active = 'start' if abs(x - sx) <= abs(x - ex) else 'end'
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e):
        if self._active is None or not self.isEnabled():
            return
        value = self._value_from_x(e.position().x())
        if self._active == 'start':
            self.setValues(min(value, self._end), self._end)
        else:
            self.setValues(self._start, max(value, self._start))

    def mouseReleaseEvent(self, _):
        self._active = None


class KnobWidget(QWidget):
    valueChanged = pyqtSignal(int)
    _HALF_SWEEP = 135

    def __init__(self, lo: int, hi: int, val: int, parent=None):
        super().__init__(parent)
        self._lo = lo
        self._hi = hi
        self._val = max(lo, min(hi, int(val)))
        self._drag_y = None
        self._drag_val = None
        self.setFixedSize(80, 80)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def value(self) -> int:
        return self._val

    def setValue(self, v: int):
        v = max(self._lo, min(self._hi, int(v)))
        if v != self._val:
            self._val = v
            self.update()
            self.valueChanged.emit(v)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        R = min(cx, cy) - 3
        tr = R - 7
        p.setPen(QPen(QColor(P['border']), 1))
        p.setBrush(QColor(P['bg_card']))
        p.drawEllipse(int(cx - R), int(cy - R), int(R * 2), int(R * 2))
        qt_start = int((90 + self._HALF_SWEEP) * 16)
        qt_span = -int(self._HALF_SWEEP * 2 * 16)
        p.setPen(QPen(QColor(P['mid']), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect_s = int(cx - tr)
        p.drawArc(rect_s, rect_s, int(tr * 2), int(tr * 2), qt_start, qt_span)
        ratio = (self._val - self._lo) / max(1, self._hi - self._lo)
        p.setPen(QPen(QColor(P['accent']), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect_s, rect_s, int(tr * 2), int(tr * 2), qt_start, -int(self._HALF_SWEEP * 2 * ratio * 16))
        ir = tr - 8
        p.setPen(QPen(QColor(P['mid']), 1))
        p.setBrush(QColor(P['bg_panel']))
        p.drawEllipse(int(cx - ir), int(cy - ir), int(ir * 2), int(ir * 2))
        std_rad = math.radians(90.0 - (-self._HALF_SWEEP + self._HALF_SWEEP * 2 * ratio))
        dot_r = ir - 6
        nx = cx + dot_r * math.cos(std_rad)
        ny = cy - dot_r * math.sin(std_rad)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(P['accent']))
        p.drawEllipse(int(nx - 4), int(ny - 4), 8, 8)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_y = e.globalPosition().y()
            self._drag_val = self._val

    def mouseMoveEvent(self, e):
        if self._drag_y is not None:
            dy = self._drag_y - e.globalPosition().y()
            self.setValue(self._drag_val + int(dy * (self._hi - self._lo) / 150))

    def mouseReleaseEvent(self, e):
        self._drag_y = None
        self._drag_val = None

    def wheelEvent(self, e):
        self.setValue(self._val + (1 if e.angleDelta().y() > 0 else -1))

    def mouseDoubleClickEvent(self, e):
        self.setValue((self._lo + self._hi) // 2)


class XfbinAudioEditor(QWidget):
    _sig_load_done = pyqtSignal(str, object, list)
    _sig_load_err = pyqtSignal(str)
    _sig_decode_done = pyqtSignal(bytes)
    _sig_decode_err = pyqtSignal(str)
    _sig_wave_ready = pyqtSignal(object)
    _sig_play_prog = pyqtSignal(float, float)
    _sig_play_done = pyqtSignal()
    _sig_convert_done = pyqtSignal(int, int, bytes)
    _sig_convert_err = pyqtSignal(str)
    _sig_save_done = pyqtSignal(str)
    _sig_save_err = pyqtSignal(str)
    _sig_batch_done = pyqtSignal(str)
    _sig_batch_err = pyqtSignal(str)
    _sig_batch_prog = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or (lambda k, **kw: kw.get('default', k))
        self._filepath = None
        self._raw = None
        self._banks = []
        self._cur_bank = 0
        self._cur_tone = -1
        self._tone_btns = []
        self._wav_cache = {}
        self._decode_and_play = False
        self._playing = False
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._seek_lock = threading.Lock()
        self._seek_target_frame = None
        self._seeking = False
        self._seek_total = 0.0
        self._seek_total_frames = 0
        self._seek_fps = 0
        self._play_thread = None
        self._pa = None
        self._sig_load_done.connect(self._on_load_done)
        self._sig_load_err.connect(self._on_load_err)
        self._sig_decode_done.connect(self._on_decode_done)
        self._sig_decode_err.connect(self._on_decode_err)
        self._sig_wave_ready.connect(self._draw_waveform)
        self._sig_play_prog.connect(self._update_play_progress)
        self._sig_play_done.connect(self._on_play_done)
        self._sig_convert_done.connect(self._on_convert_done)
        self._sig_convert_err.connect(self._on_convert_err)
        self._sig_save_done.connect(lambda path: QMessageBox.information(self, ui_text("ui_xfbin_audio_ok"), ui_text("ui_xfbin_audio_saved_value", p0=os.path.basename(path))))
        self._sig_save_err.connect(lambda msg: QMessageBox.critical(self, ui_text("dlg_title_error"), msg))
        self._sig_batch_done.connect(lambda msg: QMessageBox.information(self, ui_text("ui_xfbin_audio_ok"), msg))
        self._sig_batch_err.connect(lambda msg: QMessageBox.critical(self, ui_text("dlg_title_error"), msg))
        self._sig_batch_prog.connect(self._on_batch_prog)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(f"background-color: {P['bg_dark']};")
        top = QFrame()
        top.setFixedHeight(46)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(12, 8, 12, 8)
        tl.setSpacing(4)
        self._open_btn = QPushButton(self.t("btn_open_file", default=ui_text("btn_open_file")))
        self._open_btn.setFixedHeight(30)
        self._open_btn.setFont(QFont("Segoe UI", 10))
        self._open_btn.setStyleSheet(ss_btn(accent=True))
        self._open_btn.clicked.connect(self._load_file)
        tl.addWidget(self._open_btn)
        self._save_btn = QPushButton(self.t("btn_save_file", default=ui_text("btn_save_file")))
        self._save_btn.setFixedHeight(30)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        tl.addWidget(self._save_btn)
        self._file_lbl = QLabel(self.t("no_file_loaded", default=ui_text("cpk_no_file")))
        self._file_lbl.setFont(QFont("Consolas", 12))
        self._file_lbl.setStyleSheet(ss_file_label())
        tl.addWidget(self._file_lbl)
        tl.addStretch()
        self._bank_combo = QComboBox()
        self._bank_combo.setFixedWidth(200)
        self._bank_combo.setFont(QFont("Segoe UI", 11))
        self._bank_combo.setStyleSheet(ss_input())
        self._bank_combo.currentIndexChanged.connect(self._on_bank_changed)
        tl.addWidget(self._bank_combo)
        root.addWidget(top)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root.addWidget(sep)
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        left = QFrame()
        left.setFixedWidth(260)
        left.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 4)
        ll.setSpacing(4)
        self._search = QLineEdit()
        self._search.setPlaceholderText(self.t("search_placeholder", default=ui_text("search_placeholder")))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_tones)
        ll.addWidget(self._search)
        actions_frame = QWidget()
        actions_frame.setStyleSheet("background: transparent;")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(0, 2, 0, 4)
        actions_layout.setSpacing(4)
        btn_font = QFont("Segoe UI", 10)
        self._add_btn = QPushButton(self.t("btn_new"))
        self._add_btn.setFixedHeight(28)
        self._add_btn.setFont(btn_font)
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(ss_btn())
        self._add_btn.clicked.connect(self._add_tone)
        actions_layout.addWidget(self._add_btn, 1)
        self._dup_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_tone)
        actions_layout.addWidget(self._dup_btn, 1)
        self._del_btn = QPushButton(self.t("btn_delete"))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_tone)
        actions_layout.addWidget(self._del_btn, 1)
        ll.addWidget(actions_frame)
        self._tone_scroll = QScrollArea()
        self._tone_scroll.setWidgetResizable(True)
        self._tone_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tone_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._tone_list_widget = QWidget()
        self._tone_list_widget.setStyleSheet("background: transparent;")
        self._tone_list_layout = QVBoxLayout(self._tone_list_widget)
        self._tone_list_layout.setContentsMargins(0, 0, 0, 0)
        self._tone_list_layout.setSpacing(1)
        self._tone_list_layout.addStretch()
        self._tone_scroll.setWidget(self._tone_list_widget)
        ll.addWidget(self._tone_scroll, 1)
        main_layout.addWidget(left)
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)
        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_inner = QWidget()
        self._editor_inner.setStyleSheet(f"background: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_inner)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_inner)
        self._show_placeholder()
        main_layout.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)

    def _show_placeholder(self, text: str | None = None):
        _clear_layout(self._editor_layout)
        self._placeholder_lbl = QLabel(
            text or self.t("xfa_placeholder", default=ui_text("xfa_placeholder")))
        self._placeholder_lbl.setFont(QFont("Segoe UI", 16))
        self._placeholder_lbl.setStyleSheet(ss_placeholder())
        self._placeholder_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder_lbl)
        self._editor_layout.addStretch()

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t("xfa_open_dlg", default=ui_text("xfa_open_dlg")), "", "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return
        self._stop_playback()
        self._wav_cache.clear()
        self._file_lbl.setText(self.t("loading", default=ui_text("loading")))
        self._show_list_skeleton()
        def worker():
            try:
                raw, banks = parse_xfbin_audio(path)
                self._sig_load_done.emit(path, raw, banks)
            except Exception as e:
                self._sig_load_err.emit(str(e))
        threading.Thread(target=worker, daemon=True).start()

    def _show_list_skeleton(self):
        _clear_layout(self._tone_list_layout)
        for _ in range(12):
            self._tone_list_layout.addWidget(SkeletonListRow())
        self._tone_list_layout.addStretch()

    def _on_load_err(self, msg):
        _clear_layout(self._tone_list_layout)
        self._tone_list_layout.addStretch()
        self._file_lbl.setText(self.t("no_file_loaded", default=ui_text("cpk_no_file")))
        self._show_placeholder()
        QMessageBox.critical(self, ui_text("ui_charviewer_load_error"), msg)

    def _on_load_done(self, path, raw, banks):
        self._filepath = path
        self._raw = raw
        self._banks = banks
        self._cur_bank = 0
        self._cur_tone = -1
        self._wav_cache.clear()
        self._file_lbl.setText(os.path.basename(path))
        self._save_btn.setEnabled(bool(banks))
        self._bank_combo.blockSignals(True)
        self._bank_combo.clear()
        for i, b in enumerate(banks):
            self._bank_combo.addItem(f"[{i}]  {b.name or 'bank'}", i)
        self._bank_combo.blockSignals(False)
        if banks:
            self._bank_combo.setCurrentIndex(0)
        else:
            self._show_placeholder(
                ui_text("ui_xfbin_audio_no_embedded_nus3bank_bnsf_audio_entries_were_found_in_t"))
        self._populate_tone_list()

    def _on_bank_changed(self, idx):
        if idx < 0 or idx >= len(self._banks):
            return
        self._cur_bank = idx
        self._cur_tone = -1
        self._stop_playback()
        self._populate_tone_list()

    def _populate_tone_list(self):
        _clear_layout(self._tone_list_layout)
        self._tone_btns = []
        if not self._banks:
            self._tone_list_layout.addStretch()
            return
        bank = self._banks[self._cur_bank]
        for i, tone in enumerate(bank.tones):
            btn = QPushButton()
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(ss_sidebar_btn(False))
            inner = QWidget(btn)
            il = QHBoxLayout(inner)
            il.setContentsMargins(10, 3, 10, 3)
            il.setSpacing(4)
            tc = QWidget()
            tcl = QVBoxLayout(tc)
            tcl.setContentsMargins(0, 0, 0, 0)
            tcl.setSpacing(0)
            nl = QLabel(tone.name or f"tone_{i}")
            nl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            nl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
            nl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            tcl.addWidget(nl)
            il.addWidget(tc, 1)
            inner.setGeometry(0, 0, 260, 44)
            inner.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            btn.resizeEvent = lambda ev, iw=inner: iw.setGeometry(0, 0, ev.size().width(), ev.size().height())
            btn.clicked.connect(lambda _, ti=i: self._select_tone(ti))
            self._tone_list_layout.addWidget(btn)
            self._tone_btns.append((btn, i))
        self._tone_list_layout.addStretch()
        self._add_btn.setEnabled(True)
        self._del_btn.setEnabled(False)
        self._dup_btn.setEnabled(False)
        if bank.tones:
            self._select_tone(0)
        else:
            self._show_placeholder()

    def _filter_tones(self):
        q = self._search.text().lower()
        for btn, i in self._tone_btns:
            if not self._banks:
                break
            tone = self._banks[self._cur_bank].tones[i]
            btn.setVisible(q in (tone.name or '').lower() or q in str(i))

    def _select_tone(self, idx):
        bank = self._banks[self._cur_bank]
        if idx < 0 or idx >= len(bank.tones):
            return
        self._stop_playback()
        self._cur_tone = idx
        for btn, i in self._tone_btns:
            try:
                btn.setStyleSheet(ss_sidebar_btn(i == idx))
            except RuntimeError:
                pass
        self._del_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._decode_and_play = False
        self._build_editor(self._cur_bank, idx, bank.tones[idx])
        key = (self._cur_bank, idx)
        if key in self._wav_cache:
            self._on_decode_done(self._wav_cache[key])

    def _build_editor(self, bank_idx: int, tone_idx: int, tone: ToneEntry):
        _clear_layout(self._editor_layout)
        hdr = _card_frame()
        hl = QVBoxLayout(hdr)
        hl.setContentsMargins(16, 12, 16, 12)
        self._name_edit = QLineEdit(tone.name)
        self._name_edit.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        self._name_edit.setStyleSheet(ss_input())
        hl.addWidget(self._name_edit)
        self._editor_layout.addWidget(hdr)
        sec_play = self._make_section(ui_text("sound_section_playback"))
        play_frame = QWidget()
        play_frame.setStyleSheet("background-color: transparent;")
        play_layout = QHBoxLayout(play_frame)
        play_layout.setContentsMargins(12, 0, 12, 12)
        play_layout.setSpacing(6)
        self._play_btn = QPushButton(ui_text("ui_xfbin_audio_play"))
        self._play_btn.setFixedHeight(34)
        self._play_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self._play_btn.setStyleSheet(ss_btn(accent=True))
        self._play_btn.clicked.connect(self._play_tone)
        play_layout.addWidget(self._play_btn)
        self._pause_btn = QPushButton(ui_text("ui_sound_pause"))
        self._pause_btn.setFixedHeight(34)
        self._pause_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self._pause_btn.setEnabled(False)
        self._pause_btn.setStyleSheet(ss_btn())
        self._pause_btn.clicked.connect(self._toggle_pause)
        play_layout.addWidget(self._pause_btn)
        self._stop_btn = QPushButton(ui_text("ui_xfbin_audio_stop"))
        self._stop_btn.setFixedHeight(34)
        self._stop_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(ss_btn(danger=True))
        self._stop_btn.clicked.connect(self._stop_playback)
        play_layout.addWidget(self._stop_btn)
        self._prog_lbl = QLabel("0:00.00 / 0:00.00")
        self._prog_lbl.setFont(QFont("Consolas", 11))
        self._prog_lbl.setStyleSheet(ss_dim_label())
        play_layout.addWidget(self._prog_lbl)
        play_layout.addStretch()
        sec_play.layout().addWidget(play_frame)

        seek_frame = QWidget()
        seek_frame.setStyleSheet("background-color: transparent;")
        seek_layout = QHBoxLayout(seek_frame)
        seek_layout.setContentsMargins(12, 0, 12, 8)
        seek_layout.setSpacing(8)
        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.setValue(0)
        self._seek_slider.setEnabled(False)
        self._seek_slider.setStyleSheet(ss_slider())
        self._seek_slider.sliderPressed.connect(self._begin_seek)
        self._seek_slider.sliderReleased.connect(self._finish_seek)
        self._seek_slider.valueChanged.connect(self._preview_seek)
        seek_layout.addWidget(self._seek_slider, 1)
        sec_play.layout().addWidget(seek_frame)

        self._wave_widget = WaveformWidget()
        wf_container = QWidget()
        wf_container.setStyleSheet("background-color: transparent;")
        wf_layout = QHBoxLayout(wf_container)
        wf_layout.setContentsMargins(12, 0, 12, 12)
        wf_layout.addWidget(self._wave_widget)
        sec_play.layout().addWidget(wf_container)
        sec_vol = self._make_section(ui_text("sound_section_volume"))
        vol_frame = QWidget()
        vol_frame.setStyleSheet("background-color: transparent;")
        vol_layout = QVBoxLayout(vol_frame)
        vol_layout.setContentsMargins(12, 0, 12, 12)
        row_w, self._vol_slider, _ = _param_slider(ui_text("ui_xfbin_audio_volume"), 0.0, 4.0, tone.volume, 100)
        vol_layout.addWidget(row_w)
        sec_vol.layout().addWidget(vol_frame)
        sec_act = self._make_section(ui_text("sound_section_actions"))
        act_frame = QWidget()
        act_frame.setStyleSheet("background-color: transparent;")
        act_layout = QHBoxLayout(act_frame)
        act_layout.setContentsMargins(12, 0, 12, 12)
        act_layout.setSpacing(8)
        for text, fn, accent in [
            (ui_text("ui_sound_extract_audio"), lambda: self._export_tone('bnsf'), True),
            (ui_text("ui_sound_extract_all"), self._batch_export, False),
            (ui_text("ui_sound_replace_audio"), self._replace_audio, False),
        ]:
            b = QPushButton(text)
            b.setFixedSize(160, 34)
            b.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            b.setStyleSheet(ss_btn(accent=accent))
            b.clicked.connect(fn)
            act_layout.addWidget(b)
        act_layout.addStretch()
        sec_act.layout().addWidget(act_frame)
        sec_params = self._make_section(ui_text("skill_section_params"))
        params = QWidget()
        params.setStyleSheet("background-color: transparent;")
        pl = QVBoxLayout(params)
        pl.setContentsMargins(12, 0, 12, 12)
        pl.setSpacing(6)
        row_w, self._pitch_slider, _ = _param_slider(ui_text("ui_xfbin_audio_pitch"), 0.1, 4.0, tone.pitch, 100)
        pl.addWidget(row_w)
        row_w, self._send_slider, _ = _param_slider(ui_text("ui_xfbin_audio_send_level"), 0.0, 4.0, getattr(tone, 'send_level', 0.0), 100)
        pl.addWidget(row_w)
        pan_container = QWidget()
        pan_container.setStyleSheet("background: transparent;")
        pan_hl = QHBoxLayout(pan_container)
        pan_hl.setContentsMargins(0, 4, 0, 4)
        pan_hl.addStretch()
        col_3d, self._pan3d_knob, _ = _param_knob(ui_text("ui_xfbin_audio_pan_3d"), -180, 180, int(round(tone.pan_3d)))
        col_2d, self._pan2d_knob, _ = _param_knob(ui_text("ui_xfbin_audio_pan_2d"), -180, 180, int(round(tone.pan_2d)))
        pan_hl.addWidget(col_3d)
        pan_hl.addSpacing(28)
        pan_hl.addWidget(col_2d)
        pan_hl.addStretch()
        pl.addWidget(pan_container)
        track_row = QWidget()
        track_row.setStyleSheet("background: transparent;")
        trl = QHBoxLayout(track_row)
        trl.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(ui_text("ui_xfbin_audio_track_count"))
        lbl.setFont(QFont("Segoe UI", 11))
        lbl.setStyleSheet(ss_dim_label())
        lbl.setFixedWidth(130)
        trl.addWidget(lbl)
        self._track_spin = QSpinBox()
        self._track_spin.setRange(1, 16)
        self._track_spin.setValue(max(1, min(16, int(getattr(tone, 'track_count', 1) or 1))))
        self._track_spin.setFixedHeight(28)
        self._track_spin.setFont(QFont("Consolas", 11))
        self._track_spin.setStyleSheet(ss_input())
        trl.addWidget(self._track_spin)
        trl.addStretch()
        pl.addWidget(track_row)
        sec_params.layout().addWidget(params)
        sec_loop = self._make_section(ui_text("ui_xfbin_audio_loop_control"))
        loop = QWidget()
        loop.setStyleSheet("background-color: transparent;")
        lc = QVBoxLayout(loop)
        lc.setContentsMargins(12, 0, 12, 12)
        self._loop_chk = QCheckBox(ui_text("ui_xfbin_audio_loop_audio"))
        self._loop_chk.setFont(QFont("Segoe UI", 12))
        self._loop_chk.setStyleSheet(ss_check())
        self._loop_chk.setChecked(tone.looping)
        self._loop_chk.stateChanged.connect(self._on_loop_toggle)
        lc.addWidget(self._loop_chk)
        sr = tone.sample_rate or 1
        total = tone.total_samples
        start = tone.loop_start if tone.looping else 0
        end = tone.loop_end if tone.looping else total
        if end == 0xFFFFFFFF or end == 0:
            end = total
        row_w, self._loop_range_slider, _ = _loop_range_slider(ui_text("ui_xfbin_audio_loop_range"), total, start, end, sr)
        self._loop_range_slider.setEnabled(tone.looping)
        lc.addWidget(row_w)
        sec_loop.layout().addWidget(loop)
        self._bind_auto_apply(bank_idx, tone_idx)
        self._editor_layout.addStretch()

    def _make_section(self, title):
        sec = QFrame()
        sec.setStyleSheet(ss_panel())
        sec_layout = QVBoxLayout(sec)
        sec_layout.setContentsMargins(0, 0, 0, 0)
        sec_layout.setSpacing(0)
        title_lbl = QLabel(title)
        title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title_lbl.setStyleSheet(ss_section_label())
        title_lbl.setContentsMargins(14, 10, 14, 4)
        sec_layout.addWidget(title_lbl)
        wrapper = QWidget()
        wrapper.setStyleSheet("background-color: transparent;")
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(12, 0, 12, 8)
        wrapper_layout.addWidget(sec)
        self._editor_layout.addWidget(wrapper)
        return sec

    def _bind_auto_apply(self, bank_idx: int, tone_idx: int):
        self._name_edit.editingFinished.connect(lambda b=bank_idx, t=tone_idx: self._apply_params(b, t, refresh_list=True))
        for widget in (self._vol_slider, self._pitch_slider, self._send_slider, self._track_spin):
            widget.valueChanged.connect(lambda _=None, b=bank_idx, t=tone_idx: self._apply_params(b, t))
        self._loop_range_slider.valueChanged.connect(
            lambda _start=None, _end=None, b=bank_idx, t=tone_idx: self._apply_params(b, t))
        self._pan3d_knob.valueChanged.connect(lambda _=None, b=bank_idx, t=tone_idx: self._apply_params(b, t))
        self._pan2d_knob.valueChanged.connect(lambda _=None, b=bank_idx, t=tone_idx: self._apply_params(b, t))
        self._loop_chk.stateChanged.connect(lambda _=None, b=bank_idx, t=tone_idx: self._apply_params(b, t))

    def _on_loop_toggle(self, state):
        enabled = bool(state)
        if hasattr(self, '_loop_range_slider'):
            self._loop_range_slider.setEnabled(enabled)

    # Apply parameters

    def _apply_params(self, bank_idx: int, tone_idx: int, refresh_list: bool = False):
        if not self._banks or bank_idx >= len(self._banks):
            return
        bank = self._banks[bank_idx]
        if tone_idx < 0 or tone_idx >= len(bank.tones):
            return
        tone = bank.tones[tone_idx]

        new_name = self._name_edit.text().strip()
        if new_name and new_name != tone.name:
            tone.name = new_name

        tone.volume      = self._vol_slider.value()    / 100.0
        tone.pitch       = self._pitch_slider.value()  / 100.0
        tone.pan_3d      = float(self._pan3d_knob.value())
        tone.pan_2d      = float(self._pan2d_knob.value())
        tone.send_level  = self._send_slider.value()   / 100.0
        tone.track_count = self._track_spin.value()

        if self._loop_chk.isChecked():
            tone.loop_start, tone.loop_end = self._loop_range_slider.values()
        else:
            tone.loop_start = 0xFFFFFFFF
            tone.loop_end   = 0xFFFFFFFF

        if refresh_list and hasattr(self, '_tone_btns'):
            self._populate_tone_list()
            self._select_tone(tone_idx)

    # Decode / waveform

    def _on_decode_done(self, wav_bytes: bytes):
        # Restore play button
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(True)
            self._play_btn.setText(ui_text("ui_xfbin_audio_play"))
        if hasattr(self, '_pause_btn'):
            self._pause_btn.setEnabled(False)
            self._pause_btn.setText(ui_text("ui_sound_pause"))
        # Auto-play if triggered by Play click
        if self._decode_and_play:
            self._decode_and_play = False
            self._play_tone()
        # Draw waveform in background
        def worker():
            try:
                with wave.open(io.BytesIO(wav_bytes), 'rb') as wf:
                    n_ch = wf.getnchannels()
                    n_fr = wf.getnframes()
                    raw  = wf.readframes(n_fr)
                samps = list(struct.unpack_from(f'<{n_fr * n_ch}h', raw))
                if n_ch > 1:
                    samps = [samps[i] for i in range(0, len(samps), n_ch)]
                self._sig_wave_ready.emit(samps)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _on_decode_err(self, msg):
        self._decode_and_play = False
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(True)
            self._play_btn.setText(ui_text("ui_xfbin_audio_play"))
        if hasattr(self, '_pause_btn'):
            self._pause_btn.setEnabled(False)
            self._pause_btn.setText(ui_text("ui_sound_pause"))
        if hasattr(self, '_wave_widget'):
            self._wave_widget.clear()
        QMessageBox.critical(
            self,
            ui_text("xfa_decode_error_title"),
            ui_text("ui_xfbin_audio_value_2", p0=msg),
        )

    def _draw_waveform(self, samples):
        if not hasattr(self, '_wave_widget'):
            return
        w = max(self._wave_widget.width(), 200)
        h = self._wave_widget.height()
        mid = h // 2
        n = len(samples)
        if n == 0:
            return
        step = max(1, n // w)
        lines = []
        for x in range(min(w, n // step)):
            chunk = samples[x * step:(x + 1) * step]
            hi = max(chunk)
            lo = min(chunk)
            y_top = int(mid - (hi / 32768.0) * (mid - 2))
            y_bot = int(mid - (lo / 32768.0) * (mid - 2))
            lines.append((x, y_top, y_bot))
        self._wave_widget.set_waveform(lines)

    # Playback

    def _play_tone(self):
        if self._cur_tone < 0:
            return
        key = (self._cur_bank, self._cur_tone)
        wav = self._wav_cache.get(key)
        if wav is None:
            # Decode first, then auto-play when done
            tone = self._banks[self._cur_bank].tones[self._cur_tone]
            bnsf = get_tone_bnsf(tone)
            if not bnsf:
                QMessageBox.warning(self, ui_text("dlg_title_error"), ui_text("xfa_no_audio_playback"))
                return
            tools = _detect_audio_tool()
            cli = tools['decode']
            self._decode_and_play = True
            if hasattr(self, '_play_btn'):
                self._play_btn.setEnabled(False)
                self._play_btn.setText(ui_text("ui_xfbin_audio_decoding"))
            if hasattr(self, '_pause_btn'):
                self._pause_btn.setEnabled(False)
                self._pause_btn.setText(ui_text("ui_sound_pause"))
            def _decode_worker(bnsf=bnsf, cli=cli, key=key):
                try:
                    decoded = _decode_bnsf_to_wav(bnsf, cli)
                    self._wav_cache[key] = decoded
                    self._sig_decode_done.emit(decoded)
                except Exception as e:
                    self._sig_decode_err.emit(str(e))
            threading.Thread(target=_decode_worker, daemon=True).start()
            return
        self._stop_playback()
        self._stop_flag.clear()
        self._pause_flag.clear()
        with self._seek_lock:
            self._seek_target_frame = None
        self._playing = True
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(False)
            self._play_btn.setText(ui_text("ui_xfbin_audio_play"))
        if hasattr(self, '_pause_btn'):
            self._pause_btn.setEnabled(True)
            self._pause_btn.setText(ui_text("ui_sound_pause"))
        if hasattr(self, '_stop_btn'):
            self._stop_btn.setEnabled(True)
        if hasattr(self, '_seek_slider'):
            self._seek_slider.setEnabled(True)
            self._seek_slider.setValue(0)

        def worker():
            try:
                with wave.open(io.BytesIO(wav), 'rb') as wf:
                    sr    = wf.getframerate()
                    ch    = wf.getnchannels()
                    sw    = wf.getsampwidth()
                    total = wf.getnframes()
                    CHUNK = 1024
                    frames_read = 0
                    self._seek_total = total / sr if sr else 0.0
                    self._seek_total_frames = total
                    self._seek_fps = sr

                    try:
                        import sounddevice as _sd
                        _dtype = {1: 'int8', 2: 'int16', 4: 'int32'}.get(sw, 'int16')
                        with _sd.RawOutputStream(samplerate=sr, channels=ch, dtype=_dtype,
                                                  blocksize=CHUNK) as stream:
                            while not self._stop_flag.is_set():
                                while self._pause_flag.is_set() and not self._stop_flag.is_set():
                                    self._stop_flag.wait(0.05)
                                with self._seek_lock:
                                    target = self._seek_target_frame
                                    self._seek_target_frame = None
                                if target is not None:
                                    target = max(0, min(total, target))
                                    wf.setpos(target)
                                    frames_read = target
                                data = wf.readframes(CHUNK)
                                if not data:
                                    break
                                stream.write(data)
                                frames_read = wf.tell()
                                self._sig_play_prog.emit(frames_read / sr, total / sr)
                    except ImportError:
                        # sounddevice not installed — try pyaudio
                        import pyaudio
                        if self._pa is None:
                            self._pa = pyaudio.PyAudio()
                        stream = self._pa.open(
                            format=self._pa.get_format_from_width(sw),
                            channels=ch, rate=sr, output=True)
                        while not self._stop_flag.is_set():
                            while self._pause_flag.is_set() and not self._stop_flag.is_set():
                                self._stop_flag.wait(0.05)
                            with self._seek_lock:
                                target = self._seek_target_frame
                                self._seek_target_frame = None
                            if target is not None:
                                target = max(0, min(total, target))
                                wf.setpos(target)
                                frames_read = target
                            data = wf.readframes(CHUNK)
                            if not data:
                                break
                            stream.write(data)
                            frames_read = wf.tell()
                            self._sig_play_prog.emit(frames_read / sr, total / sr)
                        stream.stop_stream()
                        stream.close()
            except ImportError:
                self._sig_decode_err.emit(ui_text("xfa_playback_library_missing"))
            except Exception as e:
                self._sig_decode_err.emit(str(e))
            finally:
                self._playing = False
                self._sig_play_done.emit()

        self._play_thread = threading.Thread(target=worker, daemon=True)
        self._play_thread.start()

    def _toggle_pause(self):
        if not self._playing:
            return
        if self._pause_flag.is_set():
            self._pause_flag.clear()
            if hasattr(self, '_pause_btn'):
                self._pause_btn.setText(ui_text("ui_sound_pause"))
        else:
            self._pause_flag.set()
            if hasattr(self, '_pause_btn'):
                self._pause_btn.setText(ui_text("ui_sound_resume"))

    def _begin_seek(self):
        self._seeking = True

    def _preview_seek(self, value):
        if not self._seeking or not hasattr(self, '_prog_lbl') or not hasattr(self, '_seek_slider'):
            return
        if self._seek_total <= 0:
            return
        pos = self._seek_total * value / max(1, self._seek_slider.maximum())
        self._prog_lbl.setText(ui_text("ui_sound_value_value_2", p0=_fmt_dur(pos), p1=_fmt_dur(self._seek_total)))

    def _finish_seek(self):
        self._seeking = False
        if not hasattr(self, '_seek_slider'):
            return
        if self._seek_fps <= 0 or self._seek_total_frames <= 0:
            return
        ratio = self._seek_slider.value() / max(1, self._seek_slider.maximum())
        with self._seek_lock:
            self._seek_target_frame = int(self._seek_total_frames * ratio)

    def _stop_playback(self):
        self._stop_flag.set()
        self._pause_flag.clear()
        with self._seek_lock:
            self._seek_target_frame = None
        self._playing = False
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(True)
            self._play_btn.setText(ui_text("ui_xfbin_audio_play"))
        if hasattr(self, '_pause_btn'):
            self._pause_btn.setEnabled(False)
            self._pause_btn.setText(ui_text("ui_sound_pause"))
        if hasattr(self, '_stop_btn'):
            self._stop_btn.setEnabled(False)
        if hasattr(self, '_seek_slider'):
            self._seek_slider.setEnabled(False)

    def _update_play_progress(self, pos, total):
        if hasattr(self, '_prog_lbl'):
            self._prog_lbl.setText(ui_text("ui_sound_value_value_2", p0=_fmt_dur(pos), p1=_fmt_dur(total)))
        self._seek_total = total
        if hasattr(self, '_seek_slider') and not self._seeking and total > 0:
            self._seek_slider.setValue(int((pos / total) * self._seek_slider.maximum()))

    def _on_play_done(self):
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(True)
            self._play_btn.setText(ui_text("ui_xfbin_audio_play"))
        if hasattr(self, '_pause_btn'):
            self._pause_btn.setEnabled(False)
            self._pause_btn.setText(ui_text("ui_sound_pause"))
        if hasattr(self, '_stop_btn'):
            self._stop_btn.setEnabled(False)
        if hasattr(self, '_seek_slider'):
            self._seek_slider.setEnabled(False)
            self._seek_slider.setValue(0)

    # Export

    def _export_tone(self, fmt: str):
        if self._cur_tone < 0:
            return
        bank = self._banks[self._cur_bank]
        tone = bank.tones[self._cur_tone]
        bnsf = get_tone_bnsf(tone)
        if not bnsf:
            QMessageBox.warning(self, ui_text("dlg_title_error"), ui_text("xfa_no_audio_export"))
            return

        if fmt == 'bnsf':
            path, _ = QFileDialog.getSaveFileName(
                self, ui_text("ui_xfbin_audio_bnsf"), f"{tone.name}.bnsf",
                "BNSF files (*.bnsf);;All files (*.*)")
            if not path:
                return
            with open(path, 'wb') as f:
                f.write(bnsf)
            QMessageBox.information(self, ui_text("ui_xfbin_audio_ok"), ui_text("ui_xfbin_audio_value_6", p0=os.path.basename(path)))
            return

        path, _ = QFileDialog.getSaveFileName(
            self, ui_text("ui_xfbin_audio_wav"), f"{tone.name}.wav",
            "WAV files (*.wav);;All files (*.*)")
        if not path:
            return

        key = (self._cur_bank, self._cur_tone)
        cached_wav = self._wav_cache.get(key)
        if cached_wav:
            try:
                with open(path, 'wb') as f:
                    f.write(cached_wav)
                QMessageBox.information(self, ui_text("ui_xfbin_audio_ok"), ui_text("ui_xfbin_audio_value_6", p0=os.path.basename(path)))
            except Exception as e:
                QMessageBox.critical(self, ui_text("dlg_title_error"), str(e))
            return

        cli = _detect_vgaudio()

        def worker():
            try:
                wav = _decode_bnsf_to_wav(bnsf, cli)
                self._wav_cache[key] = wav
                with open(path, 'wb') as f:
                    f.write(wav)
                self._sig_save_done.emit(path)
            except Exception as e:
                self._sig_save_err.emit(str(e))
        threading.Thread(target=worker, daemon=True).start()

    # Import / Replace

    def _replace_audio(self):
        if self._cur_tone < 0:
            return
        cli = _detect_vgaudio()
        if not cli:
            QMessageBox.warning(self, ui_text("ui_xfbin_audio_vgaudiocli"), ui_text("ui_xfbin_audio_vgaudiocli_exe_tools_vgaudiocli_exe_tools_vgaudi"))
            return

        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("xfa_import_replacement_audio"), "", _AUDIO_OPEN_FILTER)
        if not path:
            return

        bank_idx = self._cur_bank
        tone_idx = self._cur_tone

        def worker():
            try:
                with open(path, 'rb') as f:
                    audio_data = f.read()
                bnsf = _encode_audio_to_bnsf(audio_data, cli)
                self._sig_convert_done.emit(bank_idx, tone_idx, bnsf)
            except Exception as e:
                self._sig_convert_err.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_convert_done(self, bank_idx: int, tone_idx: int, bnsf: bytes):
        bank = self._banks[bank_idx]
        tone = bank.tones[tone_idx]
        set_tone_bnsf(tone, bnsf)

        key = (bank_idx, tone_idx)
        self._wav_cache.pop(key, None)

        self._populate_tone_list()
        self._select_tone(tone_idx)

        QMessageBox.information(self, ui_text("ui_xfbin_audio_ok"), ui_text("ui_xfbin_audio_value_3", p0=tone.name))

    def _on_convert_err(self, msg: str):
        QMessageBox.critical(
            self,
            ui_text("xfa_conversion_error_title"),
            ui_text("ui_xfbin_audio_value_vgaudiocli_exe_bnsf", p0=msg),
        )

    def _add_tone(self):
        if not self._banks:
            return
        cli = _detect_vgaudio()
        if not cli:
            QMessageBox.warning(self, ui_text("ui_xfbin_audio_vgaudiocli"), ui_text("ui_xfbin_audio_vgaudiocli_exe_tools"))
            return

        path, _ = QFileDialog.getOpenFileName(
            self, ui_text("xfa_import_new_tone_audio"), "", _AUDIO_OPEN_FILTER)
        if not path:
            return

        bank_idx = self._cur_bank

        def worker():
            try:
                with open(path, 'rb') as f:
                    audio_data = f.read()
                bnsf = _encode_audio_to_bnsf(audio_data, cli)
                self._sig_convert_done.emit(bank_idx, -1, bnsf)
            except Exception as e:
                self._sig_convert_err.emit(str(e))

        self._pending_add_path = os.path.splitext(os.path.basename(path))[0]
        self._sig_convert_done.disconnect(self._on_convert_done)
        self._sig_convert_done.connect(self._on_add_tone_done)
        threading.Thread(target=worker, daemon=True).start()

    def _on_add_tone_done(self, bank_idx: int, _dummy: int, bnsf: bytes):
        try:
            self._sig_convert_done.disconnect(self._on_add_tone_done)
        except Exception:
            pass
        self._sig_convert_done.connect(self._on_convert_done)

        bank = self._banks[bank_idx]

        t = ToneEntry()
        t.type_id = bank._tone_type_id
        t._params_size = getattr(bank, '_tone_param_size', PARAMS_SIZE)
        t._raw_params = bytearray(t._params_size)
        t.name = getattr(self, '_pending_add_path', 'new_tone')[:15]
        set_tone_bnsf(t, bnsf)

        bank.tones.append(t)
        if hasattr(bank, '_tone_records'):
            bank._tone_records.append(t)
        new_idx = len(bank.tones) - 1

        self._wav_cache.pop((bank_idx, new_idx), None)
        self._populate_tone_list()
        self._select_tone(new_idx)

        QMessageBox.information(self, ui_text("ui_xfbin_audio_ok"), ui_text("ui_xfbin_audio_value_4", p0=t.name))

    def _delete_tone(self):
        if self._cur_tone < 0 or not self._banks:
            return
        bank = self._banks[self._cur_bank]
        tone = bank.tones[self._cur_tone]

        ans = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("ui_xfbin_audio_value_5", p0=tone.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        removed = bank.tones.pop(self._cur_tone)
        if hasattr(bank, '_tone_records'):
            try:
                bank._tone_records.remove(removed)
            except ValueError:
                pass
        self._wav_cache = {k: v for k, v in self._wav_cache.items()
                          if k != (self._cur_bank, self._cur_tone)}
        self._cur_tone = -1
        self._populate_tone_list()

    # Duplicate tone

    def _duplicate_tone(self):
        if self._cur_tone < 0 or not self._banks:
            return
        import copy
        bank     = self._banks[self._cur_bank]
        src      = bank.tones[self._cur_tone]
        clone    = copy.deepcopy(src)
        # append "_copy" suffix (truncate to 15 chars to stay safe)
        base_name = (src.name or f"tone_{self._cur_tone}")
        clone.name = (base_name + "_copy")[:15]
        bank.tones.append(clone)
        if hasattr(bank, '_tone_records'):
            bank._tone_records.append(clone)
        new_idx = len(bank.tones) - 1
        self._populate_tone_list()
        self._select_tone(new_idx)

    # Batch export

    def _batch_export(self):
        """Export all PlaySound tones in the current bank to a folder.

        Normal click → BNSF (raw, no conversion needed).
        Shift+click  → WAV  (decoded via VGAudioCli / Python fallback).
        """
        if not self._banks:
            return
        from PyQt6.QtWidgets import QApplication
        mods = QApplication.keyboardModifiers()
        as_wav = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        if as_wav:
            cli = _detect_vgaudio()
            # Even without VGAudioCli the Python IS14 decoder works for battle.xfbin tones
        else:
            cli = ''

        folder = QFileDialog.getExistingDirectory(
            self,
            ui_text("xfa_choose_export_folder_wav" if as_wav else "xfa_choose_export_folder_bnsf"),
            "")
        if not folder:
            return

        bank  = self._banks[self._cur_bank]
        tones = bank.tones
        ext   = '.wav' if as_wav else '.bnsf'

        def worker():
            ok = 0; err = 0; errs = []
            for i, tone in enumerate(tones):
                # Export PlaySound only (skip empty tones that have no audio)
                bnsf = get_tone_bnsf(tone)
                if not bnsf or len(bnsf) < 4:
                    continue
                self._sig_batch_prog.emit(ui_text("xfa_export_progress", done=i + 1, total=len(tones)))
                name = (tone.name or f"tone_{i}").replace('/', '_').replace('\\', '_')
                try:
                    if as_wav:
                        data = _decode_bnsf_to_wav(bnsf, cli)
                    else:
                        data = bnsf
                    out_path = os.path.join(folder, name + ext)
                    with open(out_path, 'wb') as f:
                        f.write(data)
                    ok += 1
                except Exception as e:
                    err += 1
                    errs.append(f"{name}: {e}")
            msg = ui_text("xfa_exported_count", n=ok)
            if err:
                msg += "\n" + ui_text("xfa_error_count", n=err) + "\n" + "\n".join(errs[:5])
                if len(errs) > 5:
                    msg += "\n" + ui_text("xfa_more_errors", n=len(errs) - 5)
            self._sig_batch_prog.emit("")
            self._sig_batch_done.emit(msg)

        threading.Thread(target=worker, daemon=True).start()

    # Batch import

    def _batch_import(self):
        """Import multiple audio files as new tones in the current bank."""
        if not self._banks:
            return
        cli = _detect_vgaudio()
        if not cli:
            QMessageBox.warning(self, ui_text("ui_xfbin_audio_vgaudiocli"), ui_text("ui_xfbin_audio_vgaudiocli_exe_tools_2"))
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, ui_text("xfa_import_audio_files"), "", _AUDIO_OPEN_FILTER)
        if not paths:
            return

        bank_idx = self._cur_bank

        def worker():
            bank  = self._banks[bank_idx]
            ok = 0; err = 0; errs = []
            for path in paths:
                name = os.path.splitext(os.path.basename(path))[0][:15]
                self._sig_batch_prog.emit(ui_text("xfa_converting_name", name=name))
                try:
                    with open(path, 'rb') as f:
                        audio_data = f.read()
                    bnsf = _encode_audio_to_bnsf(audio_data, cli)
                    t = ToneEntry()
                    t.type_id = bank._tone_type_id
                    t._params_size = getattr(bank, '_tone_param_size', PARAMS_SIZE)
                    t._raw_params = bytearray(t._params_size)
                    t.name    = name
                    set_tone_bnsf(t, bnsf)
                    bank.tones.append(t)
                    if hasattr(bank, '_tone_records'):
                        bank._tone_records.append(t)
                    ok += 1
                except Exception as e:
                    err += 1
                    errs.append(f"{name}: {e}")
            self._sig_batch_prog.emit("")
            msg = ui_text("xfa_imported_count", n=ok)
            if err:
                msg += "\n" + ui_text("xfa_error_count", n=err) + "\n" + "\n".join(errs[:5])
            # Refresh list on main thread via a side-effect signal
            self._sig_batch_done.emit(msg)

        threading.Thread(target=worker, daemon=True).start()
        # Refresh list after import — connect once to batch_done
        def _refresh_once(msg):
            try:
                self._sig_batch_done.disconnect(_refresh_once)
            except Exception:
                pass
            self._populate_tone_list()
        self._sig_batch_done.connect(_refresh_once)

    # Batch progress helper

    def _on_batch_prog(self, text: str):
        if hasattr(self, '_info_lbl'):
            if text:
                self._info_lbl.setText(text)
            elif self._banks:
                bank = self._banks[self._cur_bank]
                tones = bank.tones
                n = len(tones)
                total = sum(t.pack_size for t in tones)
                self._info_lbl.setText(ui_text("ui_xfbin_audio_value_value_2", p0=n, p1=_fmt_size(total)))

    # Save

    def _save_file(self):
        if self._filepath is None or self._raw is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            ui_text("ui_xfbin_audio_xfbin"),
            self._filepath,
            "XFBIN files (*.xfbin);;All files (*.*)")
        if not path:
            return

        raw = self._raw
        banks = self._banks

        def worker():
            try:
                save_xfbin_audio(path, bytearray(raw), banks)
                self._sig_save_done.emit(path)
            except Exception as e:
                self._sig_save_err.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    # Cleanup

    def closeEvent(self, event):
        self._stop_playback()
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
        super().closeEvent(event)


# Style helpers

def _style_accent(btn):
    btn.setStyleSheet(ss_btn(accent=True))


def _style_mid(btn):
    btn.setStyleSheet(ss_btn())


def _card_frame() -> QFrame:
    f = QFrame()
    f.setStyleSheet(ss_panel())
    return f


def _section_title(layout, text: str):
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    lbl.setStyleSheet(ss_section_label())
    layout.addWidget(lbl)


def _grid_row(grid, row: int, label: str, widget, hint: str = ""):
    lbl = QLabel(label)
    lbl.setFont(QFont("Segoe UI", 11))
    lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
    grid.addWidget(lbl, row, 0)
    grid.addWidget(widget, row, 1)
    if hint:
        hl = QLabel(hint)
        hl.setFont(QFont("Segoe UI", 9))
        hl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        grid.addWidget(hl, row, 2)


def _float_spin(lo: float, hi: float, val: float,
                step: float = 0.1, suffix: str = "") -> QDoubleSpinBox:
    sp = QDoubleSpinBox()
    sp.setRange(lo, hi)
    sp.setValue(val)
    sp.setSingleStep(step)
    sp.setDecimals(3)
    if suffix:
        sp.setSuffix("  " + suffix)
    sp.setFixedHeight(28)
    sp.setFont(QFont("Consolas", 11))
    sp.setStyleSheet(ss_input())
    return sp


def _int_spin(lo: int, hi: int, val: int, suffix: str = "") -> QSpinBox:
    sp = QSpinBox()
    # QSpinBox is limited to signed 32-bit; clamp both bounds and value
    lo = max(lo, -2147483648)
    hi = min(hi,  2147483647)
    sp.setRange(lo, hi)
    sp.setValue(max(lo, min(hi, int(val))))
    if suffix:
        sp.setSuffix("  " + suffix)
    sp.setFixedHeight(28)
    sp.setFont(QFont("Consolas", 11))
    sp.setStyleSheet(ss_input())
    return sp


# Slider helpers

_SLIDER_CSS = (
    "QSlider::groove:horizontal {{ background: {mid}; height: 6px; border-radius: 3px; }}"
    "QSlider::sub-page:horizontal {{ background: {acc}; border-radius: 3px; }}"
    "QSlider::handle:horizontal {{ background: {acc}; width: 16px; height: 16px; "
    "margin: -5px 0; border-radius: 8px; }}"
    "QSlider::handle:horizontal:hover {{ background: {acc_dim}; }}"
)


def _make_slider_css():
    return ss_slider()


def _param_slider(label: str, lo: float, hi: float, val: float,
                  scale: int, fmt: str = ui_text("ui_xfbin_audio_value_7")) -> tuple:
    """Build a labeled horizontal slider for a float param.

    Returns (container_widget, QSlider, value_QLabel).
    slider.value() / scale == current float value.
    """
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 2, 0, 2)
    rl.setSpacing(8)

    lbl = QLabel(label)
    lbl.setFont(QFont("Segoe UI", 11))
    lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
    lbl.setFixedWidth(130)
    rl.addWidget(lbl)

    sl = QSlider(Qt.Orientation.Horizontal)
    sl_lo = int(round(lo * scale))
    sl_hi = int(round(hi * scale))
    sl_val = max(sl_lo, min(sl_hi, int(round(val * scale))))
    sl.setRange(sl_lo, sl_hi)
    sl.setValue(sl_val)
    sl.setStyleSheet(_make_slider_css())
    rl.addWidget(sl, 1)

    val_lbl = QLabel(fmt.format(val))
    val_lbl.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
    val_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
    val_lbl.setFixedWidth(64)
    val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    rl.addWidget(val_lbl)

    sl.valueChanged.connect(lambda v, f=fmt, s=scale, vl=val_lbl: vl.setText(f.format(v / s)))
    return row, sl, val_lbl


def _loop_slider(label: str, total: int, val: int, sr: int) -> tuple:
    """Build a labeled horizontal slider for a loop-point (in samples).

    Returns (container_widget, QSlider, value_QLabel).
    """
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 2, 0, 2)
    rl.setSpacing(8)

    lbl = QLabel(label)
    lbl.setFont(QFont("Segoe UI", 11))
    lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
    lbl.setFixedWidth(130)
    rl.addWidget(lbl)

    sl_max = min(total, 0x7FFFFFFF)
    sl_val = max(0, min(sl_max, val))
    sl = QSlider(Qt.Orientation.Horizontal)
    sl.setRange(0, sl_max)
    sl.setValue(sl_val)
    sl.setStyleSheet(_make_slider_css())
    rl.addWidget(sl, 1)

    def _fmt_samp(s):
        t = s / sr if sr else 0.0
        return f"{s:,}  ({_fmt_dur(t)})"

    val_lbl = QLabel(_fmt_samp(sl_val))
    val_lbl.setFont(QFont("Consolas", 10))
    val_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
    val_lbl.setFixedWidth(130)
    val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    rl.addWidget(val_lbl)

    sl.valueChanged.connect(lambda v, vl=val_lbl, _sr=sr: vl.setText(_fmt_samp(v)))
    return row, sl, val_lbl


def _loop_range_slider(label: str, total: int, start: int, end: int, sr: int) -> tuple:
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    rl = QHBoxLayout(row)
    rl.setContentsMargins(0, 2, 0, 2)
    rl.setSpacing(8)

    lbl = QLabel(label)
    lbl.setFont(QFont("Segoe UI", 11))
    lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
    lbl.setFixedWidth(130)
    rl.addWidget(lbl)

    sl_max = min(total, 0x7FFFFFFF)
    start = max(0, min(sl_max, start))
    end = max(start, min(sl_max, end))
    slider = RangeSlider(0, sl_max, start, end)
    rl.addWidget(slider, 1)

    def _fmt_samp(s):
        t = s / sr if sr else 0.0
        return f"{s:,} ({_fmt_dur(t)})"

    val_lbl = QLabel(ui_text("ui_xfbin_audio_value_value", p0=_fmt_samp(start), p1=_fmt_samp(end)))
    val_lbl.setFont(QFont("Consolas", 10))
    val_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
    val_lbl.setFixedWidth(260)
    val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    rl.addWidget(val_lbl)

    slider.valueChanged.connect(
        lambda a, b, vl=val_lbl: vl.setText(ui_text("ui_xfbin_audio_value_value", p0=_fmt_samp(a), p1=_fmt_samp(b))))
    return row, slider, val_lbl


# Knob helper

def _param_knob(label: str, lo: int, hi: int, val: int) -> tuple:
    """Build a labeled KnobWidget column for a pan parameter.

    Returns (container_widget, KnobWidget, value_QLabel).
    """
    col = QWidget()
    col.setStyleSheet("background: transparent;")
    cl  = QVBoxLayout(col)
    cl.setContentsMargins(6, 2, 6, 2)
    cl.setSpacing(2)
    cl.setAlignment(Qt.AlignmentFlag.AlignCenter)

    lbl = QLabel(label)
    lbl.setFont(QFont("Segoe UI", 10))
    lbl.setStyleSheet(f"color: {P['text_sec']}; background: transparent;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cl.addWidget(lbl)

    knob = KnobWidget(lo, hi, val)
    cl.addWidget(knob, 0, Qt.AlignmentFlag.AlignCenter)

    val_lbl = QLabel(ui_text("ui_xfbin_audio_value", p0=val))
    val_lbl.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
    val_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
    val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cl.addWidget(val_lbl)

    # L / C / R positional hints
    hint_w = QWidget(); hint_w.setStyleSheet("background: transparent;")
    hl = QHBoxLayout(hint_w); hl.setContentsMargins(0, 0, 0, 0)
    for side in ("L", "C", "R"):
        sl = QLabel(side)
        sl.setFont(QFont("Segoe UI", 9))
        sl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(sl)
    cl.addWidget(hint_w)

    knob.valueChanged.connect(lambda v, vl=val_lbl: vl.setText(ui_text("ui_xfbin_audio_value", p0=v)))
    return col, knob, val_lbl



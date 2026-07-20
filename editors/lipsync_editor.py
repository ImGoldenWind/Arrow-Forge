"""Visual editor for ASBR character *_lip.xfbin lip-sync files."""

from __future__ import annotations

import copy
import io
import json
import math
import os
import subprocess
import tempfile
import threading
import wave

from PyQt6.QtCore import QCoreApplication, QRectF, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QFont, QKeySequence, QPainter, QPainterPath, QColor, QPen, QShortcut
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.external_tools import find_ffmpeg, find_rhubarb_lip_sync, find_vgaudio_cli, find_vgmstream_cli, tool_command
from core.icons import _themed_icon
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    add_editor_card_title,
    make_empty_state,
    ss_accent_label,
    ss_accent_sep,
    ss_blocking_overlay,
    ss_blocking_overlay_card,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
    ss_dim_label,
    ss_field_label,
    ss_glass_panel,
    ss_input,
    ss_icon_tool_btn,
    ss_main_label,
    ss_menu,
    ss_editor_card,
    ss_panel_menu_button,
    ss_panel_title,
    ss_progressbar,
    ss_scrollarea,
    ss_scrollarea_transparent,
    ss_search,
    ss_sep,
    ss_sidebar_btn,
    ss_sidebar_edge_toggle,
    ss_slider,
    ss_toggle_btn,
    ss_transparent,
)
from core.themes import P
from core.translations import ui_text
from editors.sound_editor import _decode_audio_to_wav
from editors.xfbin_audio_editor import _decode_bnsf_to_wav, _detect_audio_tool as _detect_xfbin_audio_tool
from parsers.acb_parser import load_companion_acb_labels
from parsers.awb_parser import extract_entry, get_entry_label, parse_awb
from parsers.lipsync_parser import (
    LipKey,
    OBSERVED_ANIMATION_TOKENS,
    OBSERVED_TAG_TOKENS,
    add_clip,
    delete_clip,
    duplicate_clip,
    load_lipsync_xfbin,
    save_lipsync_xfbin,
)
from parsers.nus3bank_parser import get_tone_bnsf, parse_xfbin_audio


RHUBARB_TO_ASBR_LIP_TOKEN = {
    "A": "PL_ANM_LIP_NO_N",
    "B": "PL_ANM_LIP_NO_E",
    "C": "PL_ANM_LIP_NO_A",
    "D": "PL_ANM_LIP_NO_A",
    "E": "PL_ANM_LIP_NO_O",
    "F": "PL_ANM_LIP_NO_U",
    "G": "PL_ANM_LIP_NO_E",
    "H": "PL_ANM_LIP_NO_A",
    "X": "PL_ANM_LIP_NO_N",
}


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _safe_ascii(text: str, max_len: int) -> str:
    encoded = text.encode("ascii", errors="replace")[:max_len]
    return encoded.decode("ascii", errors="replace")


def _norm_match_text(text: str) -> str:
    text = os.path.splitext(os.path.basename(str(text or "")))[0].lower()
    for token in ("pl_anm_", "anm_", "_lip", "lip_", "_pl", "pl_", "voice_", "vo_", "snd_", "sound_", "cue_"):
        text = text.replace(token, "_")
    return "".join(ch for ch in text if ch.isalnum())


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * min(1.0, max(0.0, ratio))))
    return ordered[idx]


def _read_wav_mono_float(wav_data: bytes) -> tuple[list[float], int]:
    with wave.open(io.BytesIO(wav_data), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frame_count = wf.getnframes()
        frames = wf.readframes(frame_count)

    if channels <= 0:
        raise ValueError(ui_text("ui_lipsync_audio_decode_failed", error=ui_text("ui_lipsync_audio_bad_channels")))
    if sample_width not in (1, 2, 3, 4):
        raise ValueError(ui_text("ui_lipsync_audio_decode_failed", error=ui_text("ui_lipsync_audio_bad_sample_width", bits=sample_width * 8)))

    def sample_at(offset: int) -> float:
        if sample_width == 1:
            return (frames[offset] - 128) / 128.0
        raw = frames[offset:offset + sample_width]
        value = int.from_bytes(raw, "little", signed=True)
        if sample_width == 2:
            return value / 32768.0
        if sample_width == 3:
            return value / 8388608.0
        return value / 2147483648.0

    stride = channels * sample_width
    samples: list[float] = []
    for frame_off in range(0, len(frames) - stride + 1, stride):
        total = 0.0
        for channel in range(channels):
            total += sample_at(frame_off + channel * sample_width)
        samples.append(total / channels)
    return samples, sample_rate


def _decode_audio_file_to_mono(path: str) -> tuple[list[float], int]:
    last_error = ""
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        cmd = [
            *tool_command(ffmpeg),
            "-hide_banner",
            "-loglevel", "error",
            "-i", path,
            "-ac", "1",
            "-ar", "16000",
            "-f", "wav",
            "pipe:1",
        ]
        res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
        if res.returncode == 0 and res.stdout:
            return _read_wav_mono_float(res.stdout)
        last_error = (res.stderr or res.stdout or b"").decode(errors="replace").strip()

    for cli in (find_vgmstream_cli(), find_vgaudio_cli()):
        if not cli:
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_path = os.path.join(tmp, "decoded.wav")
                if "vgmstream" in os.path.basename(cli).lower():
                    cmds = [[*tool_command(cli), "-o", out_path, path]]
                else:
                    cmds = [
                        [*tool_command(cli), "-i", path, "-o", out_path],
                        [*tool_command(cli), path, "-o", out_path],
                    ]
                for cmd in cmds:
                    res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
                    if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                        with open(out_path, "rb") as fh:
                            return _read_wav_mono_float(fh.read())
                    last_error = (res.stderr or res.stdout or b"").decode(errors="replace").strip()
        except Exception as exc:
            last_error = str(exc)

    if os.path.splitext(path)[1].lower() == ".wav":
        with open(path, "rb") as fh:
            return _read_wav_mono_float(fh.read())
    if ffmpeg or last_error:
        raise RuntimeError(ui_text("ui_lipsync_audio_decode_failed", error=last_error or ui_text("no_output")))
    raise RuntimeError(ui_text("ui_lipsync_ffmpeg_required_for_audio"))


def _write_samples_to_temp_wav(samples: list[float], sample_rate: int) -> str:
    fd, path = tempfile.mkstemp(prefix="asbr_lipsync_preview_", suffix=".wav")
    os.close(fd)
    try:
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(max(1, int(sample_rate)))
            pcm = bytearray()
            for sample in samples:
                value = int(max(-1.0, min(1.0, float(sample))) * 32767.0)
                pcm.extend(value.to_bytes(2, "little", signed=True))
            wf.writeframes(bytes(pcm))
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


def _write_wav_bytes_to_temp(wav_data: bytes) -> str:
    fd, path = tempfile.mkstemp(prefix="asbr_lipsync_awb_", suffix=".wav")
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(wav_data)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


def _wav_bytes_duration(wav_data: bytes) -> float:
    with wave.open(io.BytesIO(wav_data), "rb") as wf:
        rate = wf.getframerate()
        return wf.getnframes() / float(rate) if rate else 0.0


def _waveform_peaks_from_samples(samples: list[float], bucket_count: int = 1200) -> list[float]:
    if not samples:
        return []
    bucket_count = max(1, min(bucket_count, len(samples)))
    bucket_size = max(1, int(math.ceil(len(samples) / bucket_count)))
    peaks: list[float] = []
    for start in range(0, len(samples), bucket_size):
        bucket = samples[start:start + bucket_size]
        if bucket:
            peaks.append(max(min(1.0, abs(sample)) for sample in bucket))
    if not peaks:
        return []
    peak = max(peaks)
    if peak > 0.000001:
        peaks = [value / peak for value in peaks]
    return peaks


def _waveform_peaks_from_wav_path(path: str) -> list[float]:
    with open(path, "rb") as fh:
        samples, _sample_rate = _read_wav_mono_float(fh.read())
    return _waveform_peaks_from_samples(samples)


def _audio_activity_intervals(samples: list[float], sample_rate: int) -> list[tuple[float, float]]:
    if sample_rate <= 0 or not samples:
        return []

    hop = max(1, int(sample_rate * 0.02))
    window = max(hop, int(sample_rate * 0.04))
    frames: list[tuple[float, float]] = []
    for start in range(0, len(samples), hop):
        frame = samples[start:min(len(samples), start + window)]
        if not frame:
            continue
        rms = math.sqrt(sum(sample * sample for sample in frame) / len(frame))
        frames.append((start / float(sample_rate), rms))
    if not frames:
        return []

    energies = [rms for _time_value, rms in frames]
    floor = _percentile(energies, 0.20)
    peak = max(_percentile(energies, 0.95), max(energies))
    threshold = floor + ((peak - floor) * 0.14)
    frame_duration = hop / float(sample_rate)
    raw_intervals: list[tuple[float, float]] = []
    active_start: float | None = None
    last_time = 0.0
    for time_value, rms in frames:
        is_active = rms >= threshold and rms > floor * 1.4
        if is_active and active_start is None:
            active_start = time_value
        elif not is_active and active_start is not None:
            raw_intervals.append((active_start, time_value + frame_duration))
            active_start = None
        last_time = time_value
    if active_start is not None:
        raw_intervals.append((active_start, last_time + frame_duration))

    duration = len(samples) / float(sample_rate)
    intervals: list[tuple[float, float]] = []
    for start, end in raw_intervals:
        if end - start < 0.06:
            continue
        start = max(0.0, start - 0.02)
        end = min(duration, end + 0.05)
        if intervals and start - intervals[-1][1] <= 0.10:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals


def _active_time_for_key(time_value: float, intervals: list[tuple[float, float]]) -> float | None:
    for start, end in intervals:
        if start <= time_value <= end:
            return max(start, time_value)
        if time_value < start:
            return start if start - time_value <= 0.75 else None
    return None


def _compact_lip_keys(keys: list[LipKey]) -> list[LipKey]:
    compact: list[LipKey] = []
    for key in sorted(keys, key=lambda item: (item.time, 0 if item.animation == "PL_ANM_LIP_NO_N" else 1)):
        key.time = round(max(0.0, float(key.time)), 4)
        key.value = 100.0
        if compact and abs(key.time - compact[-1].time) < 0.0001:
            compact[-1] = key
            continue
        if compact and key.animation == compact[-1].animation:
            continue
        compact.append(key)
    return compact


def _clamp_lip_keys_to_duration(keys: list[LipKey], duration: float) -> list[LipKey]:
    if duration <= 0:
        return keys or [LipKey(time=0.0, animation="PL_ANM_LIP_NO_N", value=100.0)]
    clamped = [copy.deepcopy(key) for key in keys if key.time <= duration + 0.0001]
    if not clamped:
        clamped = [LipKey(time=0.0, animation="PL_ANM_LIP_NO_N", value=100.0)]
    if clamped[0].time > 0.0:
        clamped.insert(0, LipKey(time=0.0, animation="PL_ANM_LIP_NO_N", value=100.0))
    if clamped[-1].time >= duration - 0.0001:
        clamped[-1].time = round(duration, 4)
        clamped[-1].animation = "PL_ANM_LIP_NO_N"
        clamped[-1].value = 100.0
    elif clamped[-1].animation != "PL_ANM_LIP_NO_N":
        clamped.append(LipKey(time=round(duration, 4), animation="PL_ANM_LIP_NO_N", value=100.0))
    return _compact_lip_keys(clamped)


def _align_lip_keys_to_audio_activity(keys: list[LipKey], samples: list[float], sample_rate: int) -> list[LipKey]:
    intervals = _audio_activity_intervals(samples, sample_rate)
    if not intervals:
        return keys

    aligned: list[LipKey] = [LipKey(time=0.0, animation="PL_ANM_LIP_NO_N", value=100.0)]
    for key in keys:
        if key.animation == "PL_ANM_LIP_NO_N":
            aligned.append(copy.deepcopy(key))
            continue
        active_time = _active_time_for_key(key.time, intervals)
        if active_time is None:
            continue
        new_key = copy.deepcopy(key)
        new_key.time = active_time
        aligned.append(new_key)
    for _start, end in intervals:
        aligned.append(LipKey(time=round(end, 4), animation="PL_ANM_LIP_NO_N", value=100.0))
    return _compact_lip_keys(aligned)


def _lip_keys_from_rhubarb_json(data: dict) -> list[LipKey]:
    cues = data.get("mouthCues")
    if not isinstance(cues, list):
        raise ValueError(ui_text("ui_lipsync_rhubarb_no_cues"))

    keys: list[LipKey] = []
    last_token = ""
    last_end = 0.0
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        try:
            start = max(0.0, float(cue.get("start", 0.0)))
            end = max(start, float(cue.get("end", start)))
        except (TypeError, ValueError):
            continue
        rhubarb_value = str(cue.get("value", "X")).strip().upper()
        token = RHUBARB_TO_ASBR_LIP_TOKEN.get(rhubarb_value, "PL_ANM_LIP_NO_N")
        last_end = max(last_end, end)
        if token == last_token:
            continue
        keys.append(LipKey(time=round(start, 4), animation=token, value=100.0))
        last_token = token

    if not keys:
        raise ValueError(ui_text("ui_lipsync_rhubarb_no_cues"))
    if keys[0].time > 0.0:
        keys.insert(0, LipKey(time=0.0, animation="PL_ANM_LIP_NO_N", value=100.0))
    if last_end > keys[-1].time and keys[-1].animation != "PL_ANM_LIP_NO_N":
        keys.append(LipKey(time=round(last_end, 4), animation="PL_ANM_LIP_NO_N", value=100.0))
    return keys


def _generate_lip_keys_with_rhubarb(wav_path: str) -> list[LipKey]:
    rhubarb = find_rhubarb_lip_sync()
    if not rhubarb:
        raise FileNotFoundError(ui_text("ui_lipsync_rhubarb_missing"))

    last_error = ""
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "mouth_cues.json")
        commands = [
            [*tool_command(rhubarb), "-q", "-f", "json", "-o", out_path, wav_path],
            [*tool_command(rhubarb), "-q", "-r", "phonetic", "-f", "json", "-o", out_path, wav_path],
        ]
        for cmd in commands:
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
                res = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
                if res.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                    with open(out_path, "r", encoding="utf-8") as fh:
                        return _lip_keys_from_rhubarb_json(json.load(fh))
                last_error = (res.stderr or res.stdout or b"").decode(errors="replace").strip()
            except Exception as exc:
                last_error = str(exc)

    raise RuntimeError(ui_text("ui_lipsync_rhubarb_failed", error=last_error or ui_text("no_output")))


def _mouth_token_for_audio_frame(level: float, zcr: float, zcr_high: float, delta: float) -> str:
    if level <= 0.12:
        return "PL_ANM_LIP_NO_N"
    if level < 0.30:
        return "PL_ANM_LIP_NO_U"
    if delta > 0.18 and level > 0.45:
        return "PL_ANM_LIP_NO_A"
    if zcr > zcr_high and level > 0.35:
        return "PL_ANM_LIP_NO_E"
    if level < 0.66:
        return "PL_ANM_LIP_NO_O"
    return "PL_ANM_LIP_NO_A"


def _generate_lip_keys_from_audio(samples: list[float], sample_rate: int) -> list[LipKey]:
    if sample_rate <= 0 or not samples:
        return [LipKey(time=0.0, animation="PL_ANM_LIP_NO_N")]

    hop = max(1, int(sample_rate / 30.0))
    window = max(hop, int(sample_rate * 0.04))
    duration = len(samples) / float(sample_rate)
    frames: list[tuple[float, float, float]] = []
    for start in range(0, len(samples), hop):
        frame = samples[start:min(len(samples), start + window)]
        if not frame:
            continue
        rms = math.sqrt(sum(sample * sample for sample in frame) / len(frame))
        crosses = 0
        last = frame[0]
        for sample in frame[1:]:
            if (last < 0.0 <= sample) or (last >= 0.0 > sample):
                crosses += 1
            last = sample
        zcr = crosses / max(1, len(frame) - 1)
        frames.append((start / float(sample_rate), rms, zcr))

    if not frames:
        return [LipKey(time=0.0, animation="PL_ANM_LIP_NO_N")]

    energies = [frame[1] for frame in frames]
    zcr_values = [frame[2] for frame in frames]
    floor = _percentile(energies, 0.20)
    peak = max(_percentile(energies, 0.95), max(energies))
    span = max(0.000001, peak - floor)
    zcr_high = _percentile(zcr_values, 0.72)

    norm_frames = [
        (time_value, min(1.0, max(0.0, (rms - floor) / span)), zcr)
        for time_value, rms, zcr in frames
    ]

    def append_key(time_value: float, token: str):
        nonlocal last_token
        time_value = max(0.0, round(float(time_value), 4))
        if not keys and time_value > 0.0:
            keys.append(LipKey(time=0.0, animation="PL_ANM_LIP_NO_N"))
            last_token = keys[-1].animation
        if token == last_token:
            return
        if keys and time_value - keys[-1].time < min_gap:
            keys[-1].animation = token
            keys[-1].value = 100.0
            keys[-1].time = min(keys[-1].time, time_value)
        else:
            keys.append(LipKey(time=time_value, animation=token, value=100.0))
        last_token = token

    keys: list[LipKey] = []
    last_token = ""
    last_level = 0.0
    smoothed = 0.0
    silent_frames = 0
    min_gap = 1.0 / 15.0
    for idx, (time_value, level, zcr) in enumerate(norm_frames):
        lookahead_level = max(frame[1] for frame in norm_frames[idx:min(len(norm_frames), idx + 4)])
        phrase_onset = silent_frames >= 5 and level > 0.035 and lookahead_level > 0.16

        if phrase_onset:
            effective_level = max(level, min(0.32, lookahead_level * 0.58))
            token = _mouth_token_for_audio_frame(effective_level, zcr, zcr_high, effective_level - last_level)
            if token == "PL_ANM_LIP_NO_N":
                token = "PL_ANM_LIP_NO_U"
            append_key(max(0.0, time_value - 0.04), token)
            smoothed = max(smoothed, effective_level)
            last_level = smoothed
            silent_frames = 0
            continue

        if level > smoothed:
            smoothed = (smoothed * 0.22) + (level * 0.78)
        else:
            smoothed = (smoothed * 0.72) + (level * 0.28)

        delta = smoothed - last_level
        token = _mouth_token_for_audio_frame(smoothed, zcr, zcr_high, delta)
        append_key(time_value, token)
        last_level = smoothed

        if level <= 0.08:
            silent_frames += 1
        else:
            silent_frames = 0

    if not keys:
        keys.append(LipKey(time=0.0, animation="PL_ANM_LIP_NO_N"))
    if keys[0].time > 0.0:
        keys.insert(0, LipKey(time=0.0, animation="PL_ANM_LIP_NO_N"))
    compact_keys: list[LipKey] = []
    for key in keys:
        if compact_keys and key.animation == compact_keys[-1].animation:
            continue
        compact_keys.append(key)
    keys = compact_keys
    if duration > keys[-1].time + min_gap and keys[-1].animation != "PL_ANM_LIP_NO_N":
        keys.append(LipKey(time=round(duration, 4), animation="PL_ANM_LIP_NO_N", value=100.0))
    return keys


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("EditorCard")
    frame.setStyleSheet(ss_editor_card())
    return frame


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
    label.setStyleSheet(ss_accent_label())
    label.setContentsMargins(20, 10, 0, 2)
    return label


def _panel_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    label.setStyleSheet(ss_panel_title())
    label.setContentsMargins(0, 0, 0, 0)
    return label


class LipTimelineWidget(QWidget):
    keySelected = pyqtSignal(int)
    keyMoved = pyqtSignal(int, float)
    playheadScrubbed = pyqtSignal(float)
    viewRangeChanged = pyqtSignal(float, float)
    segmentSplitRequested = pyqtSignal(int, float)
    lockToggleRequested = pyqtSignal(int)
    editStarted = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list[LipKey] = []
        self._selected = -1
        self._dragging = False
        self._drag_idx = -1
        self._playhead_time: float | None = None
        self._duration_override: float | None = None
        self._view_start = 0.0
        self._view_span_ratio = 0.45
        self._range_drag_mode: str | None = None
        self._range_drag_x = 0.0
        self._range_drag_start = 0.0
        self._range_drag_end = 0.0
        self._drag_mode: str | None = None
        self._drag_next_idx = -1
        self._drag_x = 0.0
        self._drag_start_time = 0.0
        self._drag_end_time = 0.0
        self._scrubbing_playhead = False
        self._waveform: list[float] = []
        self._waveform_duration = 0.0
        self._tool_mode = "cursor"
        self._snap_enabled = True
        self._locked_indices: set[int] = set()
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_keys(self, keys: list[LipKey], selected: int = -1):
        self._keys = keys
        self._selected = selected
        self._clamp_view_range()
        self.update()

    def set_playhead_time(self, time_value: float | None):
        self._playhead_time = time_value
        self.update()

    def set_waveform(self, peaks: list[float] | None, duration: float = 0.0):
        self._waveform = list(peaks or [])
        self._waveform_duration = max(0.0, float(duration or 0.0))
        self.update()

    def set_tool_mode(self, mode: str):
        self._tool_mode = "blade" if mode == "blade" else "cursor"
        self.update()

    def set_snap_enabled(self, enabled: bool):
        self._snap_enabled = bool(enabled)

    def set_locked_indices(self, indices: set[int] | list[int] | tuple[int, ...]):
        self._locked_indices = {int(idx) for idx in indices}
        self.update()

    def set_duration_override(self, duration: float | None):
        self._duration_override = duration if duration and duration > 0 else None
        self._clamp_view_range()
        self.update()

    def _duration(self) -> float:
        if not self._keys:
            return self._duration_override or 1.0
        max_time = max(key.time for key in self._keys)
        if self._duration_override is not None:
            return max(0.001, self._duration_override)
        return max(1.0, max_time + max(0.25, max_time * 0.1))

    def _visible_duration(self) -> float:
        duration = self._duration()
        return min(duration, max(self._min_visible_duration(), duration * self._view_span_ratio))

    def _min_visible_duration(self) -> float:
        duration = self._duration()
        return min(duration, max(0.15, duration * 0.04))

    def _view_end(self) -> float:
        return min(self._duration(), self._view_start + self._visible_duration())

    def _max_view_start(self) -> float:
        return max(0.0, self._duration() - self._visible_duration())

    def _clamp_view_range(self):
        duration = self._duration()
        self._view_span_ratio = max(self._min_visible_duration() / duration, min(1.0, self._view_span_ratio))
        max_start = self._max_view_start()
        self._view_start = min(max(self._view_start, 0.0), max_start)

    def _set_view_range(self, start: float, end: float):
        duration = self._duration()
        min_span = self._min_visible_duration()
        start = max(0.0, min(duration - min_span, start))
        end = max(start + min_span, min(duration, end))
        if end - start > duration:
            start, end = 0.0, duration
        self._view_start = start
        self._view_span_ratio = max(min_span / duration, min(1.0, (end - start) / duration))
        self._clamp_view_range()
        self.update()
        self.viewRangeChanged.emit(self._view_start, self._view_end())

    def view_range(self) -> tuple[float, float]:
        return self._view_start, self._view_end()

    def timeline_duration(self) -> float:
        return self._duration()

    def set_view_range(self, start: float, end: float):
        self._set_view_range(start, end)

    def shift_view(self, direction: float):
        span = self._visible_duration()
        delta = span * 0.35 * direction
        self._set_view_range(self._view_start + delta, self._view_end() + delta)

    def zoom_view(self, factor: float):
        duration = self._duration()
        start = self._view_start
        end = self._view_end()
        center = (start + end) * 0.5
        new_span = max(self._min_visible_duration(), min(duration, (end - start) * factor))
        self._set_view_range(center - new_span * 0.5, center + new_span * 0.5)

    def zoom_normalized(self) -> float:
        duration = self._duration()
        min_span = self._min_visible_duration()
        span_range = max(0.000001, duration - min_span)
        return max(0.0, min(1.0, (duration - self._visible_duration()) / span_range))

    def set_zoom_normalized(self, value: float):
        duration = self._duration()
        min_span = self._min_visible_duration()
        value = max(0.0, min(1.0, float(value)))
        span = duration - (duration - min_span) * value
        center = (self._view_start + self._view_end()) * 0.5
        self._set_view_range(center - span * 0.5, center + span * 0.5)

    def fit_view(self):
        self._set_view_range(0.0, self._duration())

    def _ordered_key_indices(self) -> list[int]:
        return sorted(range(len(self._keys)), key=lambda idx: (self._keys[idx].time, idx))

    def _is_neutral_key(self, key: LipKey) -> bool:
        return key.animation.upper().rstrip().endswith("_N")

    def _is_locked(self, idx: int) -> bool:
        return idx in self._locked_indices

    def _key_time_limits(self, idx: int) -> tuple[float, float]:
        ordered = self._ordered_key_indices()
        if idx not in ordered:
            return 0.0, self._duration()
        pos = ordered.index(idx)
        epsilon = min(0.01, max(0.001, self._duration() * 0.0005))
        min_time = 0.0
        max_time = self._duration()
        if pos > 0:
            min_time = self._keys[ordered[pos - 1]].time + epsilon
        if pos < len(ordered) - 1:
            max_time = self._keys[ordered[pos + 1]].time - epsilon
        return min(min_time, max_time), max(min_time, max_time)

    def _segment_time_range(self, idx: int) -> tuple[float, float]:
        if (
            self._dragging
            and self._drag_mode == "body"
            and idx == self._drag_idx
            and 0 <= self._drag_next_idx < len(self._keys)
        ):
            start = max(0.0, self._keys[self._drag_idx].time)
            end = max(start, self._keys[self._drag_next_idx].time)
            return start, end
        ordered = self._ordered_key_indices()
        if idx not in ordered:
            return 0.0, 0.0
        pos = ordered.index(idx)
        start = max(0.0, self._keys[idx].time)
        end = self._duration()
        if pos < len(ordered) - 1:
            end = self._keys[ordered[pos + 1]].time
        return start, max(start, end)

    def _segment_next_index(self, idx: int) -> int:
        if (
            self._dragging
            and self._drag_mode == "body"
            and idx == self._drag_idx
            and 0 <= self._drag_next_idx < len(self._keys)
        ):
            return self._drag_next_idx
        ordered = self._ordered_key_indices()
        if idx not in ordered:
            return -1
        pos = ordered.index(idx)
        return ordered[pos + 1] if pos < len(ordered) - 1 else -1

    def _ensure_gap_before_segment(self, idx: int) -> int:
        ordered = self._ordered_key_indices()
        if idx not in ordered:
            return idx
        pos = ordered.index(idx)
        if pos <= 0:
            return idx
        prev_idx = ordered[pos - 1]
        if self._is_neutral_key(self._keys[prev_idx]):
            return idx
        gap_key = copy.deepcopy(self._keys[idx])
        gap_key.animation = "PL_ANM_LIP_NO_N"
        insert_at = idx
        self._keys.insert(insert_at, gap_key)
        self._locked_indices = {
            locked + 1 if locked >= insert_at else locked
            for locked in self._locked_indices
        }
        return idx + 1

    def _visible_segment_indices(self) -> list[int]:
        view_start = self._view_start
        view_end = self._view_end()
        indices: list[int] = []
        for idx in self._ordered_key_indices():
            key = self._keys[idx]
            if self._is_neutral_key(key):
                continue
            start, end = self._segment_time_range(idx)
            if end >= view_start and start <= view_end:
                indices.append(idx)
        return indices

    def _track_bounds(self) -> tuple[int, int]:
        left = 10
        return left, max(left + 1, self.width() - 10)

    def _scrollbar_track_rect(self) -> QRectF:
        left, right = self._track_bounds()
        return QRectF(left, max(0, self.height() - 18), right - left, 8)

    def _ruler_y(self) -> int:
        return 54

    def _lane_rect(self) -> QRectF:
        left, right = self._track_bounds()
        top = self._ruler_y() + 8
        bottom = max(top + 60, self.height() - 12)
        return QRectF(left, top, right - left, bottom - top)

    def _scrollbar_thumb_rect(self) -> QRectF:
        track = self._scrollbar_track_rect()
        duration = self._duration()
        start_ratio = self._view_start / duration
        end_ratio = self._view_end() / duration
        return QRectF(
            track.left() + track.width() * start_ratio,
            track.top() - 1,
            track.width() * max(0.0, end_ratio - start_ratio),
            track.height() + 2,
        )

    def _scrollbar_hit_mode(self, pos) -> str | None:
        track = self._scrollbar_track_rect().adjusted(0, -3, 0, 3)
        if not track.contains(pos):
            return None
        thumb = self._scrollbar_thumb_rect().adjusted(-2, -5, 2, 5)
        edge_width = 10
        if abs(pos.x() - thumb.left()) <= edge_width:
            return "left"
        if abs(pos.x() - thumb.right()) <= edge_width:
            return "right"
        if self._duration() <= self._visible_duration() + 0.0001:
            return None
        if thumb.contains(pos):
            return "move"
        return "jump"

    def _x_for_time(self, value: float) -> int:
        left, right = self._track_bounds()
        ratio = (value - self._view_start) / max(0.000001, self._visible_duration())
        return int(left + (right - left) * ratio)

    def _time_for_x(self, x: float, duration: float | None = None) -> float:
        left, right = self._track_bounds()
        ratio = min(1.0, max(0.0, (x - left) / (right - left)))
        return min(self._duration(), max(0.0, self._view_start + ratio * (duration if duration is not None else self._visible_duration())))

    def _color_for_key(self, key: LipKey) -> QColor:
        token = key.animation.upper()
        if token.endswith("_A"):
            return QColor(P["accent"])
        if token.endswith("_U"):
            return QColor(P["secondary"])
        if token.endswith("_O"):
            return QColor(P["highlight"])
        if token.endswith("_E"):
            return QColor(P["accent_dim"])
        if token.endswith("_I"):
            return QColor(P["secondary"]).lighter(118)
        return QColor(P["text_dim"])

    def _segment_rect(self, idx: int) -> QRectF:
        start, end = self._segment_time_range(idx)
        view_start = self._view_start
        view_end = self._view_end()
        clipped_start = max(start, view_start)
        clipped_end = min(end, view_end)
        left, right = self._track_bounds()
        x1 = max(left, min(right, self._x_for_time(clipped_start)))
        x2 = max(left, min(right, self._x_for_time(clipped_end)))
        if x2 - x1 < 5:
            x2 = min(right, x1 + 5)
        lane = self._lane_rect()
        lane_h = 38
        lane_y = lane.center().y() - lane_h // 2
        return QRectF(x1, lane_y, max(1.0, x2 - x1), lane_h)

    def _segment_hit(self, pos) -> tuple[str, int] | None:
        edge_width = 12
        for idx in reversed(self._visible_segment_indices()):
            base_rect = self._segment_rect(idx)
            hit_rect = base_rect.adjusted(-edge_width, -4, edge_width, 4)
            if not hit_rect.contains(pos):
                continue
            short_segment = base_rect.width() <= edge_width * 2.4
            center_x = base_rect.center().x()
            if short_segment:
                return ("left" if pos.x() <= center_x else "right"), idx
            if abs(pos.x() - base_rect.left()) <= edge_width:
                return "left", idx
            next_idx = self._segment_next_index(idx)
            if next_idx >= 0 and abs(pos.x() - base_rect.right()) <= edge_width:
                return "right", idx
            return "body", idx
        return None

    def _lock_rect(self, idx: int) -> QRectF:
        clip_rect = self._segment_rect(idx)
        size = 15
        return QRectF(clip_rect.right() - size - 4, clip_rect.top() + 5, size, size)

    def _lock_hit(self, pos) -> int:
        for idx in reversed(self._visible_segment_indices()):
            if self._lock_rect(idx).adjusted(-3, -3, 3, 3).contains(pos):
                return idx
        return -1

    def _snap_time(self, value: float, exclude: set[int] | None = None) -> float:
        if not self._snap_enabled:
            return value
        exclude = exclude or set()
        threshold = max(0.015, self._visible_duration() * 0.018)
        candidates = [0.0, self._duration()]
        candidates.extend(key.time for idx, key in enumerate(self._keys) if idx not in exclude)
        best = min(candidates, key=lambda candidate: abs(candidate - value))
        return best if abs(best - value) <= threshold else value

    def _timeline_lane_rect(self) -> QRectF:
        return self._lane_rect()

    def _playhead_hit(self, pos) -> bool:
        if self._playhead_time is None:
            return False
        x = self._x_for_time(self._playhead_time)
        marker = QRectF(x - 8, 4, 16, 16)
        center = QRectF(x - 7, self._lane_rect().center().y() - 7, 14, 14)
        return marker.contains(pos) or center.contains(pos)

    def _ruler_hit(self, pos) -> bool:
        left, right = self._track_bounds()
        ruler_y = self._ruler_y()
        return QRectF(left, ruler_y - 34, right - left, 42).contains(pos)

    def _set_scrub_position_from_x(self, x: float):
        time_value = self._time_for_x(x)
        self._playhead_time = time_value
        self.playheadScrubbed.emit(time_value)
        self.update()

    def _paint_waveform(self, painter: QPainter, lane: QRectF):
        if not self._waveform or self._waveform_duration <= 0:
            return
        view_start = self._view_start
        view_end = self._view_end()
        sample_count = len(self._waveform)
        if sample_count <= 0:
            return

        visible_start = max(0, int(math.floor((view_start / self._waveform_duration) * sample_count)))
        visible_end = min(sample_count, int(math.ceil((view_end / self._waveform_duration) * sample_count)) + 1)
        if visible_end <= visible_start:
            return

        center_y = lane.center().y()
        max_h = lane.height() * 0.42
        waveform_color = QColor(P["text_dim"])
        waveform_color.setAlpha(70)
        painter.setPen(QPen(waveform_color, 1))

        left, right = self._track_bounds()
        last_x = -1000
        column_peak = 0.0
        for idx in range(visible_start, visible_end):
            time_value = self._waveform_duration * (idx / max(1, sample_count - 1))
            x = max(left, min(right, self._x_for_time(time_value)))
            peak = self._waveform[idx]
            if x == last_x:
                column_peak = max(column_peak, peak)
                continue
            if last_x >= left:
                half_h = max(1.0, column_peak * max_h)
                painter.drawLine(last_x, int(center_y - half_h), last_x, int(center_y + half_h))
            last_x = x
            column_peak = peak
        if last_x >= left:
            half_h = max(1.0, column_peak * max_h)
            painter.drawLine(last_x, int(center_y - half_h), last_x, int(center_y + half_h))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, QColor(P.get("panel_card_bg", P["bg_panel"])))

        if not self._keys:
            painter.setPen(QColor(P["text_dim"]))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, ui_text("ui_lipsync_no_keys"))
            painter.end()
            return

        left, right = self._track_bounds()
        canvas_top = max(0, self._ruler_y() - 36)
        canvas = QRectF(left, canvas_top, right - left, max(1, rect.height() - canvas_top - 8))
        painter.setPen(QPen(QColor(P["border"]), 1))
        painter.setBrush(QColor(P["bg_card"]))
        painter.drawRoundedRect(canvas, 6, 6)

        lane = self._lane_rect()
        axis_y = int(lane.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(P.get("panel_card_bg", P["bg_panel"])))
        painter.drawRoundedRect(lane, 6, 6)
        self._paint_waveform(painter, lane.adjusted(0, 3, 0, -3))

        grid_pen = QPen(QColor(P["border"]), 1)
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        minor_count = max(8, min(64, int(self._visible_duration() * 12)))
        for tick in range(minor_count + 1):
            time_value = self._view_start + self._visible_duration() * tick / minor_count
            x = self._x_for_time(time_value)
            painter.drawLine(x, int(lane.top()), x, int(lane.bottom()))

        if self._playhead_time is not None:
            playhead_x = self._x_for_time(self._playhead_time)
            progress_width = 0
            if self._playhead_time >= self._view_end():
                progress_width = right - left
            elif self._playhead_time >= self._view_start:
                progress_width = max(0, playhead_x - left)
            progress = QRectF(left, lane.bottom() - 3, progress_width, 2)
            painter.setBrush(QColor(P["accent_dim"]))
            painter.drawRoundedRect(progress, 1, 1)

        view_start = self._view_start
        view_end = self._view_end()
        visible_duration = max(0.000001, view_end - view_start)
        tick_count = max(2, min(10, int(visible_duration * 2) + 2))
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QPen(QColor(P["text_dim"]), 1))
        ruler_y = self._ruler_y()
        for tick in range(tick_count + 1):
            time_value = view_start + visible_duration * tick / tick_count
            x = self._x_for_time(time_value)
            painter.drawLine(x, ruler_y - 8, x, ruler_y)
            painter.drawText(
                x - 18,
                ruler_y - 28,
                36,
                14,
                Qt.AlignmentFlag.AlignCenter,
                ui_text("ui_lipsync_time_tick", time=time_value),
            )

        for idx in self._visible_segment_indices():
            key = self._keys[idx]
            color = self._color_for_key(key)
            clip_rect = self._segment_rect(idx)
            fill = QColor(color)
            fill.setAlpha(210 if idx == self._selected else 165)
            painter.setBrush(color)
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(P["shine"] if idx == self._selected else P["border"]), 1))
            painter.drawRoundedRect(clip_rect, 5, 5)

            edge = QColor(P["shine"])
            edge.setAlpha(190 if idx == self._selected else 120)
            painter.setBrush(edge)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(clip_rect.left() + 3, clip_rect.top() + 4, 2, clip_rect.height() - 8), 1, 1)
            if self._segment_next_index(idx) >= 0 and clip_rect.width() > 16:
                painter.drawRoundedRect(QRectF(clip_rect.right() - 5, clip_rect.top() + 4, 2, clip_rect.height() - 8), 1, 1)

            label = key.animation.rsplit("_", 1)[-1] if "_" in key.animation else key.animation
            painter.setPen(QColor(P["shine"]))
            painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            if clip_rect.width() >= 24:
                painter.drawText(clip_rect.adjusted(0, -4, 0, -4), Qt.AlignmentFlag.AlignCenter, label)
                painter.setFont(QFont("Consolas", 7))
                start, end = self._segment_time_range(idx)
                painter.drawText(
                    clip_rect.adjusted(3, 18, -3, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    ui_text("ui_lipsync_time_tick", time=max(0.0, end - start)),
                )
            elif idx == self._selected:
                painter.drawText(clip_rect.adjusted(-12, -16, 12, -16), Qt.AlignmentFlag.AlignCenter, label)

            lock_rect = self._lock_rect(idx)
            if clip_rect.width() >= 34:
                lock_bg = QColor(P["bg_card"])
                lock_bg.setAlpha(185)
                painter.setBrush(lock_bg)
                painter.setPen(QPen(QColor(P["border"]), 1))
                painter.drawRoundedRect(lock_rect, 3, 3)
                lock_color = QColor(P["shine"] if self._is_locked(idx) else P["text_dim"])
                painter.setPen(QPen(lock_color, 1))
                body = QRectF(lock_rect.left() + 4, lock_rect.top() + 7, 7, 5)
                painter.drawRoundedRect(body, 1, 1)
                painter.drawArc(QRectF(lock_rect.left() + 4, lock_rect.top() + 3, 7, 8), 0, 180 * 16)
                if not self._is_locked(idx):
                    painter.drawLine(int(lock_rect.left() + 10), int(lock_rect.top() + 4), int(lock_rect.left() + 13), int(lock_rect.top() + 3))

        if self._playhead_time is not None:
            x = self._x_for_time(self._playhead_time)
            if left <= x <= right:
                painter.setPen(QPen(QColor(P["shine"]), 2))
                painter.drawLine(x, self._ruler_y() - 8, x, rect.height() - 12)
                painter.setBrush(QColor(P["shine"]))
                handle = QPainterPath()
                handle.moveTo(x, self._ruler_y() - 8)
                handle.lineTo(x - 6, self._ruler_y() - 18)
                handle.lineTo(x + 6, self._ruler_y() - 18)
                handle.closeSubpath()
                painter.drawPath(handle)
                painter.drawEllipse(x - 4, axis_y - 4, 8, 8)

        painter.end()

    def mousePressEvent(self, event):
        if not self._keys:
            return

        if event.button() == Qt.MouseButton.LeftButton and self._playhead_hit(event.position()):
            self._scrubbing_playhead = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._set_scrub_position_from_x(event.position().x())
            return

        if event.button() == Qt.MouseButton.LeftButton and self._ruler_hit(event.position()):
            self._scrubbing_playhead = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self._set_scrub_position_from_x(event.position().x())
            return

        lock_idx = self._lock_hit(event.position())
        if event.button() == Qt.MouseButton.LeftButton and lock_idx >= 0:
            self.lockToggleRequested.emit(lock_idx)
            return

        segment_hit = self._segment_hit(event.position())
        if segment_hit:
            hit_mode, idx = segment_hit
            self._selected = idx
            self.keySelected.emit(idx)
            if self._tool_mode == "blade":
                if not self._is_locked(idx):
                    self.editStarted.emit()
                    self.segmentSplitRequested.emit(idx, self._time_for_x(event.position().x()))
                self.update()
                return
            if self._is_locked(idx):
                self.update()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                self.editStarted.emit()
            if hit_mode == "body":
                idx = self._ensure_gap_before_segment(idx)
                self._selected = idx
                self.keySelected.emit(idx)
            self._dragging = event.button() == Qt.MouseButton.LeftButton
            self._drag_mode = hit_mode
            self._drag_idx = idx
            self._drag_next_idx = self._segment_next_index(idx)
            self._drag_x = event.position().x()
            self._drag_start_time, self._drag_end_time = self._segment_time_range(idx)
            if self._dragging:
                if hit_mode == "right" and self._drag_next_idx < 0:
                    self._dragging = False
                    self._drag_mode = None
                elif hit_mode == "body" and self._drag_next_idx < 0:
                    self._drag_mode = "left"
                self.setCursor(Qt.CursorShape.SizeAllCursor if self._drag_mode == "body" else Qt.CursorShape.SizeHorCursor)
            self.update()
            return

    def mouseMoveEvent(self, event):
        if not self._keys:
            return
        if self._scrubbing_playhead:
            self._set_scrub_position_from_x(event.position().x())
            return
        if self._dragging and 0 <= self._drag_idx < len(self._keys):
            if self._drag_mode == "body" and 0 <= self._drag_next_idx < len(self._keys):
                left, right = self._track_bounds()
                delta = (event.position().x() - self._drag_x) / max(1.0, right - left) * self._visible_duration()
                span = self._drag_end_time - self._drag_start_time
                raw_start = max(0.0, min(max(0.0, self._duration() - span), self._drag_start_time + delta))
                raw_end = raw_start + span
                snapped_start = self._snap_time(raw_start, {self._drag_idx, self._drag_next_idx})
                snapped_end = self._snap_time(raw_end, {self._drag_idx, self._drag_next_idx})
                if abs(snapped_start - raw_start) <= abs(snapped_end - raw_end):
                    start_time = max(0.0, min(max(0.0, self._duration() - span), snapped_start))
                    end_time = start_time + span
                else:
                    end_time = max(span, min(self._duration(), snapped_end))
                    start_time = end_time - span
                self._keys[self._drag_idx].time = start_time
                self._keys[self._drag_next_idx].time = end_time
                self.keyMoved.emit(self._drag_idx, start_time)
                self.keyMoved.emit(self._drag_next_idx, end_time)
                self._selected = self._drag_idx
                self.keySelected.emit(self._drag_idx)
            else:
                target_idx = self._drag_next_idx if self._drag_mode == "right" else self._drag_idx
                new_time = self._time_for_x(event.position().x())
                min_time, max_time = self._key_time_limits(target_idx)
                new_time = max(min_time, min(max_time, new_time))
                new_time = max(min_time, min(max_time, self._snap_time(new_time, {target_idx})))
                self._keys[target_idx].time = new_time
                self.keyMoved.emit(target_idx, new_time)
                if self._drag_mode == "right":
                    self._selected = self._drag_idx
                    self.keySelected.emit(self._drag_idx)
            self.update()
            return
        if self._lock_hit(event.position()) >= 0:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        segment_hit = self._segment_hit(event.position())
        if segment_hit:
            hit_mode, _idx = segment_hit
            if self._tool_mode == "blade":
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor if hit_mode == "body" else Qt.CursorShape.SizeHorCursor)
            return
        if self._playhead_hit(event.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if self._ruler_hit(event.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            return
        if not self._visible_segment_indices():
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self._dragging and self._drag_mode == "body" and 0 <= self._drag_idx < len(self._keys):
            selected_key = self._keys[self._drag_idx]
            self._keys.sort(key=lambda key: key.time)
            self._selected = self._keys.index(selected_key) if selected_key in self._keys else -1
            if self._selected >= 0:
                self.keySelected.emit(self._selected)
        self._dragging = False
        self._drag_idx = -1
        self._drag_next_idx = -1
        self._drag_mode = None
        self._range_drag_mode = None
        self._scrubbing_playhead = False
        self.unsetCursor()
        self.update()


class LipMouthPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = "PL_ANM_LIP_NO_N"
        self._blend_token = ""
        self._blend_ratio = 0.0
        self.setMinimumSize(210, 116)

    def set_token(self, token: str):
        self._token = token or "PL_ANM_LIP_NO_N"
        self._blend_token = ""
        self._blend_ratio = 0.0
        self.update()

    def set_token_blend(self, token: str, next_token: str, ratio: float):
        self._token = token or "PL_ANM_LIP_NO_N"
        self._blend_token = next_token or ""
        self._blend_ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def _suffix(self) -> str:
        token = self._token.upper().rstrip()
        return token.rsplit("_", 1)[-1] if "_" in token else token[-1:]

    def _suffix_for(self, token: str) -> str:
        token = token.upper().rstrip()
        return token.rsplit("_", 1)[-1] if "_" in token else token[-1:]

    def _mouth_params(self, suffix: str) -> tuple[float, float]:
        return {
            "A": (0.36, 0.34),
            "O": (0.22, 0.34),
            "U": (0.18, 0.20),
            "E": (0.48, 0.14),
            "I": (0.42, 0.10),
            "N": (0.30, 0.01),
        }.get(suffix, (0.30, 0.01))

    def _draw_blended_mouth(self, painter: QPainter, face_rect: QRectF, lip: QColor, inner: QColor, highlight: QColor) -> bool:
        if not self._blend_token or self._blend_ratio <= 0.001:
            return False
        start_suffix = self._suffix()
        end_suffix = self._suffix_for(self._blend_token)
        if start_suffix == end_suffix:
            return False
        start_w, start_h = self._mouth_params(start_suffix)
        end_w, end_h = self._mouth_params(end_suffix)
        ratio = self._blend_ratio
        mouth_w = start_w + (end_w - start_w) * ratio
        mouth_h = start_h + (end_h - start_h) * ratio
        cx = face_rect.center().x()
        cy = face_rect.top() + face_rect.height() * 0.64
        rect = QRectF(
            cx - face_rect.width() * mouth_w * 0.5,
            cy - face_rect.height() * mouth_h * 0.5,
            face_rect.width() * mouth_w,
            max(2.0, face_rect.height() * mouth_h),
        )
        painter.setPen(QPen(lip, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if mouth_h <= 0.035:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(int(rect.left()), int(cy), int(rect.right()), int(cy))
            return True
        painter.setBrush(QBrush(inner))
        painter.drawEllipse(rect)
        painter.setPen(QPen(highlight, 1))
        painter.drawArc(rect.adjusted(4, 3, -4, -3), 205 * 16, 130 * 16)
        return True

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, QColor(P["bg_card"]))
        painter.setPen(QPen(QColor(P["border"]), 1))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

        face_rect = QRectF(rect).adjusted(26, 10, -26, -18)
        face_color = QColor(P.get("panel_card_bg", P["bg_panel"]))
        face_color = face_color.lighter(112)
        painter.setBrush(QBrush(face_color))
        painter.setPen(QPen(QColor(P["mid"]), 1))
        painter.drawEllipse(face_rect)

        eye_color = QColor(P["text_dim"])
        eye_y = face_rect.top() + face_rect.height() * 0.36
        painter.setPen(QPen(eye_color, 2))
        painter.drawPoint(int(face_rect.left() + face_rect.width() * 0.34), int(eye_y))
        painter.drawPoint(int(face_rect.right() - face_rect.width() * 0.34), int(eye_y))

        cx = face_rect.center().x()
        cy = face_rect.top() + face_rect.height() * 0.64
        w = face_rect.width()
        suffix = self._suffix()
        lip = QColor(P["text_dim"])
        lip = lip.lighter(112)
        lip.setAlpha(235)
        inner = QColor(P["shadow"])
        inner = inner.darker(130)
        highlight = QColor(P["shine"])

        painter.setPen(QPen(lip, 2))
        painter.setBrush(QBrush(inner))

        if self._draw_blended_mouth(painter, face_rect, lip, inner, highlight):
            pass
        elif suffix == "A":
            mouth = face_rect.adjusted(w * 0.32, face_rect.height() * 0.50, -w * 0.32, -face_rect.height() * 0.13)
            painter.drawEllipse(mouth)
            painter.setPen(QPen(highlight, 1))
            painter.drawArc(mouth.adjusted(4, 5, -4, -6), 200 * 16, 140 * 16)
        elif suffix == "O":
            size = min(face_rect.width(), face_rect.height()) * 0.28
            mouth = face_rect.center()
            mouth.setY(cy)
            painter.drawEllipse(mouth, size * 0.42, size * 0.52)
        elif suffix == "U":
            mouth = face_rect.adjusted(w * 0.39, face_rect.height() * 0.58, -w * 0.39, -face_rect.height() * 0.22)
            painter.drawEllipse(mouth)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(highlight, 2))
            painter.drawEllipse(mouth.adjusted(4, 4, -4, -4))
        elif suffix == "E":
            path = QPainterPath()
            path.moveTo(cx - w * 0.24, cy)
            path.cubicTo(cx - w * 0.16, cy - 8, cx + w * 0.16, cy - 8, cx + w * 0.24, cy)
            path.cubicTo(cx + w * 0.15, cy + 11, cx - w * 0.15, cy + 11, cx - w * 0.24, cy)
            path.closeSubpath()
            painter.setBrush(QBrush(inner))
            painter.drawPath(path)
            painter.setPen(QPen(QColor(P["shine"]), 1))
            painter.drawLine(int(cx - w * 0.18), int(cy - 1), int(cx + w * 0.18), int(cy - 1))
            painter.drawLine(int(cx - w * 0.16), int(cy + 4), int(cx + w * 0.16), int(cy + 4))
        elif suffix == "I":
            mouth = face_rect.adjusted(w * 0.30, face_rect.height() * 0.61, -w * 0.30, -face_rect.height() * 0.28)
            path = QPainterPath()
            path.moveTo(mouth.left(), mouth.center().y())
            path.cubicTo(mouth.left() + mouth.width() * 0.22, mouth.top(), mouth.right() - mouth.width() * 0.22, mouth.top(), mouth.right(), mouth.center().y())
            path.cubicTo(mouth.right() - mouth.width() * 0.22, mouth.bottom(), mouth.left() + mouth.width() * 0.22, mouth.bottom(), mouth.left(), mouth.center().y())
            path.closeSubpath()
            painter.setBrush(QBrush(inner))
            painter.drawPath(path)
            painter.setPen(QPen(highlight, 1))
            painter.drawLine(int(mouth.left() + 5), int(mouth.center().y()), int(mouth.right() - 5), int(mouth.center().y()))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(lip, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(int(cx - w * 0.15), int(cy), int(cx + w * 0.15), int(cy))

        painter.setPen(QColor(P["text_dim"]))
        painter.setFont(QFont("Consolas", 8))
        painter.drawText(rect.adjusted(6, 4, -6, -4), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, self._token)
        painter.end()


class LipTimelineOverviewWidget(QWidget):
    viewRangeChanged = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list[LipKey] = []
        self._duration = 1.0
        self._view_start = 0.0
        self._view_end = 1.0
        self._dragging = False
        self._drag_mode: str | None = None
        self._drag_x = 0.0
        self._drag_start = 0.0
        self._drag_end = 1.0
        self.setFixedHeight(34)
        self.setMouseTracking(True)

    def set_data(self, keys: list[LipKey], duration: float, view_start: float, view_end: float):
        self._keys = keys
        self._duration = max(0.001, float(duration or 1.0))
        self._view_start = max(0.0, min(self._duration, float(view_start)))
        self._view_end = max(self._view_start, min(self._duration, float(view_end)))
        self.update()

    def _track_rect(self) -> QRectF:
        return QRectF(6, 8, max(1, self.width() - 12), 18)

    def _x_for_time(self, time_value: float) -> float:
        track = self._track_rect()
        return track.left() + track.width() * (time_value / self._duration)

    def _time_for_x(self, x: float) -> float:
        track = self._track_rect()
        ratio = max(0.0, min(1.0, (x - track.left()) / max(1.0, track.width())))
        return ratio * self._duration

    def _thumb_rect(self) -> QRectF:
        track = self._track_rect()
        left = self._x_for_time(self._view_start)
        right = self._x_for_time(self._view_end)
        return QRectF(left, track.top() - 4, max(14.0, right - left), track.height() + 8)

    def _thumb_hit_mode(self, pos) -> str | None:
        thumb = self._thumb_rect().adjusted(-4, -4, 4, 4)
        if not thumb.contains(pos):
            return None
        edge = 9
        if abs(pos.x() - thumb.left()) <= edge:
            return "left"
        if abs(pos.x() - thumb.right()) <= edge:
            return "right"
        return "move"

    def _emit_view(self, start: float, end: float):
        span = max(0.03, end - start)
        start = max(0.0, min(self._duration - span, start))
        end = start + span
        self._view_start = start
        self._view_end = end
        self.viewRangeChanged.emit(start, end)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        bg = QColor(P.get("bg_card", P["bg_panel"]))
        bg.setAlpha(70)
        painter.fillRect(rect, bg)
        track = self._track_rect()
        painter.setPen(Qt.PenStyle.NoPen)
        track_color = QColor(P["mid"])
        track_color.setAlpha(105)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 3, 3)

        ordered = sorted(range(len(self._keys)), key=lambda idx: (self._keys[idx].time, idx))
        for pos, idx in enumerate(ordered):
            key = self._keys[idx]
            if key.animation.upper().rstrip().endswith("_N"):
                continue
            start = max(0.0, key.time)
            end = self._duration
            if pos < len(ordered) - 1:
                end = max(start, self._keys[ordered[pos + 1]].time)
            x1 = self._x_for_time(start)
            x2 = self._x_for_time(end)
            color = QColor(P["text_dim"])
            token = key.animation.upper()
            if token.endswith("_A"):
                color = QColor(P["accent"])
            elif token.endswith("_U") or token.endswith("_I"):
                color = QColor(P["secondary"])
            elif token.endswith("_O"):
                color = QColor(P["highlight"])
            elif token.endswith("_E"):
                color = QColor(P["accent_dim"])
            color.setAlpha(170)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x1, track.top() + 3, max(2.0, x2 - x1), track.height() - 6), 2, 2)

        thumb = self._thumb_rect()
        thumb_fill = QColor(P.get("bg_card_hov", P["bg_panel"]))
        thumb_fill.setAlpha(108)
        thumb_border = QColor(P["border_hov"] if self._dragging else P["border"])
        thumb_border.setAlpha(195)
        painter.setBrush(thumb_fill)
        painter.setPen(QPen(thumb_border, 1))
        painter.drawRoundedRect(thumb, 5, 5)
        highlight = QColor(P["shine"])
        highlight.setAlpha(45)
        painter.setBrush(highlight)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(thumb.adjusted(2, 2, -2, -thumb.height() / 2), 4, 4)
        grip_color = QColor(P["shine"])
        grip_color.setAlpha(215)
        painter.setBrush(grip_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(thumb.left() + 5, thumb.top() + 6, 2, thumb.height() - 12), 1, 1)
        painter.drawRoundedRect(QRectF(thumb.right() - 7, thumb.top() + 6, 2, thumb.height() - 12), 1, 1)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_mode = self._thumb_hit_mode(event.position())
        if self._drag_mode is None:
            return
        self._dragging = True
        self._drag_x = event.position().x()
        self._drag_start = self._view_start
        self._drag_end = self._view_end
        self.setCursor(Qt.CursorShape.ClosedHandCursor if self._drag_mode == "move" else Qt.CursorShape.SizeHorCursor)

    def mouseMoveEvent(self, event):
        if not self._dragging:
            mode = self._thumb_hit_mode(event.position())
            if mode in ("left", "right"):
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif mode == "move":
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        delta = self._time_for_x(event.position().x()) - self._time_for_x(self._drag_x)
        if self._drag_mode == "move":
            span = self._drag_end - self._drag_start
            self._emit_view(self._drag_start + delta, self._drag_start + delta + span)
        elif self._drag_mode == "left":
            self._emit_view(min(self._drag_end - 0.03, self._drag_start + delta), self._drag_end)
        elif self._drag_mode == "right":
            self._emit_view(self._drag_start, max(self._drag_start + 0.03, self._drag_end + delta))

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self._drag_mode = None
        self.unsetCursor()


class LipSyncEditor(QWidget):
    _sig_awb_load_done = pyqtSignal(str, object, list, dict)
    _sig_awb_load_error = pyqtSignal(str)
    _sig_awb_decode_done = pyqtSignal(object, str, float, bool)
    _sig_awb_decode_error = pyqtSignal(object, str, bool)
    _sig_pl_load_done = pyqtSignal(str, object, list)
    _sig_pl_load_error = pyqtSignal(str)
    _sig_pl_decode_done = pyqtSignal(object, str, float, bool)
    _sig_pl_decode_error = pyqtSignal(object, str, bool)
    _sig_audio_generate_done = pyqtSignal(object, str, float, object)
    _sig_audio_generate_error = pyqtSignal(str)
    _sig_reference_audio_done = pyqtSignal(object, str, float)
    _sig_reference_audio_error = pyqtSignal(str)

    def __init__(self, parent=None, t=None, embedded=False):
        super().__init__(parent)
        self._t = t or (lambda key, **kw: ui_text(key, **kw))
        self._embedded = embedded
        self._filepath: str | None = None
        self._xfbin = None
        self._clips = []
        self._clip_snapshots = {}
        self._selected_clip_idx = -1
        self._selected_key_idx = -1
        self._clip_buttons = []
        self._dirty = False
        self._rebuilding_table = False
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(33)
        self._play_timer.timeout.connect(self._playback_tick)
        self._playing = False
        self._play_time = 0.0
        self._play_step = 1.0 / 30.0
        self._playback_speed = 1.0
        self._loop_playback = False
        self._last_play_key_idx = -1
        self._audio_preview_paths: dict[int, str] = {}
        self._audio_preview_durations: dict[int, float] = {}
        self._audio_waveforms: dict[int, list[float]] = {}
        self._audio_muted = False
        self._timeline_tool_mode = "cursor"
        self._timeline_snap_enabled = True
        self._mouth_animation_enabled = False
        self._locked_lip_keys: dict[int, set[int]] = {}
        self._undo_stack: dict[int, list[list[LipKey]]] = {}
        self._redo_stack: dict[int, list[list[LipKey]]] = {}
        self._timeline_buttons: list[QPushButton] = []
        self._sidebar_visible = True
        self._audio_output = None
        self._audio_player = None
        self._awb_path: str | None = None
        self._awb_raw = None
        self._awb_entries = []
        self._awb_entry_labels: dict[int, str] = {}
        self._awb_clip_entry_indices: dict[int, int] = {}
        self._awb_clip_sources: dict[int, tuple[object, dict, str]] = {}
        self._awb_failed_audio_keys: set[int] = set()
        self._awb_decoding_audio_keys: set[int] = set()
        self._pl_path: str | None = None
        self._pl_raw = None
        self._pl_banks = []
        self._pl_tone_refs: list[tuple[int, int, object]] = []
        self._pl_clip_tone_refs: dict[int, tuple[int, int]] = {}
        self._pl_clip_sources: dict[int, tuple[object, str]] = {}
        self._pl_failed_audio_keys: set[int] = set()
        self._pl_decoding_audio_keys: set[int] = set()
        self._busy_count = 0
        self._sig_awb_load_done.connect(self._on_awb_load_done)
        self._sig_awb_load_error.connect(self._on_awb_load_error)
        self._sig_awb_decode_done.connect(self._on_awb_decode_done)
        self._sig_awb_decode_error.connect(self._on_awb_decode_error)
        self._sig_pl_load_done.connect(self._on_pl_load_done)
        self._sig_pl_load_error.connect(self._on_pl_load_error)
        self._sig_pl_decode_done.connect(self._on_pl_decode_done)
        self._sig_pl_decode_error.connect(self._on_pl_decode_error)
        self._sig_audio_generate_done.connect(self._on_audio_generate_done)
        self._sig_audio_generate_error.connect(self._on_audio_generate_error)
        self._sig_reference_audio_done.connect(self._on_reference_audio_done)
        self._sig_reference_audio_error.connect(self._on_reference_audio_error)
        self.destroyed.connect(lambda _=None: self._cleanup_audio_previews())
        self._build_ui()
        self._install_timeline_shortcuts()

    def _tr(self, key: str, **kw) -> str:
        try:
            return self._t(key, **kw)
        except TypeError:
            return ui_text(key, **kw)

    def _install_timeline_shortcuts(self):
        shortcuts = (
            ("Ctrl+Z", self._undo_timeline),
            ("Ctrl+Shift+Z", self._redo_timeline),
            ("Delete", self._delete_key),
            ("Ctrl+C", self._copy_selected_segment),
        )
        for sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        top = QFrame()
        top.setFixedHeight(TOOLBAR_H)
        top.setStyleSheet(ss_bg_panel())
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        self._btn_open = QPushButton(ui_text("btn_open_file"))
        self._btn_open.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_open.setFont(QFont("Segoe UI", 10))
        self._btn_open.setStyleSheet(ss_btn(accent=True))
        self._btn_open.clicked.connect(self._open_file)
        top_layout.addWidget(self._btn_open)

        self._btn_save = QPushButton(ui_text("btn_save_file"))
        self._btn_save.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_save.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(ss_btn(accent=True))
        self._btn_save.clicked.connect(self._save_file)
        top_layout.addWidget(self._btn_save)

        self._btn_load_audio_container = QPushButton(ui_text("ui_lipsync_load_audio_container"))
        self._btn_load_audio_container.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_load_audio_container.setFont(QFont("Segoe UI", 10))
        self._btn_load_audio_container.setEnabled(False)
        self._btn_load_audio_container.setStyleSheet(ss_btn())
        self._btn_load_audio_container.clicked.connect(self._load_audio_container_file)
        top_layout.addWidget(self._btn_load_audio_container)

        self._file_lbl = QLabel()
        self._file_lbl.setFont(QFont("Consolas", 12))
        set_file_label_empty(self._file_lbl, ui_text("xfa_no_file"))
        top_layout.addWidget(self._file_lbl)
        top_layout.addStretch()

        self._btn_load_reference_top = QPushButton(ui_text("ui_lipsync_load_reference_audio"))
        self._btn_load_reference_top.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_load_reference_top.setFont(QFont("Segoe UI", 10))
        self._btn_load_reference_top.setEnabled(False)
        self._btn_load_reference_top.setStyleSheet(ss_btn())
        self._btn_load_reference_top.clicked.connect(self._load_reference_audio_file)
        top_layout.addWidget(self._btn_load_reference_top)

        self._btn_generate_audio_top = QPushButton(ui_text("ui_lipsync_generate_from_audio"))
        self._btn_generate_audio_top.setFixedHeight(TOOLBAR_BTN_H)
        self._btn_generate_audio_top.setFont(QFont("Segoe UI", 10))
        self._btn_generate_audio_top.setEnabled(False)
        self._btn_generate_audio_top.setStyleSheet(ss_btn(accent=True))
        self._btn_generate_audio_top.clicked.connect(self._generate_keys_from_audio_file)
        top_layout.addWidget(self._btn_generate_audio_top)

        root.addWidget(top)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        self._sidebar = sidebar
        sidebar.setFixedWidth(286)
        sidebar.setStyleSheet(ss_bg_panel())
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 4)
        sidebar_layout.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(ui_text("ui_lipsync_search_clips"))
        self._search.setFixedHeight(32)
        self._search.setFont(QFont("Segoe UI", 13))
        self._search.setStyleSheet(ss_search())
        self._search.textChanged.connect(self._filter_clips)
        sidebar_layout.addWidget(self._search)

        clip_actions = QWidget()
        clip_actions.setStyleSheet(ss_transparent())
        clip_actions_layout = QHBoxLayout(clip_actions)
        clip_actions_layout.setContentsMargins(0, 2, 0, 4)
        clip_actions_layout.setSpacing(4)
        action_font = QFont("Segoe UI", 10)

        self._btn_add_clip = QPushButton(ui_text("ui_messageinfo_add"))
        self._btn_add_clip.setFixedHeight(28)
        self._btn_add_clip.setFont(action_font)
        self._btn_add_clip.setEnabled(False)
        self._btn_add_clip.setStyleSheet(ss_btn())
        self._btn_add_clip.clicked.connect(self._add_clip)
        clip_actions_layout.addWidget(self._btn_add_clip, 1)

        self._btn_dup_clip = QPushButton(ui_text("btn_dup_short"))
        self._btn_dup_clip.setFixedHeight(28)
        self._btn_dup_clip.setFont(action_font)
        self._btn_dup_clip.setEnabled(False)
        self._btn_dup_clip.setStyleSheet(ss_btn())
        self._btn_dup_clip.clicked.connect(self._duplicate_clip)
        clip_actions_layout.addWidget(self._btn_dup_clip, 1)

        self._btn_del_clip = QPushButton(ui_text("btn_delete"))
        self._btn_del_clip.setFixedHeight(28)
        self._btn_del_clip.setFont(action_font)
        self._btn_del_clip.setEnabled(False)
        self._btn_del_clip.setStyleSheet(ss_btn(danger=True))
        self._btn_del_clip.clicked.connect(self._delete_clip)
        clip_actions_layout.addWidget(self._btn_del_clip, 1)
        sidebar_layout.addWidget(clip_actions)

        self._clip_scroll = QScrollArea()
        self._clip_scroll.setWidgetResizable(True)
        self._clip_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._clip_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._clip_inner = QWidget()
        self._clip_inner.setStyleSheet(ss_transparent())
        self._clip_layout = QVBoxLayout(self._clip_inner)
        self._clip_layout.setContentsMargins(0, 0, 0, 0)
        self._clip_layout.setSpacing(1)
        self._clip_layout.addStretch()
        self._clip_scroll.setWidget(self._clip_inner)
        sidebar_layout.addWidget(self._clip_scroll, 1)
        main_layout.addWidget(sidebar)

        toggle_rail = QFrame()
        toggle_rail.setFixedWidth(20)
        toggle_rail.setStyleSheet(ss_bg_panel())
        toggle_rail_layout = QVBoxLayout(toggle_rail)
        toggle_rail_layout.setContentsMargins(0, 0, 0, 0)
        toggle_rail_layout.setSpacing(0)
        toggle_rail_layout.addStretch()
        self._btn_toggle_sidebar = QPushButton()
        self._btn_toggle_sidebar.setFixedSize(20, 58)
        self._btn_toggle_sidebar.setToolTip(ui_text("ui_lipsync_hide_clips"))
        self._btn_toggle_sidebar.setIcon(_themed_icon("fa6s.chevron-left", color=P.get("button_text", P["text_main"]), size=12))
        self._btn_toggle_sidebar.setIconSize(QSize(12, 12))
        self._btn_toggle_sidebar.setStyleSheet(ss_sidebar_edge_toggle())
        self._btn_toggle_sidebar.clicked.connect(self._toggle_sidebar)
        toggle_rail_layout.addWidget(self._btn_toggle_sidebar)
        toggle_rail_layout.addStretch()
        self._sidebar_toggle_rail = toggle_rail
        main_layout.addWidget(toggle_rail)

        divider = QFrame()
        self._sidebar_divider = divider
        divider.setFixedWidth(1)
        divider.setStyleSheet(ss_sep())
        main_layout.addWidget(divider)

        right = QWidget()
        right.setStyleSheet(ss_bg_dark())
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._placeholder = make_empty_state(
            right,
            title=ui_text("no_file_loaded"),
            text=ui_text("ui_lipsync_open_lip_xfbin_to_begin_editing"),
            icon_name="fa6s.wave-square",
        )
        right_layout.addWidget(self._placeholder, 1, Qt.AlignmentFlag.AlignCenter)

        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_inner = QWidget()
        self._editor_inner.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_inner)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_inner)
        self._editor_scroll.setVisible(False)
        right_layout.addWidget(self._editor_scroll, 1)

        main_layout.addWidget(right, 1)
        root.addWidget(main, 1)
        self._build_busy_overlay()

    def _build_busy_overlay(self):
        self._busy_overlay = QFrame(self)
        self._busy_overlay.setObjectName("BlockingOverlay")
        self._busy_overlay.setStyleSheet(ss_blocking_overlay())
        self._busy_overlay.hide()

        overlay_layout = QVBoxLayout(self._busy_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.addStretch()

        card = QFrame()
        card.setObjectName("BlockingOverlayCard")
        card.setFixedWidth(360)
        card.setStyleSheet(ss_blocking_overlay_card())
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        card_layout.setSpacing(10)

        self._busy_title_lbl = QLabel(ui_text("loading"))
        self._busy_title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._busy_title_lbl.setStyleSheet(ss_accent_label())
        self._busy_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._busy_title_lbl)

        self._busy_detail_lbl = QLabel("")
        self._busy_detail_lbl.setFont(QFont("Segoe UI", 10))
        self._busy_detail_lbl.setStyleSheet(ss_dim_label())
        self._busy_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._busy_detail_lbl)

        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.setStyleSheet(ss_progressbar())
        card_layout.addWidget(self._busy_bar)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(card)
        row.addStretch()
        overlay_layout.addLayout(row)
        overlay_layout.addStretch()
        self._busy_overlay.setGeometry(self.rect())

    def _toggle_sidebar(self):
        self._sidebar_visible = not self._sidebar_visible
        if hasattr(self, "_sidebar"):
            self._sidebar.setVisible(self._sidebar_visible)
        if hasattr(self, "_sidebar_divider"):
            self._sidebar_divider.setVisible(self._sidebar_visible)
        if hasattr(self, "_btn_toggle_sidebar"):
            tooltip_key = "ui_lipsync_hide_clips" if self._sidebar_visible else "ui_lipsync_show_clips"
            icon_name = "fa6s.chevron-left" if self._sidebar_visible else "fa6s.chevron-right"
            self._btn_toggle_sidebar.setToolTip(ui_text(tooltip_key))
            self._btn_toggle_sidebar.setIcon(_themed_icon(icon_name, color=P.get("button_text", P["text_main"]), size=12))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_busy_overlay"):
            self._busy_overlay.setGeometry(self.rect())

    def _set_busy(self, active: bool, title: str = "", detail: str = ""):
        if not hasattr(self, "_busy_overlay"):
            return
        if active:
            self._busy_count += 1
            self._busy_title_lbl.setText(title or ui_text("loading"))
            self._busy_detail_lbl.setText(detail or "")
            self._busy_bar.setRange(0, 0)
            self._busy_overlay.setGeometry(self.rect())
            self._busy_overlay.raise_()
            self._busy_overlay.show()
            return
        self._busy_count = max(0, self._busy_count - 1)
        if self._busy_count == 0:
            self._busy_overlay.hide()

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_lipsync_open_title"),
            game_files_dialog_dir(target_patterns="*_lip.xfbin"),
            ui_text("ui_lipsync_file_filter"),
        )
        if path:
            self._load_file(path)

    def load_file(self, path: str):
        self._load_file(path)

    def _load_file(self, path: str):
        self._stop_playback(clear_playhead=True)
        self._cleanup_audio_previews()
        self._clear_audio_container_state()
        create_backup_on_open(path)
        try:
            xfbin, clips = load_lipsync_xfbin(path)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=exc))
            return

        self._filepath = path
        self._xfbin = xfbin
        self._clips = clips
        self._capture_clip_snapshots()
        self._selected_clip_idx = -1
        self._selected_key_idx = -1
        self._dirty = False

        set_file_label(self._file_lbl, path)
        self._btn_save.setEnabled(True)
        self._btn_load_audio_container.setEnabled(True)
        self._btn_add_clip.setEnabled(True)
        self._btn_dup_clip.setEnabled(True)
        self._btn_del_clip.setEnabled(len(self._clips) > 1)
        self._placeholder.setVisible(False)
        self._editor_scroll.setVisible(True)
        self._rebuild_clip_list()
        self._select_clip(0)

    def _save_file(self):
        if not self._filepath or self._xfbin is None:
            return
        try:
            save_lipsync_xfbin(self._xfbin, self._filepath, self._clips)
        except Exception as exc:
            QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_save_error", error=exc))
            return
        self._dirty = False
        self._capture_clip_snapshots()
        set_file_label(self._file_lbl, self._filepath)
        QMessageBox.information(self, ui_text("dlg_title_success"), ui_text("msg_save_success", path=self._filepath))

    def _clear_awb_state(self):
        self._awb_path = None
        self._awb_raw = None
        self._awb_entries = []
        self._awb_entry_labels = {}
        self._awb_clip_entry_indices = {}
        self._awb_clip_sources = {}
        self._awb_failed_audio_keys = set()
        self._awb_decoding_audio_keys = set()

    def _clear_pl_state(self):
        self._pl_path = None
        self._pl_raw = None
        self._pl_banks = []
        self._pl_tone_refs = []
        self._pl_clip_tone_refs = {}
        self._pl_clip_sources = {}
        self._pl_failed_audio_keys = set()
        self._pl_decoding_audio_keys = set()

    def _clear_audio_container_state(self):
        self._clear_awb_state()
        self._clear_pl_state()

    def _load_audio_container_file(self):
        if not self._clips:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_lipsync_open_audio_container_title"),
            game_files_dialog_dir(target_patterns=("*.awb", "*_pl.xtbin")),
            ui_text("ui_lipsync_audio_container_file_filter"),
        )
        if not path:
            return
        if os.path.splitext(path)[1].lower() == ".xfbin":
            QMessageBox.warning(self, ui_text("dlg_title_error"), ui_text("ui_lipsync_xfbin_audio_disabled"))
            return
        if os.path.splitext(path)[1].lower() == ".awb":
            self._start_awb_load(path)
            return
        self._start_pl_load(path)

    def _start_awb_load(self, path: str):
        self._set_busy(True, ui_text("ui_lipsync_loading_awb"), os.path.basename(path))
        self._btn_load_audio_container.setEnabled(False)

        def worker():
            try:
                raw, entries, _meta = parse_awb(path)
                try:
                    labels, _acb_path = load_companion_acb_labels(path)
                except Exception:
                    labels = {}
                self._sig_awb_load_done.emit(path, raw, entries, dict(labels or {}))
            except Exception as exc:
                self._sig_awb_load_error.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _start_pl_load(self, path: str):
        self._set_busy(True, ui_text("ui_lipsync_loading_pl_audio"), os.path.basename(path))
        self._btn_load_audio_container.setEnabled(False)

        def worker():
            try:
                raw, banks = parse_xfbin_audio(path)
                self._sig_pl_load_done.emit(path, raw, banks)
            except Exception as exc:
                self._sig_pl_load_error.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_awb_load_done(self, path: str, raw, entries: list, labels: dict):
        self._set_busy(False)
        self._btn_load_audio_container.setEnabled(bool(self._clips))
        matched_sources = self._match_awb_entries_to_clips(raw, entries, labels)
        if matched_sources:
            self._stop_playback(clear_playhead=True)
            self._awb_path = path
            self._awb_raw = raw
            self._awb_entries = entries
            self._awb_entry_labels = dict(labels or {})
            for audio_key, source in matched_sources.items():
                if audio_key not in self._pl_clip_sources:
                    self._remove_audio_preview_by_key(audio_key)
                self._awb_clip_sources[audio_key] = source
                self._awb_clip_entry_indices[audio_key] = entries.index(source[1])
                self._awb_failed_audio_keys.discard(audio_key)
        self._rebuild_clip_list()
        self._select_clip(self._selected_clip_idx if self._selected_clip_idx >= 0 else 0)
        matched = len(matched_sources)
        QMessageBox.information(
            self,
            ui_text("ui_lipsync_awb_loaded_title"),
            ui_text("ui_lipsync_awb_loaded", matched=matched, total=len(self._clips)),
        )

    def _on_awb_load_error(self, msg: str):
        self._set_busy(False)
        self._btn_load_audio_container.setEnabled(bool(self._clips))
        QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=msg))

    def _on_pl_load_done(self, path: str, raw, banks: list):
        self._set_busy(False)
        self._btn_load_audio_container.setEnabled(bool(self._clips))
        tone_refs = [
            (bank_idx, tone_idx, tone)
            for bank_idx, bank in enumerate(banks)
            for tone_idx, tone in enumerate(getattr(bank, "tones", []) or [])
        ]
        matched_sources = self._match_pl_tones_to_clips(banks, tone_refs)
        if matched_sources:
            self._stop_playback(clear_playhead=True)
            self._pl_path = path
            self._pl_raw = raw
            self._pl_banks = banks
            self._pl_tone_refs = tone_refs
            for audio_key, source in matched_sources.items():
                self._remove_audio_preview_by_key(audio_key)
                self._pl_clip_sources[audio_key] = source
                self._pl_clip_tone_refs[audio_key] = self._find_pl_tone_ref_index(source[0], tone_refs)
                self._pl_failed_audio_keys.discard(audio_key)
        self._rebuild_clip_list()
        self._select_clip(self._selected_clip_idx if self._selected_clip_idx >= 0 else 0)
        matched = len(matched_sources)
        QMessageBox.information(
            self,
            ui_text("ui_lipsync_audio_container_loaded_title"),
            ui_text("ui_lipsync_audio_container_loaded", matched=matched, total=len(self._clips)),
        )

    def _on_pl_load_error(self, msg: str):
        self._set_busy(False)
        self._btn_load_audio_container.setEnabled(bool(self._clips))
        QMessageBox.critical(self, ui_text("dlg_title_error"), ui_text("msg_load_error", error=msg))

    def _awb_entry_label(self, entry: dict) -> str:
        return self._awb_entry_label_from(self._awb_entry_labels, entry)

    def _awb_entry_label_from(self, labels: dict, entry: dict) -> str:
        return labels.get(entry.get("id")) or get_entry_label(entry.get("id", 0))

    def _clip_match_candidates(self, clip) -> set[str]:
        values = {clip.name, clip.file_path, os.path.basename(clip.file_path or "")}
        candidates = {_norm_match_text(value) for value in values if value}
        return {value for value in candidates if value}

    def _entry_match_candidates(self, idx: int, entry: dict, labels: dict | None = None) -> set[str]:
        label = self._awb_entry_label_from(labels if labels is not None else self._awb_entry_labels, entry)
        values = {label}
        for sep in (",", ";", "|"):
            values.update(part.strip() for part in label.split(sep))
        candidates = {_norm_match_text(value) for value in values if value}
        return {value for value in candidates if value}

    def _match_awb_entries_to_clips(self, raw=None, entries=None, labels=None) -> dict[int, tuple[object, dict, str]]:
        raw = self._awb_raw if raw is None else raw
        entries = self._awb_entries if entries is None else entries
        labels = self._awb_entry_labels if labels is None else labels
        mapping: dict[int, tuple[object, dict, str]] = {}
        used_entries: set[int] = set()
        entry_candidates = [
            self._entry_match_candidates(idx, entry, labels)
            for idx, entry in enumerate(entries)
        ]

        for clip in self._clips:
            audio_key = self._clip_audio_key(clip)
            if audio_key is None:
                continue
            clip_candidates = self._clip_match_candidates(clip)
            best_idx = None
            for idx, candidates in enumerate(entry_candidates):
                if idx in used_entries:
                    continue
                if clip_candidates & candidates:
                    best_idx = idx
                    break
            if best_idx is not None:
                mapping[audio_key] = (raw, entries[best_idx], self._awb_entry_label_from(labels, entries[best_idx]))
                used_entries.add(best_idx)
        return mapping

    def _pl_tone_label(self, ref: tuple[int, int, object]) -> str:
        bank_idx, tone_idx, tone = ref
        bank_name = getattr(self._pl_banks[bank_idx], "name", "") if 0 <= bank_idx < len(self._pl_banks) else ""
        tone_name = getattr(tone, "name", "") or f"tone_{tone_idx}"
        return f"{bank_name} {tone_name}".strip()

    def _tone_match_candidates(self, flat_idx: int, ref: tuple[int, int, object]) -> set[str]:
        bank_idx, tone_idx, tone = ref
        tone_name = getattr(tone, "name", "")
        values = {tone_name, self._pl_tone_label(ref)}
        candidates = {_norm_match_text(value) for value in values if value}
        return {value for value in candidates if value}

    def _find_pl_tone_ref_index(self, tone, tone_refs: list[tuple[int, int, object]] | None = None) -> tuple[int, int]:
        tone_refs = self._pl_tone_refs if tone_refs is None else tone_refs
        for bank_idx, tone_idx, candidate in tone_refs:
            if candidate is tone:
                return bank_idx, tone_idx
        return (-1, -1)

    def _match_pl_tones_to_clips(
        self,
        banks: list | None = None,
        tone_refs: list[tuple[int, int, object]] | None = None,
    ) -> dict[int, tuple[object, str]]:
        old_banks = self._pl_banks
        if banks is not None:
            self._pl_banks = banks
        tone_refs = self._pl_tone_refs if tone_refs is None else tone_refs
        mapping: dict[int, tuple[object, str]] = {}
        used_tones: set[int] = set()
        tone_candidates = [
            self._tone_match_candidates(idx, ref)
            for idx, ref in enumerate(tone_refs)
        ]

        for clip in self._clips:
            audio_key = self._clip_audio_key(clip)
            if audio_key is None:
                continue
            clip_candidates = self._clip_match_candidates(clip)
            best_idx = None
            for idx, candidates in enumerate(tone_candidates):
                if idx in used_tones:
                    continue
                if clip_candidates & candidates:
                    best_idx = idx
                    break
            if best_idx is not None:
                mapping[audio_key] = (tone_refs[best_idx][2], self._pl_tone_label(tone_refs[best_idx]))
                used_tones.add(best_idx)
        if banks is not None:
            self._pl_banks = old_banks
        return mapping

    def _capture_clip_snapshots(self):
        self._clip_snapshots = {
            id(clip.chunk): {
                "name": clip.name,
                "file_path": clip.file_path,
                "keys": copy.deepcopy(clip.keys),
            }
            for clip in self._clips
        }

    def _rebuild_clip_list(self):
        _clear_layout(self._clip_layout)
        self._clip_buttons = []
        for idx, clip in enumerate(self._clips):
            btn = QPushButton()
            btn.setFixedHeight(52)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(ss_sidebar_btn(selected=(idx == self._selected_clip_idx)))
            layout = QVBoxLayout(btn)
            layout.setContentsMargins(10, 4, 10, 4)
            layout.setSpacing(0)

            title = QLabel(clip.name or ui_text("ui_lipsync_unnamed_clip"))
            title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
            title.setStyleSheet(ss_main_label())
            title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(title)

            subtitle = QLabel(ui_text("ui_lipsync_clip_subtitle", keys=len(clip.keys), duration=clip.duration))
            subtitle.setFont(QFont("Consolas", 9))
            subtitle.setStyleSheet(ss_dim_label())
            subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(subtitle)

            btn.clicked.connect(lambda checked=False, clip_idx=idx: self._select_clip(clip_idx))
            self._clip_layout.addWidget(btn)
            self._clip_buttons.append((btn, idx, title, subtitle))
        self._clip_layout.addStretch()
        self._filter_clips()

    def _filter_clips(self):
        query = self._search.text().lower()
        for btn, idx, _title, _subtitle in self._clip_buttons:
            if idx >= len(self._clips):
                continue
            clip = self._clips[idx]
            haystack = f"{clip.name} {clip.file_path}".lower()
            btn.setVisible(not query or query in haystack)

    def _select_clip(self, idx: int):
        if idx < 0 or idx >= len(self._clips):
            return
        self._stop_playback(clear_playhead=True)
        self._selected_clip_idx = idx
        self._selected_key_idx = 0 if self._clips[idx].keys else -1
        for btn, btn_idx, _title, _subtitle in self._clip_buttons:
            btn.setStyleSheet(ss_sidebar_btn(selected=(btn_idx == idx)))
        self._btn_del_clip.setEnabled(len(self._clips) > 1)
        self._build_clip_editor()

    def _current_clip(self):
        if 0 <= self._selected_clip_idx < len(self._clips):
            return self._clips[self._selected_clip_idx]
        return None

    def _clip_audio_key(self, clip=None) -> int | None:
        clip = clip or self._current_clip()
        if clip is None:
            return None
        return id(clip.chunk)

    def _current_audio_preview_path(self) -> str:
        key = self._clip_audio_key()
        if key is None:
            return ""
        path = self._audio_preview_paths.get(key, "")
        return path if path and os.path.isfile(path) else ""

    def _current_audio_waveform(self) -> list[float]:
        key = self._clip_audio_key()
        if key is None:
            return []
        return self._audio_waveforms.get(key, [])

    def _audio_preview_duration(self, clip=None) -> float:
        key = self._clip_audio_key(clip)
        if key is None:
            return 0.0
        return max(0.0, float(self._audio_preview_durations.get(key, 0.0)))

    def _ensure_audio_player(self):
        if self._audio_player is None:
            self._audio_output = QAudioOutput(self)
            self._audio_player = QMediaPlayer(self)
            self._audio_player.setAudioOutput(self._audio_output)
            self._audio_player.mediaStatusChanged.connect(self._audio_media_status_changed)
        return self._audio_player

    def _audio_media_status_changed(self, status):
        if self._playing and status == QMediaPlayer.MediaStatus.EndOfMedia:
            clip = self._current_clip()
            self._finish_playback_at_end(self._playback_duration(clip))

    def _cleanup_audio_previews(self):
        if getattr(self, "_audio_player", None) is not None:
            self._audio_player.stop()
            self._audio_player.setSource(QUrl())
            QCoreApplication.processEvents()
        for path in list(getattr(self, "_audio_preview_paths", {}).values()):
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        self._audio_preview_paths = {}
        self._audio_preview_durations = {}
        self._audio_waveforms = {}

    def _remove_audio_preview(self, clip):
        key = self._clip_audio_key(clip)
        if key is None:
            return
        self._remove_audio_preview_by_key(key)

    def _remove_audio_preview_by_key(self, key: int):
        was_current = key == self._clip_audio_key()
        path = self._audio_preview_paths.pop(key, "")
        self._audio_preview_durations.pop(key, None)
        self._audio_waveforms.pop(key, None)
        if path:
            if was_current and self._audio_player is not None:
                self._audio_player.stop()
                self._audio_player.setSource(QUrl())
                QCoreApplication.processEvents()
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        self._sync_audio_controls()

    def _cache_waveform_for_preview(self, audio_key: int, preview_path: str, samples: list[float] | None = None):
        try:
            if samples is not None:
                self._audio_waveforms[audio_key] = _waveform_peaks_from_samples(samples)
            elif preview_path and os.path.isfile(preview_path):
                self._audio_waveforms[audio_key] = _waveform_peaks_from_wav_path(preview_path)
            else:
                self._audio_waveforms.pop(audio_key, None)
        except Exception:
            self._audio_waveforms.pop(audio_key, None)

    def _build_clip_editor(self):
        _clear_layout(self._editor_layout)
        self._table = None
        clip = self._current_clip()
        if clip is None:
            self._placeholder.setVisible(True)
            self._editor_scroll.setVisible(False)
            return

        preview_card = _card()
        preview_card.setFixedWidth(300)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(12, 10, 12, 8)
        preview_layout.setSpacing(4)
        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 0, 0, 0)
        preview_header.setSpacing(4)
        preview_header.addWidget(_panel_title(ui_text("ui_lipsync_mouth_preview")))
        preview_header.addStretch()
        self._btn_mouth_preview_menu = QPushButton()
        self._btn_mouth_preview_menu.setFixedSize(28, 24)
        self._btn_mouth_preview_menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_mouth_preview_menu.setToolTip(ui_text("ui_lipsync_mouth_preview_options"))
        self._btn_mouth_preview_menu.setIcon(_themed_icon("fa6s.ellipsis", color=P.get("button_text", P["text_main"]), size=13))
        self._btn_mouth_preview_menu.setIconSize(QSize(15, 15))
        self._btn_mouth_preview_menu.setStyleSheet(ss_panel_menu_button())
        self._mouth_preview_menu = QMenu(self._btn_mouth_preview_menu)
        self._mouth_preview_menu.setStyleSheet(ss_menu())
        self._act_mouth_animation = QAction(ui_text("ui_lipsync_animate_mouth_preview"), self)
        self._act_mouth_animation.setCheckable(True)
        self._act_mouth_animation.setChecked(self._mouth_animation_enabled)
        self._act_mouth_animation.toggled.connect(self._set_mouth_animation_enabled)
        self._mouth_preview_menu.addAction(self._act_mouth_animation)
        self._btn_mouth_preview_menu.setMenu(self._mouth_preview_menu)
        self._btn_mouth_preview_menu.clicked.connect(lambda: self._mouth_preview_menu.popup(self._btn_mouth_preview_menu.mapToGlobal(self._btn_mouth_preview_menu.rect().bottomRight())))
        preview_header.addWidget(self._btn_mouth_preview_menu)
        preview_layout.addLayout(preview_header)
        self._mouth_preview = LipMouthPreviewWidget()
        self._mouth_preview.setFixedSize(260, 138)
        preview_layout.addWidget(self._mouth_preview, 0, Qt.AlignmentFlag.AlignHCenter)
        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(0, 10, 0, 12)
        preview_row.addStretch()
        preview_row.addWidget(preview_card)
        preview_row.addStretch()
        self._editor_layout.addLayout(preview_row)

        work_row = QHBoxLayout()
        work_row.setContentsMargins(8, 0, 8, 0)
        work_row.setSpacing(8)

        instruments_card = _card()
        instruments_card.setFixedWidth(150)
        instruments_layout = QVBoxLayout(instruments_card)
        instruments_layout.setContentsMargins(12, 12, 12, 12)
        instruments_layout.setSpacing(12)
        instruments_layout.addWidget(_panel_title(ui_text("ui_lipsync_instruments")))
        tool_grid = QGridLayout()
        tool_grid.setContentsMargins(0, 0, 0, 0)
        tool_grid.setHorizontalSpacing(8)
        tool_grid.setVerticalSpacing(8)
        self._btn_cursor_tool = self._make_tool_button(ui_text("ui_lipsync_tool_cursor"), "cursor")
        self._btn_move_tool = self._make_static_tool_button(ui_text("ui_lipsync_tool_move"), "fa6s.arrows-up-down-left-right")
        self._btn_blade_tool = self._make_tool_button(ui_text("ui_lipsync_tool_blade"), "blade")
        self._btn_snap = QPushButton()
        self._btn_snap.setCheckable(True)
        self._btn_snap.setChecked(self._timeline_snap_enabled)
        self._btn_snap.setFixedSize(54, 48)
        self._btn_snap.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn_snap.setToolTip(ui_text("ui_lipsync_snap"))
        self._btn_snap.setIcon(_themed_icon("fa6s.magnet", color=P.get("button_text", P["text_main"]), size=16))
        self._btn_snap.setIconSize(QSize(18, 18))
        self._btn_snap.setStyleSheet(ss_icon_tool_btn())
        self._btn_snap.clicked.connect(self._toggle_snap)
        tool_grid.addWidget(self._btn_cursor_tool, 0, 0)
        tool_grid.addWidget(self._btn_move_tool, 0, 1)
        tool_grid.addWidget(self._btn_blade_tool, 1, 0)
        tool_grid.addWidget(self._btn_snap, 1, 1)
        instruments_layout.addLayout(tool_grid)
        instruments_layout.addStretch()
        work_row.addWidget(instruments_card)

        timeline_card = _card()
        timeline_layout = QVBoxLayout(timeline_card)
        timeline_layout.setContentsMargins(14, 12, 14, 10)
        timeline_layout.setSpacing(10)
        timeline_header = QHBoxLayout()
        timeline_header.setContentsMargins(0, 0, 0, 0)
        timeline_header.setSpacing(4)
        timeline_header.addWidget(_panel_title(ui_text("ui_lipsync_phoneme_timeline")))
        timeline_header.addStretch()
        self._btn_undo = self._make_icon_button(ui_text("ui_lipsync_undo"), "fa6s.rotate-left", self._undo_timeline)
        self._btn_redo = self._make_icon_button(ui_text("ui_lipsync_redo"), "fa6s.rotate-right", self._redo_timeline)
        self._btn_copy_segment = self._make_icon_button(ui_text("ui_lipsync_copy_segment"), "fa6s.copy", self._copy_selected_segment)
        self._btn_delete_segment = self._make_icon_button(ui_text("ui_lipsync_delete_segment"), "fa6s.trash", self._delete_key, danger=True)
        self._btn_reset_clip_timeline = self._make_icon_button(ui_text("ui_lipsync_reset_clip"), "fa6s.arrows-rotate", self._reset_current_clip)
        self._btn_reset_clip_timeline.setEnabled(False)
        self._zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self._zoom_slider.setRange(0, 100)
        self._zoom_slider.setFixedWidth(92)
        self._zoom_slider.setFixedHeight(28)
        self._zoom_slider.setToolTip(ui_text("ui_lipsync_zoom_fit"))
        self._zoom_slider.setStyleSheet(ss_slider())
        self._zoom_slider.valueChanged.connect(self._set_timeline_zoom_from_slider)
        zoom_out_lbl = QLabel("-")
        zoom_out_lbl.setStyleSheet(ss_dim_label())
        zoom_out_lbl.setFixedWidth(10)
        zoom_out_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zoom_in_lbl = QLabel("+")
        zoom_in_lbl.setStyleSheet(ss_dim_label())
        zoom_in_lbl.setFixedWidth(10)
        zoom_in_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_view_fit = self._make_icon_button(ui_text("ui_lipsync_view_fit"), "fa6s.expand", self._fit_timeline)
        timeline_header.addWidget(self._btn_undo)
        timeline_header.addWidget(self._btn_redo)
        timeline_header.addWidget(self._btn_copy_segment)
        timeline_header.addWidget(self._btn_delete_segment)
        timeline_header.addWidget(self._btn_reset_clip_timeline)
        timeline_header.addSpacing(8)
        timeline_header.addWidget(zoom_out_lbl)
        timeline_header.addWidget(self._zoom_slider)
        timeline_header.addWidget(zoom_in_lbl)
        timeline_header.addWidget(self._btn_view_fit)
        timeline_layout.addLayout(timeline_header)
        self._timeline = LipTimelineWidget()
        self._timeline.set_duration_override(self._playback_duration(clip) if self._audio_preview_duration(clip) > 0 else None)
        self._timeline.set_keys(clip.keys, self._selected_key_idx)
        self._timeline.set_waveform(self._current_audio_waveform(), self._audio_preview_duration(clip))
        self._timeline.set_tool_mode(self._timeline_tool_mode)
        self._timeline.set_snap_enabled(self._timeline_snap_enabled)
        self._timeline.set_locked_indices(self._locked_indices_for_clip(clip))
        self._timeline.keySelected.connect(self._select_key)
        self._timeline.keyMoved.connect(self._move_key_from_timeline)
        self._timeline.playheadScrubbed.connect(self._scrub_playback_from_timeline)
        self._timeline.segmentSplitRequested.connect(self._split_segment_from_timeline)
        self._timeline.lockToggleRequested.connect(self._toggle_segment_lock)
        self._timeline.editStarted.connect(self._push_undo_for_current_clip)
        self._timeline.viewRangeChanged.connect(self._sync_overview_from_timeline)
        timeline_layout.addWidget(self._timeline, 1)
        self._sync_zoom_slider_from_timeline()
        work_row.addWidget(timeline_card, 1)

        phonemes_card = _card()
        phonemes_card.setFixedWidth(150)
        phonemes_layout = QVBoxLayout(phonemes_card)
        phonemes_layout.setContentsMargins(12, 12, 12, 12)
        phonemes_layout.setSpacing(12)
        phonemes_layout.addWidget(_panel_title(ui_text("ui_lipsync_phonemes")))
        mouth_grid_widget = QWidget()
        mouth_grid_widget.setStyleSheet(ss_transparent())
        mouth_grid = QGridLayout(mouth_grid_widget)
        mouth_grid.setContentsMargins(0, 0, 0, 0)
        mouth_grid.setHorizontalSpacing(8)
        mouth_grid.setVerticalSpacing(8)
        for pos, token in enumerate(("PL_ANM_LIP_NO_A", "PL_ANM_LIP_NO_E", "PL_ANM_LIP_NO_I", "PL_ANM_LIP_NO_O", "PL_ANM_LIP_NO_U", "PL_ANM_LIP_NO_N")):
            mouth_grid.addWidget(self._make_mouth_add_button(token), pos // 2, pos % 2)
        phonemes_layout.addWidget(mouth_grid_widget, 0, Qt.AlignmentFlag.AlignTop)
        phonemes_layout.addStretch()
        work_row.addWidget(phonemes_card)
        self._editor_layout.addLayout(work_row)

        playback_card = _card()
        playback_card.setStyleSheet(ss_glass_panel())
        playback_layout = QVBoxLayout(playback_card)
        playback_layout.setContentsMargins(16, 10, 16, 10)
        playback_layout.setSpacing(8)
        playback_actions = QHBoxLayout()
        playback_actions.setContentsMargins(0, 0, 0, 0)
        playback_actions.setSpacing(4)
        playback_actions.addStretch()

        self._btn_jump_start = self._make_icon_button(ui_text("ui_lipsync_jump_start"), "fa6s.backward-step", lambda: self._set_playback_position(0.0))
        self._btn_step_back = self._make_icon_button(ui_text("ui_lipsync_step_back"), "fa6s.backward", lambda: self._nudge_playback(-0.1))
        self._btn_play = self._make_icon_button(ui_text("ui_lipsync_play"), "fa6s.play", self._play_playback)
        self._btn_pause = self._make_icon_button(ui_text("ui_lipsync_pause"), "fa6s.pause", self._pause_playback)
        self._btn_stop = self._make_icon_button(ui_text("ui_lipsync_stop"), "fa6s.stop", lambda: self._stop_playback(clear_playhead=True))
        self._btn_step_forward = self._make_icon_button(ui_text("ui_lipsync_step_forward"), "fa6s.forward", lambda: self._nudge_playback(0.1))
        self._btn_jump_end = self._make_icon_button(ui_text("ui_lipsync_jump_end"), "fa6s.forward-step", lambda: self._set_playback_position(self._playback_duration(self._current_clip())))
        playback_actions.addWidget(self._btn_jump_start)
        playback_actions.addWidget(self._btn_step_back)
        playback_actions.addWidget(self._btn_play)
        playback_actions.addWidget(self._btn_pause)
        playback_actions.addWidget(self._btn_stop)
        playback_actions.addWidget(self._btn_step_forward)
        playback_actions.addWidget(self._btn_jump_end)

        self._play_time_lbl = QLabel(ui_text("ui_lipsync_time_readout", time=0.0, duration=self._playback_duration(clip)))
        self._play_time_lbl.setFont(QFont("Consolas", 10))
        self._play_time_lbl.setStyleSheet(ss_dim_label())
        self._play_time_lbl.setMinimumWidth(150)
        self._play_time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        playback_actions.addWidget(self._play_time_lbl)

        self._playback_speed_combo = QComboBox()
        self._playback_speed_combo.setFixedHeight(28)
        self._playback_speed_combo.setStyleSheet(ss_input())
        for value in ("0.5x", "0.75x", "1.0x", "1.25x", "1.5x"):
            self._playback_speed_combo.addItem(value)
        self._playback_speed_combo.setCurrentText("1.0x")
        self._playback_speed_combo.currentTextChanged.connect(self._set_playback_speed_text)
        playback_actions.addWidget(self._playback_speed_combo)

        self._btn_loop = self._make_icon_button(ui_text("ui_lipsync_loop"), "fa6s.rotate", self._toggle_loop)
        self._btn_loop.setCheckable(True)
        playback_actions.addWidget(self._btn_loop)

        self._btn_mute_audio = QPushButton()
        self._btn_mute_audio.setFixedHeight(28)
        self._btn_mute_audio.setFont(QFont("Segoe UI", 10))
        self._btn_mute_audio.setStyleSheet(ss_btn())
        self._btn_mute_audio.clicked.connect(self._toggle_audio_mute)
        playback_actions.addWidget(self._btn_mute_audio)
        playback_actions.addStretch()
        playback_layout.addLayout(playback_actions)

        overview_actions = QHBoxLayout()
        overview_actions.setContentsMargins(0, 0, 0, 0)
        overview_actions.setSpacing(6)
        overview_actions.addWidget(self._make_icon_button(ui_text("ui_lipsync_scroll_left"), "fa6s.chevron-left", lambda: self._shift_timeline(-1.0)))
        self._timeline_overview = LipTimelineOverviewWidget()
        self._timeline_overview.viewRangeChanged.connect(self._set_timeline_view_from_overview)
        overview_actions.addWidget(self._timeline_overview, 1)
        overview_actions.addWidget(self._make_icon_button(ui_text("ui_lipsync_scroll_right"), "fa6s.chevron-right", lambda: self._shift_timeline(1.0)))
        playback_layout.addLayout(overview_actions)

        playback_row = QHBoxLayout()
        playback_row.setContentsMargins(8, 8, 8, 8)
        playback_row.addWidget(playback_card)
        self._editor_layout.addLayout(playback_row)

        meta = _card()
        meta_outer = QVBoxLayout(meta)
        meta_outer.setContentsMargins(12, 12, 12, 12)
        meta_outer.setSpacing(8)
        add_editor_card_title(meta_outer, ui_text("ui_lipsync_clip_metadata"), "fa6s.file-lines")
        meta_inner = QWidget(meta)
        meta_inner.setStyleSheet(ss_transparent())
        meta_layout = QGridLayout(meta_inner)
        meta_layout.setContentsMargins(0, 4, 0, 0)
        meta_layout.setHorizontalSpacing(12)
        meta_layout.setVerticalSpacing(8)

        self._clip_name_edit = self._make_line(meta, ui_text("ui_lipsync_clip_name"), clip.name)
        self._clip_path_edit = self._make_line(meta, ui_text("ui_lipsync_chunk_path"), clip.file_path)
        meta_layout.addWidget(self._clip_name_edit[0], 0, 0)
        meta_layout.addWidget(self._clip_path_edit[0], 0, 1)
        meta_layout.setColumnStretch(0, 1)
        meta_layout.setColumnStretch(1, 2)
        meta_outer.addWidget(meta_inner)

        self._clip_name_edit[1].editingFinished.connect(self._commit_clip_metadata)
        self._clip_path_edit[1].editingFinished.connect(self._commit_clip_metadata)
        self._editor_layout.addWidget(meta)

        self._refresh_timeline()
        self._update_preview_for_selected_key()
        self._sync_timeline_tool_buttons()
        self._sync_playback_buttons()
        for _container, edit in (self._clip_name_edit, self._clip_path_edit):
            edit.deselect()
            edit.clearFocus()
        self._timeline.setFocus(Qt.FocusReason.OtherFocusReason)
        self._editor_layout.addStretch()

    def _make_tool_button(self, text: str, mode: str) -> QPushButton:
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setFixedSize(54, 48)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(text)
        btn.setIcon(_themed_icon(
            "fa6s.arrow-pointer" if mode == "cursor" else "fa6s.scissors",
            color=P.get("button_text", P["text_main"]),
            size=16,
        ))
        btn.setIconSize(QSize(19, 19))
        btn.setStyleSheet(ss_icon_tool_btn())
        btn.clicked.connect(lambda checked=False, m=mode: self._set_timeline_tool(m))
        return btn

    def _make_static_tool_button(self, text: str, icon_name: str) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(54, 48)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(text)
        btn.setIcon(_themed_icon(icon_name, color=P.get("button_text", P["text_main"]), size=16))
        btn.setIconSize(QSize(19, 19))
        btn.setStyleSheet(ss_icon_tool_btn())
        btn.setEnabled(False)
        return btn

    def _make_icon_button(self, tooltip: str, icon_name: str, callback, *, danger: bool = False) -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(34, 28)
        btn.setToolTip(tooltip)
        btn.setIcon(_themed_icon(icon_name, color=P.get("button_text", P["text_main"]), size=16))
        btn.setIconSize(QSize(17, 17))
        btn.setStyleSheet(ss_btn(danger=danger))
        btn.clicked.connect(callback)
        return btn

    def _make_mouth_add_button(self, token: str) -> QPushButton:
        suffix = token.rsplit("_", 1)[-1] if "_" in token else token
        btn = QPushButton(suffix)
        btn.setFixedSize(54, 56)
        btn.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        btn.setStyleSheet(ss_btn(accent=(suffix != "N")))
        btn.setToolTip(ui_text("ui_lipsync_add_mouth_segment", token=suffix))
        btn.clicked.connect(lambda checked=False, t=token: self._add_segment_token(t))
        return btn

    def _set_timeline_tool(self, mode: str):
        self._timeline_tool_mode = "blade" if mode == "blade" else "cursor"
        if hasattr(self, "_timeline"):
            self._timeline.set_tool_mode(self._timeline_tool_mode)
        self._sync_timeline_tool_buttons()

    def _zoom_timeline(self, factor: float):
        if hasattr(self, "_timeline"):
            self._timeline.zoom_view(factor)

    def _sync_zoom_slider_from_timeline(self):
        if not hasattr(self, "_timeline") or not hasattr(self, "_zoom_slider"):
            return
        self._zoom_slider.blockSignals(True)
        self._zoom_slider.setValue(int(round(self._timeline.zoom_normalized() * 100)))
        self._zoom_slider.blockSignals(False)

    def _set_timeline_zoom_from_slider(self, value: int):
        if hasattr(self, "_timeline"):
            self._timeline.set_zoom_normalized(value / 100.0)

    def _fit_timeline(self):
        if hasattr(self, "_timeline"):
            self._timeline.fit_view()

    def _shift_timeline(self, direction: float):
        if hasattr(self, "_timeline"):
            self._timeline.shift_view(direction)

    def _set_timeline_view_from_overview(self, start: float, end: float):
        if hasattr(self, "_timeline"):
            self._timeline.set_view_range(start, end)
            self._sync_zoom_slider_from_timeline()

    def _sync_overview_from_timeline(self, _start: float | None = None, _end: float | None = None):
        if not hasattr(self, "_timeline") or not hasattr(self, "_timeline_overview"):
            return
        clip = self._current_clip()
        if clip is None:
            return
        view_start, view_end = self._timeline.view_range()
        self._timeline_overview.set_data(clip.keys, self._timeline.timeline_duration(), view_start, view_end)
        self._sync_zoom_slider_from_timeline()

    def _sync_timeline_tool_buttons(self):
        if hasattr(self, "_btn_cursor_tool"):
            self._btn_cursor_tool.setChecked(self._timeline_tool_mode == "cursor")
        if hasattr(self, "_btn_blade_tool"):
            self._btn_blade_tool.setChecked(self._timeline_tool_mode == "blade")
        if hasattr(self, "_btn_snap"):
            self._btn_snap.setChecked(self._timeline_snap_enabled)
        if hasattr(self, "_btn_undo"):
            key = self._clip_audio_key()
            self._btn_undo.setEnabled(bool(key is not None and self._undo_stack.get(key)))
        if hasattr(self, "_btn_redo"):
            key = self._clip_audio_key()
            self._btn_redo.setEnabled(bool(key is not None and self._redo_stack.get(key)))
        has_selection = self._selected_key_idx >= 0
        if hasattr(self, "_btn_copy_segment"):
            self._btn_copy_segment.setEnabled(has_selection)
        if hasattr(self, "_btn_delete_segment"):
            self._btn_delete_segment.setEnabled(has_selection)
        if hasattr(self, "_btn_reset_clip_timeline"):
            self._btn_reset_clip_timeline.setEnabled(self._current_clip() is not None)

    def _toggle_snap(self):
        self._timeline_snap_enabled = not self._timeline_snap_enabled
        if hasattr(self, "_timeline"):
            self._timeline.set_snap_enabled(self._timeline_snap_enabled)
        self._sync_timeline_tool_buttons()

    def _set_mouth_animation_enabled(self, enabled: bool):
        self._mouth_animation_enabled = bool(enabled)
        if hasattr(self, "_act_mouth_animation") and self._act_mouth_animation.isChecked() != self._mouth_animation_enabled:
            self._act_mouth_animation.blockSignals(True)
            self._act_mouth_animation.setChecked(self._mouth_animation_enabled)
            self._act_mouth_animation.blockSignals(False)
        if self._current_clip() is not None:
            self._set_playback_position(self._play_time)

    def _locked_indices_for_clip(self, clip=None) -> set[int]:
        key = self._clip_audio_key(clip)
        if key is None:
            return set()
        return set(self._locked_lip_keys.get(key, set()))

    def _set_locked_indices_for_clip(self, indices: set[int], clip=None):
        key = self._clip_audio_key(clip)
        if key is None:
            return
        self._locked_lip_keys[key] = {idx for idx in indices if idx >= 0}

    def _push_undo_for_current_clip(self):
        clip = self._current_clip()
        key = self._clip_audio_key(clip)
        if clip is None or key is None:
            return
        snapshot = copy.deepcopy(clip.keys)
        stack = self._undo_stack.setdefault(key, [])
        if stack and self._keys_equal(stack[-1], snapshot):
            return
        stack.append(snapshot)
        if len(stack) > 80:
            del stack[0]
        self._redo_stack.setdefault(key, []).clear()
        self._sync_timeline_tool_buttons()

    def _keys_equal(self, a: list[LipKey], b: list[LipKey]) -> bool:
        if len(a) != len(b):
            return False
        for left, right in zip(a, b):
            if (
                abs(float(left.time) - float(right.time)) > 0.0001
                or left.animation != right.animation
                or left.tag_a != right.tag_a
                or left.tag_b != right.tag_b
                or abs(float(left.value) - float(right.value)) > 0.0001
            ):
                return False
        return True

    def _restore_keys_for_current_clip(self, keys: list[LipKey]):
        clip = self._current_clip()
        if clip is None:
            return
        clip.keys = copy.deepcopy(keys)
        self._selected_key_idx = min(self._selected_key_idx, len(clip.keys) - 1)
        if self._selected_key_idx < 0 and clip.keys:
            self._selected_key_idx = 0
        self._refresh_timeline()
        self._update_preview_for_selected_key()
        self._update_clip_sidebar()
        self._mark_dirty()
        self._sync_timeline_tool_buttons()

    def _undo_timeline(self):
        clip = self._current_clip()
        key = self._clip_audio_key(clip)
        if clip is None or key is None:
            return
        stack = self._undo_stack.get(key, [])
        if not stack:
            return
        self._redo_stack.setdefault(key, []).append(copy.deepcopy(clip.keys))
        self._restore_keys_for_current_clip(stack.pop())

    def _redo_timeline(self):
        clip = self._current_clip()
        key = self._clip_audio_key(clip)
        if clip is None or key is None:
            return
        stack = self._redo_stack.get(key, [])
        if not stack:
            return
        self._undo_stack.setdefault(key, []).append(copy.deepcopy(clip.keys))
        self._restore_keys_for_current_clip(stack.pop())

    def shortcut_action(self, action_id: str) -> bool:
        if action_id == "editor.undo":
            self._undo_timeline()
            return True
        if action_id == "editor.redo":
            self._redo_timeline()
            return True
        return False

    def _make_line(self, parent, label_text: str, value: str):
        container = QWidget(parent)
        container.setStyleSheet(ss_transparent())
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        label = QLabel(label_text)
        label.setFont(QFont("Segoe UI", 11))
        label.setStyleSheet(ss_field_label())
        layout.addWidget(label)
        edit = QLineEdit(value)
        edit.setFixedHeight(30)
        edit.setFont(QFont("Consolas", 11))
        edit.setStyleSheet(ss_input())
        layout.addWidget(edit)
        return container, edit

    def _make_spin(self, value: float, row: int, field: str, decimals: int = 4) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(-999999.0, 999999.0)
        spin.setDecimals(decimals)
        spin.setSingleStep(0.01 if field == "time" else 1.0)
        spin.setKeyboardTracking(False)
        spin.setValue(float(value))
        spin.setStyleSheet(ss_input())
        spin.valueChanged.connect(lambda val, r=row, f=field: self._set_key_float(r, f, val))
        return spin

    def _make_combo(self, value: str, options: list[str], row: int, field: str, max_len: int) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setStyleSheet(ss_input())
        for option in options:
            combo.addItem(option)
        if value and combo.findText(value) < 0:
            combo.addItem(value)
        combo.setCurrentText(value)
        if combo.lineEdit() is not None:
            combo.lineEdit().setMaxLength(max_len)
        combo.currentTextChanged.connect(lambda text, r=row, f=field, m=max_len: self._set_key_text(r, f, text, m))
        return combo

    def _rebuild_table(self):
        clip = self._current_clip()
        if clip is None:
            return
        if getattr(self, "_table", None) is None:
            self._refresh_timeline()
            self._update_clip_sidebar()
            self._sync_timeline_tool_buttons()
            return
        self._rebuilding_table = True
        self._table.setRowCount(len(clip.keys))
        for row, key in enumerate(clip.keys):
            index_item = QTableWidgetItem(str(row))
            index_item.setFlags(index_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, index_item)
            self._table.setCellWidget(row, 1, self._make_spin(key.time, row, "time", 4))
            self._table.setCellWidget(row, 2, self._make_combo(
                key.animation,
                OBSERVED_ANIMATION_TOKENS,
                row,
                "animation",
                15,
            ))
            self._table.setCellWidget(row, 3, self._make_combo(key.tag_a, OBSERVED_TAG_TOKENS, row, "tag_a", 7))
            self._table.setCellWidget(row, 4, self._make_combo(key.tag_b, OBSERVED_TAG_TOKENS, row, "tag_b", 7))
            self._table.setCellWidget(row, 5, self._make_spin(key.value, row, "value", 3))
        self._rebuilding_table = False
        if 0 <= self._selected_key_idx < len(clip.keys):
            self._table.selectRow(self._selected_key_idx)
        self._refresh_timeline()
        self._update_clip_sidebar()

    def _commit_clip_metadata(self):
        clip = self._current_clip()
        if clip is None:
            return
        clip.name = self._clip_name_edit[1].text().strip() or ui_text("ui_lipsync_unnamed_clip")
        clip.file_path = self._clip_path_edit[1].text().strip()
        self._mark_dirty()
        self._rebuild_clip_list()
        self._select_clip(self._selected_clip_idx)

    def _set_key_float(self, row: int, field: str, value: float):
        if self._rebuilding_table:
            return
        clip = self._current_clip()
        if clip is None or row >= len(clip.keys):
            return
        setattr(clip.keys[row], field, float(value))
        self._selected_key_idx = row
        self._refresh_timeline()
        self._update_clip_sidebar()
        self._mark_dirty()

    def _set_key_text(self, row: int, field: str, text: str, max_len: int):
        if self._rebuilding_table:
            return
        clip = self._current_clip()
        if clip is None or row >= len(clip.keys):
            return
        setattr(clip.keys[row], field, _safe_ascii(text, max_len))
        self._selected_key_idx = row
        self._refresh_timeline()
        self._update_preview_for_selected_key()
        self._mark_dirty()

    def _refresh_timeline(self):
        clip = self._current_clip()
        if clip is None or not hasattr(self, "_timeline"):
            return
        self._timeline.set_duration_override(self._playback_duration(clip) if self._audio_preview_duration(clip) > 0 else None)
        self._timeline.set_keys(clip.keys, self._selected_key_idx)
        self._timeline.set_waveform(self._current_audio_waveform(), self._audio_preview_duration(clip))
        self._timeline.set_tool_mode(self._timeline_tool_mode)
        self._timeline.set_snap_enabled(self._timeline_snap_enabled)
        self._timeline.set_locked_indices(self._locked_indices_for_clip(clip))
        self._timeline.set_playhead_time(self._play_time)
        self._sync_timeline_tool_buttons()
        self._sync_overview_from_timeline()

    def _on_table_selection_changed(self):
        if getattr(self, "_table", None) is None:
            return
        if self._rebuilding_table:
            return
        rows = self._table.selectionModel().selectedRows() if self._table.selectionModel() else []
        if rows:
            self._selected_key_idx = rows[0].row()
            self._refresh_timeline()
            self._update_preview_for_selected_key()

    def _select_key(self, idx: int):
        clip = self._current_clip()
        if clip is None or idx < 0 or idx >= len(clip.keys):
            return
        self._selected_key_idx = idx
        if getattr(self, "_table", None) is not None:
            self._table.selectRow(idx)
        self._refresh_timeline()
        self._update_preview_for_selected_key()
        self._sync_timeline_tool_buttons()

    def _move_key_from_timeline(self, idx: int, time_value: float):
        clip = self._current_clip()
        if clip is None or idx < 0 or idx >= len(clip.keys):
            return
        clip.keys[idx].time = float(time_value)
        self._selected_key_idx = idx

        if getattr(self, "_table", None) is not None:
            time_spin = self._table.cellWidget(idx, 1)
            if isinstance(time_spin, QDoubleSpinBox):
                time_spin.blockSignals(True)
                time_spin.setValue(float(time_value))
                time_spin.blockSignals(False)

            if self._table.currentRow() != idx:
                self._table.blockSignals(True)
                self._table.selectRow(idx)
                self._table.blockSignals(False)

        self._update_clip_sidebar()
        self._mark_dirty()
        self._sync_timeline_tool_buttons()

    def _scrub_playback_from_timeline(self, time_value: float):
        clip = self._current_clip()
        if clip is None:
            return
        was_playing = self._playing
        self._set_playback_position(time_value)
        path = self._current_audio_preview_path()
        if path:
            player = self._ensure_audio_player()
            source = QUrl.fromLocalFile(path)
            if player.source() != source:
                player.setSource(source)
            player.setPosition(int(max(0.0, self._play_time) * 1000.0))
            if was_playing:
                player.play()
            else:
                player.pause()
        self._sync_playback_buttons()

    def _nudge_playback(self, delta: float):
        self._set_playback_position(self._play_time + float(delta))
        if self._audio_player is not None and self._current_audio_preview_path():
            self._audio_player.setPosition(int(max(0.0, self._play_time) * 1000.0))

    def _set_playback_speed_text(self, text: str):
        try:
            self._playback_speed = max(0.1, float(str(text).lower().replace("x", "").strip()))
        except ValueError:
            self._playback_speed = 1.0
        if self._audio_player is not None:
            self._audio_player.setPlaybackRate(self._playback_speed)

    def _toggle_loop(self):
        self._loop_playback = not self._loop_playback
        if hasattr(self, "_btn_loop"):
            self._btn_loop.setChecked(self._loop_playback)

    def _split_segment_from_timeline(self, idx: int, time_value: float):
        clip = self._current_clip()
        if clip is None or idx < 0 or idx >= len(clip.keys):
            return
        start, end = self._timeline._segment_time_range(idx) if hasattr(self, "_timeline") else (clip.keys[idx].time, self._playback_duration(clip))
        time_value = max(start + 0.001, min(end - 0.001, float(time_value)))
        if time_value <= start or time_value >= end:
            return
        new_key = copy.deepcopy(clip.keys[idx])
        new_key.time = time_value
        insert_at = idx + 1
        clip.keys.insert(insert_at, new_key)
        self._selected_key_idx = insert_at
        self._rebuild_table()
        self._mark_dirty()

    def _toggle_segment_lock(self, idx: int):
        clip = self._current_clip()
        if clip is None or idx < 0:
            return
        locked = self._locked_indices_for_clip(clip)
        if idx in locked:
            locked.remove(idx)
        else:
            locked.add(idx)
        self._set_locked_indices_for_clip(locked, clip)
        self._refresh_timeline()

    def _add_segment_token(self, token: str):
        clip = self._current_clip()
        if clip is None:
            return
        self._push_undo_for_current_clip()
        duration = self._playback_duration(clip)
        start = min(max(0.0, self._play_time), max(0.0, duration - 0.05))
        if hasattr(self, "_timeline"):
            start = max(self._timeline._view_start, min(self._timeline._view_end() - 0.05, start))
        span = min(0.35, max(0.08, duration * 0.08 if duration > 0 else 0.25))
        end = min(duration if duration > 0 else start + span, start + span)
        if end <= start:
            end = start + 0.1
        clip.keys.append(LipKey(time=round(start, 4), animation=token, value=100.0))
        if not token.endswith("_N"):
            clip.keys.append(LipKey(time=round(end, 4), animation="PL_ANM_LIP_NO_N", value=100.0))
        clip.keys.sort(key=lambda key: key.time)
        self._selected_key_idx = next((idx for idx, key in enumerate(clip.keys) if abs(key.time - start) < 0.0005 and key.animation == token), len(clip.keys) - 1)
        self._rebuild_table()
        self._mark_dirty()

    def _copy_selected_segment(self):
        clip = self._current_clip()
        if clip is None or not clip.keys or self._selected_key_idx < 0:
            return
        idx = min(self._selected_key_idx, len(clip.keys) - 1)
        if self._locked_indices_for_clip(clip) and idx in self._locked_indices_for_clip(clip):
            return
        self._push_undo_for_current_clip()
        start, end = self._timeline._segment_time_range(idx) if hasattr(self, "_timeline") else (clip.keys[idx].time, clip.keys[idx].time + 0.25)
        span = max(0.05, end - start)
        new_start = min(self._playback_duration(clip), end + 0.05)
        new_end = new_start + span
        copied = copy.deepcopy(clip.keys[idx])
        copied.time = round(new_start, 4)
        clip.keys.append(copied)
        if not copied.animation.endswith("_N"):
            clip.keys.append(LipKey(time=round(new_end, 4), animation="PL_ANM_LIP_NO_N", value=100.0))
        clip.keys.sort(key=lambda key: key.time)
        self._selected_key_idx = clip.keys.index(copied) if copied in clip.keys else 0
        self._rebuild_table()
        self._mark_dirty()

    def _update_preview_for_selected_key(self):
        clip = self._current_clip()
        if clip is None or not hasattr(self, "_mouth_preview"):
            return
        if 0 <= self._selected_key_idx < len(clip.keys):
            self._mouth_preview.set_token(clip.keys[self._selected_key_idx].animation)
        else:
            self._mouth_preview.set_token("PL_ANM_LIP_NO_N")

    def _active_key_index_at(self, time_value: float) -> int:
        clip = self._current_clip()
        if clip is None or not clip.keys:
            return -1
        active_idx = min(range(len(clip.keys)), key=lambda idx: clip.keys[idx].time)
        active_time = clip.keys[active_idx].time
        for idx, key in enumerate(clip.keys):
            if key.time <= time_value and key.time >= active_time:
                active_idx = idx
                active_time = key.time
        return active_idx

    def _next_key_index_after(self, time_value: float) -> int:
        clip = self._current_clip()
        if clip is None or not clip.keys:
            return -1
        candidates = [(idx, key.time) for idx, key in enumerate(clip.keys) if key.time > time_value + 0.0001]
        if not candidates:
            return -1
        return min(candidates, key=lambda item: item[1])[0]

    def _playback_duration(self, clip) -> float:
        if clip is None or not clip.keys:
            return 0.0
        max_time = max(key.time for key in clip.keys)
        audio_duration = self._audio_preview_duration(clip)
        if audio_duration > 0:
            return max(0.001, audio_duration)
        return max(1.0, max_time + max(0.25, max_time * 0.1))

    def _set_playback_position(self, time_value: float):
        clip = self._current_clip()
        if clip is None:
            return
        duration = self._playback_duration(clip)
        self._play_time = min(max(0.0, time_value), max(0.0, duration))
        if hasattr(self, "_timeline"):
            self._timeline.set_playhead_time(self._play_time)
        if hasattr(self, "_play_time_lbl"):
            self._play_time_lbl.setText(ui_text("ui_lipsync_time_readout", time=self._play_time, duration=duration))

        idx = self._active_key_index_at(self._play_time)
        if idx < 0:
            if hasattr(self, "_mouth_preview"):
                self._mouth_preview.set_token("PL_ANM_LIP_NO_N")
            return

        if hasattr(self, "_mouth_preview"):
            next_idx = self._next_key_index_after(self._play_time)
            if self._mouth_animation_enabled and next_idx >= 0:
                next_time = clip.keys[next_idx].time
                blend_window = min(0.12, max(0.04, self._playback_duration(clip) * 0.025))
                ratio = 1.0 - ((next_time - self._play_time) / blend_window)
                if 0.0 < ratio < 1.0:
                    self._mouth_preview.set_token_blend(clip.keys[idx].animation, clip.keys[next_idx].animation, ratio)
                else:
                    self._mouth_preview.set_token(clip.keys[idx].animation)
            else:
                self._mouth_preview.set_token(clip.keys[idx].animation)
        if idx != self._last_play_key_idx and getattr(self, "_table", None) is not None:
            self._last_play_key_idx = idx
            self._selected_key_idx = idx
            if self._playing:
                if hasattr(self, "_timeline"):
                    self._timeline.set_keys(clip.keys, self._selected_key_idx)
                    self._timeline.set_playhead_time(self._play_time)
                return
            self._table.blockSignals(True)
            self._table.selectRow(idx)
            self._table.blockSignals(False)
            self._refresh_timeline()

    def _sync_playback_buttons(self):
        clip = self._current_clip()
        has_keys = clip is not None and bool(clip.keys)
        has_clip = clip is not None
        if hasattr(self, "_btn_load_reference_top"):
            self._btn_load_reference_top.setEnabled(has_clip)
        if hasattr(self, "_btn_generate_audio_top"):
            self._btn_generate_audio_top.setEnabled(has_clip)
        if hasattr(self, "_btn_reset_clip_timeline"):
            self._btn_reset_clip_timeline.setEnabled(has_clip)
        if hasattr(self, "_btn_play"):
            self._btn_play.setEnabled(has_keys and not self._playing)
        if hasattr(self, "_btn_pause"):
            self._btn_pause.setEnabled(has_keys and self._playing)
        if hasattr(self, "_btn_stop"):
            self._btn_stop.setEnabled(has_keys and (self._playing or self._play_time > 0))
        self._sync_audio_controls()

    def _sync_audio_controls(self):
        if not hasattr(self, "_btn_mute_audio"):
            return
        clip = self._current_clip()
        audio_key = self._clip_audio_key(clip)
        has_awb_audio = audio_key is not None and audio_key in self._awb_clip_sources
        has_pl_audio = audio_key is not None and audio_key in self._pl_clip_sources
        has_audio = bool(self._current_audio_preview_path()) or has_pl_audio or has_awb_audio
        self._btn_mute_audio.setVisible(has_audio)
        self._btn_mute_audio.setEnabled(has_audio)
        self._btn_mute_audio.setText(ui_text("ui_lipsync_unmute_audio" if self._audio_muted else "ui_lipsync_mute_audio"))
        if self._audio_output is not None:
            self._audio_output.setMuted(self._audio_muted)

    def _toggle_audio_mute(self):
        self._audio_muted = not self._audio_muted
        self._sync_audio_controls()

    def _request_awb_audio_for_clip(self, clip, show_error: bool = False, play_after: bool = False) -> bool:
        audio_key = self._clip_audio_key(clip)
        if audio_key is None:
            return False
        if audio_key in self._audio_preview_paths and os.path.isfile(self._audio_preview_paths[audio_key]):
            return True
        if audio_key in self._awb_failed_audio_keys or audio_key in self._awb_decoding_audio_keys:
            return False
        if audio_key not in self._awb_clip_sources:
            return False
        raw, entry, entry_label = self._awb_clip_sources[audio_key]
        self._awb_decoding_audio_keys.add(audio_key)
        self._set_busy(True, ui_text("ui_lipsync_preparing_audio"), entry_label)

        def worker():
            try:
                audio_bytes = extract_entry(raw, entry)
                wav_data = _decode_audio_to_wav(audio_bytes, entry.get("format", ""))
                preview_path = _write_wav_bytes_to_temp(wav_data)
                duration = _wav_bytes_duration(wav_data)
                self._sig_awb_decode_done.emit(audio_key, preview_path, duration, play_after)
            except Exception as exc:
                self._sig_awb_decode_error.emit(audio_key, str(exc), show_error)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _on_awb_decode_done(self, audio_key, preview_path: str, duration: float, play_after: bool):
        self._set_busy(False)
        self._awb_decoding_audio_keys.discard(audio_key)
        self._audio_preview_paths[audio_key] = preview_path
        self._audio_preview_durations[audio_key] = duration
        self._cache_waveform_for_preview(audio_key, preview_path)
        self._refresh_timeline()
        self._sync_audio_controls()
        if play_after and audio_key == self._clip_audio_key():
            self._play_playback()

    def _on_awb_decode_error(self, audio_key, msg: str, show_error: bool):
        self._set_busy(False)
        self._awb_decoding_audio_keys.discard(audio_key)
        self._awb_failed_audio_keys.add(audio_key)
        self._sync_audio_controls()
        if show_error:
            QMessageBox.critical(
                self,
                ui_text("dlg_title_error"),
                ui_text("ui_lipsync_awb_decode_failed", error=msg),
            )

    def _request_pl_audio_for_clip(self, clip, show_error: bool = False, play_after: bool = False) -> bool:
        audio_key = self._clip_audio_key(clip)
        if audio_key is None:
            return False
        if audio_key in self._audio_preview_paths and os.path.isfile(self._audio_preview_paths[audio_key]):
            return True
        if audio_key in self._pl_failed_audio_keys or audio_key in self._pl_decoding_audio_keys:
            return False
        if audio_key not in self._pl_clip_sources:
            return False
        tone, label = self._pl_clip_sources[audio_key]
        self._pl_decoding_audio_keys.add(audio_key)
        self._set_busy(True, ui_text("ui_lipsync_preparing_audio"), label)

        def worker():
            try:
                bnsf = get_tone_bnsf(tone)
                if not bnsf:
                    raise RuntimeError(ui_text("ui_lipsync_no_audio_in_container"))
                cli = _detect_xfbin_audio_tool().get("decode", "")
                wav_data = _decode_bnsf_to_wav(bnsf, cli)
                preview_path = _write_wav_bytes_to_temp(wav_data)
                duration = _wav_bytes_duration(wav_data)
                self._sig_pl_decode_done.emit(audio_key, preview_path, duration, play_after)
            except Exception as exc:
                self._sig_pl_decode_error.emit(audio_key, str(exc), show_error)

        threading.Thread(target=worker, daemon=True).start()
        return False

    def _on_pl_decode_done(self, audio_key, preview_path: str, duration: float, play_after: bool):
        self._set_busy(False)
        self._pl_decoding_audio_keys.discard(audio_key)
        self._audio_preview_paths[audio_key] = preview_path
        self._audio_preview_durations[audio_key] = duration
        self._cache_waveform_for_preview(audio_key, preview_path)
        self._refresh_timeline()
        self._sync_audio_controls()
        if play_after and audio_key == self._clip_audio_key():
            self._play_playback()

    def _on_pl_decode_error(self, audio_key, msg: str, show_error: bool):
        self._set_busy(False)
        self._pl_decoding_audio_keys.discard(audio_key)
        self._pl_failed_audio_keys.add(audio_key)
        self._sync_audio_controls()
        if show_error:
            QMessageBox.critical(
                self,
                ui_text("dlg_title_error"),
                ui_text("ui_lipsync_awb_decode_failed", error=msg),
            )

    def _play_audio_preview(self):
        path = self._current_audio_preview_path()
        if not path:
            return
        player = self._ensure_audio_player()
        source = QUrl.fromLocalFile(path)
        if player.source() != source:
            player.setSource(source)
        self._audio_output.setMuted(self._audio_muted)
        player.setPlaybackRate(self._playback_speed)
        player.setPosition(int(max(0.0, self._play_time) * 1000.0))
        player.play()

    def _pause_audio_preview(self):
        if self._audio_player is not None:
            self._audio_player.pause()

    def _stop_audio_preview(self, reset_position: bool = True):
        if self._audio_player is not None:
            self._audio_player.stop()
            if reset_position:
                self._audio_player.setPosition(0)

    def _play_playback(self):
        clip = self._current_clip()
        if clip is None or not clip.keys:
            self._sync_playback_buttons()
            return
        audio_key = self._clip_audio_key(clip)
        if not self._current_audio_preview_path() and audio_key in self._pl_clip_sources:
            if not self._request_pl_audio_for_clip(clip, show_error=True, play_after=True):
                self._sync_playback_buttons()
                return
            self._refresh_timeline()
            self._sync_audio_controls()
        elif not self._current_audio_preview_path() and audio_key in self._awb_clip_sources:
            if not self._request_awb_audio_for_clip(clip, show_error=True, play_after=True):
                self._sync_playback_buttons()
                return
            self._refresh_timeline()
            self._sync_audio_controls()
        if self._playing:
            return
        if self._play_time >= self._playback_duration(clip):
            self._play_time = 0.0
        self._playing = True
        self._last_play_key_idx = -1
        self._set_playback_position(self._play_time)
        self._play_timer.start()
        self._play_audio_preview()
        self._sync_playback_buttons()

    def _pause_playback(self):
        if not self._playing:
            self._sync_playback_buttons()
            return
        self._playing = False
        self._play_timer.stop()
        self._pause_audio_preview()
        self._sync_playback_buttons()

    def _finish_playback_at_end(self, duration: float):
        if self._loop_playback and self._current_clip() is not None:
            self._play_time = 0.0
            self._last_play_key_idx = -1
            self._set_playback_position(0.0)
            self._play_audio_preview()
            self._play_timer.start()
            self._playing = True
            self._sync_playback_buttons()
            return
        self._playing = False
        self._play_timer.stop()
        self._set_playback_position(duration)
        self._stop_audio_preview(reset_position=False)
        if hasattr(self, "_mouth_preview"):
            self._mouth_preview.set_token("PL_ANM_LIP_NO_N")
        self._sync_playback_buttons()

    def _playback_tick(self):
        if not self._playing:
            return
        clip = self._current_clip()
        if clip is None or not clip.keys:
            self._stop_playback(clear_playhead=True)
            return
        duration = self._playback_duration(clip)
        audio_duration = self._audio_preview_duration(clip)
        if audio_duration > 0 and self._audio_player is not None:
            if self._audio_player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self._finish_playback_at_end(duration)
                return
            next_time = self._audio_player.position() / 1000.0
            if next_time <= 0.0 and self._play_time > 0.0:
                next_time = self._play_time + self._play_step
        else:
            next_time = self._play_time + self._play_step * self._playback_speed
        self._set_playback_position(next_time)
        if next_time >= duration:
            self._finish_playback_at_end(duration)

    def _stop_playback(self, clear_playhead: bool = True):
        self._playing = False
        self._play_timer.stop()
        self._stop_audio_preview(reset_position=True)
        self._play_time = 0.0
        self._last_play_key_idx = -1
        if hasattr(self, "_timeline") and clear_playhead:
            self._timeline.set_playhead_time(0.0)
        if hasattr(self, "_play_time_lbl"):
            clip = self._current_clip()
            duration = self._playback_duration(clip)
            self._play_time_lbl.setText(ui_text("ui_lipsync_time_readout", time=0.0, duration=duration))
        self._update_preview_for_selected_key()
        self._sync_playback_buttons()

    def _reset_current_clip(self):
        clip = self._current_clip()
        if clip is None:
            return
        self._stop_playback(clear_playhead=True)
        snapshot = self._clip_snapshots.get(id(clip.chunk))
        if snapshot is None:
            return
        self._remove_audio_preview(clip)
        clip.name = snapshot["name"]
        clip.file_path = snapshot["file_path"]
        clip.keys = copy.deepcopy(snapshot["keys"])
        self._selected_key_idx = 0 if clip.keys else -1
        self._mark_dirty()
        self._rebuild_clip_list()
        self._select_clip(self._selected_clip_idx)

    def _generate_keys_from_audio_file(self):
        clip = self._current_clip()
        if clip is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_lipsync_import_audio_title"),
            game_files_dialog_dir(),
            ui_text("ui_lipsync_audio_file_filter"),
        )
        if not path:
            return
        if clip.keys:
            reply = QMessageBox.question(
                self,
                ui_text("ui_lipsync_audio_replace_title"),
                ui_text("ui_lipsync_audio_replace_confirm", name=clip.name or ui_text("ui_lipsync_unnamed_clip")),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        audio_key = self._clip_audio_key(clip)
        if audio_key is None:
            return
        self._set_busy(True, ui_text("ui_lipsync_generating_audio"), os.path.basename(path))

        def worker():
            preview_path = ""
            try:
                samples, sample_rate = _decode_audio_file_to_mono(path)
                duration = len(samples) / float(sample_rate) if sample_rate else 0.0
                preview_path = _write_samples_to_temp_wav(samples, sample_rate)
                try:
                    keys = _generate_lip_keys_with_rhubarb(preview_path)
                    keys = _align_lip_keys_to_audio_activity(keys, samples, sample_rate)
                except Exception:
                    keys = _generate_lip_keys_from_audio(samples, sample_rate)
                keys = _clamp_lip_keys_to_duration(keys, duration)
                self._sig_audio_generate_done.emit(audio_key, preview_path, duration, keys)
            except Exception as exc:
                if preview_path:
                    try:
                        os.remove(preview_path)
                    except OSError:
                        pass
                self._sig_audio_generate_error.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_audio_generate_done(self, audio_key, preview_path: str, duration: float, keys_obj):
        self._set_busy(False)
        clip = next((item for item in self._clips if id(item.chunk) == audio_key), None)
        if clip is None:
            try:
                os.remove(preview_path)
            except OSError:
                pass
            return

        self._stop_playback(clear_playhead=True)
        self._remove_audio_preview(clip)
        self._audio_preview_paths[audio_key] = preview_path
        self._audio_preview_durations[audio_key] = duration
        self._cache_waveform_for_preview(audio_key, preview_path)
        clip.keys = list(keys_obj)
        is_current = audio_key == self._clip_audio_key()
        if is_current:
            self._selected_key_idx = 0 if clip.keys else -1
            self._rebuild_table()
            self._refresh_timeline()
            self._update_preview_for_selected_key()
            self._update_clip_sidebar()
        else:
            self._rebuild_clip_list()
        self._sync_audio_controls()
        self._mark_dirty()
        QMessageBox.information(
            self,
            ui_text("ui_lipsync_audio_generated_title"),
            ui_text("ui_lipsync_audio_generated", keys=len(keys_obj), duration=duration),
        )

    def _on_audio_generate_error(self, msg: str):
        self._set_busy(False)
        QMessageBox.critical(self, ui_text("dlg_title_error"), msg)

    def _load_reference_audio_file(self):
        clip = self._current_clip()
        if clip is None:
            return
        audio_key = self._clip_audio_key(clip)
        if audio_key is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            ui_text("ui_lipsync_reference_audio_title"),
            game_files_dialog_dir(),
            ui_text("ui_lipsync_audio_file_filter"),
        )
        if not path:
            return
        self._set_busy(True, ui_text("ui_lipsync_loading_reference_audio"), os.path.basename(path))

        def worker():
            preview_path = ""
            try:
                samples, sample_rate = _decode_audio_file_to_mono(path)
                duration = len(samples) / float(sample_rate) if sample_rate else 0.0
                preview_path = _write_samples_to_temp_wav(samples, sample_rate)
                self._sig_reference_audio_done.emit(audio_key, preview_path, duration)
            except Exception as exc:
                if preview_path:
                    try:
                        os.remove(preview_path)
                    except OSError:
                        pass
                self._sig_reference_audio_error.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_reference_audio_done(self, audio_key, preview_path: str, duration: float):
        self._set_busy(False)
        clip = next((item for item in self._clips if id(item.chunk) == audio_key), None)
        if clip is None:
            try:
                os.remove(preview_path)
            except OSError:
                pass
            return
        self._stop_playback(clear_playhead=True)
        self._remove_audio_preview(clip)
        self._audio_preview_paths[audio_key] = preview_path
        self._audio_preview_durations[audio_key] = duration
        self._cache_waveform_for_preview(audio_key, preview_path)
        if audio_key == self._clip_audio_key():
            self._refresh_timeline()
            if hasattr(self, "_play_time_lbl"):
                self._play_time_lbl.setText(ui_text("ui_lipsync_time_readout", time=0.0, duration=self._playback_duration(clip)))
        self._sync_audio_controls()
        QMessageBox.information(
            self,
            ui_text("ui_lipsync_reference_audio_loaded_title"),
            ui_text("ui_lipsync_reference_audio_loaded", duration=duration),
        )

    def _on_reference_audio_error(self, msg: str):
        self._set_busy(False)
        QMessageBox.critical(self, ui_text("dlg_title_error"), msg)

    def _add_key(self):
        clip = self._current_clip()
        if clip is None:
            return
        self._push_undo_for_current_clip()
        if clip.keys:
            source = clip.keys[self._selected_key_idx] if 0 <= self._selected_key_idx < len(clip.keys) else clip.keys[-1]
            new_key = copy.deepcopy(source)
            new_key.time = source.time + 0.1
        else:
            new_key = LipKey()
        insert_at = self._selected_key_idx + 1 if self._selected_key_idx >= 0 else len(clip.keys)
        clip.keys.insert(insert_at, new_key)
        self._selected_key_idx = insert_at
        self._rebuild_table()
        self._mark_dirty()

    def _duplicate_key(self):
        clip = self._current_clip()
        if clip is None or not clip.keys:
            return
        self._push_undo_for_current_clip()
        idx = self._selected_key_idx if 0 <= self._selected_key_idx < len(clip.keys) else 0
        clip.keys.insert(idx + 1, copy.deepcopy(clip.keys[idx]))
        self._selected_key_idx = idx + 1
        self._rebuild_table()
        self._mark_dirty()

    def _delete_key(self):
        clip = self._current_clip()
        if clip is None or not clip.keys:
            return
        idx = self._selected_key_idx if 0 <= self._selected_key_idx < len(clip.keys) else len(clip.keys) - 1
        locked = self._locked_indices_for_clip(clip)
        if idx in locked:
            return
        self._push_undo_for_current_clip()
        clip.keys.pop(idx)
        self._set_locked_indices_for_clip({locked_idx - 1 if locked_idx > idx else locked_idx for locked_idx in locked if locked_idx != idx}, clip)
        self._selected_key_idx = min(idx, len(clip.keys) - 1)
        self._rebuild_table()
        self._mark_dirty()

    def _sort_keys(self):
        clip = self._current_clip()
        if clip is None:
            return
        self._push_undo_for_current_clip()
        selected_key = clip.keys[self._selected_key_idx] if 0 <= self._selected_key_idx < len(clip.keys) else None
        clip.keys.sort(key=lambda key: key.time)
        self._selected_key_idx = clip.keys.index(selected_key) if selected_key in clip.keys else 0
        self._rebuild_table()
        self._mark_dirty()

    def _add_clip(self):
        if self._xfbin is None:
            return
        new_clip = add_clip(self._xfbin, self._clips, self._current_clip())
        self._clip_snapshots[id(new_clip.chunk)] = {
            "name": new_clip.name,
            "file_path": new_clip.file_path,
            "keys": copy.deepcopy(new_clip.keys),
        }
        if self._awb_entries:
            self._awb_clip_sources.update(self._match_awb_entries_to_clips())
        if self._pl_tone_refs:
            self._pl_clip_sources.update(self._match_pl_tones_to_clips())
        self._selected_clip_idx = self._clips.index(new_clip)
        self._selected_key_idx = 0 if new_clip.keys else -1
        self._rebuild_clip_list()
        self._select_clip(self._selected_clip_idx)
        self._mark_dirty()

    def _duplicate_clip(self):
        clip = self._current_clip()
        if clip is None or self._xfbin is None:
            return
        source_audio_key = self._clip_audio_key(clip)
        new_clip = duplicate_clip(self._xfbin, self._clips, clip)
        self._clip_snapshots[id(new_clip.chunk)] = {
            "name": new_clip.name,
            "file_path": new_clip.file_path,
            "keys": copy.deepcopy(new_clip.keys),
        }
        if source_audio_key in self._awb_clip_entry_indices:
            self._awb_clip_entry_indices[id(new_clip.chunk)] = self._awb_clip_entry_indices[source_audio_key]
        if source_audio_key in self._awb_clip_sources:
            self._awb_clip_sources[id(new_clip.chunk)] = self._awb_clip_sources[source_audio_key]
        if source_audio_key in self._pl_clip_tone_refs:
            self._pl_clip_tone_refs[id(new_clip.chunk)] = self._pl_clip_tone_refs[source_audio_key]
        if source_audio_key in self._pl_clip_sources:
            self._pl_clip_sources[id(new_clip.chunk)] = self._pl_clip_sources[source_audio_key]
        self._selected_clip_idx = self._clips.index(new_clip)
        self._selected_key_idx = 0 if new_clip.keys else -1
        self._rebuild_clip_list()
        self._select_clip(self._selected_clip_idx)
        self._mark_dirty()

    def _delete_clip(self):
        clip = self._current_clip()
        if clip is None or self._xfbin is None:
            return
        if len(self._clips) <= 1:
            QMessageBox.warning(self, ui_text("dlg_title_warning"), ui_text("ui_lipsync_cannot_delete_last_clip"))
            return
        reply = QMessageBox.question(
            self,
            ui_text("dlg_title_confirm_delete"),
            ui_text("ui_lipsync_delete_clip_confirm", name=clip.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted_idx = self._selected_clip_idx
        self._stop_playback(clear_playhead=True)
        self._remove_audio_preview(clip)
        if delete_clip(self._xfbin, self._clips, clip):
            self._clip_snapshots.pop(id(clip.chunk), None)
            self._awb_clip_entry_indices.pop(id(clip.chunk), None)
            self._awb_clip_sources.pop(id(clip.chunk), None)
            self._pl_clip_tone_refs.pop(id(clip.chunk), None)
            self._pl_clip_sources.pop(id(clip.chunk), None)
            self._selected_clip_idx = min(deleted_idx, len(self._clips) - 1)
            self._rebuild_clip_list()
            self._select_clip(self._selected_clip_idx)
            self._mark_dirty()

    def _update_clip_sidebar(self):
        clip = self._current_clip()
        if clip is None:
            return
        for _btn, idx, title, subtitle in self._clip_buttons:
            if idx == self._selected_clip_idx:
                title.setText(clip.name or ui_text("ui_lipsync_unnamed_clip"))
                subtitle.setText(ui_text("ui_lipsync_clip_subtitle", keys=len(clip.keys), duration=clip.duration))
                break

    def _mark_dirty(self):
        if not self._filepath:
            return
        self._dirty = True
        self._btn_save.setEnabled(True)
        set_file_label(self._file_lbl, self._filepath, dirty=True)

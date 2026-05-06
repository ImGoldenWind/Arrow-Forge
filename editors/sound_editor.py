import os
import io
import wave
import subprocess
import tempfile
import threading

from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QScrollArea, QSlider,
    QFileDialog, QMessageBox, QProgressBar,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QColor, QPen

from core.themes import P
from core.style_helpers import (
    ss_btn, ss_file_label, ss_input, ss_panel,
    ss_placeholder, ss_scrollarea, ss_scrollarea_transparent, ss_search,
    ss_section_label, ss_sep, ss_sidebar_btn, ss_slider,
    ss_blocking_overlay, ss_blocking_overlay_card, ss_progressbar,
)
from core.editor_file_state import set_file_label, set_file_label_empty
from core.skeleton import SkeletonListRow
from core.settings import create_backup_on_open, load_settings, save_settings, game_files_dialog_dir
from parsers.awb_parser import (
    parse_awb, extract_entry, rebuild_awb, save_awb,
    add_entry, delete_entry, get_entry_label, _detect_format,
)
from parsers.hca_decoder import parse_hca_info, decode_hca_to_wav, set_hca_volume
from core.translations import ui_text
from core.runtime_paths import app_path


# Audio format detection

# Each entry: (matcher_callable, file_extension, display_name)
# matcher receives the first 16 bytes of the file and returns bool.
_AUDIO_FORMAT_MATCHERS = [
    (lambda d: d[:4] == b'RIFF' and d[8:12] == b'WAVE',                    '.wav',  'WAV'),
    (lambda d: d[:3] in (b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'),  '.mp3',  'MP3'),
    (lambda d: d[:4] == b'fLaC',                                            '.flac', 'FLAC'),
    (lambda d: d[:4] == b'OggS',                                            '.ogg',  ui_text("ui_sound_ogg_opus")),
    (lambda d: d[:4] == b'FORM' and d[8:12] in (b'AIFF', b'AIFC'),        '.aiff', 'AIFF'),
    (lambda d: d[:2] in (b'\xff\xf1', b'\xff\xf9'),                        '.aac',  'AAC'),
    (lambda d: d[:4] == b'wvpk',                                            '.wv',   ui_text("ui_sound_wavpack")),
    (lambda d: d[:8] == b'\x30\x26\xb2\x75\x8e\x66\xcf\x11',              '.wma',  ui_text("ui_sound_wma_asf")),
    (lambda d: len(d) > 8 and d[4:8] == b'ftyp',                           '.m4a',  ui_text("ui_sound_aac_m4a")),
    (lambda d: d[:3] == b'HCA' or d[:3] == bytes([0xC8, 0xC3, 0xC1]),      '.hca',  'HCA'),
    (lambda d: d[:2] == b'\x80\x00',                                        '.adx',  'ADX'),
]

_AUDIO_EXTENSIONS = {
    '.wav', '.mp3', '.flac', '.ogg', '.opus', '.aiff', '.aif',
    '.m4a', '.aac', '.wv', '.wma', '.hca', '.adx', '.bin',
}

# Extensions shown in "open file" dialogs
_AUDIO_OPEN_FILTER = (
    "Audio files ("
    "*.wav *.mp3 *.flac *.ogg *.opus *.aiff *.aif "
    "*.m4a *.aac *.wv *.wma *.hca *.adx *.bin"
    ");;All files (*.*)"
)


def _ensure_file_ext(path: str, ext: str) -> str:
    return path if os.path.splitext(path)[1] else path + ext


def _detect_audio_input_format(data: bytes, fallback_path: str = '') -> str:
    """Return a suitable file extension for *data*, or raise ValueError.

    Raises
    ValueError
        When the data is empty or no known audio signature is found.
    """
    if not data:
        raise ValueError(ui_text("sound_audio_file_empty"))
    header = data[:16]
    for matcher, ext, _ in _AUDIO_FORMAT_MATCHERS:
        try:
            if matcher(header):
                return ext
        except Exception:
            continue
    fallback_ext = os.path.splitext(fallback_path)[1].lower()
    if fallback_ext in _AUDIO_EXTENSIONS:
        return fallback_ext
    raise ValueError(ui_text("sound_unsupported_audio_format", signature=header[:8].hex()))


def _run_vgaudio_conversion(
    cli_path: str,
    audio_data: bytes,
    target_ext: str = '.hca',
    source_path: str = '',
) -> bytes:
    """Convert audio bytes to HCA using VGAudioCli.exe at the given path.

    Raises
    ValueError
        If the audio format cannot be detected.
    RuntimeError
        If VGAudioCli exits with a non-zero return code or produces no output.
    """
    in_ext = _detect_audio_input_format(audio_data, source_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, f'input{in_ext}')
        out_path = os.path.join(tmpdir, f'output{target_ext}')
        with open(in_path, 'wb') as f:
            f.write(audio_data)
        commands = (
            [cli_path, '-i', in_path, '-o', out_path],
            [cli_path, in_path, '-o', out_path],
        )
        last_result = None
        for command in commands:
            if os.path.isfile(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            last_result = subprocess.run(command, capture_output=True, timeout=60)
            if last_result.returncode == 0 and os.path.isfile(out_path):
                break
        if last_result is None or last_result.returncode != 0 or not os.path.isfile(out_path):
            stderr = (last_result.stderr if last_result else b'').decode(errors='replace').strip()
            stdout = (last_result.stdout if last_result else b'').decode(errors='replace').strip()
            details = stderr or stdout or ui_text("no_output")
            code = last_result.returncode if last_result else -1
            raise RuntimeError(ui_text("sound_vgaudio_exit_code", code=code, details=details))
        with open(out_path, 'rb') as f:
            return f.read()


def _run_tool_decode_to_wav(cli_path: str, audio_data: bytes, source_path: str = '') -> bytes:
    """Decode any supported audio bytes to WAV using vgmstream or VGAudioCli."""
    in_ext = _detect_audio_input_format(audio_data, source_path)

    with tempfile.TemporaryDirectory() as tmpdir:
        in_path = os.path.join(tmpdir, f'input{in_ext}')
        out_path = os.path.join(tmpdir, 'output.wav')
        with open(in_path, 'wb') as f:
            f.write(audio_data)

        if 'vgmstream' in os.path.basename(cli_path).lower():
            cmd = [cli_path, '-o', out_path, in_path]
        else:
            commands = (
                [cli_path, '-i', in_path, '-o', out_path],
                [cli_path, in_path, '-o', out_path],
            )
            last_result = None
            for command in commands:
                if os.path.isfile(out_path):
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass
                last_result = subprocess.run(command, capture_output=True, timeout=60)
                if last_result.returncode == 0 and os.path.isfile(out_path):
                    break
            if last_result is None or last_result.returncode != 0 or not os.path.isfile(out_path):
                stderr = (last_result.stderr if last_result else b'').decode(errors='replace').strip()
                stdout = (last_result.stdout if last_result else b'').decode(errors='replace').strip()
                details = stderr or stdout or ui_text("no_output")
                code = last_result.returncode if last_result else -1
                raise RuntimeError(ui_text("sound_vgaudio_exit_code", code=code, details=details))
            with open(out_path, 'rb') as f:
                return f.read()

        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0 or not os.path.isfile(out_path):
            stderr = result.stderr.decode(errors='replace').strip()
            stdout = result.stdout.decode(errors='replace').strip()
            details = stderr or stdout or ui_text("no_output")
            raise RuntimeError(ui_text("sound_vgaudio_exit_code", code=result.returncode, details=details))
        with open(out_path, 'rb') as f:
            return f.read()


def _auto_detect_vgaudio_cli() -> str:
    """Return VGAudioCli.exe path from settings or the tools/ directory.

    Never shows a dialog — returns an empty string when not found.
    """
    settings = load_settings()
    cli = settings.get('vgaudio_cli_path', '')
    if cli and os.path.isfile(cli):
        return cli
    candidate = app_path('tools', ui_text("ui_sound_vgaudiocli_exe_2"))
    return candidate if os.path.isfile(candidate) else ''


def _auto_detect_decode_cli() -> str:
    """Return the best bundled decoder: vgmstream first, then VGAudioCli."""
    candidate = app_path('tools', 'vgmstream-cli.exe')
    if os.path.isfile(candidate):
        return candidate
    return _auto_detect_vgaudio_cli()


def _decode_audio_to_wav(audio_data: bytes, source_format: str = '', source_path: str = '') -> bytes:
    """Decode game or common audio bytes to WAV for user-facing exports."""
    if audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE':
        return audio_data
    if source_format == 'HCA' or audio_data[:3] in (b'HCA', bytes([0xC8, 0xC3, 0xC1])):
        try:
            return decode_hca_to_wav(audio_data)
        except Exception:
            pass
    cli = _auto_detect_decode_cli()
    if not cli:
        raise RuntimeError(ui_text("sound_decode_tool_missing"))
    return _run_tool_decode_to_wav(cli, audio_data, source_path)


def _target_ext_for_entry(entry: dict) -> str:
    return '.adx' if entry.get('format') == 'ADX' else '.hca'


def _encode_to_hca_python(audio_data: bytes) -> bytes:
    """Convert *audio_data* to HCA using soundfile + PyCriCodecs (no subprocess).

    Decoding chain
    1. If the data is already WAV (PCM), pass it directly to PyCriCodecs.
    2. Otherwise decode with ``soundfile`` (supports FLAC, OGG/Vorbis, AIFF,
       WAV, and many others via libsndfile).
    3. If ``soundfile`` cannot read the format (e.g. MP3, AAC, WMA), fall back
       to ``pydub`` which internally uses ffmpeg.

    Raises
    ImportError
        When neither soundfile nor PyCriCodecs is installed.
    ValueError
        When the audio format cannot be decoded by any available library.
    RuntimeError
        When PyCriCodecs fails to encode the resulting WAV to HCA.
    """
    try:
        import soundfile as sf  # noqa: PLC0415
    except ImportError:
        sf = None

    try:
        from PyCriCodecsEx.hca import HCACodec  # noqa: PLC0415
    except ImportError:
        raise ImportError(ui_text("sound_pycricodecsex_missing"))

    # Decode to PCM WAV
    is_wav = audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE'

    if is_wav:
        wav_data = audio_data
    else:
        if sf is None:
            raise RuntimeError(ui_text("sound_soundfile_missing"))
        try:
            pcm, sr = sf.read(io.BytesIO(audio_data), dtype='int16', always_2d=True)
        except Exception as e:
            raise ValueError(ui_text("sound_decode_audio_failed", error=e)) from e
        buf = io.BytesIO()
        sf.write(buf, pcm, sr, format='WAV', subtype='PCM_16')
        wav_data = buf.getvalue()

    # Encode WAV → HCA
    try:
        return HCACodec(io.BytesIO(wav_data)).encode()
    except Exception as e:
        raise RuntimeError(ui_text("sound_pycricodecs_encode_failed", error=e)) from e


def _fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _fmt_duration(sec):
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:05.2f}"


def _clear_layout(layout):
    if layout is None:
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
        self._mid = 40
        self._width = 200
        self.setStyleSheet(f"background-color: {P['bg_card']};")

    def set_waveform(self, lines, mid, width):
        self._lines = lines
        self._mid = mid
        self._width = width
        self.update()

    def clear(self):
        self._lines = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()
        mid = h // 2

        # Background
        painter.fillRect(self.rect(), QColor(P["bg_card"]))

        # Center line
        painter.setPen(QPen(QColor(P["mid"]), 1))
        painter.drawLine(0, mid, w, mid)

        if self._lines is not None:
            accent = QColor(P["accent"])
            painter.setPen(QPen(accent, 1))
            for x, y_top, y_bot in self._lines:
                if x < w:
                    painter.drawLine(x, y_top, x, y_bot)
        else:
            painter.setPen(QPen(QColor(P["text_dim"]), 1))
            fm = painter.fontMetrics()
            text = "..."
            tx = (w - fm.horizontalAdvance(text)) // 2
            painter.drawText(tx, mid + fm.ascent() // 2, text)

        painter.end()


class SoundEditor(QWidget):
    # Signals for thread-safe UI updates
    _sig_load_done = pyqtSignal(str, object, list, dict)
    _sig_load_error = pyqtSignal(str)
    _sig_editor_ready = pyqtSignal(int, object)
    _sig_decode_done = pyqtSignal(bytes, int)
    _sig_decode_error = pyqtSignal(str)
    _sig_play_progress = pyqtSignal(float, float)
    _sig_playback_done = pyqtSignal()
    _sig_waveform_ready = pyqtSignal(object)
    _sig_export_success = pyqtSignal(str)
    _sig_export_error = pyqtSignal(str)
    _sig_busy_progress = pyqtSignal(str, int, int)
    # Conversion (add / replace) — emitted from background threads
    _sig_convert_replace_done = pyqtSignal(int, bytes)   # (entry_idx, hca_bytes)
    _sig_convert_add_done     = pyqtSignal(bytes)        # (hca_bytes,)
    _sig_convert_error        = pyqtSignal(str)          # error message

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or (lambda k, **kw: k)

        self._raw_data = None
        self._entries = []
        self._meta = None
        self._current_entry = None
        self._entry_buttons = []
        self._filepath = None
        self._fields = {}
        self._dirty = False

        # Audio playback state
        self._wav_cache = {}       # idx -> wav bytes
        self._playing = False
        self._play_thread = None
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._seek_lock = threading.Lock()
        self._seek_target_frame = None
        self._seeking = False
        self._seek_total = 0.0
        self._seek_total_frames = 0
        self._seek_fps = 0
        self._pa = None            # PyAudio instance (lazy)

        # Connect signals
        self._sig_load_done.connect(self._on_load_done)
        self._sig_load_error.connect(self._on_load_error)
        self._sig_editor_ready.connect(self._build_editor)
        self._sig_decode_done.connect(self._on_decode_done)
        self._sig_decode_error.connect(self._on_decode_error)
        self._sig_play_progress.connect(self._update_play_progress)
        self._sig_playback_done.connect(self._on_playback_done)
        self._sig_waveform_ready.connect(self._finish_draw_waveform)
        self._sig_export_success.connect(self._on_export_success)
        self._sig_export_error.connect(self._on_export_error)
        self._sig_busy_progress.connect(self._on_busy_progress)
        self._sig_convert_replace_done.connect(self._on_convert_replace_done)
        self._sig_convert_add_done.connect(self._on_convert_add_done)
        self._sig_convert_error.connect(self._on_convert_error)

        self._build_ui()

    def closeEvent(self, event):
        self._stop_playback()
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
        super().closeEvent(event)

    # UI construction

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setStyleSheet(f"background-color: {P['bg_dark']};")

        # Top bar
        top = QFrame()
        top.setFixedHeight(46)
        top.setStyleSheet(f"background-color: {P['bg_panel']};")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(4)

        open_btn = QPushButton(self.t("btn_open_file"))
        open_btn.setFixedHeight(30)
        open_btn.setFont(QFont("Segoe UI", 10))
        open_btn.setStyleSheet(ss_btn(accent=True))
        open_btn.clicked.connect(self._load_file)
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setFixedHeight(30)
        self._save_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(ss_btn(accent=True))
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"))
        self._file_label.setFont(QFont("Consolas", 12))
        self._file_label.setStyleSheet(ss_file_label())
        top_layout.addWidget(self._file_label)
        top_layout.addStretch()

        root_layout.addWidget(top)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(ss_sep())
        root_layout.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Entry list sidebar
        list_frame = QFrame()
        list_frame.setFixedWidth(260)
        list_frame.setStyleSheet(f"QFrame {{ background-color: {P['bg_panel']}; }}")
        list_vlayout = QVBoxLayout(list_frame)
        list_vlayout.setContentsMargins(8, 8, 8, 4)
        list_vlayout.setSpacing(4)

        # Search
        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText(self.t("search_placeholder"))
        self._search_entry.setFixedHeight(32)
        self._search_entry.setFont(QFont("Segoe UI", 13))
        self._search_entry.setStyleSheet(ss_search())
        self._search_entry.textChanged.connect(lambda: self._filter_list())
        list_vlayout.addWidget(self._search_entry)

        # Action buttons
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
        self._add_btn.clicked.connect(self._add_new_entry)
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_duplicate"))
        self._dup_btn.setFixedHeight(28)
        self._dup_btn.setFont(btn_font)
        self._dup_btn.setEnabled(False)
        self._dup_btn.setStyleSheet(ss_btn())
        self._dup_btn.clicked.connect(self._duplicate_entry)
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"))
        self._del_btn.setFixedHeight(28)
        self._del_btn.setFont(btn_font)
        self._del_btn.setEnabled(False)
        self._del_btn.setStyleSheet(ss_btn(danger=True))
        self._del_btn.clicked.connect(self._delete_entry)
        actions_layout.addWidget(self._del_btn, 1)

        list_vlayout.addWidget(actions_frame)

        # Scrollable entry list
        self._entry_scroll = QScrollArea()
        self._entry_scroll.setWidgetResizable(True)
        self._entry_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entry_scroll.setStyleSheet(ss_scrollarea_transparent())
        self._entry_list_widget = QWidget()
        self._entry_list_widget.setStyleSheet("background-color: transparent;")
        self._entry_list_layout = QVBoxLayout(self._entry_list_widget)
        self._entry_list_layout.setContentsMargins(0, 0, 0, 0)
        self._entry_list_layout.setSpacing(1)
        self._entry_list_layout.addStretch()
        self._entry_scroll.setWidget(self._entry_list_widget)
        list_vlayout.addWidget(self._entry_scroll, 1)

        main_layout.addWidget(list_frame)

        # Vertical separator
        vsep = QFrame()
        vsep.setFixedWidth(1)
        vsep.setStyleSheet(f"background-color: {P['mid']};")
        main_layout.addWidget(vsep)

        # Editor panel (scrollable)
        self._editor_scroll = QScrollArea()
        self._editor_scroll.setWidgetResizable(True)
        self._editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._editor_scroll.setStyleSheet(ss_scrollarea())
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(f"background-color: {P['bg_dark']};")
        self._editor_layout = QVBoxLayout(self._editor_widget)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._editor_layout.setSpacing(0)
        self._editor_scroll.setWidget(self._editor_widget)

        self._placeholder = QLabel(self.t("placeholder_sound"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(ss_placeholder())
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()

        main_layout.addWidget(self._editor_scroll, 1)
        root_layout.addWidget(main, 1)
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

        self._busy_title_lbl = QLabel(self.t("loading"))
        self._busy_title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        self._busy_title_lbl.setStyleSheet(ss_section_label())
        self._busy_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._busy_title_lbl)

        self._busy_detail_lbl = QLabel("")
        self._busy_detail_lbl.setFont(QFont("Segoe UI", 10))
        self._busy_detail_lbl.setStyleSheet(ss_file_label())
        self._busy_detail_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._busy_detail_lbl)

        self._busy_bar = QProgressBar()
        self._busy_bar.setRange(0, 100)
        self._busy_bar.setValue(0)
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_busy_overlay'):
            self._busy_overlay.setGeometry(self.rect())

    def _set_busy(self, active: bool, title: str = '', detail: str = '', done: int = 0, total: int = 0):
        if not hasattr(self, '_busy_overlay'):
            return
        if active:
            self._busy_title_lbl.setText(title or self.t("loading"))
            self._on_busy_progress(detail, done, total)
            self._busy_overlay.setGeometry(self.rect())
            self._busy_overlay.raise_()
            self._busy_overlay.show()
            return
        self._busy_overlay.hide()

    def _on_busy_progress(self, text: str, done: int, total: int):
        if not hasattr(self, '_busy_bar'):
            return
        self._busy_detail_lbl.setText(text or "")
        if total > 0:
            self._busy_bar.setRange(0, total)
            self._busy_bar.setValue(max(0, min(done, total)))
        else:
            self._busy_bar.setRange(0, 0)

    def _on_export_success(self, msg: str):
        self._set_busy(False)
        QMessageBox.information(self, self.t("dlg_title_success"), msg)

    def _on_export_error(self, msg: str):
        self._set_busy(False)
        QMessageBox.critical(self, self.t("dlg_title_error"), msg)

    # File loading

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_sound"),
            game_files_dialog_dir(target_patterns=("*.awb", "*.acb")), "AWB files (*.awb);;All files (*.*)")
        if not path:
            return
        create_backup_on_open(path)
        self._stop_playback()
        self._wav_cache.clear()
        set_file_label_empty(self._file_label, self.t("loading"))
        self._show_list_skeleton()
        self._show_editor_skeleton()

        def worker():
            try:
                raw, entries, meta = parse_awb(path)
            except Exception as e:
                self._sig_load_error.emit(str(e))
                return
            self._sig_load_done.emit(path, raw, entries, meta)

        threading.Thread(target=worker, daemon=True).start()

    def _show_list_skeleton(self):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []
        for _ in range(10):
            self._entry_list_layout.addWidget(SkeletonListRow())
        self._entry_list_layout.addStretch()

    def _show_editor_skeleton(self):
        from core.skeleton import SkeletonBar
        _clear_layout(self._editor_layout)

        hdr = QFrame()
        hdr.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 14, 16, 14)
        hdr_layout.addWidget(SkeletonBar(height=36, corner_radius=5))
        self._editor_layout.addWidget(hdr)

        for _ in range(3):
            sec = QFrame()
            sec.setStyleSheet(f"background-color: {P['bg_panel']}; border-radius: 10px;")
            sec_layout = QVBoxLayout(sec)
            sec_layout.setContentsMargins(12, 12, 12, 12)
            g = QGridLayout()
            g.setSpacing(8)
            for col in range(3):
                f = QWidget()
                f_layout = QVBoxLayout(f)
                f_layout.setContentsMargins(0, 0, 0, 0)
                f_layout.setSpacing(4)
                f_layout.addWidget(SkeletonBar(height=11, corner_radius=3))
                f_layout.addWidget(SkeletonBar(height=30, corner_radius=4))
                g.addWidget(f, 0, col)
            sec_layout.addLayout(g)
            self._editor_layout.addWidget(sec)

        self._editor_layout.addStretch()

    def _on_load_error(self, msg):
        _clear_layout(self._entry_list_layout)
        self._entry_list_layout.addStretch()
        _clear_layout(self._editor_layout)
        self._placeholder = QLabel(self.t("placeholder_sound"))
        self._placeholder.setFont(QFont("Segoe UI", 16))
        self._placeholder.setStyleSheet(ss_placeholder())
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(self._placeholder)
        self._editor_layout.addStretch()
        self._filepath = None
        self._dirty = False
        set_file_label_empty(self._file_label, self.t("no_file_loaded"))
        QMessageBox.critical(self, self.t("dlg_title_error"),
                             self.t("msg_load_error", error=msg))

    def _on_load_done(self, path, raw, entries, meta):
        self._raw_data = raw
        self._entries = entries
        self._meta = meta
        self._filepath = path
        self._dirty = False
        set_file_label(self._file_label, path)

        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(bool(entries))
        self._del_btn.setEnabled(bool(entries))

        self._populate_list()

    # Save

    def _save_file(self):
        if self._raw_data is None:
            return
        if not self._filepath:
            return
        try:
            path = self._filepath
            new_raw, new_entries, new_meta = rebuild_awb(
                self._entries, self._meta, self._raw_data)
            save_awb(path, new_raw)
            self._raw_data = bytearray(new_raw)
            self._entries = new_entries
            self._meta = new_meta
            self._dirty = False
            set_file_label(self._file_label, path)
            self._wav_cache.clear()
            QMessageBox.information(self, self.t("dlg_title_success"),
                                    self.t("msg_save_success", path=os.path.basename(path)))
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"),
                                 self.t("msg_save_error", error=str(e)))

    # Entry list

    def _populate_list(self):
        _clear_layout(self._entry_list_layout)
        self._entry_buttons = []

        for i, entry in enumerate(self._entries):
            label_text = get_entry_label(entry['id'])

            btn = QPushButton()
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(ss_sidebar_btn(False))

            # Inner layout for the button
            btn_widget = QWidget(btn)
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(10, 3, 10, 3)
            btn_layout.setSpacing(0)

            text_col = QWidget()
            text_layout = QVBoxLayout(text_col)
            text_layout.setContentsMargins(0, 0, 0, 0)
            text_layout.setSpacing(0)

            name_lbl = QLabel(label_text)
            name_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
            name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_layout.addWidget(name_lbl)

            btn_layout.addWidget(text_col, 1)

            btn_widget.setGeometry(0, 0, 260, 44)
            btn_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

            idx = i
            btn.clicked.connect(lambda checked, idx=idx: self._select_entry(idx))
            btn.resizeEvent = lambda event, bw=btn_widget: bw.setGeometry(0, 0, event.size().width(), event.size().height())

            self._entry_list_layout.addWidget(btn)
            self._entry_buttons.append((btn, entry, i))

        self._entry_list_layout.addStretch()

        if self._entries:
            self._select_entry(0)

    def _filter_list(self):
        query = self._search_entry.text().lower()
        for btn, entry, idx in self._entry_buttons:
            label = get_entry_label(entry['id']).lower()
            match = (query in label or query in str(entry['id'])
                     or query in entry['format'].lower())
            btn.setVisible(match)

    def _select_entry(self, idx):
        if idx < 0 or idx >= len(self._entries):
            return
        self._stop_playback()
        self._current_entry = idx
        for btn, entry, i in self._entry_buttons:
            try:
                if i == idx:
                    btn.setStyleSheet(ss_sidebar_btn(True))
                else:
                    btn.setStyleSheet(ss_sidebar_btn(False))
            except RuntimeError:
                pass
        self._show_editor_skeleton()

        def worker():
            entry = self._entries[idx]
            hca_bytes = self._get_entry_bytes(idx)
            hca_info = None
            if entry['format'] == 'HCA':
                try:
                    hca_info = parse_hca_info(hca_bytes)
                except Exception:
                    pass
            self._sig_editor_ready.emit(idx, hca_info)

        threading.Thread(target=worker, daemon=True).start()

    # Editor panel

    def _build_editor(self, idx, hca_info=None):
        if self._current_entry != idx:
            return  # User already clicked another entry
        _clear_layout(self._editor_layout)
        self._fields = {}

        entry = self._entries[idx]

        # Header
        hdr = QFrame()
        hdr.setStyleSheet(ss_panel())
        hdr_layout = QVBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 12, 16, 12)
        title = get_entry_label(entry['id'])
        title_lbl = QLabel(ui_text("ui_sound_value_value", p0=entry['id'], p1=title))
        title_lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        hdr_layout.addWidget(title_lbl)
        self._editor_layout.addWidget(hdr)

        # Audio Info
        # Playback
        if hca_info:
            sec_play = self._make_section(self.t("sound_section_playback"))
            play_frame = QWidget()
            play_frame.setStyleSheet("background-color: transparent;")
            play_layout = QHBoxLayout(play_frame)
            play_layout.setContentsMargins(12, 0, 12, 12)
            play_layout.setSpacing(6)

            bf = QFont("Segoe UI", 13, QFont.Weight.Bold)
            self._play_btn = QPushButton(self.t("sound_btn_play"))
            self._play_btn.setFixedHeight(34)
            self._play_btn.setFont(bf)
            self._play_btn.setStyleSheet(ss_btn(accent=True))
            self._play_btn.clicked.connect(lambda: self._play_audio(idx))
            play_layout.addWidget(self._play_btn)

            self._pause_btn = QPushButton(ui_text("ui_sound_pause"))
            self._pause_btn.setFixedHeight(34)
            self._pause_btn.setFont(bf)
            self._pause_btn.setEnabled(False)
            self._pause_btn.setStyleSheet(ss_btn())
            self._pause_btn.clicked.connect(self._toggle_pause)
            play_layout.addWidget(self._pause_btn)

            self._stop_btn = QPushButton(self.t("sound_btn_stop"))
            self._stop_btn.setFixedHeight(34)
            self._stop_btn.setFont(bf)
            self._stop_btn.setEnabled(False)
            self._stop_btn.setStyleSheet(ss_btn(danger=True))
            self._stop_btn.clicked.connect(self._stop_playback)
            play_layout.addWidget(self._stop_btn)

            self._play_status = QLabel("")
            self._play_status.setFont(QFont("Consolas", 11))
            self._play_status.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            play_layout.addWidget(self._play_status)
            play_layout.addStretch()

            sec_play.layout().addWidget(play_frame)

            seek_row = QWidget()
            seek_row.setStyleSheet("background-color: transparent;")
            seek_layout = QHBoxLayout(seek_row)
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
            sec_play.layout().addWidget(seek_row)

            # Waveform
            self._waveform_widget = WaveformWidget()
            wf_container = QWidget()
            wf_container.setStyleSheet("background-color: transparent;")
            wf_layout = QHBoxLayout(wf_container)
            wf_layout.setContentsMargins(12, 0, 12, 12)
            wf_layout.addWidget(self._waveform_widget)
            sec_play.layout().addWidget(wf_container)

            # Draw waveform if cached
            if idx in self._wav_cache:
                self._draw_waveform(self._wav_cache[idx])

        # Volume Control
        if hca_info:
            sec_vol = self._make_section(self.t("sound_section_volume"))
            vol_frame = QWidget()
            vol_frame.setStyleSheet("background-color: transparent;")
            vol_layout = QVBoxLayout(vol_frame)
            vol_layout.setContentsMargins(12, 0, 12, 12)

            cur_vol = hca_info.get('rva_volume', 1.0)

            vol_label = QLabel(self.t("sound_volume_label"))
            vol_label.setFont(QFont("Segoe UI", 12))
            vol_label.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            vol_layout.addWidget(vol_label)

            slider_row = QWidget()
            slider_row.setStyleSheet("background-color: transparent;")
            slider_row_layout = QHBoxLayout(slider_row)
            slider_row_layout.setContentsMargins(0, 4, 0, 0)
            slider_row_layout.setSpacing(8)

            self._vol_slider = QSlider(Qt.Orientation.Horizontal)
            self._vol_slider.setRange(0, 200)
            self._vol_slider.setValue(int(cur_vol * 100))
            self._vol_slider.setStyleSheet(ss_slider())
            self._vol_slider.valueChanged.connect(lambda v: self._on_volume_slider(v / 100.0))
            self._vol_slider.sliderReleased.connect(lambda: self._apply_volume(idx, notify=False))
            slider_row_layout.addWidget(self._vol_slider, 1)

            self._vol_label = QLabel(ui_text("ui_sound_value", p0=cur_vol))
            self._vol_label.setFont(QFont("Consolas", 14, QFont.Weight.Bold))
            self._vol_label.setStyleSheet(f"color: {P['accent']}; background: transparent;")
            self._vol_label.setFixedWidth(60)
            self._vol_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            slider_row_layout.addWidget(self._vol_label)

            vol_layout.addWidget(slider_row)

            sec_vol.layout().addWidget(vol_frame)

        # Actions
        sec_act = self._make_section(self.t("sound_section_actions"))
        act_frame = QWidget()
        act_frame.setStyleSheet("background-color: transparent;")
        act_layout = QHBoxLayout(act_frame)
        act_layout.setContentsMargins(12, 0, 12, 12)
        act_layout.setSpacing(8)

        bf3 = QFont("Segoe UI", 13, QFont.Weight.Bold)

        extract_btn = QPushButton(ui_text("ui_sound_extract_audio"))
        extract_btn.setFixedSize(160, 34)
        extract_btn.setFont(bf3)
        extract_btn.setStyleSheet(ss_btn(accent=True))
        extract_btn.clicked.connect(lambda: self._extract_single(idx))
        act_layout.addWidget(extract_btn)

        self._extract_btn = QPushButton(ui_text("ui_sound_extract_all"))
        self._extract_btn.setFixedSize(160, 34)
        self._extract_btn.setFont(bf3)
        self._extract_btn.setStyleSheet(ss_btn())
        self._extract_btn.clicked.connect(self._extract_all)
        act_layout.addWidget(self._extract_btn)

        replace_btn = QPushButton(ui_text("ui_sound_replace_audio"))
        replace_btn.setFixedSize(160, 34)
        replace_btn.setFont(bf3)
        replace_btn.setStyleSheet(ss_btn())
        replace_btn.clicked.connect(lambda: self._replace_single(idx))
        act_layout.addWidget(replace_btn)

        act_layout.addStretch()
        sec_act.layout().addWidget(act_frame)

        # Container Info
        # Analysis
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

    def _add_field(self, parent_grid, label, value, key, row=0, col=0, readonly=False):
        frame = QWidget()
        frame.setStyleSheet("background-color: transparent;")
        f_layout = QVBoxLayout(frame)
        f_layout.setContentsMargins(0, 0, 0, 0)
        f_layout.setSpacing(2)

        lbl = QLabel(label)
        lbl.setFont(QFont("Segoe UI", 11))
        lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
        f_layout.addWidget(lbl)

        ent = QLineEdit(value)
        ent.setFixedHeight(30)
        ent.setFont(QFont("Consolas", 12))
        ent.setStyleSheet(ss_input())
        if readonly:
            ent.setReadOnly(True)
        f_layout.addWidget(ent)

        parent_grid.addWidget(frame, row, col)
        self._fields[key] = ent
        return ent

    # Helpers

    def _get_entry_bytes(self, idx):
        """Get raw HCA bytes for an entry (respects pending replacements)."""
        entry = self._entries[idx]
        if '_new_data' in entry:
            return entry['_new_data']
        return extract_entry(self._raw_data, entry)

    def _resolve_vgaudio_cli(self) -> str:
        """Return VGAudioCli.exe path, prompting the user if not yet configured.

        Must be called from the main (UI) thread because it may open a file
        dialog.  Raises RuntimeError when the user cancels or the path is
        invalid.
        """
        settings = load_settings()
        cli = settings.get('vgaudio_cli_path', '')
        if cli and not os.path.isfile(cli):
            cli = ''

        if not cli:
            candidate = app_path('tools', ui_text("ui_sound_vgaudiocli_exe_2"))
            if os.path.isfile(candidate):
                cli = candidate

        if not cli:
            cli, _ = QFileDialog.getOpenFileName(
                self, ui_text("ui_sound_vgaudiocli_exe"), "", "VGAudioCli (VGAudioCli.exe);;All files (*.*)")
            if not cli or not os.path.isfile(cli):
                raise RuntimeError(ui_text("sound_vgaudio_not_selected"))
            settings['vgaudio_cli_path'] = cli
            save_settings(settings)

        return cli

    def _convert_audio_to_hca(self, audio_data: bytes) -> bytes:
        """Convert *audio_data* to HCA synchronously (blocks the caller).

        Safe to call from the main thread only for the HCA fast-path; for
        non-HCA data prefer the async helpers ``_start_replace_async`` /
        ``_start_add_async`` which offload VGAudioCli to a background thread.
        """
        if audio_data[:3] in (b'HCA', bytes([0xC8, 0xC3, 0xC1])):
            return audio_data
        cli = self._resolve_vgaudio_cli()
        return _run_vgaudio_conversion(cli, audio_data)

    # Audio Playback

    def _ensure_pyaudio(self):
        if self._pa is None:
            import pyaudiowpatch as pyaudio
            self._pa = pyaudio.PyAudio()
        return self._pa

    def _play_audio(self, idx):
        """Decode HCA and play audio in a background thread."""
        if self._playing:
            self._stop_playback()

        entry = self._entries[idx]
        if entry['format'] != 'HCA':
            return

        if hasattr(self, '_play_status'):
            self._play_status.setText(self.t("sound_status_decoding"))
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(False)

        def worker():
            try:
                if idx in self._wav_cache:
                    wav_data = self._wav_cache[idx]
                else:
                    hca_bytes = self._get_entry_bytes(idx)
                    wav_data = decode_hca_to_wav(hca_bytes)
                    self._wav_cache[idx] = wav_data

                self._sig_decode_done.emit(wav_data, idx)
            except Exception as e:
                self._sig_decode_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_decode_done(self, wav_data, idx):
        if hasattr(self, '_waveform_widget'):
            self._draw_waveform(wav_data)
        self._start_playback(wav_data, idx)

    def _on_decode_error(self, msg):
        if hasattr(self, '_play_status'):
            self._play_status.setText(self.t("sound_status_error"))
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(True)
        QMessageBox.critical(self, self.t("dlg_title_error"), msg)

    def _start_playback(self, wav_data, idx):
        self._stop_flag.clear()
        self._pause_flag.clear()
        with self._seek_lock:
            self._seek_target_frame = None
        self._playing = True
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(False)
        if hasattr(self, '_pause_btn'):
            self._pause_btn.setEnabled(True)
            self._pause_btn.setText(ui_text("ui_sound_pause"))
        if hasattr(self, '_stop_btn'):
            self._stop_btn.setEnabled(True)
        if hasattr(self, '_seek_slider'):
            self._seek_slider.setEnabled(True)
            self._seek_slider.setValue(0)

        def play_worker():
            try:
                pa = self._ensure_pyaudio()
                import pyaudiowpatch as pyaudio

                wf = wave.open(io.BytesIO(wav_data), 'rb')
                stream = pa.open(
                    format=pa.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True)

                chunk = 2048
                total_frames = wf.getnframes()
                fps = wf.getframerate()
                self._seek_total = total_frames / fps if fps else 0.0
                self._seek_total_frames = total_frames
                self._seek_fps = fps
                played = 0
                # Update UI at most ~10 times per second to avoid spamming main thread
                update_every = max(1, fps // 10 // chunk)
                update_counter = 0

                while not self._stop_flag.is_set():
                    while self._pause_flag.is_set() and not self._stop_flag.is_set():
                        self._stop_flag.wait(0.05)
                    with self._seek_lock:
                        target = self._seek_target_frame
                        self._seek_target_frame = None
                    if target is not None:
                        target = max(0, min(total_frames, target))
                        wf.setpos(target)
                        played = target
                        update_counter = update_every
                    data = wf.readframes(chunk)
                    if not data:
                        break
                    stream.write(data)
                    played = wf.tell()
                    update_counter += 1
                    if update_counter >= update_every:
                        update_counter = 0
                        elapsed = played / fps
                        total = total_frames / fps
                        self._sig_play_progress.emit(elapsed, total)

                stream.stop_stream()
                stream.close()
                wf.close()
            except Exception:
                pass
            finally:
                self._playing = False
                self._sig_playback_done.emit()

        self._play_thread = threading.Thread(target=play_worker, daemon=True)
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
        if not self._seeking or not hasattr(self, '_play_status') or not hasattr(self, '_seek_slider'):
            return
        total = self._seek_total
        if total <= 0:
            return
        elapsed = total * value / max(1, self._seek_slider.maximum())
        self._play_status.setText(ui_text("ui_sound_value_value_2", p0=_fmt_duration(elapsed), p1=_fmt_duration(total)))

    def _finish_seek(self):
        self._seeking = False
        if not hasattr(self, '_seek_slider'):
            return
        if self._seek_fps <= 0 or self._seek_total_frames <= 0:
            return
        ratio = self._seek_slider.value() / max(1, self._seek_slider.maximum())
        with self._seek_lock:
            self._seek_target_frame = int(self._seek_total_frames * ratio)

    def _update_play_progress(self, elapsed, total):
        if hasattr(self, '_play_status'):
            try:
                self._play_status.setText(
                    ui_text("ui_sound_value_value_2", p0=_fmt_duration(elapsed), p1=_fmt_duration(total)))
            except RuntimeError:
                pass
        self._seek_total = total
        if hasattr(self, '_seek_slider') and not self._seeking and total > 0:
            try:
                self._seek_slider.setValue(int((elapsed / total) * self._seek_slider.maximum()))
            except RuntimeError:
                pass

    def _on_playback_done(self):
        if hasattr(self, '_play_btn'):
            try:
                self._play_btn.setEnabled(True)
            except RuntimeError:
                pass
        if hasattr(self, '_pause_btn'):
            try:
                self._pause_btn.setEnabled(False)
                self._pause_btn.setText(ui_text("ui_sound_pause"))
            except RuntimeError:
                pass
        if hasattr(self, '_stop_btn'):
            try:
                self._stop_btn.setEnabled(False)
            except RuntimeError:
                pass
        if hasattr(self, '_play_status'):
            try:
                self._play_status.setText("")
            except RuntimeError:
                pass
        if hasattr(self, '_seek_slider'):
            try:
                self._seek_slider.setEnabled(False)
                self._seek_slider.setValue(0)
            except RuntimeError:
                pass

    def _stop_playback(self):
        self._stop_flag.set()
        self._pause_flag.clear()
        with self._seek_lock:
            self._seek_target_frame = None
        self._playing = False
        if hasattr(self, '_play_btn'):
            try:
                self._play_btn.setEnabled(True)
            except RuntimeError:
                pass
        if hasattr(self, '_pause_btn'):
            try:
                self._pause_btn.setEnabled(False)
                self._pause_btn.setText(ui_text("ui_sound_pause"))
            except RuntimeError:
                pass
        if hasattr(self, '_stop_btn'):
            try:
                self._stop_btn.setEnabled(False)
            except RuntimeError:
                pass
        if hasattr(self, '_seek_slider'):
            try:
                self._seek_slider.setEnabled(False)
            except RuntimeError:
                pass

    # Waveform

    def _draw_waveform(self, wav_data):
        if not hasattr(self, '_waveform_widget'):
            return
        widget = self._waveform_widget
        widget.clear()

        w = max(widget.width(), 200)
        h = widget.height() or 80
        mid = h // 2

        def compute():
            try:
                wf = wave.open(io.BytesIO(wav_data), 'rb')
                raw_pcm = wf.readframes(wf.getnframes())
                wf.close()
            except Exception:
                return None
            import struct as st
            count = len(raw_pcm) // 2
            if count == 0:
                return None
            samples = st.unpack(f'<{count}h', raw_pcm)
            step = max(1, count // w)
            lines = []
            for i in range(0, min(count, w * step), step):
                chunk = samples[i:i + step]
                if not chunk:
                    break
                x = len(lines)
                y_top = mid - int(max(chunk) / 32768 * mid)
                y_bot = mid - int(min(chunk) / 32768 * mid)
                lines.append((x, y_top, y_bot))
            return lines, mid, w

        def worker():
            result = compute()
            self._sig_waveform_ready.emit(result)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_draw_waveform(self, result):
        if not hasattr(self, '_waveform_widget'):
            return
        if result is None:
            self._waveform_widget.clear()
            return
        lines, mid, w = result
        self._waveform_widget.set_waveform(lines, mid, w)

    # Volume Control

    def _on_volume_slider(self, value):
        if hasattr(self, '_vol_label'):
            self._vol_label.setText(ui_text("ui_sound_value", p0=float(value)))

    def _set_volume_preset(self, value):
        if hasattr(self, '_vol_slider'):
            self._vol_slider.setValue(int(value * 100))
            self._on_volume_slider(value)

    def _apply_volume(self, idx, notify=True):
        """Apply the volume slider value to the HCA entry."""
        if not hasattr(self, '_vol_slider'):
            return
        new_vol = self._vol_slider.value() / 100.0
        entry = self._entries[idx]

        try:
            hca_bytes = self._get_entry_bytes(idx)
            modified = set_hca_volume(hca_bytes, new_vol)
            entry['_new_data'] = modified
            entry['size'] = len(modified)
            # Clear cached WAV so next play uses new volume
            self._wav_cache.pop(idx, None)
            self._mark_dirty()
            if notify:
                QMessageBox.information(self, self.t("dlg_title_success"),
                                        self.t("sound_volume_applied", vol=f"{new_vol:.2f}"))
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(e))

    # Export WAV

    def _export_wav(self, idx):
        """Export entry as decoded WAV file."""
        entry = self._entries[idx]

        default_name = f"entry_{entry['id']:03d}.wav"
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("sound_export_wav_title"),
            default_name, "WAV files (*.wav);;All files (*.*)")
        if not path:
            return
        path = _ensure_file_ext(path, '.wav')

        def worker():
            try:
                audio_bytes = self._get_entry_bytes(idx)
                wav_data = _decode_audio_to_wav(audio_bytes, entry.get('format', ''))
                with open(path, 'wb') as f:
                    f.write(wav_data)
                self._sig_export_success.emit(
                    self.t("sound_export_wav_success", name=os.path.basename(path)))
            except Exception as e:
                self._sig_export_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    # Extract / Replace

    def _extract_single(self, idx):
        entry = self._entries[idx]
        default_name = f"entry_{entry['id']:03d}.wav"

        path, _ = QFileDialog.getSaveFileName(
            self, self.t("sound_extract_title"),
            default_name, "WAV files (*.wav);;All files (*.*)")
        if not path:
            return
        path = _ensure_file_ext(path, '.wav')

        def worker():
            try:
                data = self._get_entry_bytes(idx)
                wav_data = _decode_audio_to_wav(data, entry.get('format', ''))
                with open(path, 'wb') as f:
                    f.write(wav_data)
                self._sig_export_success.emit(
                    self.t("sound_extract_success", name=os.path.basename(path),
                           size=_fmt_size(len(wav_data))))
            except Exception as e:
                self._sig_export_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _extract_all(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("sound_extract_all_title"))
        if not folder:
            return
        total = len(self._entries)
        if total == 0:
            return

        self._set_busy(
            True,
            self.t("sound_export_wav_title"),
            self.t("xfa_export_progress", done=0, total=total),
            0,
            total,
        )

        def worker():
            try:
                count = 0
                errors = []
                for i, entry in enumerate(self._entries):
                    progress_text = self.t("xfa_export_progress", done=i + 1, total=total)
                    self._sig_busy_progress.emit(progress_text, i + 1, total)
                    fname = f"entry_{entry['id']:03d}.wav"
                    try:
                        wav_data = self._wav_cache.get(i)
                        if wav_data is None:
                            data = self._get_entry_bytes(i)
                            wav_data = _decode_audio_to_wav(data, entry.get('format', ''))
                            self._wav_cache[i] = wav_data
                        with open(os.path.join(folder, fname), 'wb') as f:
                            f.write(wav_data)
                        count += 1
                    except Exception as e:
                        errors.append(f"{fname}: {e}")
                msg = self.t("sound_extract_all_success", n=count, folder=folder)
                if errors:
                    msg += "\n" + "\n".join(errors[:5])
                self._sig_export_success.emit(msg)
            except Exception as e:
                self._sig_export_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _replace_single(self, idx):
        """Open a file dialog and replace the entry at *idx* with the chosen audio."""
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("sound_replace_title"), game_files_dialog_dir(), _AUDIO_OPEN_FILTER)
        if not path:
            return

        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except OSError as e:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(e))
            return

        # Fast-path: file is already HCA — no subprocess needed.
        target_ext = _target_ext_for_entry(self._entries[idx])

        if target_ext == '.hca' and raw[:3] in (b'HCA', bytes([0xC8, 0xC3, 0xC1])):
            self._sig_convert_replace_done.emit(idx, raw)
            return
        if target_ext == '.adx' and raw[:2] == b'\x80\x00':
            self._sig_convert_replace_done.emit(idx, raw)
            return

        self._set_converting(True)

        def worker():
            try:
                if target_ext == '.hca':
                    converted = _encode_to_hca_python(raw)
                else:
                    raise ImportError(ui_text("sound_vgaudio_required_for_target", target=target_ext.upper().lstrip('.')))
            except ImportError as imp_err:
                # PyCriCodecs/soundfile not installed — try VGAudioCli as a last resort.
                cli = _auto_detect_vgaudio_cli()
                if not cli:
                    # Neither Python lib nor VGAudioCli available — tell user clearly.
                    self._sig_convert_error.emit(str(imp_err))
                    return
                try:
                    converted = _run_vgaudio_conversion(cli, raw, target_ext, path)
                except Exception as exc:
                    self._sig_convert_error.emit(str(exc))
                    return
            except Exception as exc:
                cli = _auto_detect_vgaudio_cli()
                if not cli:
                    self._sig_convert_error.emit(str(exc))
                    return
                try:
                    converted = _run_vgaudio_conversion(cli, raw, target_ext, path)
                except Exception as conv_exc:
                    self._sig_convert_error.emit(str(conv_exc))
                    return
            self._sig_convert_replace_done.emit(idx, converted)

        threading.Thread(target=worker, daemon=True).start()

    def _on_convert_replace_done(self, idx: int, hca_bytes: bytes) -> None:
        """Apply converted HCA bytes to the entry and refresh the UI."""
        self._set_converting(False)
        entry = self._entries[idx]
        entry['_new_data'] = hca_bytes
        entry['size'] = len(hca_bytes)
        entry['format'] = _detect_format(hca_bytes)
        self._wav_cache.pop(idx, None)
        self._populate_list()
        self._select_entry(idx)
        self._mark_dirty()
        QMessageBox.information(
            self, self.t("dlg_title_success"),
            self.t("sound_replace_success",
                   id=entry['id'], size=_fmt_size(len(hca_bytes))))

    # Add / Delete

    def _add_new_entry(self):
        """Open a file dialog, convert the chosen audio to HCA, and add it."""
        if self._entries is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("sound_add_title"), game_files_dialog_dir(), _AUDIO_OPEN_FILTER)
        if not path:
            return

        try:
            with open(path, 'rb') as f:
                raw = f.read()
        except OSError as e:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(e))
            return

        # Fast-path: already HCA.
        if raw[:3] in (b'HCA', bytes([0xC8, 0xC3, 0xC1])):
            self._sig_convert_add_done.emit(raw)
            return

        self._set_converting(True)

        def worker():
            try:
                hca = _encode_to_hca_python(raw)
            except ImportError as imp_err:
                cli = _auto_detect_vgaudio_cli()
                if not cli:
                    self._sig_convert_error.emit(str(imp_err))
                    return
                try:
                    hca = _run_vgaudio_conversion(cli, raw, '.hca', path)
                except Exception as exc:
                    self._sig_convert_error.emit(str(exc))
                    return
            except Exception as exc:
                cli = _auto_detect_vgaudio_cli()
                if not cli:
                    self._sig_convert_error.emit(str(exc))
                    return
                try:
                    hca = _run_vgaudio_conversion(cli, raw, '.hca', path)
                except Exception as conv_exc:
                    self._sig_convert_error.emit(str(conv_exc))
                    return
            self._sig_convert_add_done.emit(hca)

        threading.Thread(target=worker, daemon=True).start()

    def _on_convert_add_done(self, hca_bytes: bytes) -> None:
        """Append the converted HCA entry and refresh the UI."""
        self._set_converting(False)
        try:
            self._entries, self._meta = add_entry(
                self._entries, self._meta, audio_bytes=hca_bytes)
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(e))
            return
        self._wav_cache.clear()
        self._populate_list()
        self._select_entry(len(self._entries) - 1)
        self._mark_dirty()

    def _on_convert_error(self, msg: str) -> None:
        """Show a conversion error and restore the UI."""
        self._set_converting(False)
        QMessageBox.critical(self, self.t("dlg_title_error"), msg)

    def _set_converting(self, active: bool) -> None:
        """Disable or re-enable mutating controls while a conversion runs."""
        for name in ("_add_btn", "_dup_btn", "_del_btn", "_save_btn", "_extract_btn"):
            try:
                btn = getattr(self, name)
                btn.setEnabled(not active)
            except (AttributeError, RuntimeError):
                pass

    def _duplicate_entry(self):
        if self._current_entry is None or not self._entries:
            return
        try:
            data = self._get_entry_bytes(self._current_entry)
            self._entries, self._meta = add_entry(
                self._entries, self._meta, audio_bytes=data)
        except Exception as e:
            QMessageBox.critical(self, self.t("dlg_title_error"), str(e))
            return
        self._wav_cache.clear()
        self._populate_list()
        self._select_entry(len(self._entries) - 1)
        self._mark_dirty()

    def _delete_entry(self):
        if self._current_entry is None or not self._entries:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("sound_cannot_delete_last"))
            return
        entry = self._entries[self._current_entry]
        label = get_entry_label(entry['id'])
        reply = QMessageBox.question(
            self, self.t("dlg_title_confirm_delete"),
            self.t("sound_confirm_delete", id=entry['id'], name=label),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._entries, self._meta = delete_entry(
            self._entries, self._meta, self._current_entry)
        self._current_entry = None
        self._wav_cache.clear()
        self._populate_list()
        self._mark_dirty()

    def _mark_dirty(self):
        if self._dirty:
            return
        self._dirty = True
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=True)

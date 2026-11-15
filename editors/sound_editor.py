from core.design_tokens import (
    Insets,
    LayoutRole,
    Size,
    TypeSize,
    ui_font,
)
from core.style_helpers import (
    add_editor_card_title,
    make_editor_card,
    make_editor_field_shell,
    make_empty_state,
    ss_bg_dark,
    ss_blocking_overlay,
    ss_blocking_overlay_card,
    ss_dim_label,
    ss_progressbar,
    ss_transparent,
)
from core.ui.editor_widgets import (
    EditorActionRow,
    EditorFilterCombo,
    EditorSeparator,
    EditorSidebar,
    EditorToolbar,
    configure_button,
    configure_card,
    configure_file_label,
    configure_input,
    configure_layout,
    configure_scrollarea,
    configure_search,
)
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_actions import commit_save_path, editor_path, install_file_actions, refresh_file_actions
import os
import io
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

from core.audio_tools import AudioCache, scale_wav
from core.ui.record_list import EditorRecordList, RecordListModel

from PyQt6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QScrollArea,
    QFileDialog, QMessageBox, QProgressBar, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSignalBlocker

from core.editor_file_state import set_file_label, set_file_label_empty
from core.external_tools import find_vgaudio_cli, find_vgmstream_cli, is_tool_path, tool_command
from core.settings import create_backup_on_open, load_settings, save_settings, game_files_dialog_dir
from core.quiet_unlocks import request_and_cascade
from parsers.awb_parser import (
    parse_awb, extract_entry, rebuild_awb, save_awb,
    add_entry, delete_entry, get_entry_label, _detect_format,
)
from parsers.acb_parser import load_companion_acb_labels, parse_acb_awb_labels
from parsers.hca_decoder import parse_hca_info, decode_hca_to_wav
from core.translations import ui_text


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

_SLOW_ENCRYPTED_OFFSET = 64 * 1024 * 1024


def _ensure_file_ext(path: str, ext: str) -> str:
    return path if os.path.splitext(path)[1] else path + ext


def _import_pyaudio():
    from core.audio_tools import import_pyaudio
    return import_pyaudio()


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
    """Convert audio bytes to HCA using VGAudioCli at the given path.

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
            [*tool_command(cli_path), '-i', in_path, '-o', out_path],
            [*tool_command(cli_path), in_path, '-o', out_path],
        )
        last_result = None
        for command in commands:
            if os.path.isfile(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            last_result = subprocess.run(command, capture_output=True, timeout=60,
                                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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
            cmd = [*tool_command(cli_path), '-i', '-o', out_path, in_path]
        else:
            commands = (
                [*tool_command(cli_path), '-i', in_path, '-o', out_path],
                [*tool_command(cli_path), in_path, '-o', out_path],
            )
            last_result = None
            for command in commands:
                if os.path.isfile(out_path):
                    try:
                        os.remove(out_path)
                    except OSError:
                        pass
                last_result = subprocess.run(command, capture_output=True, timeout=60,
                                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
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

        result = subprocess.run(cmd, capture_output=True, timeout=60,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode != 0 or not os.path.isfile(out_path):
            stderr = result.stderr.decode(errors='replace').strip()
            stdout = result.stdout.decode(errors='replace').strip()
            details = stderr or stdout or ui_text("no_output")
            raise RuntimeError(ui_text("sound_vgaudio_exit_code", code=result.returncode, details=details))
        with open(out_path, 'rb') as f:
            return f.read()


def _auto_detect_vgaudio_cli() -> str:
    """Return VGAudioCli path from settings, tools/, or PATH.

    Never shows a dialog — returns an empty string when not found.
    """
    settings = load_settings()
    cli = settings.get('vgaudio_cli_path', '')
    if cli and is_tool_path(cli):
        return cli
    return find_vgaudio_cli()


def _auto_detect_decode_cli() -> str:
    """Return the best bundled decoder: vgmstream first, then VGAudioCli."""
    candidate = find_vgmstream_cli()
    if candidate:
        return candidate
    return _auto_detect_vgaudio_cli()


def _decode_audio_to_wav(audio_data: bytes, source_format: str = '', source_path: str = '', subkey=0) -> bytes:
    """Decode a single stream once; native CLI first, Python HCA fallback."""
    if audio_data[:4] == b'RIFF' and audio_data[8:12] == b'WAVE':
        return audio_data
    is_hca = source_format == 'HCA' or _detect_format(audio_data) == 'HCA'
    if is_hca and subkey and parse_hca_info(audio_data)['cipher_type'] == 56:
        raise ValueError(ui_text('awb_subkey_unsupported'))
    cli = find_vgmstream_cli()
    if cli:
        wav = _run_tool_decode_to_wav(cli, audio_data, source_path)
        # clHCA/vgmstream deliberately leaves RVA unapplied. Audition it explicitly.
        return scale_wav(wav, parse_hca_info(audio_data)['rva_volume']) if is_hca else wav
    if is_hca:
        return decode_hca_to_wav(audio_data)
    cli = _auto_detect_decode_cli()
    if not cli:
        raise RuntimeError(ui_text('sound_decode_tool_missing'))
    return _run_tool_decode_to_wav(cli, audio_data, source_path)


def _target_ext_for_entry(entry: dict) -> str:
    return '.adx' if entry.get('format') == 'ADX' else '.hca'


def _encode_to_hca_python(audio_data: bytes) -> bytes:
    """Convert audio to PCM WAV with SoundFile, then encode with CriCodecs.

    The callers retain the bundled VGAudioCLI fallback for unsupported inputs.
    """
    try:
        import soundfile as sf  # noqa: PLC0415
    except ImportError:
        sf = None

    from cricodecs import hca, wav  # noqa: PLC0415

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
        return hca.encode(wav.load(wav_data))
    except Exception as e:
        raise RuntimeError(ui_text("sound_hca_encode_failed", error=e)) from e


def _fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def _entry_needs_slow_seek(entry: dict) -> bool:
    return (
        entry.get('encryption') == 'asbr_cpk'
        and entry.get('size', 0) > 0
        and entry.get('offset', 0) >= _SLOW_ENCRYPTED_OFFSET
        and '_new_data' not in entry
        and '_prepared_data' not in entry
    )


def _fmt_duration(sec):
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:05.2f}"


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            widget = item.widget()
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _truncate(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[:max(1, limit - 3)] + "..."


from editors.sound_workspace import AudioWorkspace


class SoundEditor(AudioWorkspace, QWidget):
    # Signals for thread-safe UI updates
    _sig_load_done = pyqtSignal(str, object, list, dict)
    _sig_load_error = pyqtSignal(str)
    _sig_editor_ready = pyqtSignal(int, object)
    _sig_play_progress = pyqtSignal(int, float, float)
    _sig_playback_done = pyqtSignal(int, str)
    _sig_preview_ready = pyqtSignal(object)
    _sig_save_done = pyqtSignal(object)
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
        self._entry_labels = {}
        self._filepath = None
        self._fields = {}
        self._dirty = False
        self._decode_busy = False
        self._busy = False
        self._closed = False
        self._shutdown_event = threading.Event()

        # Audio playback state
        self._wav_cache = AudioCache()       # idx -> wav bytes
        self._original_raw = None
        self._original_entries = []
        self._preview_generation = 0
        self._preview_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='awb-preview')
        def shutdown_workers(*_, stopped=self._shutdown_event, pool=self._preview_pool):
            stopped.set()
            pool.shutdown(wait=False, cancel_futures=True)
        self.destroyed.connect(shutdown_workers)
        self._preview_future = self._metadata_future = None
        self._preview_active = None
        self._preview_wav = None
        self._play_generation = 0
        self._cursor_seconds = 0.
        self._audition_loop = threading.Event()
        self._original_mode = False
        self._playing = False
        self._play_thread = None
        self._stop_flag = threading.Event()
        self._pause_flag = threading.Event()
        self._seek_lock = threading.Lock()
        self._seek_total = 0.0
        self._seek_total_frames = 0
        self._seek_fps = 0

        # Connect signals
        self._sig_preview_ready.connect(self._preview_done)
        self._sig_save_done.connect(self._on_save_done)
        self._sig_load_done.connect(self._on_load_done)
        self._sig_load_error.connect(self._on_load_error)
        self._sig_editor_ready.connect(self._build_editor)
        self._sig_play_progress.connect(self._update_play_progress)
        self._sig_playback_done.connect(self._on_playback_done)
        self._sig_export_success.connect(self._on_export_success)
        self._sig_export_error.connect(self._on_export_error)
        self._sig_busy_progress.connect(self._on_busy_progress)
        self._sig_convert_replace_done.connect(self._on_convert_replace_done)
        self._sig_convert_add_done.connect(self._on_convert_add_done)
        self._sig_convert_error.connect(self._on_convert_error)

        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path), asynchronous=True)
        install_editor_chrome(self)

    def closeEvent(self, event):
        self._closed = True
        self._shutdown_event.set()
        self._stop_playback()
        self._preview_generation += 1
        self._preview_pool.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    # UI construction

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        configure_layout(root_layout, LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())

        # Top bar
        top = EditorToolbar()
        self._toolbar = top
        top_layout = top.content_layout

        open_btn = QPushButton(self.t("btn_open_file"))
        configure_button(open_btn, accent=True)
        open_btn.clicked.connect(self._load_file)
        open_btn.setProperty("designAction", 'open')
        top_layout.addWidget(open_btn)

        self._save_btn = QPushButton(self.t("btn_save_file"))
        self._save_btn.setEnabled(False)
        configure_button(self._save_btn, accent=True)
        self._save_btn.clicked.connect(self._save_file)
        top_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"))
        self._file_label.setMinimumWidth(0)
        self._file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        configure_file_label(self._file_label)
        top_layout.addWidget(self._file_label, 1)

        root_layout.addWidget(top)

        # Separator
        sep = EditorSeparator(accent=True)


        root_layout.addWidget(sep)

        # Main area
        main = QWidget()
        main_layout = QHBoxLayout(main)
        configure_layout(main_layout, LayoutRole.ROOT)

        # Entry list sidebar
        list_frame = EditorSidebar()


        list_vlayout = list_frame.content_layout


        # Search
        self._search_entry = QLineEdit()
        configure_search(self._search_entry)
        self._search_entry.textChanged.connect(lambda: self._filter_list())
        list_vlayout.addWidget(self._search_entry)

        # Action buttons
        actions_frame = EditorActionRow()

        actions_layout = actions_frame.content_layout


        btn_font = ui_font(TypeSize.BODY)

        self._add_btn = QPushButton(self.t("btn_new"))
        self._add_btn.setEnabled(False)
        configure_button(self._add_btn, height=Size.COMPACT_CONTROL)
        self._add_btn.clicked.connect(self._add_new_entry)
        self._add_btn.setProperty("designAction", 'new')
        actions_layout.addWidget(self._add_btn, 1)

        self._dup_btn = QPushButton(self.t("btn_dup_short"))
        self._dup_btn.setEnabled(False)
        configure_button(self._dup_btn, height=Size.COMPACT_CONTROL)
        self._dup_btn.clicked.connect(self._duplicate_entry)
        self._dup_btn.setProperty("designAction", 'duplicate')
        actions_layout.addWidget(self._dup_btn, 1)

        self._del_btn = QPushButton(self.t("btn_delete"))
        self._del_btn.setEnabled(False)
        configure_button(self._del_btn, danger=True, height=Size.COMPACT_CONTROL)
        self._del_btn.clicked.connect(self._delete_entry)
        self._del_btn.setProperty("designAction", 'delete')
        actions_layout.addWidget(self._del_btn, 1)

        list_vlayout.addWidget(actions_frame)

        self._format_filter = EditorFilterCombo()
        self._format_filter.addItem(ui_text('awb_filter_format'), None)
        for fmt in ('HCA', 'ADX', 'unknown'):
            self._format_filter.addItem(ui_text('awb_unknown_format') if fmt == 'unknown' else fmt, fmt)
        self._format_filter.currentIndexChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._format_filter)
        self._state_filter = EditorFilterCombo()
        self._state_filter.addItem(ui_text('awb_filter_state'), None)
        for key in ('modified', 'empty'):
            self._state_filter.addItem(ui_text('awb_filter_' + key), key)
        self._state_filter.currentIndexChanged.connect(self._filter_list)
        list_vlayout.addWidget(self._state_filter)
        self._record_model = RecordListModel(self)
        self._entry_scroll = EditorRecordList(self._record_model,
            lambda index: self._record_model.data(index, Qt.ItemDataRole.UserRole)[1:])
        self._entry_scroll.selectionModel().currentChanged.connect(self._list_selected)
        list_vlayout.addWidget(self._entry_scroll, 1)

        main_layout.addWidget(list_frame)

        # Vertical separator
        vsep = EditorSeparator(orientation=Qt.Orientation.Vertical)


        main_layout.addWidget(vsep)

        # Editor panel (scrollable)
        self._editor_scroll = QScrollArea()


        configure_scrollarea(self._editor_scroll)
        self._editor_widget = QWidget()
        self._editor_widget.setStyleSheet(ss_bg_dark())
        self._editor_layout = QVBoxLayout(self._editor_widget)
        configure_layout(self._editor_layout, LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_widget)

        self._show_placeholder()

        main_layout.addWidget(self._editor_scroll, 1)
        root_layout.addWidget(main, 1)
        self._build_busy_overlay()

    def _show_placeholder(self):
        _clear_layout(self._editor_layout)
        card = make_empty_state(
            self._editor_widget,
            title=self.t("no_file_loaded"),
            text=self.t("placeholder_sound"),
            icon_name="fa6s.music",
        )
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _build_busy_overlay(self):
        self._busy_overlay = QFrame(self)
        self._busy_overlay.setObjectName("BlockingOverlay")
        self._busy_overlay.setStyleSheet(ss_blocking_overlay())
        self._busy_overlay.hide()

        overlay_layout = QVBoxLayout(self._busy_overlay)
        overlay_layout.setContentsMargins(*Insets.NONE)
        overlay_layout.addStretch()

        card = QFrame()
        card.setObjectName("BlockingOverlayCard")
        card.setFixedWidth(360)
        card.setStyleSheet(ss_blocking_overlay_card())
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 18)
        card_layout.setSpacing(Size.CARD_GAP)

        self._busy_title_lbl = QLabel(self.t("loading"))

        configure_file_label(self._busy_title_lbl)
        self._busy_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._busy_title_lbl)

        self._busy_detail_lbl = QLabel("")

        configure_file_label(self._busy_detail_lbl)
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
        self._busy = active
        self._toolbar.setEnabled(not active)
        self._editor_widget.setEnabled(not active)
        self._entry_scroll.setEnabled(not active)
        refresh_file_actions(self)
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

    def _show_decode_busy(self, detail: str = ""):
        self._decode_busy = True
        self._set_busy(True, self.t("sound_status_decoding"), detail, 0, 0)

    def _hide_decode_busy(self):
        if self._decode_busy:
            self._decode_busy = False
            self._set_busy(False)

    def _on_export_success(self, msg: str):
        self._set_busy(False)
        QMessageBox.information(self, self.t("dlg_title_success"), msg)

    def _on_export_error(self, msg: str):
        self._set_busy(False)
        QMessageBox.critical(self, self.t("dlg_title_error"), msg)

    # File loading

    def _entry_label(self, entry) -> str:
        return self._entry_labels.get(entry.get('id')) or ui_text('awb_track_label', id=entry['id'])

    def _load_file(self):
        if not self._commit_volume():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self.t("file_open_sound"),
            game_files_dialog_dir(target_patterns=("*.awb", "*.acb")), "AWB files (*.awb);;All files (*.*)")
        if not path:
            return
        create_backup_on_open(path)
        self._preview_generation += 1
        self._preview_active = None
        self._stop_playback()
        self._wav_cache.clear()
        set_file_label_empty(self._file_label, self.t("loading"))
        self._show_list_skeleton()
        self._show_editor_skeleton()
        self._set_busy(True, self.t('loading'), os.path.basename(path))

        def worker():
            try:
                raw, entries, meta = parse_awb(path)
            except Exception as e:
                self._sig_load_error.emit(str(e))
                return
            try:
                labels, acb_path = load_companion_acb_labels(path)
                if labels:
                    meta['_entry_labels'] = labels
                    meta['_acb_path'] = acb_path
                elif not acb_path:
                    meta['_acb_missing'] = True
            except Exception as e:
                meta['_acb_error'] = str(e)
            self._sig_load_done.emit(path, raw, entries, meta)

        threading.Thread(target=worker, daemon=True).start()

    def _show_list_skeleton(self):
        self._record_model.reset_rows([])

    def _show_editor_skeleton(self):
        from core.skeleton import SkeletonBar
        self._clear_audio_controls()
        _clear_layout(self._editor_layout)

        hdr, hdr_layout = make_editor_card(self._editor_widget)
        hdr_layout.addWidget(SkeletonBar(height=36, corner_radius=5))
        self._editor_layout.addWidget(hdr)

        for _ in range(3):
            sec, sec_layout = make_editor_card(self._editor_widget)
            g = QGridLayout()
            g.setSpacing(Size.GAP)
            for col in range(3):
                f = QWidget()
                f.setStyleSheet(ss_transparent())
                f_layout = QVBoxLayout(f)
                configure_layout(f_layout, LayoutRole.FIELD)
                f_layout.addWidget(SkeletonBar(height=11, corner_radius=3))
                f_layout.addWidget(SkeletonBar(height=30, corner_radius=4))
                g.addWidget(f, 0, col)
            sec_layout.addLayout(g)
            self._editor_layout.addWidget(sec)

        self._editor_layout.addStretch()

    def _on_load_error(self, msg):
        if self._closed:
            return
        self._set_busy(False)
        # Keep the previous document available when another file cannot be opened.
        self._populate_list()
        if self._raw_data is None:
            self._show_placeholder()
            set_file_label_empty(self._file_label, self.t('no_file_loaded'))
        else:
            set_file_label(self._file_label, self._filepath, dirty=self._dirty)
        QMessageBox.critical(self, self.t('dlg_title_error'), self.t('msg_load_error', error=msg))

    def _on_load_done(self, path, raw, entries, meta):
        if self._closed:
            return
        self._set_busy(False)
        self._stop_playback()
        self._clear_audio_controls()
        self._preview_generation += 1
        self._wav_cache.clear()
        self._preview_wav = None
        self._original_raw = raw
        self._original_entries = [dict(entry) for entry in entries]
        for index, entry in enumerate(entries):
            entry['_source_index'] = index
        self._raw_data = raw
        self._entries = entries
        self._meta = meta
        self._entry_labels = dict(meta.get('_entry_labels') or {})
        self._filepath = path
        self._dirty = False
        set_file_label(self._file_label, path)

        self._save_btn.setEnabled(True)
        self._add_btn.setEnabled(True)
        self._dup_btn.setEnabled(bool(entries))
        self._del_btn.setEnabled(bool(entries))

        self._populate_list()
        if meta.get('_acb_missing'):
            self._prompt_for_acb_file(path)

    def _prompt_for_acb_file(self, awb_path: str):
        expected = os.path.splitext(os.path.basename(awb_path))[0] + ".acb"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(self.t("sound_acb_missing_title"))
        box.setText(self.t("sound_acb_missing_title"))
        box.setInformativeText(self.t("sound_acb_missing_detail", acb=expected))
        load_btn = box.addButton(self.t("sound_btn_load_acb"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() == load_btn:
            self._load_manual_acb_file()

    def _load_manual_acb_file(self):
        if not self._filepath or not self._commit_volume():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("sound_open_acb_title"),
            game_files_dialog_dir(target_patterns=("*.acb",)),
            "ACB files (*.acb);;All files (*.*)",
        )
        if not path:
            return
        try:
            labels = parse_acb_awb_labels(path)
        except Exception as e:
            QMessageBox.critical(
                self,
                self.t("dlg_title_error"),
                self.t("sound_acb_load_failed", error=str(e)),
            )
            return
        if not labels:
            QMessageBox.warning(
                self,
                self.t("dlg_title_warning"),
                self.t("sound_acb_no_labels"),
            )
            return

        self._entry_labels = dict(labels)
        if self._meta is not None:
            self._meta['_entry_labels'] = dict(labels)
            self._meta['_acb_path'] = path
            self._meta['_acb_missing'] = False
        current = self._current_entry
        self._populate_list()
        if current is not None and 0 <= current < len(self._entries):
            self._select_entry(current)

    # Save

    def _save_file(self, target_path=None):
        if self._busy:
            return
        save_path = target_path or editor_path(self)
        if self._raw_data is None or not save_path or not self._commit_volume():
            self._file_actions.pending_path = None
            self._file_actions.refresh()
            return
        raw, entries, meta = self._raw_data, [dict(e) for e in self._entries], dict(self._meta)
        changed = self._dirty
        self._set_busy(True, self.t('btn_save_file'), os.path.basename(save_path))
        def worker():
            try:
                if changed:
                    new_raw, new_entries, new_meta = rebuild_awb(entries, meta, raw)
                    saved = save_awb(save_path, new_raw, new_meta)
                    for old, new in zip(entries, new_entries):
                        if '_source_index' in old:
                            new['_source_index'] = old['_source_index']
                        if new_meta.get('encryption') == 'asbr_cpk':
                            new['encryption'], new['container_size'] = 'asbr_cpk', len(saved)
                else:
                    saved = save_awb(save_path, raw, dict(meta, encryption=None))
                    new_entries, new_meta = entries, meta
                result = (save_path, saved, new_entries, new_meta, '')
            except Exception as error:
                result = (save_path, None, None, None, str(error))
            try:
                self._sig_save_done.emit(result)
            except RuntimeError:
                return
        threading.Thread(target=worker, daemon=True).start()

    def _on_save_done(self, result):
        if self._closed:
            return
        path, raw, entries, meta, error = result
        self._set_busy(False)
        if error:
            self._file_actions.pending_path = None
            self._file_actions.refresh()
            QMessageBox.critical(self, self.t('dlg_title_error'), self.t('msg_save_error', error=error))
            return
        self._raw_data, self._entries, self._meta = raw, entries, meta
        commit_save_path(self, path)
        self._dirty = False
        set_file_label(self._file_label, path)
        self._wav_cache.clear()
        self._filter_list()
        request_and_cascade(self, 'Geb')
        QMessageBox.information(self, self.t('dlg_title_success'), self.t('msg_save_success', path=os.path.basename(path)))

    def _populate_list(self):
        self._filter_list()
        if self._entries:
            selected = self._current_entry
            if selected is None or selected >= len(self._entries):
                selected = next((i for i, e in enumerate(self._entries) if e.get('size', 0)), 0)
            self._select_entry(selected)
        else:
            self._current_entry = None
            self._show_placeholder()
        self._dup_btn.setEnabled(bool(self._entries))
        self._del_btn.setEnabled(bool(self._entries))

    def _filter_list(self):
        if not hasattr(self, '_record_model'):
            return
        query = self._search_entry.text().casefold().strip()
        fmt, state = self._format_filter.currentData(), self._state_filter.currentData()
        rows = []
        for index, entry in enumerate(self._entries):
            title = self._entry_label(entry)
            modified = '_new_data' in entry
            format_label = ui_text('awb_unknown_format') if entry['format'] == 'unknown' else entry['format']
            subtitle = f"ID {entry['id']} · {format_label} · {_fmt_size(entry['size'])}"
            if modified:
                subtitle += ' · ' + ui_text('awb_filter_modified')
            if ((fmt and entry['format'] != fmt) or
                (state == 'modified' and not modified) or
                (state == 'empty' and entry['size'] > 0)):
                continue
            if query and query not in (title + ' ' + subtitle).casefold():
                continue
            rows.append((index, title, subtitle, title + '\n' + subtitle))
        with QSignalBlocker(self._entry_scroll.selectionModel()):
            self._record_model.reset_rows(rows)
            self._sync_list_selection()

    def _sync_list_selection(self):
        for row, record in enumerate(self._record_model.rows):
            if record[0] == self._current_entry:
                with QSignalBlocker(self._entry_scroll.selectionModel()):
                    self._entry_scroll.setCurrentIndex(self._record_model.index(row, 0))
                return
        self._entry_scroll.selectionModel().clear()

    def _list_selected(self, current, previous):
        if current.isValid():
            if not self._select_entry(self._record_model.rows[current.row()][0]):
                self._sync_list_selection()

    def _select_entry(self, idx):
        if not 0 <= idx < len(self._entries) or not self._commit_volume():
            return False
        self._stop_playback()
        self._preview_generation += 1
        generation = self._preview_generation
        self._preview_active = None
        self._preview_wav = None
        self._cursor_seconds = 0.
        self._original_mode = False
        self._current_entry = idx
        self._sync_list_selection()
        self._show_editor_skeleton()
        entry, raw = dict(self._entries[idx]), self._raw_data
        def worker():
            info = None
            detected = entry['format']
            if not _entry_needs_slow_seek(entry):
                try:
                    data = entry.get('_new_data', entry.get('_prepared_data'))
                    if data is None:
                        data = extract_entry(raw, entry)
                    detected = _detect_format(data)
                    info = parse_hca_info(data) if detected == 'HCA' else None
                except Exception:
                    pass
            if generation == self._preview_generation:
                try:
                    self._sig_editor_ready.emit(idx, (generation, info, None, detected))
                except RuntimeError:
                    return
        if self._metadata_future is not None:
            self._metadata_future.cancel()
        self._metadata_future = self._preview_pool.submit(worker)
        return True

    def _build_editor(self, idx, hca_info=None):
        if isinstance(hca_info, tuple):
            generation, hca_info, *prepared = hca_info
            if generation != self._preview_generation:
                return
            if prepared and prepared[0] is not None:
                self._entries[idx]['_prepared_data'] = prepared[0]
                self._entries[idx]['format'] = _detect_format(prepared[0])
            elif len(prepared) > 1:
                self._entries[idx]['format'] = prepared[1]
        if self._current_entry != idx:
            return  # User already clicked another entry
        self._hide_decode_busy()
        self._filter_list()
        _clear_layout(self._editor_layout)
        self._fields = {}
        self._clear_audio_controls()
        entry = self._entries[idx]

        # Header
        hdr, hdr_layout = make_editor_card(self._editor_widget)
        self._prep_card(hdr)
        title = self._entry_label(entry)
        add_editor_card_title(
            hdr_layout,
            ui_text("ui_sound_value_value", p0=entry['id'], p1=title),
            "fa6s.music",
            f"{entry.get('format', '').upper()}  |  {entry.get('size', 0):,} bytes",
        )
        self._editor_layout.addWidget(hdr)

        if _entry_needs_slow_seek(entry) and not hca_info:
            sec_slow = self._make_section(ui_text("sound_slow_encrypted_title"))
            slow_frame = QWidget()
            slow_frame.setStyleSheet(ss_transparent())
            slow_layout = QHBoxLayout(slow_frame)
            configure_layout(slow_layout, LayoutRole.TITLE)

            slow_lbl = QLabel(ui_text("sound_slow_encrypted_detail"))
            slow_lbl.setWordWrap(True)
            slow_lbl.setFont(ui_font(TypeSize.CODE))
            slow_lbl.setStyleSheet(ss_dim_label())
            slow_layout.addWidget(slow_lbl, 1)

            prepare_btn = QPushButton(ui_text("sound_btn_prepare_audio"))
            configure_button(prepare_btn, accent=True, height=Size.CONTROL)
            prepare_btn.clicked.connect(lambda: self._prepare_entry_info(idx))
            slow_layout.addWidget(prepare_btn)
            sec_slow.layout().addWidget(slow_frame)

        if entry.get('size', 0):
            self._build_audio_workspace(idx, hca_info)

        # Actions
        sec_act = self._make_section(self.t("sound_section_actions"))
        act_frame = QWidget()
        act_frame.setStyleSheet(ss_transparent())
        act_layout = configure_layout(QGridLayout(act_frame), LayoutRole.GRID)
        actions = ((ui_text('ui_sound_extract_audio'), lambda: self._extract_single(idx)),
                   (ui_text('ui_sound_replace_audio'), lambda: self._replace_single(idx)),
                   (ui_text('ui_sound_extract_all'), self._extract_all),
                   (ui_text('awb_export_encoded'), lambda: self._extract_encoded(idx)),
                   (ui_text('sound_btn_load_acb'), self._load_manual_acb_file))
        for position, (caption, callback) in enumerate(actions):
            button = configure_button(QPushButton(caption))
            button.clicked.connect(callback)
            act_layout.addWidget(button, position // 2, position % 2)
            if position == 2:
                self._extract_btn = button
        sec_act.layout().addWidget(act_frame)

        # Container Info
        # Analysis
        self._editor_layout.addStretch()

    def _make_section(self, title):
        sec, sec_layout = make_editor_card(self._editor_widget)
        self._prep_card(sec)
        icon_name = "fa6s.sliders"
        if title == self.t("sound_section_playback"):
            icon_name = "fa6s.play"
        elif title == self.t("sound_section_volume"):
            icon_name = "fa6s.volume-high"
        elif title == self.t("sound_section_actions"):
            icon_name = "fa6s.screwdriver-wrench"
        add_editor_card_title(sec_layout, title, icon_name)
        self._editor_layout.addWidget(sec)
        return sec

    def _prep_card(self, card: QWidget, *, max_width: int = 16777215):
        configure_card(card, maximum_width=max_width, vertical_policy=QSizePolicy.Policy.Maximum)

    def _add_field(self, parent_grid, label, value, key, row=0, col=0, readonly=False):
        frame, f_layout, _label, _hint = make_editor_field_shell(label)
        frame.setMinimumWidth(0)
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        ent = QLineEdit(value)
        ent.setMinimumWidth(0)
        ent.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        configure_input(ent, monospace=True)
        ent.setCursorPosition(0)
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
        if '_prepared_data' in entry:
            return entry['_prepared_data']
        return extract_entry(self._raw_data, entry)

    def _prepare_entry_info(self, idx):
        generation = self._preview_generation
        entry, raw = dict(self._entries[idx]), self._raw_data
        self._show_decode_busy(ui_text('sound_slow_prepare_detail', id=entry['id']))
        def worker():
            try:
                data = extract_entry(raw, entry)
                info = parse_hca_info(data) if _detect_format(data) == 'HCA' else None
                if generation == self._preview_generation:
                    self._sig_editor_ready.emit(idx, (generation, info, data))
            except Exception as error:
                if generation == self._preview_generation:
                    try:
                        self._sig_preview_ready.emit((generation, idx, None, None, None, str(error)))
                    except RuntimeError:
                        return
        threading.Thread(target=worker, daemon=True).start()

    def _resolve_vgaudio_cli(self) -> str:
        """Return VGAudioCli path, prompting the user if not yet configured.

        Must be called from the main (UI) thread because it may open a file
        dialog.  Raises RuntimeError when the user cancels or the path is
        invalid.
        """
        settings = load_settings()
        cli = settings.get('vgaudio_cli_path', '')
        if cli and not is_tool_path(cli):
            cli = ''

        if not cli:
            cli = _auto_detect_vgaudio_cli()

        if not cli:
            cli, _ = QFileDialog.getOpenFileName(
                self, ui_text("ui_sound_vgaudiocli_exe"), "", "VGAudioCli (VGAudioCli VGAudioCli.exe VGAudioCli.dll);;All files (*.*)")
            if not cli or not is_tool_path(cli):
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

    # Export WAV

    def _export_wav(self, idx):
        """Export entry as decoded WAV file."""
        if not self._commit_volume():
            return
        entry = self._entries[idx]

        default_name = f"entry_{entry['id']:03d}.wav"
        path, _ = QFileDialog.getSaveFileName(
            self, self.t("sound_export_wav_title"),
            default_name, "WAV files (*.wav);;All files (*.*)")
        if not path:
            return
        path = _ensure_file_ext(path, '.wav')
        self._set_busy(True, self.t("sound_status_decoding"), os.path.basename(path), 0, 0)

        def worker():
            try:
                audio_bytes = self._get_entry_bytes(idx)
                wav_data = _decode_audio_to_wav(audio_bytes, entry.get('format', ''), subkey=self._meta.get('subkey', 0))
                with open(path, 'wb') as f:
                    f.write(wav_data)
                self._sig_export_success.emit(
                    self.t("sound_export_wav_success", name=os.path.basename(path)))
            except Exception as e:
                self._sig_export_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    # Extract / Replace

    def _extract_single(self, idx):
        if not self._commit_volume():
            return
        entry = self._entries[idx]
        default_name = f"entry_{entry['id']:03d}.wav"

        path, _ = QFileDialog.getSaveFileName(
            self, self.t("sound_extract_title"),
            default_name, "WAV files (*.wav);;All files (*.*)")
        if not path:
            return
        path = _ensure_file_ext(path, '.wav')
        self._set_busy(True, self.t("sound_status_decoding"), os.path.basename(path), 0, 0)

        def worker():
            try:
                data = self._get_entry_bytes(idx)
                wav_data = _decode_audio_to_wav(data, entry.get('format', ''), subkey=self._meta.get('subkey', 0))
                with open(path, 'wb') as f:
                    f.write(wav_data)
                self._sig_export_success.emit(
                    self.t("sound_extract_success", name=os.path.basename(path),
                           size=_fmt_size(len(wav_data))))
            except Exception as e:
                self._sig_export_error.emit(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _extract_all(self):
        if not self._commit_volume():
            return
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
                            wav_data = _decode_audio_to_wav(data, entry.get('format', ''), subkey=self._meta.get('subkey', 0))
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
        if not self._commit_volume():
            return
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
                # Python encoder unavailable; use the bundled VGAudioCLI fallback.
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
        if not self._commit_volume():
            return
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
        self._set_busy(active, ui_text('sound_status_decoding'))
        for name in ("_add_btn", "_dup_btn", "_del_btn", "_save_btn", "_extract_btn"):
            try:
                btn = getattr(self, name)
                btn.setEnabled(not active)
            except (AttributeError, RuntimeError):
                pass

    def _duplicate_entry(self):
        if not self._commit_volume():
            return
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
        if not self._commit_volume():
            return
        if self._current_entry is None or not self._entries:
            return
        if len(self._entries) <= 1:
            QMessageBox.warning(self, self.t("dlg_title_warning"),
                                self.t("sound_cannot_delete_last"))
            return
        entry = self._entries[self._current_entry]
        label = self._entry_label(entry)
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

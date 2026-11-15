"""Native-preserving NUS3BANK workspace and decoded stream audition."""
import copy
import io
import os
import struct
import math
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from PyQt6.QtCore import Qt, pyqtSignal, QSignalBlocker, QTimer
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QComboBox, QCheckBox, QFileDialog, QMessageBox,
    QSizePolicy)
from core.audio_tools import AudioCache, analyze_wav, import_pyaudio
from core.design_tokens import LayoutRole, Size, TypeSize, ui_font
from core.editor_file_state import set_file_label
from core.quiet_unlocks import request_and_cascade
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.external_tools import find_vgmstream_cli, find_vgaudio_cli
from core.style_helpers import (make_editor_card, add_editor_card_title, make_editor_field_shell,
    make_empty_state, ss_bg_dark, ss_dim_label, ss_error_label, ss_check, ss_input_validation)
from core.translations import ui_text
from core.ui.audio_waveform import AudioWaveform
from core.ui.editor_actions import install_file_actions, commit_save_path, editor_path
from core.ui.editor_chrome import install_editor_chrome
from core.ui.editor_widgets import (EditorToolbar, EditorSidebar, EditorSeparator, EditorActionRow,
    EditorFilterCombo, configure_layout, configure_button, configure_input, configure_file_label,
    configure_search, configure_scrollarea, configure_card, fit_scroll_page)
from core.ui.number_input import FloatSliderInput
from core.ui.record_list import RecordListModel, EditorRecordList
from core.ui.timeline_controls import timeline_icon_button
from core.xfbin_audio_tools import (decode_audio, import_audio, stream_loop, set_stream_loop,
    tone_state, export_filename)
from parsers.nus3bank_parser import (parse_xfbin_audio, save_xfbin_audio, set_tone_bnsf,
    parse_audio_meta, ToneEntry)

_AUDIO_OPEN_FILTER = 'Audio (*.wav *.mp3 *.flac *.ogg *.opus *.aiff *.aif *.m4a *.aac *.wv *.wma *.bnsf *.hca *.adx *.bin);;All files (*)'


# Display-unit conversion; slider spans are authoring conveniences, not file limits.
_DISPLAY_UNITS = {'pitch_cents': (Decimal('.01'), Decimal(0)),
                  'volume': (Decimal(100), Decimal(0)),
                  'pitch': (Decimal(-100), Decimal(100)),
                  'send_level': (Decimal(100), Decimal(0))}


def _display_text(name, value):
    scale, offset = _DISPLAY_UNITS.get(name, (Decimal(1), Decimal(0)))
    number = Decimal(str(value))
    return format(float(number * scale + offset), '.7g') if number.is_finite() else str(value)


def _decode_bnsf_to_wav(blob, cli=''):
    return decode_audio(blob, cli)


def _detect_audio_tool():
    return dict(decode=find_vgmstream_cli(), encode=find_vgaudio_cli())


def _fmt_dur(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f'{int(minutes)}:{seconds:06.3f}'


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()


class XfbinAudioEditor(QWidget):
    defer_file_load_notification = True
    _sig_load_done = pyqtSignal(str, object, list)
    _sig_load_err = pyqtSignal(str)
    _sig_preview = pyqtSignal(int, object, object, str)
    _sig_play = pyqtSignal(int, float, str)
    _sig_job = pyqtSignal(str, object, str)
    _sig_progress = pyqtSignal(str)
    _sig_save_done = pyqtSignal(str)
    _sig_save_err = pyqtSignal(str)

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or ui_text
        self._filepath, self._raw, self._banks = None, None, []
        self._cur_bank, self._cur_tone = 0, -1
        self._dirty, self._busy, self._closed = False, False, False
        self._originals, self._saved_state = {}, None
        self._templates = {}
        self._wav_cache = AudioCache()
        self._generation, self._play_generation = 0, 0
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='xfb-audio')
        self._preview_future = None
        self._wav, self._envelope = None, None
        self._player, self._playing = None, False
        self._fields = {}
        self._building = False
        self.destroyed.connect(lambda: self._dispose())
        self._sig_load_done.connect(self._on_load_done)
        self._sig_load_err.connect(self._on_load_err)
        self._sig_preview.connect(self._on_preview)
        self._sig_play.connect(self._on_play_event)
        self._sig_job.connect(self._on_job)
        self._sig_progress.connect(self._set_status)
        self._sig_save_done.connect(self._on_save_done)
        self._sig_save_err.connect(self._on_save_err)
        self._build_ui()
        install_file_actions(self, self._save_btn, save_to=lambda path: self._save_file(target_path=path), asynchronous=True)
        install_editor_chrome(self)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())
        self._toolbar = EditorToolbar()
        row = self._toolbar.content_layout
        self._open_btn = configure_button(QPushButton(ui_text('btn_open_file')), accent=True)
        self._open_btn.setProperty('designAction', 'open')
        self._open_btn.clicked.connect(lambda: self._load_file())
        row.addWidget(self._open_btn)
        self._save_btn = configure_button(QPushButton(ui_text('btn_save_file')), accent=True)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(lambda: self._save_file())
        row.addWidget(self._save_btn)
        self._file_lbl = configure_file_label(QLabel(ui_text('cpk_no_file')))
        self._file_lbl.setMinimumWidth(0)
        self._file_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self._file_lbl, 1)
        root.addWidget(self._toolbar)
        root.addWidget(EditorSeparator(accent=True))
        main = QWidget()
        body = configure_layout(QHBoxLayout(main), LayoutRole.ROOT)
        self._sidebar = EditorSidebar()
        side = self._sidebar.content_layout
        self._bank_combo = configure_input(QComboBox(), monospace=False)
        self._bank_combo.setMinimumWidth(0)
        self._bank_combo.setToolTip(ui_text('xfa_bank_hint'))
        self._bank_combo.currentIndexChanged.connect(self._on_bank_changed)
        self._search = configure_search(QLineEdit())
        self._search.textChanged.connect(self._filter_tones)
        side.addWidget(self._search)
        self._state_filter = EditorFilterCombo()
        for key, value in (('xfa_filter_state', None), ('xfa_edited', 'edited'), ('xfa_looped', 'loop')):
            self._state_filter.addItem(ui_text(key), value)
        self._state_filter.currentIndexChanged.connect(self._filter_tones)
        actions = EditorActionRow()
        for attr, key, callback, action in (('_add_btn', 'btn_new', self._add_tone, 'new'),
                ('_dup_btn', 'btn_duplicate', self._duplicate_tone, 'duplicate'),
                ('_del_btn', 'btn_delete', self._delete_tone, 'delete')):
            button = configure_button(QPushButton(ui_text(key)), danger=action == 'delete', height=Size.COMPACT_CONTROL)
            button.setEnabled(False)
            button.setProperty('designAction', action)
            button.clicked.connect(callback)
            setattr(self, attr, button)
            actions.content_layout.addWidget(button, 1)
        side.addWidget(actions)
        side.addWidget(self._bank_combo)
        side.addWidget(self._state_filter)
        self._list_model = RecordListModel(self)
        self._tone_list = EditorRecordList(self._list_model, self._describe_tone)
        self._tone_list.selectionModel().currentRowChanged.connect(self._catalog_selected)
        side.addWidget(self._tone_list, 1)
        body.addWidget(self._sidebar)
        body.addWidget(EditorSeparator(orientation=Qt.Orientation.Vertical))
        self._editor_scroll = configure_scrollarea(QScrollArea())
        self._editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._editor_inner = QWidget()
        self._editor_inner.setMinimumWidth(0)
        self._editor_layout = configure_layout(QVBoxLayout(self._editor_inner), LayoutRole.PAGE)
        self._editor_scroll.setWidget(self._editor_inner)
        body.addWidget(self._editor_scroll, 1)
        root.addWidget(main, 1)
        self._status = QLabel('')
        self._status.setWordWrap(True)
        self._status.setStyleSheet(ss_dim_label())
        root.addWidget(self._status)
        self._show_placeholder()

    def _show_placeholder(self, text=None):
        self._generation += 1
        self._wav, self._envelope = None, None
        for name in ('_play_btn', '_pause_btn', '_stop_btn', '_wave_widget', '_prog_lbl'):
            if hasattr(self, name):
                delattr(self, name)
        self._fields = {}
        _clear_layout(self._editor_layout)
        self._editor_layout.addStretch()
        self._editor_layout.addWidget(make_empty_state(self._editor_inner,
            title=ui_text('no_file_loaded') if not self._filepath else ui_text('select_entry'),
            text=text or ui_text('xfa_placeholder')), 0, Qt.AlignmentFlag.AlignCenter)
        self._editor_layout.addStretch()

    def _set_status(self, text):
        self._status.setText(text)

    def _set_busy(self, active, *args):
        self._busy = active
        self._toolbar.setEnabled(not active)
        self._sidebar.setEnabled(not active)
        self._editor_inner.setEnabled(not active)
        self._save_btn.setEnabled(bool(self._banks) and not active)
        if hasattr(self, '_file_actions'):
            self._file_actions.refresh()
        if active:
            self._set_status(ui_text('loading'))

    def _load_file(self, path=None):
        if self._busy or not self._apply_params():
            return False
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, ui_text('xfa_open_dlg'),
                game_files_dialog_dir(target_patterns=('battle.xfbin', '*.xfbin')), 'XFBIN (*.xfbin);;All files (*)')
        if not path:
            return False
        path = os.path.abspath(os.fspath(path))
        self._stop_playback()
        self._generation += 1
        self._set_busy(True)
        def worker():
            try:
                raw, banks = parse_xfbin_audio(path)
                if not banks:
                    raise ValueError(ui_text('ui_xfbin_audio_no_embedded_nus3bank_bnsf_audio_entries_were_found_in_t'))
                create_backup_on_open(path)
                if not self._closed:
                    self._sig_load_done.emit(path, raw, banks)
            except Exception as error:
                if not self._closed:
                    self._sig_load_err.emit(str(error))
        self._pool.submit(worker)
        return True

    def _on_load_done(self, path, raw, banks):
        if self._closed:
            return
        self._stop_playback()
        self._filepath, self._raw, self._banks = path, raw, banks
        self._originals = {id(tone): (tone, copy.deepcopy(tone)) for bank in banks for tone in bank.tones}
        self._templates = {id(bank): copy.deepcopy(bank.tones[0]) for bank in banks if bank.tones}
        self._saved_state = self._document_state()
        self._dirty = False
        self._fields = {}
        self._cur_bank, self._cur_tone = 0, -1
        self._wav_cache.clear()
        with QSignalBlocker(self._bank_combo):
            self._bank_combo.clear()
            for i, bank in enumerate(banks):
                self._bank_combo.addItem(bank.name or f'Bank {i}', i)
            self._bank_combo.setCurrentIndex(0)
        self._set_busy(False)
        set_file_label(self._file_lbl, path)
        self._populate_tone_list()
        self._set_status('')

    def _on_load_err(self, message):
        self._set_busy(False)
        self._set_status(message)
        if self._tone() is not None and self._wav is None:
            self._request_preview()
        QMessageBox.critical(self, ui_text('dlg_title_error'), message)

    def _document_state(self):
        return tuple(tuple(('tone', tone_state(record)) if isinstance(record, ToneEntry)
                           else ('opaque', bytes(record))
                           for record in bank._tone_records) for bank in self._banks)

    def _original(self, tone):
        pair = self._originals.get(id(tone))
        return pair[1] if pair and pair[0] is tone else None

    def _modified(self, tone):
        original = self._original(tone)
        return original is None or tone_state(original) != tone_state(tone)

    def _tone(self):
        if self._banks and 0 <= self._cur_tone < len(self._banks[self._cur_bank].tones):
            return self._banks[self._cur_bank].tones[self._cur_tone]
        return None

    def _describe_tone(self, index):
        title, idx, subtitle = index.data(Qt.ItemDataRole.UserRole)
        return title, subtitle, title + '\n' + subtitle

    def _filter_tones(self, *_):
        rows = []
        tone = self._tone()
        if self._banks:
            query, state = self._search.text().casefold(), self._state_filter.currentData()
            edited_caption = ui_text('xfa_edited')
            bank = self._banks[self._cur_bank]
            slots = {id(record): i for i, record in enumerate(bank._tone_records)}
            for i, entry in enumerate(bank.tones):
                info = parse_audio_meta(entry._bnsf_blob or b'')
                codec = info['codec'] if info else '?'
                title = entry.name or f'Tone {i}'
                duration = _fmt_dur(info['total_samples'] / info['sample_rate']) if info else '?'
                subtitle = f'#{slots.get(id(entry), i)} · {codec} · {duration}'
                if self._modified(entry):
                    subtitle += ' · ' + ui_text('xfa_edited')
                if query and query not in (title + ' ' + subtitle).casefold():
                    continue
                if state == 'edited' and not self._modified(entry) or state == 'loop' and not stream_loop(entry._bnsf_blob or b''):
                    continue
                rows.append((title, i, subtitle))
        with QSignalBlocker(self._tone_list.selectionModel()):
            self._list_model.reset_rows(rows)
            selected = next((r for r, row in enumerate(rows) if self._banks[self._cur_bank].tones[row[1]] is tone), -1)
            self._tone_list.setCurrentIndex(self._list_model.index(selected, 0))
        self._tone_list.refresh()

    def _populate_tone_list(self, selected=None):
        self._filter_tones()
        self._add_btn.setEnabled(bool(self._banks and id(self._banks[self._cur_bank]) in self._templates) and not self._busy)
        tones = self._banks[self._cur_bank].tones if self._banks else []
        if tones:
            self._select_tone(min(selected if selected is not None else max(0, self._cur_tone), len(tones) - 1), force=True)
        else:
            self._cur_tone = -1
            self._del_btn.setEnabled(False)
            self._dup_btn.setEnabled(False)
            key = 'xfa_empty_bank' if self._banks and id(self._banks[self._cur_bank]) in self._templates else 'xfa_no_template'
            self._show_placeholder(ui_text(key) if self._banks else None)

    def _catalog_selected(self, index, previous):
        if index.isValid() and not self._select_tone(index.data(Qt.ItemDataRole.UserRole)[1]):
            with QSignalBlocker(self._tone_list.selectionModel()):
                self._tone_list.setCurrentIndex(previous)

    def _on_bank_changed(self, index):
        if index < 0 or index >= len(self._banks) or index == self._cur_bank:
            return
        if self._busy or not self._apply_params():
            with QSignalBlocker(self._bank_combo):
                self._bank_combo.setCurrentIndex(self._cur_bank)
            return
        self._stop_playback()
        self._cur_bank, self._cur_tone = index, -1
        self._fields = {}
        self._populate_tone_list()

    def _select_tone(self, index, force=False):
        if not self._banks or not 0 <= index < len(self._banks[self._cur_bank].tones):
            return False
        if not force and (self._busy or not self._apply_params()):
            return False
        if index == self._cur_tone and not force:
            return True
        self._stop_playback()
        self._generation += 1
        self._cur_tone = index
        self._wav, self._envelope = None, None
        self._del_btn.setEnabled(True)
        self._dup_btn.setEnabled(True)
        self._build_editor(self._cur_bank, index, self._tone())
        self._filter_tones()
        self._tone_list.scrollTo(self._tone_list.currentIndex())
        self._request_preview()
        return True

    def _make_section(self, title, icon='fa6s.sliders'):
        card, layout = make_editor_card()
        configure_card(card, maximum_width=16777215, vertical_policy=QSizePolicy.Policy.Maximum)
        add_editor_card_title(layout, title, icon)
        self._editor_layout.addWidget(card)
        return layout

    def _hint(self, layout, key, **values):
        label = QLabel(ui_text(key, **values))
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_dim_label())
        layout.addWidget(label)
        return label

    def _field(self, layout, key, edit, hint=''):
        shell, content, label, _ = make_editor_field_shell(ui_text(key), ui_text(hint) if hint and hint not in ('xfa_exact_hint', 'xfa_unknown_hint') else '')
        content.addWidget(edit)
        edit.setAccessibleName(ui_text(key))
        if hint:
            edit.setToolTip(ui_text(hint))
        layout.addWidget(shell)

    def _build_editor(self, bank_index, tone_index, tone):
        self._building = True
        self._fields = {}
        _clear_layout(self._editor_layout)
        header = self._make_section(tone.name or f'Tone {tone_index}', 'fa6s.music')
        self._name_edit = configure_input(QLineEdit(tone.name))
        self._field(header, 'xfa_tone_name', self._name_edit, 'xfa_name_hint')
        self._fields['name'] = (self._name_edit, tone.name)
        self._name_edit.editingFinished.connect(self._apply_params)
        self._name_edit.textChanged.connect(self._mark_dirty)
        layout = self._make_section(ui_text('sound_section_playback'), 'fa6s.wave-square')
        self._source_combo = configure_input(QComboBox(), monospace=False)
        self._source_combo.addItem(ui_text('awb_source_current'), False)
        if self._original(tone):
            self._source_combo.addItem(ui_text('awb_source_original'), True)
        self._source_combo.currentIndexChanged.connect(self._change_source)
        layout.addWidget(self._source_combo)
        controls = QWidget()
        row = configure_layout(QHBoxLayout(controls), LayoutRole.FIELD)
        self._play_btn = timeline_icon_button(ui_text('ui_xfbin_audio_play'), 'fa6s.play', self._play_tone)
        self._pause_btn = timeline_icon_button(ui_text('ui_sound_pause'), 'fa6s.pause', self._toggle_pause)
        self._stop_btn = timeline_icon_button(ui_text('ui_xfbin_audio_stop'), 'fa6s.stop', self._stop_playback)
        for button in (self._play_btn, self._pause_btn, self._stop_btn):
            row.addWidget(button)
        self._play_btn.setToolTip(ui_text('xfa_play_decoded_hint'))
        self._play_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._prog_lbl = QLabel('')
        self._prog_lbl.setMinimumWidth(0)
        self._prog_lbl.setStyleSheet(ss_dim_label())
        row.addWidget(self._prog_lbl, 1)
        layout.addWidget(controls)
        self._wave_widget = AudioWaveform()
        self._wave_widget.loop_min_samples = 2
        self._wave_widget.loopSelectionChanged.connect(self._loop_selection_changed)
        self._wave_widget.seekRequested.connect(self._seek_to)
        self._wave_widget.loopEditRequested.connect(self._edit_loop_markers)
        layout.addWidget(self._wave_widget)
        self._preview_stats = self._hint(layout, 'loading')
        info = parse_audio_meta(tone._bnsf_blob or b'')
        bounds = stream_loop(tone._bnsf_blob or b'')
        self._loop_total = info['total_samples'] if info else 0
        self._loop_bounds = bounds or (0, self._loop_total)
        loop_row = EditorActionRow()
        self._loop_chk = QCheckBox(ui_text('xfa_loop_short'))
        self._loop_chk.setStyleSheet(ss_check())
        self._loop_chk.setFont(ui_font(TypeSize.LABEL))
        self._loop_chk.setChecked(bounds is not None)
        self._loop_saved = self._loop_form()
        self._loop_chk.toggled.connect(self._toggle_loop_fields)
        loop_row.content_layout.addWidget(self._loop_chk)
        self._select_loop_btn = configure_button(QPushButton(ui_text('xfa_select_loop')), toggle=True)
        self._select_loop_btn.setCheckable(True)
        self._select_loop_btn.setToolTip(ui_text('xfa_select_loop_hint'))
        self._select_loop_btn.toggled.connect(self._select_loop)
        loop_row.content_layout.addWidget(self._select_loop_btn)
        self._loop_btn = configure_button(QPushButton(ui_text('xfa_audition_short')), toggle=True)
        self._loop_btn.setCheckable(True)
        self._loop_btn.setToolTip(ui_text('xfa_audition_loop'))
        self._loop_btn.toggled.connect(self._update_audition_loop)
        loop_row.content_layout.addWidget(self._loop_btn)
        loop_row.content_layout.addStretch()
        layout.addWidget(loop_row)
        self._loop_status = self._hint(layout, 'xfa_select_loop_hint')
        self._retry_btn = configure_button(QPushButton(ui_text('awb_prepare_waveform')))
        self._retry_btn.clicked.connect(self._request_preview)
        self._retry_btn.hide()
        layout.addWidget(self._retry_btn)
        parameters = self._make_section(ui_text('xfa_tone_properties'))
        self._sliders = {}
        for name, label, lo, hi, step in (
                ('gain_db', 'xfa_gain_db', -90, 12, .5),
                ('pitch_cents', 'xfa_pitch_semitones', -24, 24, .5),
                ('pan_degrees', 'xfa_pan_degrees', -180, 180, 1)):
            self._float_field(parameters, name, label, lo, hi, step)
        self._processing_status = QLabel('')
        self._processing_status.setWordWrap(True)
        self._processing_status.setStyleSheet(ss_error_label())
        self._processing_status.hide()
        parameters.addWidget(self._processing_status)
        filters = self._make_section(ui_text('xfa_filters'))
        for name, label, lo, hi, step in (
                ('volume', 'xfa_lowpass_percent', 0, 100, 1),
                ('pitch', 'xfa_highpass_percent', 0, 100, 1),
                ('pan_3d', 'xfa_spatial_field', -90, 12, .5),
                ('send_level', 'xfa_blend_percent', 0, 100, 1)):
            self._float_field(filters, name, label, lo, hi, step)
        self._parameter_status = QLabel('')
        self._parameter_status.setWordWrap(True)
        self._parameter_status.setStyleSheet(ss_dim_label())
        filters.addWidget(self._parameter_status)
        actions = self._make_section(ui_text('sound_section_actions'), 'fa6s.screwdriver-wrench')
        self._hint(actions, 'xfa_import_hint')
        for key, callback in (('ui_sound_extract_audio', lambda: self._export_tone('wav')),
            ('xfa_export_encoded', lambda: self._export_tone('encoded')), ('ui_sound_replace_audio', self._replace_audio),
            ('ui_sound_extract_all', self._batch_export), ('xfa_import_batch', self._batch_import)):
            button = configure_button(QPushButton(ui_text(key)))
            button.clicked.connect(callback)
            actions.addWidget(button)
        self._editor_layout.addStretch()
        self._building = False
        self._processing_feedback()
        QTimer.singleShot(0, self._fit_page)

    def _float_field(self, layout, name, label, lo, hi, step):
        edit = configure_input(QLineEdit(_display_text(name, getattr(self._tone(), name))))
        edit.setAccessibleName(ui_text(label))
        edit.setToolTip(ui_text('xfa_exact_hint'))
        self._fields[name] = (edit, edit.text())
        control = FloatSliderInput(edit, lo, hi, step)
        self._sliders[name] = control
        self._field(layout, label, control)
        edit.editingFinished.connect(self._apply_params)
        edit.textChanged.connect(self._mark_dirty)
        edit.textChanged.connect(self._processing_feedback)
        control.value_changed.connect(self._apply_params)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_editor_scroll'):
            QTimer.singleShot(0, self._fit_page)

    def _processing_feedback(self, *_):
        if self._building or not self._fields:
            return
        try:
            gain = float(self._fields['gain_db'][0].text())
            pitch = float(self._fields['pitch_cents'][0].text())
            if not math.isfinite(gain) or not math.isfinite(pitch):
                raise ValueError()
            self._processing_status.clear()
            self._processing_status.hide()
        except (ValueError, OverflowError):
            self._processing_status.setText(ui_text('xfa_invalid_properties'))
            self._processing_status.show()

    def _fit_page(self):
        if not self._closed:
            fit_scroll_page(self._editor_scroll)

    def _apply_params(self, *args, **kwargs):
        tone = self._tone()
        if tone is None or not self._fields:
            return True
        changes = {}
        for name, (edit, loaded) in self._fields.items():
            text = edit.text()
            if text == loaded:
                edit.setStyleSheet(ss_input_validation(False))
                continue
            try:
                if name == 'name':
                    if len(text.encode('ascii')) > 253 or '\0' in text:
                        raise ValueError()
                    value = text
                else:
                    scale, offset = _DISPLAY_UNITS.get(name, (Decimal(1), Decimal(0)))
                    value = struct.unpack('<f', struct.pack('<f', float((Decimal(text) - offset) / scale)))[0]
                    if not math.isfinite(value):
                        raise ValueError()
                edit.setStyleSheet(ss_input_validation(False))
                changes[name] = value
            except (ValueError, OverflowError, struct.error, UnicodeError, InvalidOperation):
                edit.setStyleSheet(ss_input_validation(True))
                self._parameter_status.setText(ui_text('xfa_invalid_properties'))
                edit.setFocus()
                return False
        if not self._commit_loop():
            return False
        for name, value in changes.items():
            setattr(tone, name, value)
            edit, _ = self._fields[name]
            self._fields[name] = edit, edit.text()
        if changes:
            self._mark_dirty()
            self._filter_tones()
            self._parameter_status.setText(ui_text('xfa_properties_applied'))
        return True

    def _loop_form(self):
        return self._loop_chk.isChecked(), *(str(value) for value in self._loop_bounds)

    def _toggle_loop_fields(self, *_):
        if self._building:
            return
        if not self._apply_params():
            with QSignalBlocker(self._loop_chk):
                self._loop_chk.setChecked(self._loop_saved[0])
            self._refresh_loop_view()

    def _commit_loop(self, *_):
        if not self._fields or not hasattr(self, '_loop_chk') or self._tone() is None:
            return True
        form = self._loop_form()
        if form == self._loop_saved:
            return True
        enabled = form[0]
        try:
            start, end = (int(value) for value in form[1:]) if enabled else (0, 0)
            blob = set_stream_loop(self._tone()._bnsf_blob, enabled, start, end)
        except (ValueError, TypeError) as error:
            self._loop_status.setText(ui_text('xfa_loop_invalid', detail=str(error)))
            return False
        self._tone()._bnsf_blob = blob
        self._tone().pack_size = len(blob)
        self._loop_saved = form
        self._update_audition_loop(self._loop_btn.isChecked())
        self._mark_dirty()
        self._filter_tones()
        self._refresh_loop_view()
        return True

    def _select_loop(self, enabled):
        if enabled and (self._busy or self._source_combo.currentData() or self._envelope is None or not self._apply_params()):
            with QSignalBlocker(self._select_loop_btn):
                self._select_loop_btn.setChecked(False)
            return
        self._wave_widget.set_loop_selection_enabled(enabled)

    def _loop_selection_changed(self, phase):
        with QSignalBlocker(self._select_loop_btn):
            self._select_loop_btn.setChecked(phase != 0)
        if phase:
            self._loop_status.setText(ui_text('xfa_loop_first_point' if phase == 1 else 'xfa_loop_second_point'))
        else:
            self._refresh_loop_view()
        QTimer.singleShot(0, self._fit_page)

    def _edit_loop_markers(self, bounds):
        if self._source_combo.currentData() or not self._apply_params():
            self._refresh_loop_view()
            return
        self._loop_bounds = tuple(bounds)
        with QSignalBlocker(self._loop_chk):
            self._loop_chk.setChecked(True)
        if not self._commit_loop():
            with QSignalBlocker(self._loop_chk):
                self._loop_chk.setChecked(self._loop_saved[0])
            self._loop_bounds = tuple(int(value) for value in self._loop_saved[1:])
            self._refresh_loop_view()

    def _refresh_loop_view(self):
        source = self._preview_source()
        blob = source._bnsf_blob if source else None
        bounds = stream_loop(blob) if blob else None
        info = parse_audio_meta(blob) if blob else None
        editable = bool(self._envelope and not self._source_combo.currentData() and info
                        and info['total_samples'] >= 2 and not info.get('flags'))
        rate = self._envelope.sample_rate if self._envelope else 1
        self._wave_widget.loop = tuple(value / rate for value in bounds) if bounds else None
        self._wave_widget.loop_editable = bool(bounds and editable)
        self._loop_chk.setEnabled(editable)
        self._select_loop_btn.setEnabled(editable)
        self._loop_btn.setEnabled(bool(bounds and self._envelope))
        if not bounds:
            self._loop_btn.setChecked(False)
        if not self._wave_widget.loop_selection_active:
            self._loop_status.setText(ui_text('xfa_loop_times', start=_fmt_dur(bounds[0] / rate),
                end=_fmt_dur(bounds[1] / rate)) if bounds and self._envelope else ui_text('xfa_select_loop_hint'))
        self._wave_widget.update()
        QTimer.singleShot(0, self._fit_page)

    def _preview_source(self):
        tone = self._tone()
        return self._original(tone) if tone and self._source_combo.currentData() else tone

    def _change_source(self, *_):
        if not self._apply_params():
            with QSignalBlocker(self._source_combo):
                self._source_combo.setCurrentIndex(1 - self._source_combo.currentIndex())
            return
        self._stop_playback()
        self._request_preview()

    def _request_preview(self, *_):
        source = self._preview_source()
        if source is None or self._closed:
            return
        self._generation += 1
        generation, blob = self._generation, source._bnsf_blob
        self._wav, self._envelope = None, None
        self._wave_widget.clear()
        self._play_btn.setEnabled(False)
        self._preview_stats.setText(ui_text('ui_xfbin_audio_decoding'))
        self._retry_btn.hide()
        if self._preview_future:
            self._preview_future.cancel()
        cached = self._wav_cache.get(blob)
        def worker():
            try:
                wav = cached if cached is not None else decode_audio(blob)
                envelope = analyze_wav(wav)
                if not self._closed:
                    self._sig_preview.emit(generation, wav, envelope, '')
            except Exception as error:
                if not self._closed:
                    self._sig_preview.emit(generation, None, None, str(error))
        self._preview_future = self._pool.submit(worker)

    def _on_preview(self, generation, wav, envelope, error):
        if generation != self._generation or self._closed:
            return
        if error:
            self._preview_stats.setText(ui_text('xfa_preview_error', detail=error))
            self._retry_btn.show()
            self._fit_page()
            return
        self._wav, self._envelope = wav, envelope
        self._wav_cache[self._preview_source()._bnsf_blob] = wav
        self._wave_widget.set_audio(envelope)
        self._seek_to(0)
        self._refresh_loop_view()
        self._play_btn.setEnabled(True)
        self._preview_stats.setText(ui_text('xfa_stream_details', channels=envelope.channels,
            rate=envelope.sample_rate, samples=envelope.frames, duration=f'{envelope.duration:.3f}'))
        fit_scroll_page(self._editor_scroll)

    def _seek_to(self, seconds):
        if self._envelope is None:
            return
        seconds = max(0., min(seconds, self._envelope.duration))
        self._wave_widget.set_position(seconds)
        self._prog_lbl.setText(f'{_fmt_dur(seconds)} / {_fmt_dur(self._envelope.duration)}')
        if self._player:
            with self._player['lock']:
                self._player['seek'] = round(seconds * self._envelope.sample_rate)

    def _play_tone(self):
        if self._busy or not self._apply_params() or self._wav is None:
            return
        self._stop_playback(reset=False)
        self._set_status('')
        self._play_generation += 1
        token = self._play_generation
        state = dict(stop=threading.Event(), pause=threading.Event(), lock=threading.Lock(), seek=None, loop=None)
        self._player, self._playing = state, True
        self._play_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        wav = self._wav
        start = round(self._wave_widget.position * self._envelope.sample_rate)
        state['loop'] = stream_loop(self._preview_source()._bnsf_blob) if self._loop_btn.isChecked() else None
        def worker():
            pa, output = None, None
            try:
                pa = import_pyaudio().PyAudio()
                with wave.open(io.BytesIO(wav), 'rb') as audio:
                    total, rate = audio.getnframes(), audio.getframerate()
                    audio.setpos(start if start < total else 0)
                    output = pa.open(format=pa.get_format_from_width(audio.getsampwidth()),
                                     rate=rate, channels=audio.getnchannels(), output=True)
                    while not state['stop'].is_set():
                        if state['pause'].is_set():
                            state['stop'].wait(.03)
                            continue
                        with state['lock']:
                            target, state['seek'] = state['seek'], None
                            bounds = state['loop']
                        if target is not None:
                            audio.setpos(max(0, min(total, target)))
                        if bounds and audio.tell() >= bounds[1]:
                            audio.setpos(bounds[0])
                        count = min(1024, bounds[1] - audio.tell()) if bounds else 1024
                        data = audio.readframes(count)
                        if not data:
                            break
                        output.write(data)
                        if not self._closed:
                            self._sig_play.emit(token, audio.tell() / rate, '')
            except Exception as error:
                if not self._closed:
                    self._sig_play.emit(token, -1, str(error))
            finally:
                if output:
                    try:
                        output.stop_stream()
                        output.close()
                    except Exception:
                        pass
                if pa:
                    try:
                        pa.terminate()
                    except Exception:
                        pass
                if not self._closed:
                    self._sig_play.emit(token, -2, '')
        threading.Thread(target=worker, daemon=True, name='xfb-audition').start()

    def _on_play_event(self, token, seconds, error):
        if token != self._play_generation or self._closed:
            return
        if error:
            self._set_status(ui_text('xfa_playback_error', detail=error))
        elif seconds == -2:
            self._stop_playback(reset=False)
        elif seconds >= 0:
            player, self._player = self._player, None
            self._seek_to(seconds)
            self._player = player

    def _update_audition_loop(self, enabled):
        if self._player:
            with self._player['lock']:
                self._player['loop'] = stream_loop(self._preview_source()._bnsf_blob) if enabled else None

    def _toggle_pause(self):
        if self._player:
            pause = self._player['pause']
            pause.clear() if pause.is_set() else pause.set()
            self._pause_btn.setToolTip(ui_text('ui_sound_resume') if pause.is_set() else ui_text('ui_sound_pause'))

    def _stop_playback(self, reset=True):
        self._play_generation += 1
        if self._player:
            self._player['stop'].set()
        self._player, self._playing = None, False
        if hasattr(self, '_play_btn'):
            self._play_btn.setEnabled(self._wav is not None)
            self._pause_btn.setEnabled(False)
            self._stop_btn.setEnabled(False)
            if reset:
                self._seek_to(0)

    def _mark_dirty(self, *_):
        if self._building:
            return
        pending = any(edit.text() != loaded for edit, loaded in self._fields.values())
        if self._fields and hasattr(self, '_loop_saved'):
            pending = pending or self._loop_form() != self._loop_saved
        self._dirty = pending or self._saved_state != self._document_state()
        if self._filepath:
            set_file_label(self._file_lbl, self._filepath, dirty=self._dirty)

    def _run_job(self, kind, worker):
        if self._busy or not self._apply_params():
            return False
        self._stop_playback()
        self._set_busy(True)
        def run():
            try:
                result = worker()
                if not self._closed:
                    self._sig_job.emit(kind, result, '')
            except Exception as error:
                if not self._closed:
                    self._sig_job.emit(kind, None, str(error))
        self._pool.submit(run)
        return True

    def _import_paths(self, paths, replace=False):
        bank, tone = self._banks[self._cur_bank], self._tone()
        def worker():
            results, errors = [], []
            for path in paths:
                self._sig_progress.emit(ui_text('xfa_converting_name', name=os.path.basename(path)))
                try:
                    with open(path, 'rb') as stream:
                        blob = import_audio(stream.read(), path)
                    results.append((os.path.splitext(os.path.basename(path))[0], blob))
                except Exception as error:
                    errors.append(f'{os.path.basename(path)}: {error}')
            return bank, tone if replace else None, results, errors
        self._run_job('import', worker)

    def _replace_audio(self):
        if self._busy or not self._tone() or not self._apply_params():
            return
        path, _ = QFileDialog.getOpenFileName(self, ui_text('ui_sound_replace_audio'), game_files_dialog_dir(), _AUDIO_OPEN_FILTER)
        if path:
            self._import_paths([path], replace=True)

    def _add_tone(self):
        if self._busy or not self._banks or not self._apply_params():
            return
        path, _ = QFileDialog.getOpenFileName(self, ui_text('xfa_import_new_tone_audio'), game_files_dialog_dir(), _AUDIO_OPEN_FILTER)
        if path:
            self._import_paths([path])

    def _batch_import(self):
        if self._busy or not self._banks or not self._apply_params():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, ui_text('xfa_import_audio_files'), game_files_dialog_dir(), _AUDIO_OPEN_FILTER)
        if paths:
            self._import_paths(paths)

    def _on_job(self, kind, result, error):
        self._set_busy(False)
        if error:
            self._set_status(error)
            QMessageBox.critical(self, ui_text('dlg_title_error'), error)
            return
        if kind == 'import':
            bank, target, items, errors = result
            added = 0
            for name, blob in items:
                if target is None:
                    template = self._tone() or (bank.tones[0] if bank.tones else self._templates.get(id(bank)))
                    if template is None:
                        errors.append(ui_text('xfa_no_template'))
                        continue
                    entry = copy.deepcopy(template)
                    entry.name = name.encode('ascii', errors='replace').decode()[:253]
                    bank.tones.append(entry)
                    bank._tone_records.append(entry)
                else:
                    entry = target
                set_tone_bnsf(entry, blob)
                added += 1
            if added:
                self._fields = {}
                self._mark_dirty()
                self._populate_tone_list(len(bank.tones) - 1 if target is None else self._cur_tone)
            self._set_status(ui_text('xfa_import_result', count=added, errors=len(errors)))
            if errors:
                QMessageBox.warning(self, ui_text('dlg_title_error'), '\n'.join(errors[:10]))
        else:
            count = result['count'] if isinstance(result, dict) else result
            self._set_status(ui_text('xfa_exported_count', n=count))
            if isinstance(result, dict) and result['errors']:
                QMessageBox.warning(self, ui_text('dlg_title_error'), '\n'.join(result['errors'][:10]))

    def _duplicate_tone(self):
        if self._busy or not self._tone() or not self._apply_params():
            return
        bank = self._banks[self._cur_bank]
        clone = copy.deepcopy(self._tone())
        clone.name = clone.name.encode('ascii', errors='replace').decode()[:248] + '_copy'
        bank.tones.append(clone)
        bank._tone_records.append(clone)
        self._fields = {}
        self._mark_dirty()
        self._populate_tone_list(len(bank.tones) - 1)

    def _delete_tone(self):
        if self._busy or not self._tone() or not self._apply_params():
            return
        if QMessageBox.question(self, ui_text('dlg_title_confirm_delete'),
            ui_text('xfa_delete_hint', name=self._tone().name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        bank = self._banks[self._cur_bank]
        tone = self._tone()
        # Native references to later TONE slots remain valid.
        slot = bank._tone_records.index(tone)
        bank._tone_records[slot] = bytes(12)
        bank.tones.remove(tone)
        self._fields = {}
        self._cur_tone = -1
        self._stop_playback()
        self._mark_dirty()
        self._populate_tone_list()

    def _restore_tone(self):
        if self._busy or not self._tone():
            return
        tone = self._tone()
        original = self._original(tone)
        if original is None:
            return
        for name in ToneEntry.__slots__:
            setattr(tone, name, copy.deepcopy(getattr(original, name)))
        self._fields = {}
        self._mark_dirty()
        self._select_tone(self._cur_tone, force=True)

    def _export_tone(self, fmt):
        if self._busy or not self._tone() or not self._apply_params():
            return
        blob = self._preview_source()._bnsf_blob
        extension = '.wav' if fmt == 'wav' or blob[:4] == b'RIFF' else '.bnsf'
        path, _ = QFileDialog.getSaveFileName(self, ui_text('ui_sound_extract_audio'),
            export_filename(self._cur_tone, self._preview_source().name, extension), f'Audio (*{extension})')
        if path:
            if not os.path.splitext(path)[1]:
                path += extension
            def worker():
                data = decode_audio(blob) if fmt == 'wav' else blob
                with open(path, 'wb') as stream:
                    stream.write(data)
                return 1
            self._run_job('export', worker)

    def _batch_export(self):
        if self._busy or not self._banks or not self._apply_params():
            return
        folder = QFileDialog.getExistingDirectory(self, ui_text('xfa_choose_export_folder_wav'))
        if not folder:
            return
        items = [(i, t.name, t._bnsf_blob) for i, t in enumerate(self._banks[self._cur_bank].tones)]
        def worker():
            count, errors = 0, []
            for number, (index, name, blob) in enumerate(items, 1):
                self._sig_progress.emit(ui_text('xfa_export_progress', done=number, total=len(items)))
                try:
                    data = decode_audio(blob)
                    with open(os.path.join(folder, export_filename(index, name, '.wav')), 'wb') as stream:
                        stream.write(data)
                    count += 1
                except Exception as error:
                    errors.append(f'{name}: {error}')
            return dict(count=count, errors=errors)
        self._run_job('export', worker)

    def _save_file(self, target_path=None):
        if self._busy or not self._banks or self._raw is None or not self._apply_params():
            if hasattr(self, '_file_actions'):
                self._file_actions.pending_path = None
                self._file_actions.refresh()
            return False
        path = target_path or editor_path(self)
        if not path:
            return False
        self._stop_playback()
        raw, banks = bytes(self._raw), copy.deepcopy(self._banks)
        self._set_busy(True)
        def worker():
            try:
                save_xfbin_audio(path, bytearray(raw), banks)
                if not self._closed:
                    self._sig_save_done.emit(path)
            except Exception as error:
                if not self._closed:
                    self._sig_save_err.emit(str(error))
        self._pool.submit(worker)
        return True

    def _on_save_done(self, path):
        self._set_busy(False)
        commit_save_path(self, path)
        self._saved_state = self._document_state()
        self._dirty = False
        set_file_label(self._file_lbl, path)
        self._set_status(ui_text('ui_xfbin_audio_saved_value', p0=os.path.basename(path)))
        request_and_cascade(self, 'Geb')

    def _on_save_err(self, message):
        self._set_busy(False)
        self._file_actions.pending_path = None
        self._file_actions.refresh()
        self._set_status(message)
        QMessageBox.critical(self, ui_text('dlg_title_error'), message)

    def hideEvent(self, event):
        self._stop_playback()
        super().hideEvent(event)

    def _dispose(self):
        self._closed = True
        self._generation += 1
        if self._player:
            self._player['stop'].set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def closeEvent(self, event):
        self._stop_playback()
        self._dispose()
        super().closeEvent(event)

"""Visual USM workspace. Media plans and validation live in core.usm_tools."""
import json
import os
import re
import shutil
import tempfile
from dataclasses import replace

from PyQt6.QtCore import (QObject, QRunnable, QThreadPool, QProcess, QSignalBlocker, QTimer,
                          QSize, Qt, QUrl, pyqtSignal)
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QBoxLayout, QLabel,
    QPushButton, QComboBox, QDoubleSpinBox, QFileDialog, QMessageBox, QScrollArea,
    QSizePolicy, QStackedLayout, QProgressBar, QCheckBox)

from core.design_tokens import LayoutRole, Insets
from core.editor_file_state import set_file_label, set_file_label_empty
from core.external_tools import find_ffmpeg, find_ffprobe, find_sofdec2_encoder, tool_command
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.translations import ui_text
from core.style_helpers import (ss_bg_dark, ss_video_matte, ss_dim_label, ss_error_label,
    ss_check, ss_progressbar, make_editor_card, add_editor_card_title,
    make_editor_field_shell)
from core.ui.editor_widgets import (EditorToolbar, EditorSeparator, configure_layout,
    configure_button, configure_file_label, configure_input, configure_scrollarea)
from core.ui.editor_actions import install_file_actions, refresh_file_actions
from core.ui.editor_chrome import install_editor_chrome
from core.ui.timeline_controls import timeline_icon_button, TimelineZoomControls
from core.ui.video_timeline import VideoTimeline, VideoTimelineOverview
from core.ui.number_input import SliderInput
from core.usm_tools import (MediaInfo, VideoEdits, parse_media, check_usm, prepare_args,
    encoder_args, preview_args, video_timing_args, validate_output, intermediate_bytes, atomic_copy_usm)

PREVIEW_MIN_WIDTH = 220


class AspectRatioWidget(QWidget):
    resized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._aspect_ratio = 16 / 9
        self._height_limit = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._sync_height)
        self.setMinimumWidth(PREVIEW_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_aspect(self, width, height):
        self._aspect_ratio = width / height if width and height else 16 / 9
        self.updateGeometry()
        self._sync_height()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        height = max(1, round(width / self._aspect_ratio))
        return min(height, self._height_limit) if self._height_limit else height

    def set_height_limit(self, limit):
        if self._height_limit != limit:
            self._height_limit = limit
            self.updateGeometry()
            self._resize_timer.start(0)

    def sizeHint(self):
        return QSize(640, self.heightForWidth(640))

    def minimumSizeHint(self):
        return QSize(PREVIEW_MIN_WIDTH, self.heightForWidth(PREVIEW_MIN_WIDTH))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start(0)
        self.resized.emit()

    def _sync_height(self):
        if getattr(self, '_syncing', False):
            return
        target = self.heightForWidth(self.width())
        if self.height() != target:
            self._syncing = True
            try:
                self.setFixedHeight(target)
            finally:
                self._syncing = False


class _CopySignals(QObject):
    finished = pyqtSignal(str, str)


class _CopyJob(QRunnable):
    def __init__(self, source, target, signals, temporary_directory):
        super().__init__()
        self.source, self.target, self.signals = source, target, signals
        self.temporary_directory = temporary_directory

    def run(self):
        try:
            atomic_copy_usm(self.source, self.target)
            error = ''
        except Exception as exc:
            error = str(exc)
        self.signals.finished.emit(self.target, error)


class UsmVideoEditor(QWidget):
    defer_file_load_notification = True

    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or ui_text
        self._original_path = self._filepath = self._import_path = self._staged_path = ''
        self._original_info = self._import_info = self._staged_info = MediaInfo()
        self._dirty = False
        self._saved_edits = self._staged_edits = None
        self._snapshot_pending = None
        self._process = None
        self._copying = self._closing = self._cancelled = False
        self._tmpdir = tempfile.TemporaryDirectory(prefix='arrowforge_usm_')
        self._serial = 0
        self._video_fit_timer = QTimer(self)
        self._video_fit_timer.setSingleShot(True)
        self._video_fit_timer.timeout.connect(self._fit_video_height)
        self._proxy_cache = {}
        self._external_temporaries = set()
        self._preview_ready = False
        self._preview_path = self._preview_kind = ''
        self._poster_process = None
        self._poster_pixmap = QPixmap()
        self._copy_signals = _CopySignals()
        self._copy_signals.finished.connect(self._on_copy_done)
        self._build_ui()
        self.destroyed.connect(lambda: self._dispose())
        install_file_actions(self, self._save_btn, save_to=self._save_to, asynchronous=True)
        install_editor_chrome(self)
        self._refresh_state()

    def _button(self, key, callback, *, accent=False):
        button = configure_button(QPushButton(self.t(key)), accent=accent)
        button.clicked.connect(callback)
        return button

    def _hint(self, layout, key):
        label = QLabel(self.t(key))
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setStyleSheet(ss_dim_label())
        layout.addWidget(label)
        return label

    def _field(self, layout, key, control, hint=''):
        frame, inner, label, _ = make_editor_field_shell(self.t(key))
        control.setAccessibleName(self.t(key))
        if hint:
            control.setToolTip(self.t(hint))
        label.setBuddy(control)
        inner.addWidget(control)
        layout.addWidget(frame)

    def _build_ui(self):
        root = configure_layout(QVBoxLayout(self), LayoutRole.ROOT)
        self.setStyleSheet(ss_bg_dark())
        toolbar = EditorToolbar()
        self._open_btn = self._button('btn_open_file', self._load_file, accent=True)
        self._open_btn.setProperty('designAction', 'open')
        self._save_btn = self._button('btn_save_file', self._save_file, accent=True)
        toolbar.content_layout.addWidget(self._open_btn)
        toolbar.content_layout.addWidget(self._save_btn)
        self._file_label = configure_file_label(QLabel())
        self._file_label.setMinimumWidth(0)
        self._file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        toolbar.content_layout.addWidget(self._file_label, 1)
        root.addWidget(toolbar)
        root.addWidget(EditorSeparator(accent=True))
        self._scroll = configure_scrollarea(QScrollArea())
        body = QWidget()
        self._body_layout = configure_layout(QHBoxLayout(body), LayoutRole.PAGE)
        self._body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._compact = None
        self._preview_panel, preview = make_editor_card()
        preview.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._preview_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        add_editor_card_title(preview, self.t('usm_section_preview'), 'fa6s.film')
        self._source_combo = configure_input(QComboBox(), monospace=False)
        self._source_combo.currentIndexChanged.connect(self._change_preview)
        self._field(preview, 'usm_preview_source', self._source_combo, 'usm_preview_scope')
        self._preview_surface = AspectRatioWidget()
        self._preview_surface.setStyleSheet(ss_video_matte())
        self._preview_surface.resized.connect(self._render_poster)
        self._preview_stack = QStackedLayout(self._preview_surface)
        self._preview_stack.setContentsMargins(*Insets.NONE)
        self._video_widget = QVideoWidget()
        self._video_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._video_widget.setStyleSheet(ss_video_matte())
        self._poster_label = QLabel(self.t('usm_empty_preview'))
        self._poster_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._poster_label.setWordWrap(True)
        self._poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_label.setStyleSheet(ss_video_matte())
        self._preview_stack.addWidget(self._poster_label)
        self._preview_stack.addWidget(self._video_widget)
        preview.addWidget(self._preview_surface)
        transport = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self._play_btn = timeline_icon_button(self.t('usm_preview_play'), 'fa6s.play', self._toggle_preview_playback)
        self._stop_btn = timeline_icon_button(self.t('usm_preview_stop'), 'fa6s.stop', self._stop_preview)
        self._back_btn = timeline_icon_button(self.t('usm_previous_frame'), 'fa6s.backward-step', lambda: self._step_frame(-1))
        self._next_btn = timeline_icon_button(self.t('usm_next_frame'), 'fa6s.forward-step', lambda: self._step_frame(1))
        for button in (self._play_btn, self._stop_btn, self._back_btn, self._next_btn):
            transport.addWidget(button)
        self._time_label = QLabel(self.t('usm_preview_time_empty'))
        self._time_label.setStyleSheet(ss_dim_label())
        transport.addWidget(self._time_label, 1)
        preview.addLayout(transport)
        self._timeline = VideoTimeline()
        self._timeline.playheadScrubbed.connect(lambda seconds: self._seek_to(round(seconds * 1000)))
        self._timeline.intervalChanged.connect(self._timeline_trim)
        preview.addWidget(self._timeline)
        self._overview = VideoTimelineOverview()
        self._overview.viewRangeChanged.connect(self._timeline.set_view_range)
        self._timeline.viewRangeChanged.connect(self._refresh_overview)
        preview.addWidget(self._overview)
        timeline_nav = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self._zoom = TimelineZoomControls(self._timeline)
        timeline_nav.addWidget(self._zoom)
        seek_row = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self._seek_input = self._seconds_input()
        self._seek_input.setAccessibleName(self.t('usm_seek'))
        self._seek_input.editingFinished.connect(lambda: self._seek_to(round(self._seek_input.value() * 1000)))
        seek_row.addWidget(self._seek_input)
        self._mute = QCheckBox(self.t('usm_mute'))
        self._mute.setStyleSheet(ss_check())
        seek_row.addWidget(self._mute)
        self._loop = QCheckBox(self.t('usm_loop'))
        self._loop.setStyleSheet(ss_check())
        seek_row.addWidget(self._loop)
        preview.addLayout(seek_row)
        preview.addLayout(timeline_nav)
        self._volume = SliderInput(self.t('usm_monitor_volume'), 0, 100, 80)
        self._volume.setToolTip(self.t('usm_monitor_hint'))
        preview.addWidget(self._volume)
        self._preview_status = self._hint(preview, 'usm_preview_scope')
        self._preview_status.hide()
        self._retry_btn = self._button('usm_retry_preview', self._change_preview)
        self._retry_btn.hide()
        preview.addWidget(self._retry_btn)
        actions = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self._export_btn = self._button('usm_btn_export', self._export_video)
        self._import_btn = self._button('usm_btn_import', self._import_video)
        actions.addWidget(self._export_btn)
        actions.addWidget(self._import_btn)
        preview.addLayout(actions)
        self._body_layout.addWidget(self._preview_panel, 3)
        self._settings_panel, settings = make_editor_card()
        settings.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._settings_panel.setMaximumWidth(520)
        self._settings_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        add_editor_card_title(settings, self.t('usm_replacement_settings'), 'fa6s.sliders')
        self._original_value = self._hint(settings, 'usm_value_empty')
        self._import_value = self._hint(settings, 'usm_import_instruction')
        self._fit_combo = configure_input(QComboBox(), monospace=False)
        for key, value in (('usm_fit_letterbox', 'fit'), ('usm_fit_crop', 'crop'), ('usm_fit_stretch', 'stretch')):
            self._fit_combo.addItem(self.t(key), value)
        self._field(settings, 'usm_fit_mode', self._fit_combo, 'usm_fit_hint')
        self._audio_combo = configure_input(QComboBox(), monospace=False)
        for key, value in (('usm_audio_import', 'import'), ('usm_audio_original', 'original'), ('usm_audio_silent', 'silent')):
            self._audio_combo.addItem(self.t(key), value)
        self._field(settings, 'usm_audio_source', self._audio_combo, 'usm_audio_hint')
        trim = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self._trim_start, self._trim_end = self._seconds_input(), self._seconds_input()
        for key, spin in (('usm_trim_start', self._trim_start), ('usm_trim_end', self._trim_end)):
            self._field(trim, key, spin)
        settings.addLayout(trim)
        markers = configure_layout(QHBoxLayout(), LayoutRole.FIELD)
        self._mark_in = self._button('usm_mark_in', lambda: self._mark_trim(False))
        self._mark_out = self._button('usm_mark_out', lambda: self._mark_trim(True))
        markers.addWidget(self._mark_in)
        markers.addWidget(self._mark_out)
        settings.addLayout(markers)
        self._plan_value = self._hint(settings, 'usm_import_instruction')
        self._validation = self._hint(settings, 'usm_value_empty')
        self._build_btn = self._button('usm_build_replacement', self._build_replacement, accent=True)
        self._build_btn.setToolTip(self.t('usm_build_hint'))
        settings.addWidget(self._build_btn)
        self._restore_btn = self._button('usm_discard_replacement', self._discard_replacement)
        settings.addWidget(self._restore_btn)
        self._restore_btn.hide()
        self._body_layout.addWidget(self._settings_panel, 2)
        self._scroll.setWidget(body)
        root.addWidget(self._scroll, 1)
        self._operation = QWidget()
        progress = configure_layout(QHBoxLayout(self._operation), LayoutRole.PAGE)
        self._status_label = QLabel()
        self._status_label.setMinimumWidth(0)
        self._status_label.setWordWrap(True)
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._status_label.setStyleSheet(ss_dim_label())
        progress.addWidget(self._status_label, 1)
        self._progress = QProgressBar()
        self._progress.setStyleSheet(ss_progressbar())
        self._progress.setRange(0, 0)
        progress.addWidget(self._progress, 1)
        self._cancel_btn = self._button('usm_cancel_operation', self._cancel_process)
        progress.addWidget(self._cancel_btn)
        root.addWidget(self._operation)
        self._operation.hide()
        for control in (self._trim_start, self._trim_end):
            control.valueChanged.connect(self._edits_changed)
        for control in (self._fit_combo, self._audio_combo):
            control.currentIndexChanged.connect(self._edits_changed)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(.8)
        self._volume.value_changed.connect(lambda value: self._audio_output.setVolume(value / 100))
        self._mute.toggled.connect(self._audio_output.setMuted)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        self._player.durationChanged.connect(self._on_preview_duration)
        self._player.positionChanged.connect(self._on_preview_position)
        self._player.playbackStateChanged.connect(self._on_preview_state)
        self._player.mediaStatusChanged.connect(self._media_status)
        self._player.errorOccurred.connect(self._on_preview_error)

    def _seconds_input(self):
        spin = configure_input(QDoubleSpinBox())
        spin.setDecimals(3)
        spin.setRange(0, 0)
        spin.setSuffix(' s')
        spin.setKeyboardTracking(False)
        spin.setMinimumWidth(0)
        return spin

    def _error(self, error):
        value = str(error)
        return self.t(value) if value.startswith('usm_') else value

    def _show_error(self, error):
        QMessageBox.critical(self, self.t('dlg_title_error'), self._error(error))

    def _edits(self):
        return VideoEdits(self._trim_start.value(), self._trim_end.value(),
                          self._fit_combo.currentData(), self._audio_combo.currentData())

    def _valid_edits(self):
        if not self._import_path:
            return False
        try:
            self._edits().validate(self._original_info, self._import_info)
            return True
        except ValueError:
            return False

    def _set_dirty(self, value):
        self._dirty = value
        if self._filepath:
            set_file_label(self._file_label, self._filepath, dirty=value)
        else:
            set_file_label_empty(self._file_label, self.t('no_file_loaded'))

    def has_unsaved_changes(self):
        return self._dirty

    def _confirm_discard(self):
        return not self._dirty or QMessageBox.question(self, self.t('dlg_title_warning'),
            self.t('usm_confirm_discard'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes

    def load_file(self, path):
        return self._open_usm(path)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.t('usm_open_title'),
            game_files_dialog_dir(target_patterns=('*.usm',)), self.t('usm_filter_usm'))
        if path:
            self._open_usm(path)

    def _open_usm(self, path):
        if self._is_busy() or not path or not self._confirm_discard():
            return False
        try:
            check_usm(path)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return False

        def opened(info):
            if info.format_name != 'usm':
                raise ValueError('usm_error_container')
            create_backup_on_open(path)
            self._release_previews()
            if self._staged_path:
                self._remove_work_tree(os.path.dirname(self._staged_path))
            self._original_path = self._filepath = path
            self._original_info = info
            self._clear_replacement()
            self._set_dirty(False)
            self._refresh_sources('original')
            self._refresh_state()
            self._change_preview()
        self._probe(path, opened)
        return True

    def _probe(self, path, done, failed=None):
        probe = find_ffprobe()
        if not probe:
            self._show_error(self.t('usm_error_ffprobe_missing'))
            if failed:
                failed()
            return

        def probed(ok):
            if ok:
                try:
                    info = parse_media(json.loads(self._stdout), path)
                    done(info)
                    return
                except Exception as exc:
                    self._show_error(exc)
            if failed:
                failed()
            self._refresh_state()
        self._start_process(self.t('usm_reading_media'), probe,
            ['-v', 'error', '-of', 'json', '-show_streams', '-show_format', path], probed, timeout=30000)

    def _import_video(self):
        if not self._original_path or self._is_busy():
            return
        path, _ = QFileDialog.getOpenFileName(self, self.t('usm_import_title'),
            game_files_dialog_dir(self._original_path), self.t('usm_filter_media'))
        if path:
            self._import_media(path)

    def _import_media(self, path):
        if self._is_busy() or not self._original_path or not self._confirm_discard():
            return

        def imported(info):
            if not info.duration:
                raise ValueError('usm_error_timing')
            self._release_previews(keep_original=True)
            if self._staged_path:
                self._remove_work_tree(os.path.dirname(self._staged_path))
            self._import_path, self._import_info = path, info
            self._staged_path, self._staged_edits, self._saved_edits = '', None, None
            for spin in (self._trim_start, self._trim_end):
                with QSignalBlocker(spin):
                    spin.setRange(0, info.duration)
                    spin.setSingleStep(1 / info.fps if info.fps else .001)
            with QSignalBlocker(self._trim_start):
                self._trim_start.setValue(0)
            with QSignalBlocker(self._trim_end):
                self._trim_end.setValue(int(info.duration * 1000) / 1000)
            with QSignalBlocker(self._audio_combo):
                self._audio_combo.setCurrentIndex(0 if info.audio_codec else (1 if self._original_info.audio_codec else 2))
            self._set_dirty(True)
            self._refresh_sources('import')
            self._refresh_state()
            self._change_preview()
        self._probe(path, imported)

    def _clear_replacement(self):
        self._import_path = self._staged_path = ''
        self._import_info = self._staged_info = MediaInfo()
        self._saved_edits = self._staged_edits = None

    def _discard_replacement(self):
        if self._is_busy() or not self._confirm_discard():
            return
        self._release_previews(keep_original=True)
        if self._staged_path:
            self._remove_work_tree(os.path.dirname(self._staged_path))
        self._clear_replacement()
        self._filepath = self._original_path
        self._set_dirty(self._original_info.path != self._original_path)
        self._refresh_sources('original')
        self._refresh_state()
        self._change_preview()

    def _release_previews(self, keep_original=False):
        self._player.stop()
        self._player.setSource(QUrl())
        self._stop_poster()
        self._preview_ready = False
        for key, value in list(self._proxy_cache.items()):
            if not keep_original or key[0] != self._original_info.path:
                self._remove_work_file(value)
                del self._proxy_cache[key]
        self._preview_path = self._preview_kind = ''

    def _edits_changed(self, *_):
        if self._import_path:
            self._set_dirty(self._saved_edits != self._edits())
        self._refresh_state()

    def _describe_info(self, info):
        return self.t('usm_value_media_info', video=info.video_codec,
            resolution=f'{info.width} × {info.height}', fps=f'{info.fps:.3f}',
            duration=f'{info.duration:.3f} s', audio=(self.t('usm_value_audio', codec=info.audio_codec,
            channels=info.audio_channels, rate=info.audio_rate) if info.audio_codec else self.t('usm_value_no_audio')))

    def _refresh_state(self):
        busy = self._is_busy()
        loaded, imported = bool(self._original_path), bool(self._import_path)
        valid = self._valid_edits()
        self._open_btn.setEnabled(not busy)
        self._save_btn.setEnabled(loaded and not busy and (not imported or valid))
        self._import_btn.setEnabled(loaded and not busy)
        self._export_btn.setEnabled(loaded and not busy)
        for control in (self._fit_combo, self._audio_combo, self._trim_start, self._trim_end):
            control.setEnabled(imported and not busy)
        for index, available in ((0, self._import_info.audio_codec), (1, self._original_info.audio_codec)):
            self._audio_combo.model().item(index).setEnabled(bool(available))
        self._build_btn.setEnabled(valid and not busy)
        self._restore_btn.setEnabled(imported and not busy)
        self._mark_in.setEnabled(imported and self._preview_kind == 'import' and self._preview_ready and not busy)
        self._mark_out.setEnabled(self._mark_in.isEnabled())
        self._original_value.setText((os.path.basename(self._original_path) + '\n' + self._describe_info(self._original_info))
                                     if loaded else self.t('usm_open_instruction'))
        self._import_value.setText((os.path.basename(self._import_path) + '\n' + self._describe_info(self._import_info))
                                   if imported else self.t('usm_import_instruction'))
        self._plan_value.setText('')
        error = ''
        if imported:
            edits = self._edits()
            try:
                edits.validate(self._original_info, self._import_info)
                estimate = intermediate_bytes(self._original_info, edits)
                self._plan_value.setText(self.t('usm_output_plan', width=self._original_info.width,
                    height=self._original_info.height, fps=f'{self._original_info.fps:.3f}',
                    seconds=f'{edits.duration:.3f}') + (self.t('usm_disk_estimate', gib=f'{estimate / 1024**3:.2f}') if estimate else ''))
            except ValueError as exc:
                error = self._error(exc)
        self._validation.setStyleSheet(ss_error_label() if error else ss_dim_label())
        self._validation.setText(error or (self.t('usm_replacement_ready') if self._staged_path and self._staged_edits == self._edits()
                                          else self.t('usm_build_hint') if imported else ''))
        staged_index = self._source_combo.findData('staged')
        if staged_index >= 0:
            self._source_combo.setItemText(staged_index, self.t('usm_encoded_source' if self._staged_edits == self._edits() else 'usm_previous_result'))
        enabled = self._preview_ready and not busy
        for control in (self._play_btn, self._stop_btn, self._back_btn, self._next_btn,
                        self._seek_input, self._timeline, self._overview, self._zoom):
            control.setEnabled(enabled)
        self._sync_timeline()
        self._source_combo.setEnabled(loaded and not busy)
        refresh_file_actions(self, loaded=loaded)
        if hasattr(self, '_file_actions'):
            self._file_actions.button.setEnabled(self._save_btn.isEnabled() and not self._file_actions.pending_path)
        self._apply_responsive_layout()

    def _refresh_sources(self, selected=None):
        selected = selected or self._source_combo.currentData()
        with QSignalBlocker(self._source_combo):
            self._source_combo.clear()
            for kind, available, key in (('original', self._original_path, 'usm_label_original'),
                    ('import', self._import_path, 'usm_label_imported'), ('staged', self._staged_path, 'usm_encoded_source')):
                if available:
                    self._source_combo.addItem(self.t(key), kind)
            self._source_combo.setCurrentIndex(max(0, self._source_combo.findData(selected)))

    def _selected_media(self):
        return {'original': self._original_info, 'import': self._import_info,
                'staged': self._staged_info}.get(self._source_combo.currentData(), MediaInfo())

    def _change_preview(self, *_):
        if self._is_busy():
            return
        info = self._selected_media()
        if not info.path:
            return
        position = self._player.position()
        was_playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        old_kind, new_kind = self._preview_kind, self._source_combo.currentData()
        trim_offset = round((self._staged_edits.start if self._staged_edits else self._edits().start) * 1000)
        if old_kind == 'import' and new_kind != 'import':
            position = max(0, position - trim_offset)
        elif old_kind != 'import' and new_kind == 'import':
            position += trim_offset
        self._preview_kind = self._source_combo.currentData()
        try:
            key = (info.path, os.path.getmtime(info.path), os.path.getsize(info.path))
        except OSError as exc:
            self._show_error(exc)
            return
        cached = self._proxy_cache.get(key)
        if cached and os.path.isfile(cached):
            self._set_preview_source(cached, info, position, was_playing)
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self._show_error(self.t('usm_error_ffmpeg_missing'))
            return
        self._player.stop()
        self._preview_ready = False
        self._serial += 1
        output = os.path.join(self._tmpdir.name, f'preview-{self._serial}.mp4')

        def preview_done(ok):
            if ok and os.path.isfile(output):
                self._proxy_cache[key] = output
                while len(self._proxy_cache) > 3:
                    old = next(iter(self._proxy_cache))
                    old_path = self._proxy_cache.pop(old)
                    if old_path != self._preview_path:
                        self._remove_work_file(old_path)
                self._set_preview_source(output, info, position, was_playing)
            else:
                self._remove_work_file(output)
                self._preview_status.setText(self.t('usm_preview_failed'))
                self._preview_status.show()
                self._retry_btn.show()
            self._refresh_state()
        self._start_process(self.t('usm_preparing_preview'), ffmpeg, preview_args(info.path, output, info),
                            preview_done, duration=info.duration)

    def _set_preview_source(self, path, info, position=0, play=False):
        self._player.stop()
        self._preview_path = path
        self._preview_ready = True
        self._resume_position, self._resume_play = min(position, round(info.duration * 1000)), play
        self._preview_surface.set_aspect(info.width, info.height)
        self._preview_status.setText(self.t('usm_preview_scope'))
        self._preview_status.setStyleSheet(ss_dim_label())
        self._preview_status.hide()
        self._retry_btn.hide()
        self._player.setSource(QUrl.fromLocalFile(path))
        self._start_poster(path)
        self._refresh_state()

    def _start_poster(self, path):
        self._stop_poster()
        self._poster_pixmap = QPixmap()
        self._poster_label.clear()
        self._preview_stack.setCurrentWidget(self._poster_label)
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return
        self._serial += 1
        poster = os.path.join(self._tmpdir.name, f'poster-{self._serial}.jpg')
        process = QProcess(self)
        command = tool_command(ffmpeg)
        process.setProgram(command[0])
        process.setArguments([*command[1:], '-v', 'error', '-nostdin', '-y', '-i', path, '-frames:v', '1', poster])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        def finished(code, _status):
            if self._poster_process is process:
                self._poster_process = None
                if code == 0:
                    self._poster_pixmap = QPixmap(poster)
                    self._render_poster()
            self._remove_work_file(poster)
            process.deleteLater()
        process.finished.connect(finished)
        self._poster_process = process
        process.start()

    def _stop_poster(self):
        process, self._poster_process = self._poster_process, None
        if process:
            process.kill()
            process.waitForFinished(2000)
            process.deleteLater()

    def _render_poster(self):
        if not self._poster_pixmap.isNull():
            self._poster_label.setPixmap(self._poster_pixmap.scaled(self._preview_surface.size(),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _media_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._seek_to(getattr(self, '_resume_position', 0))
            if getattr(self, '_resume_play', False):
                self._player.play()
            self._resume_play = False
        elif status == QMediaPlayer.MediaStatus.EndOfMedia and self._loop.isChecked():
            self._player.setPosition(0)
            self._player.play()

    def _toggle_preview_playback(self):
        if not self._preview_ready:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._preview_stack.setCurrentWidget(self._video_widget)
            self._player.play()

    def _stop_preview(self):
        self._player.stop()
        self._player.setPosition(0)
        self._preview_stack.setCurrentWidget(self._poster_label)

    def _on_preview_state(self, state):
        from core.icons import _themed_icon
        from core.themes import P
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._play_btn.setIcon(_themed_icon('fa6s.pause' if playing else 'fa6s.play', color=P['text_main'], size=16))
        self._play_btn.setToolTip(self.t('usm_preview_pause' if playing else 'usm_preview_play'))
        if playing:
            self._preview_stack.setCurrentWidget(self._video_widget)

    def _on_preview_error(self, error, message):
        if error != QMediaPlayer.Error.NoError:
            self._preview_ready = False
            self._preview_status.setStyleSheet(ss_error_label())
            self._preview_status.setText(self.t('usm_player_error', error=message))
            self._preview_status.show()
            self._retry_btn.show()
            self._refresh_state()

    def _seek_to(self, value):
        self._player.setPosition(max(0, min(value, self._player.duration())))
        if value > 0:
            self._preview_stack.setCurrentWidget(self._video_widget)

    def _step_frame(self, direction):
        self._player.pause()
        fps = self._selected_media().fps
        if fps:
            frame = round(self._player.position() * fps / 1000) + direction
            self._seek_to(round(frame * 1000 / fps))

    def _mark_trim(self, end):
        if self._preview_kind == 'import':
            (self._trim_end if end else self._trim_start).setValue(self._player.position() / 1000)

    def _timeline_trim(self, start, end):
        if self._preview_kind != 'import':
            return
        for spin, value in ((self._trim_start, start), (self._trim_end, end)):
            with QSignalBlocker(spin):
                spin.setValue(value)
        self._edits_changed()

    def _sync_timeline(self):
        if not hasattr(self, '_timeline'):
            return
        info = self._selected_media()
        editable = self._preview_kind == 'import' and self._valid_edits()
        start, end = (self._trim_start.value(), self._trim_end.value()) if editable else (0., info.duration)
        self._timeline.set_media(info.duration, start, end, label=os.path.basename(info.path), editable=editable, fps=info.fps)
        self._refresh_overview()

    def _refresh_overview(self, *_):
        self._overview.set_data(self._timeline._keys, self._timeline.timeline_duration(), *self._timeline.view_range())

    def _on_preview_duration(self, duration):
        with QSignalBlocker(self._seek_input):
            self._seek_input.setRange(0, max(0, duration) / 1000)
        self._on_preview_position(self._player.position())

    def _on_preview_position(self, position):
        self._timeline.set_playhead_time(position / 1000)
        if not self._seek_input.hasFocus():
            with QSignalBlocker(self._seek_input):
                self._seek_input.setValue(position / 1000)
        self._time_label.setText(self.t('usm_preview_time', position=self._format_ms(position),
                                      duration=self._format_ms(self._player.duration())))

    @staticmethod
    def _format_ms(value):
        seconds, ms = divmod(max(0, int(value)), 1000)
        minutes, seconds = divmod(seconds, 60)
        return f'{minutes}:{seconds:02d}.{ms:03d}'

    def _build_replacement(self, checked=False, after=None):
        if self._is_busy() or not self._valid_edits():
            return
        edits = self._edits()
        if self._staged_path and self._staged_edits == edits:
            if after:
                after()
            else:
                self._refresh_sources('staged')
                self._change_preview()
            return
        ffmpeg, encoder = find_ffmpeg(), find_sofdec2_encoder()
        if not ffmpeg or not encoder:
            self._show_error(self.t('usm_error_ffmpeg_missing' if not ffmpeg else 'usm_error_sofdec2_missing'))
            self._clear_pending_save()
            return
        estimate = intermediate_bytes(self._original_info, edits)
        if estimate * 1.05 + 64 * 1024**2 > shutil.disk_usage(self._tmpdir.name).free:
            self._show_error(self.t('usm_error_disk', gib=f'{estimate / 1024**3:.2f}'))
            self._clear_pending_save()
            return
        self._serial += 1
        work = os.path.join(self._tmpdir.name, f'build-{self._serial}')
        os.makedirs(work)
        video = os.path.join(work, 'video.264' if self._original_info.video_codec == 'h264' else 'video.avi')
        audio, output = os.path.join(work, 'audio.wav'), os.path.join(work, 'replacement.usm')

        def failed():
            self._clear_pending_save()
            self._remove_work_tree(work)

        def verified(info):
            check_usm(output)
            validate_output(info, self._original_info, self._import_info, edits)

            def decoded(ok):
                if not ok:
                    failed()
                    return
                previous = self._staged_path
                self._staged_path, self._staged_info, self._staged_edits = output, info, edits
                self._remove_work_file(video)
                self._remove_work_file(audio)
                if previous:
                    self._remove_work_tree(os.path.dirname(previous))
                self._refresh_sources('staged')
                self._refresh_state()
                if after:
                    after()
                else:
                    self._change_preview()
            self._start_process(self.t('usm_checking_result'), ffmpeg,
                ['-v', 'error', '-nostdin', '-xerror', '-i', output, '-map', '0:v:0',
                 '-map', '0:a?', '-f', 'null', '-'], decoded, duration=edits.duration)

        def encoded(ok):
            if not ok:
                failed()
                return
            try:
                check_usm(output)
            except Exception as exc:
                failed()
                self._show_error(exc)
                return
            self._probe(output, verified, failed)

        def prepared(ok):
            if not ok:
                failed()
                return
            self._start_process(self.t('usm_status_encoding_usm'), encoder,
                encoder_args(self._original_info, self._import_info, edits, video, audio, output),
                encoded, workdir=os.path.dirname(encoder), duration=edits.duration)
        self._player.pause()
        self._start_process(self.t('usm_status_preparing_media'), ffmpeg,
            prepare_args(self._original_info, self._import_info, edits, video, audio),
            prepared, duration=edits.duration)

    def _save_file(self):
        if self._filepath:
            self._save_to(self._filepath)

    def _save_to(self, path):
        if self._is_busy():
            return
        if os.path.splitext(path)[1].lower() != '.usm':
            self._show_error(self.t('usm_warning_not_usm'))
            self._clear_pending_save()
            return
        if self._import_path and not self._valid_edits():
            self._clear_pending_save()
            return
        if self._import_path and (not self._staged_path or self._staged_edits != self._edits()):
            self._build_replacement(after=lambda: self._save_to(path))
            return
        source = self._staged_path or self._original_info.path
        if not source:
            self._clear_pending_save()
            return
        try:
            check_usm(source)
            if os.path.exists(path) and os.path.abspath(source) != os.path.abspath(path):
                create_backup_on_open(path)
        except Exception as exc:
            self._show_error(exc)
            self._clear_pending_save()
            return
        # Preserve the opened bytes for comparison when Save replaces that file.
        destination_key = os.path.normcase(os.path.abspath(path))
        for media_info, name in ((self._original_info, 'opened.usm'), (self._import_info, 'imported.usm')):
            if self._import_path and media_info.path and destination_key == os.path.normcase(os.path.abspath(media_info.path)):
                self._serial += 1
                snapshot_path = os.path.join(self._tmpdir.name, f'{self._serial}-{name}')
                self._snapshot_pending = (path, media_info.path)
                source, path = media_info.path, snapshot_path
                break
        self._player.pause()
        self._copying = True
        self._status_label.setText(self.t('usm_status_repacking'))
        self._progress.setRange(0, 0)
        self._operation.show()
        self._cancel_btn.setEnabled(False)
        self._refresh_state()
        QThreadPool.globalInstance().start(_CopyJob(source, path, self._copy_signals, self._tmpdir))

    def _on_copy_done(self, path, error):
        self._copying = False
        self._operation.hide()
        if self._snapshot_pending:
            (destination, previous_source), self._snapshot_pending = self._snapshot_pending, None
            if error:
                self._show_error(error)
                self._clear_pending_save()
                self._refresh_state()
            else:
                for attribute in ('_original_info', '_import_info'):
                    media_info = getattr(self, attribute)
                    if os.path.normcase(os.path.abspath(media_info.path)) == os.path.normcase(os.path.abspath(previous_source)):
                        setattr(self, attribute, replace(media_info, path=path))
                self._save_to(destination)
            return
        if error:
            self._show_error(error)
        else:
            self._filepath = path
            self._saved_edits = self._edits() if self._import_path else None
            self._set_dirty(False)
        self._clear_pending_save()
        self._refresh_state()

    def _clear_pending_save(self):
        if hasattr(self, '_file_actions'):
            self._file_actions.pending_path = None
            self._file_actions.refresh()

    def _export_video(self):
        if self._is_busy():
            return
        info = self._selected_media()
        if not info.path:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.t('usm_export_video_title'),
            os.path.splitext(self._filepath)[0] + '.mp4', self.t('usm_filter_mp4'))
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += '.mp4'
        if os.path.normcase(os.path.abspath(path)) in {os.path.normcase(os.path.abspath(p)) for p in
                (self._original_path, self._import_path, self._staged_path) if p}:
            self._show_error(self.t('usm_error_export_source'))
            return
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self._show_error(self.t('usm_error_ffmpeg_missing'))
            return
        try:
            fd, temporary = tempfile.mkstemp(prefix='.arrowforge-video-', suffix='.mp4', dir=os.path.dirname(os.path.abspath(path)))
        except OSError as exc:
            self._show_error(exc)
            return
        os.close(fd)
        self._external_temporaries.add(temporary)
        timing, options = video_timing_args(info)
        args = ['-hide_banner', '-nostdin', '-y', '-i', info.path, '-map', '0:v:0', '-map', '0:a?']
        if timing:
            args += ['-vf', timing, *options]
        args += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', temporary]

        def exported(ok):
            try:
                if ok:
                    os.replace(temporary, path)
            except OSError as exc:
                self._show_error(exc)
            finally:
                self._remove_work_file(temporary)
                self._external_temporaries.discard(temporary)
        self._start_process(self.t('usm_status_exporting'), ffmpeg, args, exported, duration=info.duration)

    def _start_process(self, title, program, args, callback, *, workdir='', duration=0, timeout=0):
        if self._is_busy() or self._closing:
            return
        self._stdout, self._log = '', ''
        self._cancelled = False
        self._done = callback
        self._duration = duration
        self._status_label.setText(title)
        self._progress.setRange(0, 0)
        self._cancel_btn.setEnabled(True)
        self._operation.show()
        process = QProcess(self)
        command = tool_command(program)
        process.setProgram(command[0])
        process.setArguments([*command[1:], *args])
        if workdir:
            process.setWorkingDirectory(workdir)
        process.readyReadStandardOutput.connect(lambda: self._read_output(process))
        process.readyReadStandardError.connect(lambda: self._read_output(process))
        process.finished.connect(lambda code, status: self._process_finished(process,
            code == 0 and status == QProcess.ExitStatus.NormalExit))
        process.errorOccurred.connect(lambda error: self._process_error(process, error))
        self._process = process
        if timeout:
            timer = QTimer(process)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._timeout_process(process))
            timer.start(timeout)
        self._refresh_state()
        process.start()

    def _read_output(self, process):
        if self._process is not process:
            return
        stdout = bytes(process.readAllStandardOutput()).decode('utf-8', errors='replace')
        stderr = bytes(process.readAllStandardError()).decode('utf-8', errors='replace')
        self._stdout = (self._stdout + stdout)[-4 * 1024 * 1024:]
        self._log = (self._log + stdout + stderr)[-16000:]
        text = self._log[-2000:]
        times = re.findall(r'time=(\d+):(\d+):(\d+(?:\.\d+)?)', text)
        frames = re.findall(r'\(\s*(\d+)\s*/\s*(\d+)\s*\)', text)
        value = None
        if times and self._duration:
            h, m, s = map(float, times[-1])
            value = (h * 3600 + m * 60 + s) * 100 / self._duration
        elif frames:
            n, d = map(int, frames[-1])
            value = n * 100 / max(1, d)
        if value is not None:
            self._progress.setRange(0, 100)
            self._progress.setValue(max(0, min(100, int(value))))

    def _process_error(self, process, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._process_finished(process, False, process.errorString())

    def _process_finished(self, process, ok, error=''):
        if self._process is not process:
            return
        if self._closing:
            self._process = None
            process.deleteLater()
            return
        self._read_output(process)
        callback, self._done = self._done, None
        cancelled = self._cancelled or self._closing
        self._process = None
        process.deleteLater()
        self._operation.hide()
        self._refresh_state()
        if not ok and not cancelled:
            self._show_error(error or self._log[-3000:] or self.t('no_output'))
        if callback and not self._closing:
            callback(ok and not cancelled)
        if (not ok or cancelled) and not self._is_busy():
            self._clear_pending_save()

    def _timeout_process(self, process):
        if self._process is process:
            self._log += '\n' + self.t('usm_process_timeout')
            process.kill()

    @property
    def _busy(self):
        return self._is_busy()

    def _cancel_process(self):
        if self._process:
            self._cancelled = True
            self._cancel_btn.setEnabled(False)
            self._process.kill()

    def _is_busy(self):
        return self._process is not None or self._copying

    @staticmethod
    def _remove_work_file(path):
        try:
            os.unlink(path)
        except OSError:
            pass

    def _remove_work_tree(self, path):
        root, resolved = os.path.realpath(self._tmpdir.name), os.path.realpath(path)
        if os.path.commonpath((root, resolved)) == root and resolved != root:
            shutil.rmtree(resolved, ignore_errors=True)

    def _apply_responsive_layout(self):
        if not hasattr(self, '_body_layout'):
            return
        compact = self.width() < 1050
        if compact != self._compact:
            self._body_layout.setDirection(QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight)
            self._settings_panel.setMaximumWidth(16777215 if compact else 520)
            self._compact = compact
        self._video_fit_timer.start(0)

    def _fit_video_height(self):
        if self._closing:
            return
        if self._compact:
            self._preview_surface.set_height_limit(None)
            return
        # Measure the actual translated controls instead of reserving a fixed
        # toolbar/form height. The video remains letterboxed with its own aspect.
        margins = self._body_layout.contentsMargins()
        available = self._scroll.viewport().height() - margins.top() - margins.bottom()
        controls = self._preview_panel.layout().totalSizeHint().height() - self._preview_surface.height()
        self._preview_surface.set_height_limit(max(160, available - controls))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def hideEvent(self, event):
        self._player.pause()
        super().hideEvent(event)

    def _dispose(self):
        if self._closing:
            return
        self._closing = True
        self._player.stop()
        self._player.setSource(QUrl())
        self._stop_poster()
        if self._process:
            self._process.kill()
            self._process.waitForFinished(3000)
        for path in self._external_temporaries:
            self._remove_work_file(path)
        self._external_temporaries.clear()
        # A background atomic copy holds the directory until its last read.
        if not self._copying:
            self._tmpdir.cleanup()

    def closeEvent(self, event):
        if self._copying:
            event.ignore()
            return
        if not self._confirm_discard():
            event.ignore()
            return
        self._dispose()
        super().closeEvent(event)

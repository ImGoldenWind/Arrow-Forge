"""AWB stream workspace. Parsing and PCM analysis live outside the UI."""
import io
import math
import os
import struct
import threading
import wave

from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton,
                             QLineEdit, QComboBox, QSlider, QDoubleSpinBox,
                             QFileDialog, QMessageBox, QCheckBox)

from core.audio_tools import analyze_wav
from core.design_tokens import LayoutRole, TypeSize, ui_font
from core.style_helpers import ss_dim_label, ss_input_validation, ss_slider, ss_error_label, ss_check, make_editor_field_shell
from core.translations import ui_text
from core.ui.audio_waveform import AudioWaveform
from core.ui.editor_widgets import configure_layout, configure_button, configure_input
from core.ui.number_input import FloatStepper, IntegerStepper
from core.ui.timeline_controls import TimelineZoomControls, timeline_icon_button
from parsers.awb_parser import extract_entry, _detect_format
from parsers.hca_decoder import parse_hca_info, set_hca_volume, set_hca_loop


class AudioWorkspace:
    def _clear_audio_controls(self):
        for name in ('_vol_input', '_play_btn', '_pause_btn', '_stop_btn', '_play_status',
                     '_seek_slider', '_waveform_widget', '_gain_status', '_loop_enable'):
            if hasattr(self, name):
                delattr(self, name)

    def _audio_hint(self, layout, key, **values):
        label = QLabel(ui_text(key, **values))
        label.setWordWrap(True)
        label.setFont(ui_font(TypeSize.HINT))
        label.setStyleSheet(ss_dim_label())
        label.setMinimumWidth(0)
        layout.addWidget(label)
        return label

    def _build_audio_workspace(self, idx, info):
        section = self._make_section(self.t('sound_section_playback'))
        layout = section.layout()
        if info:
            self._audio_hint(layout, 'awb_stream_info', channels=info['channels'],
                             rate=info['sample_rate'], duration=f"{info['duration']:.3f}")
        self._audio_hint(layout, 'awb_preview_scope')
        self._source_combo = configure_input(QComboBox(), monospace=False)
        self._source_combo.setMinimumWidth(0)
        self._source_combo.addItem(ui_text('awb_source_current'), False)
        original = self._entries[idx].get('_source_index')
        if original is not None:
            self._source_combo.addItem(ui_text('awb_source_original'), True)
        self._source_combo.setToolTip(ui_text('awb_source_hint'))
        self._source_combo.currentIndexChanged.connect(self._change_source)
        layout.addWidget(self._source_combo)
        controls = QWidget()
        row = configure_layout(QHBoxLayout(controls), LayoutRole.FIELD)
        self._play_btn = timeline_icon_button(self.t('sound_btn_play'), 'fa6s.play', lambda: self._play_audio(idx))
        self._pause_btn = timeline_icon_button(ui_text('ui_sound_pause'), 'fa6s.pause', self._toggle_pause)
        self._stop_btn = timeline_icon_button(self.t('sound_btn_stop'), 'fa6s.stop', self._stop_playback)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        for button in (self._play_btn, self._pause_btn, self._stop_btn):
            row.addWidget(button)
        self._play_status = QLabel('')
        self._play_status.setMinimumWidth(0)
        self._play_status.setWordWrap(True)
        self._play_status.setStyleSheet(ss_dim_label())
        row.addWidget(self._play_status, 1)
        layout.addWidget(controls)
        self._waveform_widget = AudioWaveform()
        self._waveform_widget.seekRequested.connect(self._seek_to)
        layout.addWidget(self._waveform_widget)
        self._zoom = TimelineZoomControls(self._waveform_widget)
        layout.addWidget(self._zoom)
        seek_row = QWidget()
        seek = configure_layout(QHBoxLayout(seek_row), LayoutRole.FIELD)
        self._seek_slider = QSlider(Qt.Orientation.Horizontal)
        self._seek_slider.setRange(0, 10000)
        self._seek_slider.setStyleSheet(ss_slider())
        self._seek_slider.setToolTip(ui_text('awb_seek'))
        self._seek_slider.setAccessibleName(ui_text('awb_seek'))
        self._seek_slider.valueChanged.connect(self._slider_seek)
        seek.addWidget(self._seek_slider, 1)
        self._seek_time = configure_input(QDoubleSpinBox())
        self._seek_time.setDecimals(3)
        self._seek_time.setRange(0, 0)
        self._seek_time.setSingleStep(.1)
        self._seek_time.setSuffix(' s')
        self._seek_time.setToolTip(ui_text('awb_seek'))
        self._seek_time.setAccessibleName(ui_text('awb_seek'))
        self._seek_time.editingFinished.connect(lambda: self._seek_to(self._seek_time.value()))
        seek.addWidget(self._seek_time)
        layout.addWidget(seek_row)
        self._preview_stats = self._audio_hint(layout, 'awb_waveform_empty')
        self._loop_btn = configure_button(QPushButton(ui_text('awb_audition_loop')))
        self._loop_btn.setCheckable(True)
        self._loop_btn.setChecked(False)
        self._audition_loop.clear()
        self._loop_btn.toggled.connect(lambda enabled: self._audition_loop.set() if enabled else self._audition_loop.clear())
        self._loop_btn.setEnabled(bool(info and info.get('loop_valid')))
        self._loop_btn.setToolTip(ui_text('awb_loop_hint'))
        layout.addWidget(self._loop_btn)
        self._loop_summary = self._audio_hint(layout, 'awb_loop_none')
        if info and info['loop_enabled']:
            self._loop_summary.setText(ui_text('awb_loop_points' if info['loop_valid'] else 'awb_loop_invalid',
                             start=f"{info['loop_start_sample'] / info['sample_rate']:.3f}",
                             end=f"{info['loop_end_sample'] / info['sample_rate']:.3f}"))

        if info:
            volume_section = self._make_section(self.t('sound_section_volume'))
            volume = volume_section.layout()
            self._audio_hint(volume, 'awb_gain_hint')
            self._volume_entry = idx
            self._volume_loaded = info['rva_volume']
            self._vol_input = configure_input(QLineEdit(str(self._volume_loaded)))
            self._volume_text = self._vol_input.text()
            self._vol_input.setAccessibleName(ui_text('awb_gain'))
            self._vol_input.setToolTip(ui_text('awb_gain_hint'))
            self._gain_stepper = FloatStepper(self._vol_input, .05)
            volume.addWidget(self._gain_stepper)
            self._gain_status = self._audio_hint(volume, 'awb_gain')
            self._vol_input.textChanged.connect(self._volume_feedback)
            self._vol_input.editingFinished.connect(self._commit_volume)
            self._volume_feedback()
            apply_button = configure_button(QPushButton(ui_text('awb_apply_gain')), accent=True)
            self._apply_gain_btn = apply_button
            apply_button.clicked.connect(self._commit_volume)
            volume.addWidget(apply_button)
            self._build_loop_fields(idx, info)
        restore = configure_button(QPushButton(ui_text('awb_restore_stream')))
        restore.setEnabled(original is not None)
        restore.setToolTip(ui_text('awb_restore_hint'))
        restore.clicked.connect(self._restore_stream)
        layout.addWidget(restore)
        restore.hide()
        # Decryption far into encrypted banks is explicit; all other previews decode lazily.
        self._prepare_preview_btn = configure_button(QPushButton(ui_text('awb_prepare_waveform')))
        self._prepare_preview_btn.clicked.connect(lambda: self._request_preview(False))
        layout.addWidget(self._prepare_preview_btn)
        self._seek_slider.setEnabled(False)
        self._seek_time.setEnabled(False)
        from editors.sound_editor import _entry_needs_slow_seek
        if not _entry_needs_slow_seek(self._entries[idx]):
            self._request_preview(False)

    def _volume_feedback(self, *_):
        value = self._gain_value()
        self._vol_input.setStyleSheet(ss_input_validation(value is None))
        self._gain_status.setStyleSheet(ss_dim_label())
        if value is None:
            self._gain_status.setText(ui_text('awb_gain_invalid'))
        else:
            db = '−∞' if value == 0 else f'{20 * math.log10(value):+.2f}'
            self._gain_status.setText(ui_text('awb_gain_level', gain=f'{value:.7g}', db=db))

    def _gain_value(self):
        try:
            value = float(self._vol_input.text())
            value = struct.unpack('>f', struct.pack('>f', value))[0]
            return value if math.isfinite(value) and value >= 0 else None
        except (ValueError, OverflowError, struct.error):
            return None

    def _commit_volume(self, *_):
        """Validate the complete audio form, then publish one header edit."""
        if self._busy:
            return False
        if not hasattr(self, '_vol_input'):
            return True
        gain_changed = self._vol_input.text() != self._volume_text
        loop_changed = self._loop_form_state() != self._loop_saved
        if not gain_changed and not loop_changed:
            return True
        value = self._gain_value() if gain_changed else self._volume_loaded
        if gain_changed and value is None:
            self._vol_input.setFocus()
            return False
        enabled = self._loop_enable.isChecked()
        start, end = (field.value() for field in self._loop_fields)
        if loop_changed and enabled and (start is None or end is None or start >= end):
            self._loop_feedback.setText(ui_text('awb_loop_edit_invalid', total=self._loop_total))
            self._loop_feedback.setStyleSheet(ss_error_label())
            return False
        idx = self._volume_entry
        original = self._get_entry_bytes(idx)
        data = original
        feedback = self._loop_feedback
        try:
            if loop_changed:
                data = set_hca_loop(data, enabled, start or 0, end)
            feedback = self._gain_status
            if gain_changed and value != self._volume_loaded:
                data = set_hca_volume(data, value)
        except Exception as error:
            feedback.setText(str(error))
            feedback.setStyleSheet(ss_error_label())
            return False
        self._volume_loaded, self._volume_text = value, self._vol_input.text()
        self._loop_saved = self._loop_form_state()
        self._loop_feedback.setText(ui_text('awb_loop_edit_hint'))
        self._loop_feedback.setStyleSheet(ss_dim_label())
        if data == original:
            return True
        self._stop_playback()
        entry = self._entries[idx]
        entry['_new_data'], entry['size'] = data, len(data)
        if gain_changed:
            self._wav_cache.pop(idx, None)
        self._preview_generation += 1
        self._preview_active = None
        self._preview_wav = None
        self._mark_dirty()
        self._filter_list()
        self._request_preview(False)
        return True

    def _change_source(self, *_):
        if not self._commit_volume():
            with QSignalBlocker(self._source_combo):
                self._source_combo.setCurrentIndex(1 if self._original_mode else 0)
            return
        self._stop_playback()
        self._preview_generation += 1
        self._preview_active = None
        self._preview_wav = None
        self._original_mode = bool(self._source_combo.currentData())
        if hasattr(self, '_vol_input'):
            self._vol_input.setReadOnly(self._original_mode)
            self._gain_stepper.refresh()
            self._apply_gain_btn.setEnabled(not self._original_mode)
        if hasattr(self, '_loop_enable'):
            self._loop_enable.setEnabled(not self._original_mode)
            self._loop_edit_state()
        self._cursor_seconds = 0.
        self._request_preview(False)

    def _request_preview(self, play=False):
        idx = self._current_entry
        if idx is None:
            return
        generation = self._preview_generation
        if self._preview_active == generation:
            self._play_after_preview = self._play_after_preview or play
            return
        self._play_after_preview = play
        self._preview_active = generation
        self._play_status.setText(self.t('sound_status_decoding'))
        self._preview_stats.setText(ui_text('awb_waveform_empty'))
        self._waveform_widget.clear()
        self._seek_slider.setEnabled(False)
        self._seek_time.setEnabled(False)
        self._prepare_preview_btn.setEnabled(False)
        current = dict(self._entries[idx])
        original = self._original_mode
        cache_key = ('original', current.get('_source_index')) if original else idx
        if original:
            entry = dict(self._original_entries[current['_source_index']])
            raw = self._original_raw
        else:
            entry, raw = current, self._raw_data
        cached = self._wav_cache.get(cache_key)
        def worker():
            if generation != self._preview_generation:
                return
            try:
                data = entry.get('_new_data', entry.get('_prepared_data'))
                if data is None:
                    data = extract_entry(raw, entry)
                info = parse_hca_info(data) if _detect_format(data) == 'HCA' else None
                if info and info['cipher_type'] == 56 and self._meta.get('subkey', 0):
                    raise ValueError(ui_text('awb_subkey_unsupported'))
                # The CLI is substantially faster for large banks; Python remains a fallback.
                from editors.sound_editor import _decode_audio_to_wav
                if generation != self._preview_generation:
                    return
                wav = cached if cached is not None else _decode_audio_to_wav(data, _detect_format(data))
                envelope = analyze_wav(wav)
                result = (generation, cache_key, wav, envelope, info, '')
            except Exception as error:
                result = (generation, cache_key, None, None, None, str(error))
            if generation == self._preview_generation:
                try:
                    self._sig_preview_ready.emit(result)
                except RuntimeError:
                    return  # The owner window was destroyed during decoding.
        if self._preview_future is not None:
            self._preview_future.cancel()
        self._preview_future = self._preview_pool.submit(worker)

    def _preview_done(self, result):
        generation, cache_key, wav, envelope, info, error = result
        if generation != self._preview_generation:
            return
        self._hide_decode_busy()
        self._preview_active = None
        self._prepare_preview_btn.setEnabled(True)
        if error:
            self._play_status.setText(self.t('sound_status_error'))
            self._preview_stats.setText(error)
            self._preview_stats.setStyleSheet(ss_error_label())
            return
        self._wav_cache[cache_key] = wav
        self._preview_wav = wav
        self._seek_total, self._seek_fps = envelope.duration, envelope.sample_rate
        self._seek_total_frames = envelope.frames
        self._loop_samples = ((info['loop_start_sample'], info['loop_end_sample'])
                              if info and info.get('loop_valid') else None)
        self._loop_btn.setEnabled(self._loop_samples is not None)
        if self._loop_samples is None:
            self._loop_btn.setChecked(False)
        self._loop_summary.setText(ui_text('awb_loop_none') if not info or not info['loop_enabled'] else
            ui_text('awb_loop_points' if info['loop_valid'] else 'awb_loop_invalid',
                start=f"{info['loop_start_sample'] / info['sample_rate']:.3f}",
                end=f"{info['loop_end_sample'] / info['sample_rate']:.3f}"))
        loop = tuple(value / envelope.sample_rate for value in self._loop_samples) if self._loop_samples else None
        self._waveform_widget.set_audio(envelope, loop)
        self._waveform_widget.loop_editable = not self._original_mode
        self._seek_slider.setEnabled(True)
        self._seek_time.setEnabled(True)
        self._seek_time.setMaximum(envelope.duration)
        self._seek_to(min(self._cursor_seconds, envelope.duration))
        self._preview_stats.setStyleSheet(ss_dim_label())
        self._preview_stats.setText(ui_text('awb_pcm_stats', channels=envelope.channels,
            rate=envelope.sample_rate, peak=f'{envelope.peak * 100:.2f}', clipped=envelope.clipped))
        if self._play_after_preview:
            self._start_playback(wav, self._current_entry)

    def _play_audio(self, idx):
        if not self._commit_volume():
            return
        if self._preview_wav is None:
            self._request_preview(True)
        else:
            self._start_playback(self._preview_wav, idx)

    def _start_playback(self, wav_data, idx):
        if self._shutdown_event.is_set():
            return
        self._stop_playback()
        self._play_generation += 1
        generation = self._play_generation
        self._stop_flag, self._pause_flag = threading.Event(), threading.Event()
        stop, pause = self._stop_flag, self._pause_flag
        self._seek_state = [None]
        seek_state = self._seek_state
        seek_lock, shutdown = self._seek_lock, self._shutdown_event
        progress_signal, done_signal = self._sig_play_progress, self._sig_playback_done
        start = int(self._cursor_seconds * self._seek_fps)
        loop, loop_enabled = self._loop_samples, self._audition_loop
        self._playing = True
        self._play_btn.setEnabled(False)
        self._pause_btn.setEnabled(True)
        self._stop_btn.setEnabled(True)
        def worker():
            pa, stream = None, None
            error = ''
            try:
                from editors.sound_editor import _import_pyaudio
                pa = _import_pyaudio().PyAudio()
                with wave.open(io.BytesIO(wav_data), 'rb') as wav:
                    stream = pa.open(format=pa.get_format_from_width(wav.getsampwidth()),
                                     channels=wav.getnchannels(), rate=wav.getframerate(), output=True)
                    total, rate = wav.getnframes(), wav.getframerate()
                    wav.setpos(start if start < total else 0)
                    while not stop.is_set() and not shutdown.is_set():
                        if pause.is_set():
                            stop.wait(.03)
                            continue
                        with seek_lock:
                            target, seek_state[0] = seek_state[0], None
                        if target is not None:
                            wav.setpos(max(0, min(total, target)))
                        end = loop[1] if loop and loop_enabled.is_set() else total
                        if wav.tell() >= end:
                            if loop and loop_enabled.is_set():
                                wav.setpos(loop[0])
                            else:
                                break
                        data = wav.readframes(min(2048, end - wav.tell()))
                        if not data:
                            break
                        stream.write(data)
                        if stop.is_set() or shutdown.is_set():
                            break
                        try:
                            progress_signal.emit(generation, wav.tell() / rate, total / rate)
                        except RuntimeError:
                            break  # The QObject can be deleted between the check and emit.
            except Exception as exc:
                error = str(exc)
            finally:
                if stream:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                if pa:
                    try:
                        pa.terminate()
                    except Exception:
                        pass
                if not shutdown.is_set():
                    try:
                        done_signal.emit(generation, error)
                    except RuntimeError:
                        pass
        self._play_thread = threading.Thread(target=worker, daemon=True)
        self._play_thread.start()

    def _toggle_pause(self):
        if self._pause_flag.is_set():
            self._pause_flag.clear()
            self._pause_btn.setToolTip(ui_text('ui_sound_pause'))
        else:
            self._pause_flag.set()
            self._pause_btn.setToolTip(ui_text('ui_sound_resume'))

    def _slider_seek(self, value):
        self._seek_to(self._seek_total * value / self._seek_slider.maximum())

    def _seek_to(self, seconds):
        self._cursor_seconds = max(0., min(self._seek_total, seconds))
        with QSignalBlocker(self._seek_slider):
            self._seek_slider.setValue(round(self._cursor_seconds / max(.001, self._seek_total) * self._seek_slider.maximum()))
        with QSignalBlocker(self._seek_time):
            self._seek_time.setValue(self._cursor_seconds)
        self._waveform_widget.set_position(self._cursor_seconds)
        self._play_status.setText(f'{self._cursor_seconds:.3f} / {self._seek_total:.3f} s')
        if self._playing:
            with self._seek_lock:
                self._seek_state[0] = int(self._cursor_seconds * self._seek_fps)

    def _update_play_progress(self, generation, elapsed, total):
        if generation != self._play_generation:
            return
        # Update cursor without scheduling a seek back into the worker.
        self._playing = False
        self._seek_to(elapsed)
        self._playing = True

    def _on_playback_done(self, generation, error=''):
        if generation != self._play_generation:
            return
        self._playing = False
        self._play_btn.setEnabled(True)
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        if error:
            self._play_status.setText(error)

    def _stop_playback(self):
        self._stop_flag.set()
        self._pause_flag.clear()
        self._play_generation += 1
        self._playing = False
        self._play_after_preview = False
        for name, enabled in (('_play_btn', True), ('_pause_btn', False), ('_stop_btn', False)):
            button = getattr(self, name, None)
            if button is not None:
                try:
                    button.setEnabled(enabled)
                except RuntimeError:
                    pass

    def _restore_stream(self):
        if not self._commit_volume():
            return
        idx = self._current_entry
        entry = self._entries[idx]
        if '_source_index' not in entry:
            return
        original = self._original_entries[entry['_source_index']]
        entry['_new_data'] = extract_entry(self._original_raw, original)
        entry['size'], entry['format'] = len(entry['_new_data']), original['format']
        self._wav_cache.pop(idx, None)
        self._mark_dirty()
        self._populate_list()

    def _extract_encoded(self, idx):
        if not self._commit_volume():
            return
        entry = self._entries[idx]
        extension = {'HCA': '.hca', 'ADX': '.adx'}.get(entry['format'], '.bin')
        path, _ = QFileDialog.getSaveFileName(self, ui_text('awb_export_encoded'),
                    f"entry_{entry['id']}{extension}", 'Audio (*' + extension + ')')
        if path:
            try:
                with open(path if os.path.splitext(path)[1] else path + extension, 'wb') as output:
                    output.write(self._get_entry_bytes(idx))
            except Exception as error:
                QMessageBox.critical(self, self.t('dlg_title_error'), str(error))

    def _build_loop_fields(self, idx, info):
        section = self._make_section(ui_text('awb_loop_settings'))
        layout = section.layout()
        self._loop_enable = QCheckBox(ui_text('awb_loop_enabled'))
        self._loop_enable.setFont(ui_font(TypeSize.LABEL))
        self._loop_enable.setStyleSheet(ss_check())
        self._loop_enable.setChecked(info['loop_enabled'])
        self._loop_enable.toggled.connect(self._loop_edit_state)
        layout.addWidget(self._loop_enable)
        self._loop_fields = []
        for key, value in (('awb_loop_start', info['loop_start_sample'] if info['loop_enabled'] else 0),
                           ('awb_loop_end', info['loop_end_sample'] if info['loop_enabled'] else info['actual_samples'])):
            shell, field_layout, _, _ = make_editor_field_shell(ui_text(key))
            edit = configure_input(QLineEdit(str(value)))
            edit.setAccessibleName(ui_text(key))
            stepper = IntegerStepper(edit, 0, info['actual_samples'])
            field_layout.addWidget(stepper)
            layout.addWidget(shell)
            self._loop_fields.append(stepper)
        self._loop_total = info['actual_samples']
        self._loop_saved = self._loop_form_state()
        self._loop_feedback = self._audio_hint(layout, 'awb_loop_edit_hint')
        self._loop_apply = configure_button(QPushButton(ui_text('awb_apply_loop')))
        self._loop_apply.clicked.connect(self._commit_volume)
        layout.addWidget(self._loop_apply)
        self._waveform_widget.loopEditRequested.connect(self._drag_loop)
        self._loop_edit_state()

    def _loop_form_state(self):
        return (self._loop_enable.isChecked(), *(field.edit.text() for field in self._loop_fields))

    def _loop_edit_state(self, *_):
        if not hasattr(self, '_loop_fields'):
            return
        editable = not self._original_mode
        for field in self._loop_fields:
            field.setEnabled(editable and self._loop_enable.isChecked())
        self._loop_apply.setEnabled(editable)

    def _commit_loop(self):
        return self._commit_volume()

    def _drag_loop(self, samples):
        if self._original_mode or not self._commit_volume():
            return
        start, end = samples
        self._loop_fields[0].edit.setText(str(start))
        self._loop_fields[1].edit.setText(str(end))
        if not self._commit_loop():
            # Failed edits leave the precise input visible; restore the graph to stored data.
            info = parse_hca_info(self._get_entry_bytes(self._current_entry))
            self._waveform_widget.loop = (info['loop_start_sample'] / info['sample_rate'],
                                           info['loop_end_sample'] / info['sample_rate'])
            self._waveform_widget.update()

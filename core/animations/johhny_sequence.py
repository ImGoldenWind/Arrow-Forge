import os

from PyQt6.QtCore import QPropertyAnimation, QSize, Qt, QTimer, QUrl
from PyQt6.QtGui import QImageReader, QMovie, QPixmap
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QMessageBox

from core.runtime_paths import app_path
from core.quiet_unlocks import request_and_cascade
from core.secret_assets import materialize_secret_asset


class JohhnySequenceMixin:
    def _start_typing(self, text):
        self._typing_timer.stop()
        self._typing_text = text
        self._typing_idx = 0
        self._char_quote_label.setText("")
        self._typing_timer.start()

    def _type_tick(self):
        if self._typing_idx <= len(self._typing_text):
            self._char_quote_label.setText(self._typing_text[:self._typing_idx])
            self._typing_idx += 1
        else:
            self._typing_timer.stop()

    def _on_hover(self, dlg_key, cat_key=None):
        cat_key = cat_key or self._current_cat
        speaker_key = self._category_speaker_key(cat_key)
        speaker_name = self.t(speaker_key)
        portrait = self._portrait_images.get(cat_key)
        if portrait:
            self._avatar_label.setPixmap(portrait)
            self._avatar_label.setText("")
        else:
            self._avatar_label.setPixmap(QPixmap())
            self._avatar_label.setText(speaker_name[0] if speaker_name else "")
        self._char_name_label.setText(speaker_name)
        self._start_typing(self.t(dlg_key))

    def _on_leave(self):
        pass

    def _on_avatar_click(self, event=None):
        if self._current_cat == "MOVESET":
            self._moveset_avatar_clicks += 1
            if self._moveset_avatar_clicks == 5:
                self._unlock_secret_tab()
            return

        self._moveset_avatar_clicks = 0
        if self._current_cat == "CHARACTER":
            request_and_cascade(self, "Baby Face")
            wav_path = app_path("resources", "audio", "DiMolto.wav")
            if not os.path.exists(wav_path):
                return
            if os.name != "nt":
                try:
                    from PyQt6.QtMultimedia import QSoundEffect
                    effect = getattr(self, "_avatar_sound_effect", None)
                    if effect is None:
                        effect = QSoundEffect(self)
                        effect.setSource(QUrl.fromLocalFile(wav_path))
                        effect.setVolume(0.5)
                        self._avatar_sound_effect = effect
                    effect.play()
                except Exception:
                    pass
                return
            import wave, array, io
            try:
                import winsound
            except ImportError:
                return
            try:
                with wave.open(wav_path, "rb") as wf:
                    params = wf.getparams()
                    frames = wf.readframes(params.nframes)
                sw = params.sampwidth
                if sw == 2:
                    samples = array.array("h", frames)
                    for i in range(len(samples)):
                        samples[i] = int(samples[i] * 0.5)
                    frames = samples.tobytes()
                elif sw == 1:
                    samples = array.array("B", frames)
                    for i in range(len(samples)):
                        samples[i] = int((samples[i] - 128) * 0.5 + 128)
                    frames = samples.tobytes()
                buf = io.BytesIO()
                with wave.open(buf, "wb") as out:
                    out.setparams(params)
                    out.writeframes(frames)
                winsound.PlaySound(buf.getvalue(), winsound.SND_MEMORY | winsound.SND_ASYNC)
            except Exception:
                try:
                    winsound.PlaySound(wav_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
                except Exception:
                    pass

    def _unlock_secret_tab(self):
        if self._secret_unlocked:
            return
        self._secret_unlocked = True
        self._moveset_avatar_clicks = 0
        self._rebuild_ui()

    def _start_johhny_sequence(self):
        try:
            gif_path = materialize_secret_asset("jwalker")
        except Exception:
            QMessageBox.warning(self, "Johhny walking-nator", "Animation payload not found.")
            return

        self._play_johhny_sound()

        if self._johhny_overlay:
            self._johhny_overlay.deleteLater()

        overlay = QLabel(self._view_stack)
        overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay.setStyleSheet("background: transparent;")
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        movie = QMovie(gif_path)
        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        movie.setScaledSize(self._johhny_scaled_size(gif_path))
        overlay.setFixedSize(movie.scaledSize())
        overlay.setMovie(movie)

        opacity = QGraphicsOpacityEffect(overlay)
        opacity.setOpacity(0.0)
        overlay.setGraphicsEffect(opacity)

        fade = QPropertyAnimation(opacity, b"opacity", self)
        fade.setDuration(750)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)

        self._johhny_overlay = overlay
        self._johhny_movie = movie
        self._johhny_opacity_anim = fade
        self._johhny_loops = 0
        self._johhny_prev_frame = -1
        self._johhny_closing = False

        movie.frameChanged.connect(self._on_johhny_frame_changed)
        movie.finished.connect(self._on_johhny_movie_finished)

        self._center_johhny_overlay()
        overlay.raise_()
        overlay.show()
        fade.start()
        movie.start()

    def _johhny_scaled_size(self, gif_path):
        bounds = self._view_stack.size()
        max_w = max(240, int(bounds.width() * 0.72))
        max_h = max(180, int(bounds.height() * 0.72))
        src_size = QImageReader(gif_path).size()
        if src_size.isValid() and not src_size.isEmpty():
            return src_size.scaled(QSize(max_w, max_h), Qt.AspectRatioMode.KeepAspectRatio)
        return QSize(min(480, max_w), min(360, max_h))

    def _center_johhny_overlay(self):
        overlay = getattr(self, "_johhny_overlay", None)
        if not overlay:
            return
        x = max(0, (self._view_stack.width() - overlay.width()) // 2)
        y = max(0, (self._view_stack.height() - overlay.height()) // 2)
        overlay.move(x, y)

    def _play_johhny_sound(self):
        try:
            wav_path = materialize_secret_asset("mystery_go")
        except Exception:
            return
        try:
            from PyQt6.QtMultimedia import QSoundEffect
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(wav_path))
            effect.setVolume(0.8)
            effect.setLoopCount(1)
            self._johhny_sound_effect = effect
            effect.play()
            return
        except Exception:
            pass
        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(wav_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
            except Exception:
                pass

    def _on_johhny_frame_changed(self, frame):
        movie = self._johhny_movie
        if movie is None:
            return
        total = movie.frameCount()
        if total > 0 and frame == total - 1:
            self._johhny_loops += 1
            self._finish_johhny_if_ready()
        elif total <= 0 and self._johhny_prev_frame >= 0 and frame < self._johhny_prev_frame:
            self._johhny_loops += 1
            self._finish_johhny_if_ready()
        self._johhny_prev_frame = frame

    def _on_johhny_movie_finished(self):
        movie = self._johhny_movie
        if movie is None:
            return
        total = movie.frameCount()
        if total <= 0 or self._johhny_prev_frame != total - 1:
            self._johhny_loops += 1
        if self._johhny_loops < 3:
            movie.jumpToFrame(0)
            movie.start()
            return
        self._finish_johhny_if_ready()

    def _finish_johhny_if_ready(self):
        if self._johhny_loops < 3 or self._johhny_closing:
            return
        self._johhny_closing = True
        movie = self._johhny_movie
        if movie is not None:
            movie.stop()
        QTimer.singleShot(250, self.close)

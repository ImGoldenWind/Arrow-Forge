import math
import os
import random
import struct
import tempfile
import time
import wave

from PyQt6.QtCore import QTimer, QUrl, Qt
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel

from core.secret_assets import materialize_secret_asset, secret_asset_pixmap
from core.themes import P


class Death13ChaosMixin:
    def _init_death13_chaos(self):
        self._death13_audio_timer = QTimer(self)
        self._death13_audio_timer.setSingleShot(True)
        self._death13_audio_timer.timeout.connect(self._death13_audio_tick)

        self._death13_overlay_timer = QTimer(self)
        self._death13_overlay_timer.setSingleShot(True)
        self._death13_overlay_timer.timeout.connect(self._death13_overlay_tick)

        self._death13_flash_timer = QTimer(self)
        self._death13_flash_timer.setInterval(46)
        self._death13_flash_timer.timeout.connect(self._death13_flash_frame)

        self._death13_shimmer_timer = QTimer(self)
        self._death13_shimmer_timer.setInterval(24)
        self._death13_shimmer_timer.timeout.connect(self._death13_shimmer_frame)

        self._death13_sound_effects = {}
        self._death13_temp_effects = []
        self._death13_temp_wavs = []
        self._death13_overlay = None
        self._death13_overlay_source = None
        self._death13_flash_frames_left = 0
        self._death13_shimmer_overlay = None
        self._death13_shimmer_started_at = 0.0
        self._death13_shimmer_until = 0.0
        self._sync_death13_chaos()

    def _death13_chaos_active(self):
        return (
            getattr(self, "_theme_key", None) == "Death 13"
            and self._settings.get("animation_theme_personality", True)
        )

    def _sync_death13_chaos(self):
        if not hasattr(self, "_death13_audio_timer"):
            return
        if self._death13_chaos_active():
            self._schedule_death13_audio()
            self._death13_overlay_timer.stop()
            return

        if hasattr(self, "_death13_audio_timer"):
            self._death13_audio_timer.stop()
        if hasattr(self, "_death13_overlay_timer"):
            self._death13_overlay_timer.stop()
        if hasattr(self, "_death13_flash_timer"):
            self._death13_flash_timer.stop()
        if hasattr(self, "_death13_shimmer_timer"):
            self._death13_shimmer_timer.stop()
        self._hide_death13_overlay()
        self._hide_death13_shimmer()

    def _schedule_death13_audio(self):
        if not self._death13_chaos_active():
            return
        min_minutes = self._death13_theme_float("death13_event_min_minutes", 30.0)
        max_minutes = self._death13_theme_float("death13_event_max_minutes", 60.0)
        if max_minutes < min_minutes:
            max_minutes = min_minutes
        delay = random.randint(int(min_minutes * 60_000), int(max_minutes * 60_000))
        self._death13_audio_timer.start(delay)

    def _schedule_death13_overlay(self):
        self._schedule_death13_audio()

    def _death13_audio_tick(self):
        if not self._death13_chaos_active():
            self._sync_death13_chaos()
            return

        roll = random.random()
        if roll < 0.52:
            self._play_death13_random_clip()
        elif roll < 0.78:
            self._flash_death13_overlay()
            self._play_death13_glitch_sound()
        elif roll < 0.90:
            self._play_death13_glitch_sound()
        else:
            self._play_death13_random_clip()
            QTimer.singleShot(random.randint(80, 220), self._flash_death13_overlay)
            self._play_death13_glitch_sound()
        self._schedule_death13_audio()

    def _death13_overlay_tick(self):
        if not self._death13_chaos_active():
            self._sync_death13_chaos()
            return

        self._flash_death13_overlay()
        self._play_death13_glitch_sound()
        if random.random() < 0.45:
            QTimer.singleShot(random.randint(70, 180), self._play_death13_glitch_sound)
        self._schedule_death13_overlay()

    def _death13_theme_float(self, key, default):
        try:
            return float(P.get(key, default))
        except (TypeError, ValueError):
            return default

    def _play_death13_random_clip(self):
        asset_ids = [
            asset_id.strip()
            for asset_id in P.get("death13_sound_ids", "d13_laugh|d13_circus|d13_robot").split("|")
            if asset_id.strip()
        ]
        if asset_ids:
            self._play_death13_clip_asset(random.choice(asset_ids))

    def _play_death13_named_clip(self, name):
        aliases = {
            "laugh": "d13_laugh",
            "circus": "d13_circus",
            "robot": "d13_robot",
        }
        asset_id = aliases.get(str(name).strip().lower())
        if asset_id:
            self._play_death13_clip_asset(asset_id)

    def _play_death13_clip_asset(self, asset_id):
        try:
            wav_path = materialize_secret_asset(asset_id)
        except Exception:
            return
        if asset_id == "d13_circus":
            self._start_death13_circus_shimmer(wav_path)

        try:
            from PyQt6.QtMultimedia import QSoundEffect
        except Exception:
            self._play_death13_winsound_clip(wav_path)
            return

        effect = self._death13_sound_effects.get(wav_path)
        if effect is None:
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(wav_path))
            effect.setLoopCount(1)
            self._death13_sound_effects[wav_path] = effect
        effect.setVolume(random.uniform(0.16, 0.42))
        effect.play()

    def _play_death13_winsound_clip(self, wav_path=None):
        if os.name != "nt":
            return
        if wav_path is None:
            asset_id = random.choice(("d13_laugh", "d13_circus", "d13_robot"))
            try:
                wav_path = materialize_secret_asset(asset_id)
            except Exception:
                return
            if asset_id == "d13_circus":
                self._start_death13_circus_shimmer(wav_path)
        try:
            import winsound
            winsound.PlaySound(wav_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
        except Exception:
            pass

    def _start_death13_circus_shimmer(self, wav_path):
        if not self._death13_chaos_active() or not hasattr(self, "_central"):
            return

        if self._death13_shimmer_overlay is None or self._death13_shimmer_overlay.parent() is not self._central:
            if self._death13_shimmer_overlay is not None:
                self._death13_shimmer_overlay.deleteLater()
            self._death13_shimmer_overlay = QLabel(self._central)
            self._death13_shimmer_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._death13_shimmer_overlay.setStyleSheet("background: transparent; border: none;")
            effect = QGraphicsOpacityEffect(self._death13_shimmer_overlay)
            effect.setOpacity(1.0)
            self._death13_shimmer_overlay.setGraphicsEffect(effect)

        duration = self._death13_wav_duration(wav_path)
        now = time.monotonic()
        self._death13_shimmer_started_at = now
        self._death13_shimmer_until = now + max(0.8, duration + 0.18)
        self._death13_shimmer_overlay.setGeometry(self._central.rect())
        self._death13_shimmer_overlay.show()
        self._death13_shimmer_overlay.raise_()
        self._death13_shimmer_frame()
        self._death13_shimmer_timer.start()

    def _death13_wav_duration(self, wav_path):
        try:
            with wave.open(wav_path, "rb") as wf:
                rate = wf.getframerate()
                if rate <= 0:
                    return 2.0
                return wf.getnframes() / rate
        except Exception:
            return 2.0

    def _death13_shimmer_frame(self):
        overlay = getattr(self, "_death13_shimmer_overlay", None)
        if overlay is None:
            self._death13_shimmer_timer.stop()
            return

        now = time.monotonic()
        if not self._death13_chaos_active() or now >= self._death13_shimmer_until:
            self._death13_shimmer_timer.stop()
            self._hide_death13_shimmer()
            return

        elapsed = now - self._death13_shimmer_started_at
        overlay.setGeometry(self._central.rect())
        overlay.raise_()

        def rgba(hue, alpha):
            color = QColor.fromHsv(int(hue) % 360, 210, 255)
            return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"

        sweep = elapsed * 980.0
        pulse = 0.5 + 0.5 * math.sin(elapsed * math.tau * 7.4)
        alpha_hi = int(42 + pulse * 44)
        alpha_mid = int(24 + pulse * 26)
        wobble = math.sin(elapsed * math.tau * 3.1) * 34.0
        overlay.setStyleSheet(
            "QLabel {"
            " border: none;"
            " background: qlineargradient("
            f" x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {rgba(sweep + wobble, alpha_hi)},"
            f" stop:0.18 {rgba(sweep + 86, alpha_mid)},"
            f" stop:0.36 {rgba(sweep + 151 - wobble, alpha_hi)},"
            f" stop:0.54 {rgba(sweep + 218, alpha_mid)},"
            f" stop:0.73 {rgba(sweep + 287 + wobble, alpha_hi)},"
            f" stop:1 {rgba(sweep + 354, alpha_mid)}"
            " );"
            "}"
        )

    def _hide_death13_shimmer(self):
        overlay = getattr(self, "_death13_shimmer_overlay", None)
        if overlay is not None:
            overlay.hide()

    def _play_death13_glitch_sound(self):
        wav_path = self._generate_death13_glitch_wav()
        if not wav_path:
            return
        try:
            from PyQt6.QtMultimedia import QSoundEffect
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(wav_path))
            effect.setLoopCount(1)
            effect.setVolume(random.uniform(0.12, 0.34))
            self._death13_temp_effects.append(effect)
            self._death13_temp_wavs.append(wav_path)
            effect.play()
            QTimer.singleShot(2600, lambda e=effect, p=wav_path: self._cleanup_death13_temp_sound(e, p))
            return
        except Exception:
            pass

        if os.name == "nt":
            try:
                import winsound
                winsound.PlaySound(wav_path, winsound.SND_ASYNC | winsound.SND_FILENAME)
            except Exception:
                pass

    def _generate_death13_glitch_wav(self):
        try:
            rate = 22050
            duration = random.uniform(0.13, 0.34)
            frames = int(rate * duration)
            base_freq = random.choice((73, 91, 123, 177, 231, 313, 421))
            bitcrush = random.choice((5, 6, 7, 8))
            gate = random.choice((37, 53, 71, 97))
            data = bytearray()
            for i in range(frames):
                t = i / rate
                chirp = base_freq + (i / max(1, frames)) * random.choice((480, 720, 960, 1320))
                tone = math.sin(math.tau * chirp * t)
                square = 1.0 if math.sin(math.tau * (base_freq * 0.37) * t) >= 0 else -1.0
                noise = random.uniform(-1.0, 1.0)
                sample = tone * 0.42 + square * 0.24 + noise * 0.34
                if (i // gate) % random.choice((3, 4, 5)) == 0:
                    sample *= random.uniform(0.04, 0.20)
                sample = round(sample * bitcrush) / bitcrush
                fade = min(1.0, i / max(1, rate * 0.018), (frames - i) / max(1, rate * 0.028))
                value = int(max(-1.0, min(1.0, sample * fade)) * 13500)
                data.extend(struct.pack("<h", value))

            fd, wav_path = tempfile.mkstemp(prefix="death13_glitch_", suffix=".wav")
            os.close(fd)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(bytes(data))
            return wav_path
        except Exception:
            return None

    def _cleanup_death13_temp_sound(self, effect, wav_path):
        try:
            effect.stop()
        except Exception:
            pass
        if effect in self._death13_temp_effects:
            self._death13_temp_effects.remove(effect)
        if wav_path in self._death13_temp_wavs:
            self._death13_temp_wavs.remove(wav_path)
        try:
            os.remove(wav_path)
        except OSError:
            pass

    def _flash_death13_overlay(self):
        source = self._death13_overlay_pixmap()
        if source is None:
            return
        if self._death13_overlay is None or self._death13_overlay.parent() is not self._central:
            if self._death13_overlay is not None:
                self._death13_overlay.deleteLater()
            self._death13_overlay = QLabel(self._central)
            self._death13_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._death13_overlay.setStyleSheet("background: transparent; border: none;")
            effect = QGraphicsOpacityEffect(self._death13_overlay)
            self._death13_overlay.setGraphicsEffect(effect)
        self._death13_flash_frames_left = random.randint(4, 8)
        self._death13_flash_frame()
        self._death13_flash_timer.start()

    def _death13_overlay_pixmap(self):
        asset_id = P.get("death13_overlay_asset", "d13_face")
        if self._death13_overlay_source is None or getattr(self, "_death13_overlay_asset", None) != asset_id:
            source = secret_asset_pixmap(asset_id)
            if source.isNull():
                return None
            self._death13_overlay_source = source
            self._death13_overlay_asset = asset_id
        return self._death13_overlay_source

    def _death13_glitched_overlay_frame(self):
        source = self._death13_overlay_pixmap()
        if source is None or not hasattr(self, "_central"):
            return None
        size = self._central.size()
        if size.width() <= 1 or size.height() <= 1:
            return None

        scaled = source.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - size.width()) // 2)
        y = max(0, (scaled.height() - size.height()) // 2)
        frame = scaled.copy(x, y, size.width(), size.height())

        base_frame = frame.copy()
        painter = QPainter(frame)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        for _ in range(random.randint(10, 22)):
            band_h = random.randint(2, max(4, size.height() // 22))
            band_y = random.randint(0, max(0, size.height() - band_h))
            shift = random.randint(-46, 46)
            band = base_frame.copy(0, band_y, size.width(), band_h)
            painter.setOpacity(random.uniform(0.45, 0.92))
            painter.drawPixmap(shift, band_y, band)

        colors = ("#B9FF38", "#62D7D9", "#FF5D8D", "#E84C63", "#FFF6C8")
        for _ in range(random.randint(8, 16)):
            color = QColor(random.choice(colors))
            color.setAlpha(random.randint(34, 96))
            painter.fillRect(
                random.randint(-40, size.width()),
                random.randint(0, size.height()),
                random.randint(32, max(48, size.width() // 3)),
                random.randint(2, 18),
                color,
            )

        painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        scan = QColor("#62D7D9")
        scan.setAlpha(42)
        painter.setPen(scan)
        for yy in range(random.randint(0, 5), size.height(), random.choice((5, 6, 8))):
            painter.drawLine(0, yy, size.width(), yy)
        painter.end()
        return frame

    def _death13_flash_frame(self):
        if self._death13_flash_frames_left <= 0 or self._death13_overlay is None:
            self._death13_flash_timer.stop()
            self._hide_death13_overlay()
            return
        pixmap = self._death13_glitched_overlay_frame()
        if pixmap is None:
            self._hide_death13_overlay()
            return
        self._death13_overlay.setGeometry(self._central.rect())
        self._death13_overlay.setPixmap(pixmap)
        effect = self._death13_overlay.graphicsEffect()
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(random.uniform(0.18, 0.44))
        self._death13_overlay.raise_()
        self._death13_overlay.show()
        self._death13_flash_frames_left -= 1

    def _hide_death13_overlay(self):
        overlay = getattr(self, "_death13_overlay", None)
        if overlay is not None:
            overlay.hide()

    def _resize_death13_overlay(self):
        overlay = getattr(self, "_death13_overlay", None)
        if overlay is not None and hasattr(self, "_central"):
            overlay.setGeometry(self._central.rect())
        shimmer = getattr(self, "_death13_shimmer_overlay", None)
        if shimmer is not None and hasattr(self, "_central"):
            shimmer.setGeometry(self._central.rect())

    def _shutdown_death13_chaos(self):
        for timer_name in (
            "_death13_audio_timer",
            "_death13_overlay_timer",
            "_death13_flash_timer",
            "_death13_shimmer_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        self._hide_death13_shimmer()
        for effect in list(getattr(self, "_death13_temp_effects", [])):
            try:
                effect.stop()
            except Exception:
                pass
        for wav_path in list(getattr(self, "_death13_temp_wavs", [])):
            try:
                os.remove(wav_path)
            except OSError:
                pass
        self._death13_temp_effects = []
        self._death13_temp_wavs = []

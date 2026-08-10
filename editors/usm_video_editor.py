import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

from PyQt6.QtCore import QProcess, QSize, Qt, pyqtSignal
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QBoxLayout,
    QFileDialog,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QStackedLayout,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from core.editor_file_state import set_file_label, set_file_label_empty
from core.external_tools import (
    find_ffmpeg,
    find_ffprobe,
    find_sofdec2_encoder,
    find_sofdec2_h264_encoder,
)
from core.settings import create_backup_on_open, game_files_dialog_dir
from core.style_helpers import (
    TOOLBAR_BTN_H,
    TOOLBAR_H,
    add_editor_card_title,
    ss_bg_dark,
    ss_bg_panel,
    ss_btn,
    ss_accent_sep,
    ss_blocking_overlay,
    ss_blocking_overlay_card,
    ss_check,
    ss_dim_label,
    ss_editor_card,
    ss_file_label,
    ss_main_label,
    ss_progressbar,
    ss_scrollarea,
    ss_section_label,
    ss_sep,
    ss_slider,
    ss_transparent,
    ss_video_matte,
)
from core.translations import ui_text


@dataclass
class MediaInfo:
    path: str = ""
    duration: float = 0.0
    video_codec: str = ""
    width: int = 0
    height: int = 0
    fps_text: str = ""
    fps: float = 0.0
    audio_codec: str = ""
    audio_channels: int = 0
    audio_layout: str = ""
    audio_rate: int = 0


PREVIEW_MAX_WIDTH = 640
PREVIEW_MIN_WIDTH = 220
MAX_IMPORT_DURATION_SECONDS = 10 * 60


def _ensure_ext(path: str, ext: str) -> str:
    return path if os.path.splitext(path)[1] else path + ext


def _parse_rate(value: str) -> tuple[str, float]:
    if not value or value == "0/0":
        return "", 0.0
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            den_f = float(den)
            fps = float(num) / den_f if den_f else 0.0
        except ValueError:
            return value, 0.0
        return value, fps
    try:
        return value, float(value)
    except ValueError:
        return value, 0.0


def _to_seconds(value: str | int | float | None) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _ffmpeg_time_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":", 2)
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _probe_creation_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AspectRatioWidget(QWidget):
    resized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._aspect_ratio = 16 / 9
        self.setMinimumWidth(PREVIEW_MIN_WIDTH)
        self.setMaximumWidth(PREVIEW_MAX_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_widescreen_aspect(self):
        self._aspect_ratio = 16 / 9
        self.updateGeometry()
        self._sync_height()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return max(1, round(width / self._aspect_ratio))

    def sizeHint(self) -> QSize:
        return QSize(PREVIEW_MAX_WIDTH, self.heightForWidth(PREVIEW_MAX_WIDTH))

    def minimumSizeHint(self) -> QSize:
        return QSize(PREVIEW_MIN_WIDTH, self.heightForWidth(PREVIEW_MIN_WIDTH))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_height()
        self.resized.emit()

    def _sync_height(self):
        width = self.width()
        if width <= 0:
            return
        target = self.heightForWidth(width)
        if self.height() != target:
            self.setFixedHeight(target)


class UsmVideoEditor(QWidget):
    def __init__(self, parent=None, lang_func=None, embedded=False):
        super().__init__(parent)
        self.t = lang_func or (lambda key, **kw: ui_text(key, **kw))
        self._original_path = ""
        self._import_path = ""
        self._staged_path = ""
        self._original_info = MediaInfo()
        self._import_info = MediaInfo()
        self._dirty = False
        self._process = None
        self._process_done = None
        self._process_log = []
        self._process_duration = 0.0
        self._process_duration_limit = 0.0
        self._process_workdir = ""
        self._tmpdir = tempfile.TemporaryDirectory(prefix="arrowforge_usm_")
        self._preview_path = ""
        self._preview_ready = False
        self._poster_path = ""
        self._poster_pixmap = QPixmap()
        self._poster_process = None
        self._poster_token = 0
        self._seeking = False

        self._build_ui()
        self._refresh_state()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setStyleSheet(ss_bg_dark())

        toolbar = QFrame()
        toolbar.setFixedHeight(TOOLBAR_H)
        toolbar.setStyleSheet(ss_bg_panel())
        toolbar_layout = QHBoxLayout(toolbar)

        self._open_btn = self._toolbar_button("btn_open_file", accent=True)
        self._open_btn.clicked.connect(self._load_file)
        toolbar_layout.addWidget(self._open_btn)

        self._save_btn = self._toolbar_button("btn_save_file", accent=True)
        self._save_btn.clicked.connect(self._save_file)
        toolbar_layout.addWidget(self._save_btn)

        self._file_label = QLabel(self.t("no_file_loaded"))
        self._file_label.setStyleSheet(ss_file_label())
        self._file_label.setMinimumWidth(0)
        self._file_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        toolbar_layout.addWidget(self._file_label, 1)

        root.addWidget(toolbar)

        sep = QFrame()
        sep.setFixedHeight(2)
        sep.setStyleSheet(ss_accent_sep())
        root.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_scrollarea())

        body = QWidget()
        body.setStyleSheet(ss_bg_dark())
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(14, 14, 14, 14)
        body_layout.setSpacing(14)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._body = body
        self._body_layout = body_layout
        self._compact_layout = None

        preview = self._panel()
        self._preview_panel = preview
        preview.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(10)
        preview_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        add_editor_card_title(preview_layout, self.t("usm_section_preview"), "fa6s.film")

        self._preview_inner = QWidget()
        self._preview_inner.setStyleSheet(ss_transparent())
        self._preview_inner.setMinimumWidth(0)
        self._preview_inner.setMaximumWidth(PREVIEW_MAX_WIDTH)
        self._preview_inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preview_inner_layout = QVBoxLayout(self._preview_inner)
        preview_inner_layout.setContentsMargins(0, 0, 0, 0)
        preview_inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._preview_surface = AspectRatioWidget()
        self._preview_surface.setStyleSheet(ss_video_matte())
        self._preview_surface.resized.connect(self._render_poster_pixmap)
        self._preview_stack = QStackedLayout(self._preview_surface)
        self._preview_stack.setContentsMargins(0, 0, 0, 0)

        self._poster_label = QLabel()
        self._poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._poster_label.setStyleSheet(ss_video_matte())

        self._video_widget = QVideoWidget()
        self._video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._video_widget.setStyleSheet(ss_video_matte())
        self._preview_stack.addWidget(self._poster_label)
        self._preview_stack.addWidget(self._video_widget)
        preview_inner_layout.addWidget(self._preview_surface)

        self._stretch_video_chk = QCheckBox(self.t("usm_toggle_stretch_video"))
        self._stretch_video_chk.setStyleSheet(ss_check())
        preview_inner_layout.addWidget(self._stretch_video_chk)

        controls = QHBoxLayout()
        self._play_btn = QPushButton()
        self._play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self._play_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._play_btn.setStyleSheet(ss_btn())
        self._play_btn.setToolTip(self.t("usm_preview_play"))
        self._play_btn.clicked.connect(self._toggle_preview_playback)
        controls.addWidget(self._play_btn)

        self._stop_btn = QPushButton()
        self._stop_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self._stop_btn.setFixedHeight(TOOLBAR_BTN_H)
        self._stop_btn.setStyleSheet(ss_btn())
        self._stop_btn.setToolTip(self.t("usm_preview_stop"))
        self._stop_btn.clicked.connect(self._stop_preview)
        controls.addWidget(self._stop_btn)

        self._position_slider = QSlider(Qt.Orientation.Horizontal)
        self._position_slider.setRange(0, 0)
        self._position_slider.setStyleSheet(ss_slider())
        self._position_slider.sliderPressed.connect(self._on_seek_start)
        self._position_slider.sliderReleased.connect(self._on_seek_finish)
        controls.addWidget(self._position_slider, 1)

        self._time_label = QLabel(self.t("usm_preview_time_empty"))
        self._time_label.setStyleSheet(ss_dim_label())
        controls.addWidget(self._time_label)
        preview_inner_layout.addLayout(controls)

        video_actions = QHBoxLayout()
        video_actions.setContentsMargins(0, 0, 0, 0)
        video_actions.setSpacing(8)
        self._export_btn = self._toolbar_button("usm_btn_export")
        self._export_btn.clicked.connect(self._export_video)
        video_actions.addWidget(self._export_btn)

        self._import_btn = self._toolbar_button("usm_btn_import")
        self._import_btn.clicked.connect(self._import_video)
        video_actions.addWidget(self._import_btn)
        preview_inner_layout.addLayout(video_actions)

        preview_layout.addWidget(self._preview_inner, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        body_layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignTop)

        summary = self._panel()
        self._summary_panel = summary
        summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(16, 14, 16, 14)
        summary_layout.setSpacing(10)
        add_editor_card_title(summary_layout, self.t("usm_section_media"), "fa6s.circle-info")
        grid = QGridLayout()
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(max(0, self.style().pixelMetric(QStyle.PixelMetric.PM_LayoutHorizontalSpacing)))
        grid.setVerticalSpacing(max(0, self.style().pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing)))
        self._source_value = self._value_label()
        self._original_value = self._value_label()
        self._import_value = self._value_label()
        self._staged_value = self._value_label()
        self._add_row(grid, "usm_label_source", self._source_value)
        self._add_row(grid, "usm_label_original", self._original_value)
        self._add_row(grid, "usm_label_imported", self._import_value)
        self._add_row(grid, "usm_label_staged", self._staged_value)
        summary_layout.addLayout(grid)
        summary_layout.addStretch()
        body_layout.addWidget(summary, 1, Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._build_busy_overlay()
        self._build_preview_player()
        self._apply_responsive_layout()

    def _toolbar_button(self, key: str, *, accent: bool = False) -> QPushButton:
        btn = QPushButton(self.t(key))
        btn.setFixedHeight(TOOLBAR_BTN_H)
        btn.setStyleSheet(ss_btn(accent=accent))
        return btn

    def _panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("EditorCard")
        panel.setStyleSheet(ss_editor_card())
        return panel

    def _section_label(self, key: str) -> QLabel:
        label = QLabel(self.t(key))
        label.setStyleSheet(ss_section_label())
        return label

    def _value_label(self) -> QLabel:
        label = QLabel(self.t("usm_value_empty"))
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setStyleSheet(ss_main_label())
        return label

    def _add_row(self, grid: QGridLayout, key: str, value: QLabel):
        row = grid.rowCount()
        label = QLabel(self.t(key))
        label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        label.setStyleSheet(ss_dim_label())
        grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
        grid.addWidget(value, row, 1, Qt.AlignmentFlag.AlignTop)

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        if self._original_path:
            set_file_label(self._file_label, self._original_path, dirty=dirty)

    def has_unsaved_changes(self):
        return self._dirty

    def load_file(self, path: str):
        self._open_usm(path)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("usm_open_title"),
            game_files_dialog_dir(target_patterns=("*.usm",)),
            self.t("usm_filter_usm"),
        )
        if path:
            self._open_usm(path)

    def _open_usm(self, path: str):
        if self._is_busy():
            return
        if not path or os.path.splitext(path)[1].lower() != ".usm":
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("usm_warning_not_usm"))
            return
        create_backup_on_open(path)
        self._original_path = path
        self._import_path = ""
        self._staged_path = ""
        self._import_info = MediaInfo()
        set_file_label_empty(self._file_label, self.t("loading"))
        try:
            self._original_info = self._probe_media(path)
        except Exception as exc:
            self._original_info = MediaInfo(path=path)
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("usm_status_probe_failed", error=exc))
        self._set_dirty(False)
        self._set_preview_source(path)
        self._refresh_state()

    def _probe_media(self, path: str) -> MediaInfo:
        ffprobe = find_ffprobe()
        if not ffprobe:
            raise RuntimeError(self.t("usm_error_ffprobe_missing"))
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_probe_creation_flags(),
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or self.t("no_output")).strip())
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        fps_text, fps = _parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate") or "")
        duration = _to_seconds(video.get("duration")) or _to_seconds((data.get("format") or {}).get("duration"))
        return MediaInfo(
            path=path,
            duration=duration,
            video_codec=str(video.get("codec_name") or ""),
            width=int(video.get("width") or 0),
            height=int(video.get("height") or 0),
            fps_text=fps_text,
            fps=fps,
            audio_codec=str(audio.get("codec_name") or ""),
            audio_channels=int(audio.get("channels") or 0),
            audio_layout=str(audio.get("channel_layout") or ""),
            audio_rate=int(audio.get("sample_rate") or 0),
        )

    def _refresh_state(self):
        has_original = bool(self._original_path)
        has_import = bool(self._import_path)
        has_staged = bool(self._staged_path)
        busy = self._is_busy()
        self._export_btn.setEnabled(has_original and not busy)
        self._import_btn.setEnabled(has_original and not busy)
        self._save_btn.setEnabled(has_original and (has_import or has_staged) and not busy)
        self._source_value.setText(os.path.basename(self._original_path) if has_original else self.t("usm_value_empty"))
        self._original_value.setText(self._describe_info(self._original_info) if has_original else self.t("usm_value_empty"))
        self._import_value.setText(self._describe_info(self._import_info) if has_import else self.t("usm_value_empty"))
        self._staged_value.setText(os.path.basename(self._staged_path) if has_staged else self.t("usm_value_empty"))
        self._update_preview_controls()
        self._apply_responsive_layout()

    def _apply_responsive_layout(self):
        if not hasattr(self, "_body_layout"):
            return
        compact = self.width() < 980
        if compact != self._compact_layout:
            direction = QBoxLayout.Direction.TopToBottom if compact else QBoxLayout.Direction.LeftToRight
            self._body_layout.setDirection(direction)
            self._preview_panel.setSizePolicy(
                QSizePolicy.Policy.Expanding if compact else QSizePolicy.Policy.Maximum,
                QSizePolicy.Policy.Preferred,
            )
            self._summary_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self._compact_layout = compact

        margins = self._body_layout.contentsMargins()
        available = max(0, self.width() - margins.left() - margins.right() - 32)
        preview_width = min(PREVIEW_MAX_WIDTH, max(PREVIEW_MIN_WIDTH, available))
        if compact:
            self._preview_panel.setMaximumWidth(16777215)
            self._summary_panel.setMaximumWidth(16777215)
            self._preview_inner.setMaximumWidth(preview_width)
            self._preview_surface.setMaximumWidth(preview_width)
            return

        self._preview_panel.setMaximumWidth(PREVIEW_MAX_WIDTH + 32)
        self._summary_panel.setMaximumWidth(620)
        self._preview_inner.setMaximumWidth(PREVIEW_MAX_WIDTH)
        self._preview_surface.setMaximumWidth(PREVIEW_MAX_WIDTH)

    def _describe_info(self, info: MediaInfo) -> str:
        if not info.path:
            return self.t("usm_value_empty")
        resolution = self.t("usm_value_unknown")
        if info.width and info.height:
            resolution = self.t("usm_value_resolution", width=info.width, height=info.height)
        fps = info.fps_text or self.t("usm_value_unknown")
        duration = self.t("usm_value_duration", seconds=f"{info.duration:.2f}") if info.duration else self.t("usm_value_unknown")
        audio = self.t("usm_value_no_audio")
        if info.audio_codec:
            audio = self.t(
                "usm_value_audio",
                codec=info.audio_codec,
                channels=info.audio_channels or self.t("usm_value_unknown"),
                rate=info.audio_rate or self.t("usm_value_unknown"),
            )
        return self.t(
            "usm_value_media_info",
            video=info.video_codec or self.t("usm_value_unknown"),
            resolution=resolution,
            fps=fps,
            duration=duration,
            audio=audio,
        )

    def _export_video(self):
        if not self._original_path or self._is_busy():
            return
        ffmpeg = self._require_ffmpeg()
        if not ffmpeg:
            return

        stem = os.path.splitext(os.path.basename(self._original_path))[0]

        path, _ = QFileDialog.getSaveFileName(
            self,
            self.t("usm_export_video_title"),
            os.path.join(game_files_dialog_dir(self._original_path), f"{stem}.mp4"),
            self.t("usm_filter_mp4"),
        )
        if not path:
            return
        self._start_process(
            self.t("usm_status_exporting"),
            *self._command_export_video(ffmpeg, _ensure_ext(path, ".mp4")),
        )

    def _command_export_video(self, ffmpeg: str, output_path: str):
        args = ["-y", "-i", self._original_path, "-map", "0:v:0", "-map", "0:a?"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
        args += ["-movflags", "+faststart", output_path]
        return ffmpeg, args, lambda ok: self._on_export_done(ok, output_path)

    def _on_export_done(self, ok: bool, output_path: str):
        if ok:
            self._set_preview_source(output_path)
            QMessageBox.information(self, self.t("dlg_title_success"), self.t("usm_status_exported", name=os.path.basename(output_path)))

    def _import_video(self):
        if not self._original_path or self._is_busy():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("usm_import_title"),
            game_files_dialog_dir(self._original_path),
            self.t("usm_filter_media"),
        )
        if not path:
            return

        try:
            info = self._probe_media(path)
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("usm_status_probe_failed", error=exc))
            return

        self._import_path = path
        self._import_info = info

        ffmpeg = self._require_ffmpeg()
        if not ffmpeg:
            return
        sofdec2 = self._require_sofdec2_encoder()
        if not sofdec2:
            return
        prepared = os.path.join(self._tmpdir.name, "asbr_compatible.avi")
        staged = os.path.join(self._tmpdir.name, "asbr_compatible.usm")
        args = self._prepare_avi_args(path, prepared)
        self._start_process(
            self.t("usm_status_preparing_media"),
            ffmpeg,
            args,
            lambda ok: self._on_prepare_done(ok, prepared, staged),
            progress_duration=self._import_progress_duration(),
        )

    def _prepare_avi_args(self, input_path: str, output_path: str) -> list[str]:
        original = self._original_info
        args = ["-y", "-i", input_path, "-map", "0:v:0", "-map", "0:a?"]
        filters = []
        if original.width and original.height:
            filters.append(self._video_fit_filter(original.width, original.height))
        if original.fps_text:
            filters.append(f"fps={original.fps_text}")
        if filters:
            args += ["-vf", ",".join(filters)]
        args += ["-t", str(MAX_IMPORT_DURATION_SECONDS)]
        args += ["-c:v", "rawvideo", "-pix_fmt", "bgr24"]
        if original.audio_codec or self._import_info.audio_codec:
            args += ["-c:a", "pcm_s16le"]
            if original.audio_channels:
                args += ["-ac", str(original.audio_channels)]
            if original.audio_rate:
                args += ["-ar", str(original.audio_rate)]
        else:
            args += ["-an"]
        args += ["-shortest", output_path]
        return args

    def _video_fit_filter(self, width: int, height: int) -> str:
        if self._stretch_video_chk.isChecked():
            return f"scale={width}:{height},setsar=1"
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
        )

    def _import_progress_duration(self) -> float:
        duration = self._import_info.duration or self._original_info.duration
        if duration:
            return min(duration, MAX_IMPORT_DURATION_SECONDS)
        return MAX_IMPORT_DURATION_SECONDS

    def _sofdec2_args(self, input_path: str, output_path: str) -> tuple[str, list[str]]:
        encoder = find_sofdec2_encoder()
        if self._original_info.video_codec == "h264":
            h264_encoder = find_sofdec2_h264_encoder()
            if h264_encoder:
                return h264_encoder, [
                    f"-in={input_path}",
                    "-target=ps4",
                    f"-out={output_path}",
                    "-hca=ON",
                    "-hca_quality=4",
                ]
        return encoder, [f"-in={input_path}", f"-out={output_path}"]

    def _on_prepare_done(self, ok: bool, prepared: str, staged: str):
        if not ok:
            return
        encoder, args = self._sofdec2_args(prepared, staged)
        self._start_process(
            self.t("usm_status_encoding_usm"),
            encoder,
            args,
            lambda done: self._on_transcode_done(done, staged),
            workdir=os.path.dirname(encoder),
        )

    def _on_transcode_done(self, ok: bool, staged: str):
        if not ok:
            return
        self._staged_path = staged
        self._set_dirty(True)
        self._set_preview_source(staged)
        self._refresh_state()
        QMessageBox.information(self, self.t("dlg_title_success"), self.t("usm_status_transcoded", name=os.path.basename(staged)))

    def _save_file(self):
        self._save_repack()

    def _save_repack(self):
        if not self._original_path or self._is_busy():
            return
        media_path = self._staged_path or self._import_path
        if not media_path:
            QMessageBox.warning(self, self.t("dlg_title_warning"), self.t("usm_warning_import_first"))
            return

        stem = os.path.splitext(os.path.basename(self._original_path))[0]
        default_path = os.path.join(os.path.dirname(self._original_path), self.t("usm_repack_default_name", stem=stem))
        output_path, _ = QFileDialog.getSaveFileName(
            self,
            self.t("usm_repack_title"),
            default_path,
            self.t("usm_filter_usm"),
        )
        if not output_path:
            return
        output_path = _ensure_ext(output_path, ".usm")
        if os.path.exists(output_path):
            answer = QMessageBox.question(
                self,
                self.t("dlg_title_warning"),
                self.t("usm_confirm_overwrite", name=os.path.basename(output_path)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            create_backup_on_open(output_path)

        try:
            shutil.copy2(media_path, output_path)
        except OSError as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("msg_save_error", error=exc))
            return
        self._on_repack_done(True, output_path)

    def _on_repack_done(self, ok: bool, output_path: str):
        if ok:
            self._set_dirty(False)
            QMessageBox.information(self, self.t("dlg_title_success"), self.t("usm_status_repacked", name=os.path.basename(output_path)))

    def _require_ffmpeg(self) -> str:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("usm_error_ffmpeg_missing"))
            return ""
        return ffmpeg

    def _require_sofdec2_encoder(self) -> str:
        sofdec2 = find_sofdec2_encoder()
        if not sofdec2:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("usm_error_sofdec2_missing"))
            return ""
        return sofdec2

    def _run_queue(self, commands: list[tuple[str, list[str], object]], title: str):
        if not commands:
            return

        def run_next(index: int):
            program, args, done = commands[index]

            def after(ok: bool):
                done(ok)
                if ok and index + 1 < len(commands):
                    run_next(index + 1)

            self._start_process(title, program, args, after)

        run_next(0)

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
        self._busy_title_lbl.setStyleSheet(ss_section_label())
        self._busy_title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._busy_title_lbl)

        self._busy_detail_lbl = QLabel("")
        self._busy_detail_lbl.setStyleSheet(ss_dim_label())
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
        self._apply_responsive_layout()
        if hasattr(self, "_busy_overlay"):
            self._busy_overlay.setGeometry(self.rect())
        self._render_poster_pixmap()

    def _set_busy(self, active: bool, title: str = "", detail: str = "", done: int = 0, total: int = 0):
        if not hasattr(self, "_busy_overlay"):
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
        if not hasattr(self, "_busy_bar"):
            return
        self._busy_detail_lbl.setText(text or "")
        if total > 0:
            self._busy_bar.setRange(0, total)
            self._busy_bar.setValue(max(0, min(done, total)))
        else:
            self._busy_bar.setRange(0, 0)

    def _start_process(self, title: str, program: str, args: list[str], done_callback, *, workdir: str = "", progress_duration: float = 0.0):
        if self._is_busy():
            return
        self._process_log = []
        self._process_done = done_callback
        self._process_duration = progress_duration or self._original_info.duration or self._import_info.duration
        self._process_duration_limit = progress_duration
        self._set_busy(True, title, "", 0, 100 if self._process_duration else 0)
        if self._process_duration:
            self._on_busy_progress("", 0, 100)
        else:
            self._on_busy_progress("", 0, 0)

        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(args)
        if workdir:
            process.setWorkingDirectory(workdir)
        process.readyReadStandardError.connect(self._read_process_output)
        process.readyReadStandardOutput.connect(self._read_process_output)
        process.finished.connect(self._on_process_finished)
        process.errorOccurred.connect(self._on_process_error)
        self._process = process
        self._refresh_state()
        process.start()

    def _read_process_output(self):
        if not self._process:
            return
        chunks = [
            bytes(self._process.readAllStandardError()).decode(errors="replace"),
            bytes(self._process.readAllStandardOutput()).decode(errors="replace"),
        ]
        text = "".join(chunks)
        if not text:
            return
        self._process_log.append(text)
        duration_match = re.search(r"Duration:\s*(\d+:\d+:\d+(?:\.\d+)?)", text)
        if duration_match:
            duration = _ffmpeg_time_to_seconds(duration_match.group(1))
            if self._process_duration_limit:
                duration = min(duration, self._process_duration_limit)
            self._process_duration = duration
            self._on_busy_progress("", 0, 100)
        time_matches = re.findall(r"time=(\d+:\d+:\d+(?:\.\d+)?)", text)
        if time_matches and self._process_duration:
            current = _ffmpeg_time_to_seconds(time_matches[-1])
            value = max(0, min(100, int((current / self._process_duration) * 100)))
            self._on_busy_progress(self.t("usm_status_progress", percent=value), value, 100)
            return
        percent_matches = re.findall(r"(\d+(?:\.\d+)?)%\s*/\s*100%", text)
        if percent_matches:
            value = max(0, min(100, int(float(percent_matches[-1]))))
            self._on_busy_progress(self.t("usm_status_progress", percent=value), value, 100)
            return
        frame_matches = re.findall(r"\(\s*(\d+)\s*/\s*(\d+)\s*\)", text)
        if frame_matches:
            done, total = frame_matches[-1]
            done_i = int(done)
            total_i = max(1, int(total))
            value = max(0, min(100, int((done_i / total_i) * 100)))
            self._on_busy_progress(self.t("usm_status_progress", percent=value), value, 100)

    def _on_process_error(self, error):
        self._finish_process(False, self.t("usm_error_process", error=error))

    def _on_process_finished(self, exit_code: int, exit_status):
        ok = exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit
        error_text = ""
        if not ok:
            error_text = "".join(self._process_log).strip()[-2000:] or self.t("no_output")
        self._finish_process(ok, error_text)

    def _finish_process(self, ok: bool, error_text: str = ""):
        callback = self._process_done
        self._process_done = None
        if self._process:
            self._process.deleteLater()
            self._process = None
        self._process_duration_limit = 0.0
        self._set_busy(False)
        self._refresh_state()
        if not ok:
            QMessageBox.critical(self, self.t("dlg_title_error"), error_text)
        if callback:
            callback(ok)

    def _is_busy(self) -> bool:
        return self._process is not None

    def _build_preview_player(self):
        self._audio_output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        self._player.durationChanged.connect(self._on_preview_duration)
        self._player.positionChanged.connect(self._on_preview_position)
        self._player.playbackStateChanged.connect(self._on_preview_state)
        self._player.errorOccurred.connect(self._on_preview_error)

    def _set_preview_source(self, path: str):
        self._preview_path = path or ""
        self._preview_ready = bool(path)
        self._player.stop()
        self._update_preview_aspect()
        self._player.setSource(QUrl.fromLocalFile(path) if path else QUrl())
        self._clear_preview_poster()
        if path:
            self._show_poster()
            self._start_preview_poster(path)
        else:
            self._show_video()
        self._position_slider.setValue(0)
        self._time_label.setText(self.t("usm_preview_time_empty"))
        self._update_preview_controls()

    def _update_preview_aspect(self):
        if not hasattr(self, "_preview_surface"):
            return
        self._preview_surface.set_widescreen_aspect()
        self._render_poster_pixmap()

    def _toggle_preview_playback(self):
        if not self._preview_ready:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            return
        self._show_video()
        self._player.play()

    def _stop_preview(self):
        self._player.stop()
        self._player.setPosition(0)
        self._show_poster()

    def _on_seek_start(self):
        self._seeking = True

    def _on_seek_finish(self):
        self._seeking = False
        if self._position_slider.value() > 0:
            self._show_video()
        else:
            self._show_poster()
        self._player.setPosition(self._position_slider.value())

    def _on_preview_duration(self, duration: int):
        self._position_slider.setRange(0, max(0, duration))
        self._update_time_label(self._player.position(), duration)

    def _on_preview_position(self, position: int):
        if not self._seeking:
            self._position_slider.setValue(position)
        self._update_time_label(position, self._player.duration())

    def _on_preview_state(self, state):
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._show_video()
            self._play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self._play_btn.setToolTip(self.t("usm_preview_pause"))
        else:
            self._play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self._play_btn.setToolTip(self.t("usm_preview_play"))

    def _start_preview_poster(self, source_path: str):
        self._stop_preview_poster()
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return
        self._poster_token += 1
        token = self._poster_token
        poster_path = os.path.join(self._tmpdir.name, f"preview_poster_{token}.jpg")
        args = [
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "0",
            "-i",
            source_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            poster_path,
        ]
        process = QProcess(self)
        process.setProgram(ffmpeg)
        process.setArguments(args)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.finished.connect(lambda exit_code, _status, p=poster_path, t=token: self._on_preview_poster_done(t, p, exit_code == 0))
        self._poster_process = process
        process.start()

    def _stop_preview_poster(self):
        process = getattr(self, "_poster_process", None)
        if not process:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished()
        process.deleteLater()
        self._poster_process = None

    def _on_preview_poster_done(self, token: int, poster_path: str, ok: bool):
        process = self.sender()
        if process:
            process.deleteLater()
        if getattr(self, "_poster_process", None) is process:
            self._poster_process = None
        if token != self._poster_token or not ok or not os.path.exists(poster_path):
            return
        pixmap = QPixmap(poster_path)
        if pixmap.isNull():
            return
        self._poster_path = poster_path
        self._poster_pixmap = pixmap
        self._render_poster_pixmap()
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState and self._player.position() == 0:
            self._show_poster()

    def _clear_preview_poster(self):
        self._stop_preview_poster()
        self._poster_path = ""
        self._poster_pixmap = QPixmap()
        if hasattr(self, "_poster_label"):
            self._poster_label.clear()

    def _render_poster_pixmap(self):
        if not hasattr(self, "_poster_label") or self._poster_pixmap.isNull():
            return
        size = self._preview_surface.size() if hasattr(self, "_preview_surface") else self._poster_label.size()
        if not size.isValid() or size.width() <= 0 or size.height() <= 0:
            return
        scaled = self._poster_pixmap.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._poster_label.setPixmap(scaled)

    def _show_poster(self):
        if hasattr(self, "_preview_stack"):
            self._preview_stack.setCurrentWidget(self._poster_label)

    def _show_video(self):
        if hasattr(self, "_preview_stack"):
            self._preview_stack.setCurrentWidget(self._video_widget)

    def _on_preview_error(self, error, error_string: str):
        if error != QMediaPlayer.Error.NoError and error_string:
            set_file_label(self._file_label, self._preview_path or self._original_path, dirty=self._dirty)

    def _update_preview_controls(self):
        enabled = bool(getattr(self, "_preview_ready", False)) and not self._is_busy()
        if hasattr(self, "_play_btn"):
            self._play_btn.setEnabled(enabled)
            self._stop_btn.setEnabled(enabled)
            self._position_slider.setEnabled(enabled)
        if hasattr(self, "_stretch_video_chk"):
            self._stretch_video_chk.setEnabled(not self._is_busy())

    def _update_time_label(self, position: int, duration: int):
        self._time_label.setText(self.t(
            "usm_preview_time",
            position=self._format_ms(position),
            duration=self._format_ms(duration),
        ))

    def _format_ms(self, value: int) -> str:
        total = max(0, int(value // 1000))
        minutes, seconds = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def closeEvent(self, event):
        if hasattr(self, "_player"):
            self._player.stop()
        self._stop_preview_poster()
        if self._process:
            self._process.kill()
            self._process.waitForFinished()
        self._tmpdir.cleanup()
        super().closeEvent(event)

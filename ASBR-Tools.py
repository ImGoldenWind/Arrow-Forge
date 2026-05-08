import sys
import os
import re
import inspect

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QRadioButton,
    QButtonGroup, QCheckBox, QLineEdit, QSizePolicy, QFileDialog,
    QMessageBox, QProgressDialog, QDialog, QTextEdit,
)
from PyQt6.QtGui import QFont, QPixmap, QIcon, QCursor, QDesktopServices
from PyQt6.QtCore import Qt, QTimer, QSize, QPoint, QUrl, QThread, pyqtSignal

from core.themes import THEMES, P, apply_theme, normalize_theme_key
from core.translations import TRANSLATIONS, available_languages, ui_text
from core.icons import (icon_settings_gear, icon_cpk_unpack, icon_credits_star, icon_favorite_category,
                        icon_favorite_star, icon_tool_pin, _pil_to_qpixmap,
                        icon_social_github, icon_social_youtube, icon_social_discord, icon_social_nexusmods)
from core.tool_data import TOOLS, CAT_KEYS, CAT_META, CAT_PORTRAIT
from core.runtime_paths import app_path
from core.settings import load_settings, save_settings
from core.skeleton import reset_palette, SkeletonBar, SkeletonCard
from core import updater
from core.file_drop import install_file_drop
from core.style_helpers import (
    ss_home_grid_scrollarea, ss_main_label, ss_tool_card,
    ss_tool_favorite_btn, ss_tool_file_hint_label, ss_search,
    ss_btn, ss_dialog, ss_textedit,
)
from editors.char_stats_editor import CharacterStatsEditor
from editors.characode_editor import CharacodeEditor
from editors.info_editor import InfoEditor
from editors.costume_editor import CostumeEditor
from editors.sound_editor import SoundEditor
from editors.skill_editor import SkillEditor
from editors.effect_editor import EffectEditor
from editors.cpk_editor import CpkEditor
from editors.spm_editor import SpmEditor
from editors.projectile_editor import ProjectileEditor
from editors.constparam_editor import ConstParamEditor
from editors.assist_editor import AssistEditor
from editors.damageprm_editor import DamagePrmEditor
from editors.damageeff_editor import DamageEffEditor
from editors.btladjprm_editor import BtlAdjPrmEditor
from editors.mainmodeparam_editor import MainModeParamEditor
from editors.speaking_editor import SpeakingEditor
from editors.messageinfo_editor import MessageInfoEditor
from editors.dictionaryparam_editor import DictionaryParamEditor
from editors.stageinfo_editor import StageInfoEditor
from editors.stagemotion_editor import StageMotionEditor
from editors.customcardparam_editor import CustomCardParamEditor
from editors.charviewer_editor import CharViewerEditor
from editors.guidecharparam_editor import GuideCharParamEditor
from editors.customizedefaultparam_editor import CustomizeDefaultParamEditor
from editors.dlcinfoparam_editor import DlcInfoParamEditor
from editors.galleryartparam_editor import GalleryArtParamEditor
from editors.playertitleparam_editor import PlayerTitleParamEditor
from editors.xfbin_audio_editor import XfbinAudioEditor
from editors.texture_editor import TextureEditor
from editors.sndcmnparam_editor import SndCmnParamEditor
from editors.soundtestparam_editor import SoundTestParamEditor


def _clear_layout(layout):
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _make_styled_btn(text, bg, hover, fg, font, width=0, height=0, icon=None):
    btn = QPushButton(text)
    btn.setFont(font)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    style = (
        f"QPushButton {{ background-color: {bg}; color: {fg}; border: none; "
        f"border-radius: 8px; padding: 4px 12px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
    )
    btn.setStyleSheet(style)
    if width:
        btn.setFixedWidth(width)
    if height:
        btn.setFixedHeight(height)
    if icon:
        btn.setIcon(icon)
        btn.setIconSize(QSize(22, 22))
    return btn


# Tool card
class ToolCard(QFrame):
    def __init__(self, parent, label, file_hint, icon, dlg_key,
                 on_hover=None, on_leave=None, app=None,
                 tool_id=None, favorite=False, favorite_tooltip="",
                 on_toggle_favorite=None, pinned=False, pin_tooltip="",
                 on_toggle_pin=None, pin_category_key=None, category_key=None):
        super().__init__(parent)
        self._label = label
        self._file_hint = file_hint
        self._dlg_key = dlg_key
        self._on_hover_cb = on_hover
        self._on_leave_cb = on_leave
        self._app = app
        self._tool_id = tool_id or dlg_key
        self._category_key = category_key
        self._pin_category_key = pin_category_key or category_key
        self._favorite = favorite
        self._pinned = pinned
        self._on_toggle_favorite = on_toggle_favorite
        self._on_toggle_pin = on_toggle_pin
        self._pressed_inside = False

        self._default_style = ss_tool_card(hover=False)
        self._hover_style = ss_tool_card(hover=True)
        self.setStyleSheet(self._default_style)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(125)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 70, 7)
        row.setSpacing(8)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icon.pixmap(QSize(20, 20)))
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

        texts = QVBoxLayout()
        texts.setSpacing(1)
        name_lbl = QLabel(label)
        name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name_lbl.setStyleSheet(ss_main_label())
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts.addWidget(name_lbl)

        hint_lbl = QLabel(file_hint)
        hint_lbl.setFont(QFont("Consolas", 10))
        hint_lbl.setStyleSheet(ss_tool_file_hint_label())
        hint_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts.addWidget(hint_lbl)
        row.addLayout(texts, 1)

        self._favorite_btn = QPushButton(self)
        self._favorite_btn.setCheckable(True)
        self._favorite_btn.setChecked(favorite)
        self._favorite_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._favorite_btn.setFixedSize(26, 26)
        self._favorite_btn.setIcon(icon_favorite_star(filled=favorite))
        self._favorite_btn.setIconSize(QSize(14, 14))
        self._favorite_btn.setToolTip(favorite_tooltip)
        self._favorite_btn.setStyleSheet(ss_tool_favorite_btn(checked=favorite))
        self._favorite_btn.clicked.connect(self._toggle_favorite)
        self._pin_btn = QPushButton(self)
        self._pin_btn.setCheckable(True)
        self._pin_btn.setChecked(pinned)
        self._pin_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pin_btn.setFixedSize(26, 26)
        self._pin_btn.setIcon(icon_tool_pin(filled=pinned))
        self._pin_btn.setIconSize(QSize(14, 14))
        self._pin_btn.setToolTip(pin_tooltip)
        self._pin_btn.setStyleSheet(ss_tool_favorite_btn(checked=pinned))
        self._pin_btn.clicked.connect(self._toggle_pin)
        self._position_action_btns()

    def _position_action_btns(self):
        self._favorite_btn.move(self.width() - self._favorite_btn.width() - 7, 7)
        self._pin_btn.move(self._favorite_btn.x() - self._pin_btn.width() - 5, 7)

    def resizeEvent(self, event):
        self._position_action_btns()
        super().resizeEvent(event)

    def _toggle_favorite(self, checked):
        self._favorite = checked
        self._favorite_btn.setIcon(icon_favorite_star(filled=checked))
        self._favorite_btn.setStyleSheet(ss_tool_favorite_btn(checked=checked))
        if self._on_toggle_favorite:
            self._on_toggle_favorite(self._tool_id)

    def _toggle_pin(self, checked):
        self._pinned = checked
        self._pin_btn.setIcon(icon_tool_pin(filled=checked))
        self._pin_btn.setStyleSheet(ss_tool_favorite_btn(checked=checked))
        if self._on_toggle_pin:
            self._on_toggle_pin(self._tool_id, self._pin_category_key)

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        if self._on_hover_cb:
            self._on_hover_cb(self._dlg_key, self._category_key)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._default_style)
        if self._on_leave_cb:
            self._on_leave_cb()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed_inside = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_inside:
            self._pressed_inside = False
            if self.rect().contains(event.position().toPoint()) and self._app:
                self._app._open_tool_inline(self._label, self._file_hint, self._tool_id)
            event.accept()
            return
        self._pressed_inside = False
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressed_inside and not self.rect().contains(event.position().toPoint()):
            self._pressed_inside = False
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._app:
            self._pressed_inside = False
            self._app._open_tool_inline(self._label, self._file_hint, self._tool_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


# Sidebar button
class _SidebarBtn(QFrame):
    def __init__(self, text, icon, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self._active = False
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(10)

        self._icon_lbl = QLabel()
        self._icon_lbl.setPixmap(icon.pixmap(QSize(20, 20)))
        self._icon_lbl.setFixedSize(20, 20)
        self._icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self._icon_lbl)

        self._text_lbl = QLabel(text)
        self._text_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self._text_lbl, 1)

        self._set_style(active=False, hover=False)

    def _set_style(self, active, hover):
        if active:
            bg = P["mid"]
            fg = P["accent"]
        elif hover:
            bg = P["mid"]
            fg = P["text_dim"]
        else:
            bg = "transparent"
            fg = P["text_dim"]
        self.setStyleSheet(f"_SidebarBtn {{ background-color: {bg}; border: none; }}")
        self._text_lbl.setStyleSheet(f"color: {fg}; background: transparent;")

    def set_active(self, active: bool):
        self._active = active
        self._set_style(active=active, hover=False)

    def enterEvent(self, event):
        self._set_style(active=self._active, hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_style(active=self._active, hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._on_click()
        super().mousePressEvent(event)


class _UpdateCheckWorker(QThread):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def run(self):
        try:
            self.finished.emit(updater.check_for_update())
        except Exception as exc:
            self.failed.emit(str(exc))


class _UpdateDownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self._info = info

    def run(self):
        try:
            result = updater.download_and_prepare_update(
                self._info,
                progress_callback=lambda done, total: self.progress.emit(done, total),
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


# Main App
class App(QMainWindow):
    _PORTRAIT_SIZE = 150
    _PORTRAIT_OVERFLOW = 60  # px the portrait floats above the panel top

    def __init__(self):
        super().__init__()
        self.setWindowTitle(ui_text("ui_ASBR-Tools_asbr_toolbox"))
        self.resize(1280, 720)
        self.setMinimumSize(960, 540)
        _ico_path = app_path("ArrowForgeIcon.ico")
        self._app_icon = QIcon(_ico_path)
        self.setWindowIcon(self._app_icon)

        self._settings = load_settings()
        self._lang = self._settings.get("language", "en")
        self._theme_key = normalize_theme_key(self._settings.get("theme"))
        apply_theme(self._theme_key)
        if self._settings.get("theme") != self._theme_key:
            self._settings["theme"] = self._theme_key
            save_settings(self._settings)
        self._favorite_tools = self._normalise_favorites(self._settings.get("favorite_tools", []))
        self._recent_tools = self._normalise_recent_tools(self._settings.get("recent_tools", []))
        self._pinned_tools = self._normalise_pinned_tools(self._settings.get("pinned_tools", {}))
        if (
            self._settings.get("favorite_tools", []) != self._favorite_tools
            or self._settings.get("recent_tools", []) != self._recent_tools
            or self._settings.get("pinned_tools", {}) != self._pinned_tools
        ):
            self._settings["favorite_tools"] = self._favorite_tools
            self._settings["recent_tools"] = self._recent_tools
            self._settings["pinned_tools"] = self._pinned_tools
            save_settings(self._settings)

        self._current_cat = "CHARACTER"
        self._typing_job = None
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(5)
        self._typing_timer.timeout.connect(self._type_tick)
        self._settings_win = None
        self._tool_frame = None
        self._cpk_editor_win = None
        self._loading = False
        self._portrait_images = {}
        self._cat_icons = {}
        self._tool_icons_cache = {}
        self._cat_frames = {}
        self._cat_buttons = {}
        self._pending_cats = []
        self._tool_search_query = ""
        self._tool_search_entry = None
        self._search_frame = None
        self._update_check_worker = None
        self._update_download_worker = None
        self._update_progress_dialog = None
        self._update_status_label = None
        self._embedded_editor = None

        self._central = QWidget()
        self.setCentralWidget(self._central)
        self._root_layout = QVBoxLayout(self._central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._rebuild_ui()
        QTimer.singleShot(1400, self._auto_check_for_updates)

    def _tool_lookup(self):
        lookup = {}
        for cat_key in CAT_KEYS:
            for fh, icon_fn, tk, dk in TOOLS[cat_key]:
                lookup[dk] = (cat_key, fh, icon_fn, tk, dk)
        return lookup

    def _normalise_favorites(self, favorites):
        lookup = self._tool_lookup()
        result = []
        seen = set()
        if not isinstance(favorites, list):
            return result
        for tool_id in favorites:
            if not isinstance(tool_id, str):
                continue
            if tool_id in lookup and tool_id not in seen:
                result.append(tool_id)
                seen.add(tool_id)
        return result

    def _normalise_recent_tools(self, recent_tools):
        lookup = self._tool_lookup()
        result = []
        seen = set()
        if not isinstance(recent_tools, list):
            return result
        for tool_id in recent_tools:
            if not isinstance(tool_id, str):
                continue
            if tool_id in lookup and tool_id not in seen:
                result.append(tool_id)
                seen.add(tool_id)
        return result

    def _normalise_pinned_tools(self, pinned_tools):
        lookup = self._tool_lookup()
        valid_categories = set(CAT_KEYS) | {"FAVORITES"}
        result = {}
        if not isinstance(pinned_tools, dict):
            return result
        for cat_key, tool_ids in pinned_tools.items():
            if cat_key not in valid_categories or not isinstance(tool_ids, list):
                continue
            clean_ids = []
            seen = set()
            for tool_id in tool_ids:
                if not isinstance(tool_id, str) or tool_id in seen or tool_id not in lookup:
                    continue
                if cat_key == "FAVORITES":
                    if tool_id not in self._favorite_tools:
                        continue
                elif lookup[tool_id][0] != cat_key:
                    continue
                clean_ids.append(tool_id)
                seen.add(tool_id)
            if clean_ids:
                result[cat_key] = clean_ids
        return result

    def _sort_tool_rows_for_category(self, rows, cat_key):
        pinned_rank = {
            tool_id: idx for idx, tool_id in enumerate(self._pinned_tools.get(cat_key, []))
        }
        recent_rank = {tool_id: idx for idx, tool_id in enumerate(self._recent_tools)}
        return [
            row for _idx, row in sorted(
                enumerate(rows),
                key=lambda item: (
                    0 if item[1][4] in pinned_rank else 1,
                    pinned_rank.get(item[1][4], len(pinned_rank)),
                    recent_rank.get(item[1][4], len(recent_rank)),
                    item[0],
                ),
            )
        ]

    def _visible_cat_keys(self):
        return (["FAVORITES"] if self._favorite_tools else []) + list(CAT_KEYS)

    def _category_i18n_key(self, cat_key):
        if cat_key == "FAVORITES":
            return "cat_FAVORITES"
        return CAT_META[cat_key][1]

    def _category_speaker_key(self, cat_key):
        if cat_key == "FAVORITES":
            return "speaker_FAVORITES"
        return CAT_META[cat_key][2]

    def _favorite_tool_rows(self):
        lookup = self._tool_lookup()
        rows = [lookup[tool_id] for tool_id in self._favorite_tools if tool_id in lookup]
        return self._sort_tool_rows_for_category(rows, "FAVORITES")

    def _all_tool_rows(self):
        rows = []
        for cat_key in CAT_KEYS:
            rows.extend((cat_key, fh, icon_fn, tk, dk) for fh, icon_fn, tk, dk in TOOLS[cat_key])
        return rows

    def _is_favorite_tool(self, tool_id):
        return tool_id in self._favorite_tools

    def _is_pinned_tool(self, tool_id, cat_key):
        return tool_id in self._pinned_tools.get(cat_key, [])

    def _rebuild_cat_frame_cache(self, cat_key):
        old_frame = self._cat_frames.get(cat_key)
        if old_frame:
            old_frame.deleteLater()
        self._cat_frames[cat_key] = self._build_cat_frame(cat_key)

    def _mark_tool_used(self, tool_id):
        lookup = self._tool_lookup()
        if tool_id not in lookup:
            return

        recent_tools = [tool_id] + [
            item for item in self._recent_tools
            if item != tool_id and item in lookup
        ]
        if recent_tools == self._recent_tools:
            return

        self._recent_tools = recent_tools
        self._settings["recent_tools"] = self._recent_tools
        save_settings(self._settings)

        cat_key = lookup[tool_id][0]
        if cat_key in self._cat_frames:
            self._rebuild_cat_frame_cache(cat_key)
        if tool_id in self._favorite_tools and "FAVORITES" in self._cat_frames:
            self._rebuild_cat_frame_cache("FAVORITES")

    def _toggle_favorite_tool(self, tool_id):
        if tool_id in self._favorite_tools:
            self._favorite_tools = [item for item in self._favorite_tools if item != tool_id]
            fav_pins = [item for item in self._pinned_tools.get("FAVORITES", []) if item != tool_id]
            if fav_pins:
                self._pinned_tools["FAVORITES"] = fav_pins
            else:
                self._pinned_tools.pop("FAVORITES", None)
        else:
            self._favorite_tools.append(tool_id)
        self._settings["favorite_tools"] = self._favorite_tools
        self._settings["pinned_tools"] = self._pinned_tools
        save_settings(self._settings)
        if self._current_cat == "FAVORITES" and not self._favorite_tools:
            self._current_cat = "CHARACTER"
        self._rebuild_ui()

    def _toggle_pinned_tool(self, tool_id, cat_key):
        lookup = self._tool_lookup()
        valid_categories = set(CAT_KEYS) | {"FAVORITES"}
        if cat_key not in valid_categories or tool_id not in lookup:
            return
        if cat_key == "FAVORITES":
            if tool_id not in self._favorite_tools:
                return
        elif lookup[tool_id][0] != cat_key:
            return

        pinned = [item for item in self._pinned_tools.get(cat_key, []) if item in lookup]
        if tool_id in pinned:
            pinned = [item for item in pinned if item != tool_id]
        else:
            pinned.append(tool_id)

        if pinned:
            self._pinned_tools[cat_key] = pinned
        else:
            self._pinned_tools.pop(cat_key, None)
        self._settings["pinned_tools"] = self._pinned_tools
        save_settings(self._settings)

        if self._tool_search_query:
            self._show_tool_search_results()
            return
        if cat_key in self._cat_frames:
            self._rebuild_cat_frame_cache(cat_key)
        if self._current_cat == cat_key:
            self._show_category(cat_key)

    def _rebuild_ui(self):
        self._typing_timer.stop()
        self._typing_job = None
        self._update_status_label = None
        if self._current_cat not in self._visible_cat_keys():
            self._current_cat = "CHARACTER"

        _clear_layout(self._root_layout)
        if hasattr(self, "_avatar_label") and self._avatar_label is not None:
            self._avatar_label.deleteLater()
            self._avatar_label = None
        self.setStyleSheet(f"QMainWindow {{ background-color: {P['bg_dark']}; }}")
        self._loading = True
        reset_palette()

        # Rebuild icon caches
        self._cat_icons = {}
        self._tool_icons_cache = {}
        self._cat_icons["FAVORITES"] = icon_favorite_category(size=24)
        for cat, (icon_fn, *_) in CAT_META.items():
            self._cat_icons[cat] = icon_fn(size=24)
        self._settings_icon = icon_settings_gear(size=22)
        self._unpack_icon   = icon_cpk_unpack(size=22)
        self._credits_icon  = icon_credits_star(size=22)

        # Load portraits
        self._portrait_images = {}
        for cat_key, rel_path in CAT_PORTRAIT.items():
            pm = self._load_portrait(rel_path, size=self._PORTRAIT_SIZE, corner_radius=11, draw_border=False)
            if pm:
                self._portrait_images[cat_key] = pm

        self._build_header()

        main = QWidget()
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self._root_layout.addWidget(main, 1)

        self._build_sidebar(main_layout)
        self._build_content(main_layout)
        self._build_char_panel()
        if not self._settings.get("show_guide", True):
            self._hide_char_panel()

        # Build category frames incrementally
        self._cat_frames = {}
        self._search_frame = None
        self._pending_cats = self._visible_cat_keys()
        QTimer.singleShot(20, self._build_next_cat_frame)

    def _build_next_cat_frame(self):
        if not self._pending_cats:
            self._loading = False
            if self._tool_search_query:
                self._show_tool_search_results()
            else:
                self._show_category(self._current_cat)
            QTimer.singleShot(100, self._reposition_portrait)
            return
        cat_key = self._pending_cats.pop(0)
        self._cat_frames[cat_key] = self._build_cat_frame(cat_key)
        QTimer.singleShot(10, self._build_next_cat_frame)

    def t(self, key, **kw):
        text = TRANSLATIONS.get(self._lang, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"].get(key, key))
        return text.format(**kw) if kw else text

    def _set_update_status(self, text):
        if self._update_status_label is None:
            return
        try:
            self._update_status_label.setText(text)
        except RuntimeError:
            self._update_status_label = None

    def _auto_check_for_updates(self):
        if not self._settings.get("check_updates_on_startup", True):
            return
        if not updater.should_check_today(self._settings.get("last_update_check")):
            return
        self._check_for_updates(manual=False)

    def _check_for_updates(self, manual=False):
        if self._update_check_worker and self._update_check_worker.isRunning():
            if manual:
                self._set_update_status(self.t("updates_checking"))
            return

        if manual:
            self._set_update_status(self.t("updates_checking"))

        worker = _UpdateCheckWorker(self)
        worker.finished.connect(lambda info, m=manual: self._on_update_check_finished(info, m))
        worker.failed.connect(lambda error, m=manual: self._on_update_check_failed(error, m))
        worker.finished.connect(lambda _info, w=worker: w.deleteLater())
        worker.failed.connect(lambda _error, w=worker: w.deleteLater())
        self._update_check_worker = worker
        worker.start()

    def _download_and_install_update(self, info):
        if self._update_download_worker and self._update_download_worker.isRunning():
            return

        self._set_update_status(self.t("updates_downloading"))

        progress = QProgressDialog(self.t("updates_download_progress", asset=info.get("asset_name", "")), "", 0, 100, self)
        progress.setWindowTitle(self.t("updates_title"))
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        self._update_progress_dialog = progress

        worker = _UpdateDownloadWorker(info, self)
        worker.progress.connect(self._on_update_download_progress)
        worker.finished.connect(self._on_update_download_finished)
        worker.failed.connect(self._on_update_download_failed)
        worker.finished.connect(lambda _result, w=worker: w.deleteLater())
        worker.failed.connect(lambda _error, w=worker: w.deleteLater())
        self._update_download_worker = worker
        worker.start()

    def _on_update_download_progress(self, done, total):
        progress = self._update_progress_dialog
        if progress is None:
            return
        if total > 0:
            progress.setRange(0, 100)
            progress.setValue(min(100, int(done * 100 / total)))
        else:
            progress.setRange(0, 0)

    def _close_update_progress(self):
        if self._update_progress_dialog is not None:
            self._update_progress_dialog.close()
            self._update_progress_dialog.deleteLater()
            self._update_progress_dialog = None

    def _on_update_download_finished(self, result):
        self._update_download_worker = None
        self._close_update_progress()
        self._set_update_status(self.t("updates_installing"))
        QMessageBox.information(self, self.t("updates_title"), self.t("updates_restart_message"))
        try:
            updater.launch_prepared_update(result.get("script_path", ""))
        except Exception as exc:
            QMessageBox.warning(self, self.t("updates_title"), self.t("updates_failed_details", error=str(exc)))
            return
        QApplication.quit()

    def _on_update_download_failed(self, error):
        self._update_download_worker = None
        self._close_update_progress()
        self._set_update_status(self.t("updates_failed"))
        QMessageBox.warning(self, self.t("updates_title"), self.t("updates_failed_details", error=error))

    def _on_update_check_finished(self, info, manual):
        self._update_check_worker = None
        self._settings["last_update_check"] = updater.today_string()
        save_settings(self._settings)

        if not info.get("update_available"):
            status = self.t("updates_up_to_date", version=info.get("current_version", updater.APP_VERSION))
            self._set_update_status(status)
            if manual:
                QMessageBox.information(self, self.t("updates_title"), status)
            return

        self._set_update_status(self.t(
            "updates_available_status",
            version=info.get("latest_version", ""),
        ))
        self._prompt_for_update(info)

    def _on_update_check_failed(self, error, manual):
        self._update_check_worker = None
        self._set_update_status(self.t("updates_failed"))
        if manual:
            QMessageBox.warning(self, self.t("updates_title"), self.t("updates_failed_details", error=error))

    def _show_update_changelog_dialog(self, info, message):
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("updates_changelog_window_title", version=info.get("latest_version", "")))
        dialog.setModal(True)
        dialog.resize(680, 520)
        dialog.setStyleSheet(ss_dialog())

        result = {"action": "cancel"}

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel(self.t("updates_changelog_title", version=info.get("latest_version", "")))
        title.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; background: transparent;")
        layout.addWidget(title)

        summary = QLabel(message)
        summary.setFont(QFont("Segoe UI", 10))
        summary.setStyleSheet(f"color: {P['text_main']}; background: transparent;")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        if not info.get("asset_url"):
            no_asset = QLabel(self.t("updates_no_download_asset_dialog"))
            no_asset.setFont(QFont("Segoe UI", 10))
            no_asset.setStyleSheet(f"color: {P['text_dim']}; background: transparent;")
            no_asset.setWordWrap(True)
            layout.addWidget(no_asset)

        changelog_label = QLabel(self.t("updates_changelog_label"))
        changelog_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        changelog_label.setStyleSheet(f"color: {P['secondary']}; background: transparent;")
        layout.addWidget(changelog_label)

        body = str(info.get("body") or "").strip() or self.t("updates_changelog_empty")
        changelog = QTextEdit()
        changelog.setReadOnly(True)
        changelog.setMinimumHeight(260)
        changelog.setStyleSheet(ss_textedit())
        try:
            changelog.setMarkdown(body)
        except Exception:
            changelog.setPlainText(body)
        layout.addWidget(changelog, 1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 2, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch()

        def add_dialog_button(text, action, accent=False):
            btn = QPushButton(text)
            btn.setFixedHeight(32)
            btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold if accent else QFont.Weight.Normal))
            btn.setStyleSheet(ss_btn(accent=accent))
            btn.clicked.connect(lambda _checked=False, a=action: (result.update(action=a), dialog.accept()))
            button_row.addWidget(btn)
            return btn

        if info.get("release_url"):
            add_dialog_button(self.t("updates_open_release"), "release", accent=not info.get("asset_url"))
        if info.get("asset_url"):
            add_dialog_button(self.t("updates_install_now"), "download", accent=True)
        cancel_btn = QPushButton(self.t("unsaved_changes_cancel"))
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFont(QFont("Segoe UI", 10))
        cancel_btn.setStyleSheet(ss_btn())
        cancel_btn.clicked.connect(dialog.reject)
        button_row.addWidget(cancel_btn)

        layout.addLayout(button_row)
        dialog.exec()
        return result["action"] if dialog.result() == QDialog.DialogCode.Accepted else "cancel"

    def _prompt_for_update(self, info):
        asset_size = updater.human_size(info.get("asset_size", 0))
        message = self.t(
            "updates_available_message",
            current=info.get("current_version", updater.APP_VERSION),
            latest=info.get("latest_version", ""),
            asset=info.get("asset_name", ""),
            size=asset_size,
        )
        action = self._show_update_changelog_dialog(info, message)
        if action == "download":
            if not self._confirm_close_embedded_editor():
                return
            self._delete_tool_frame()
            self._download_and_install_update(info)
        elif action == "release":
            QDesktopServices.openUrl(QUrl(info.get("release_url", "")))

    # Header
    def _build_header(self):
        accent_bar = QFrame()
        accent_bar.setFixedHeight(3)
        accent_bar.setStyleSheet(f"background-color: {P['accent']};")
        self._root_layout.addWidget(accent_bar)

        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background-color: {P['bg_panel']};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 20, 8)
        header_layout.setSpacing(10)

        app_icon_lbl = QLabel()
        app_icon_lbl.setPixmap(self._app_icon.pixmap(QSize(32, 32)))
        app_icon_lbl.setFixedSize(32, 32)
        header_layout.addWidget(app_icon_lbl)

        self._header_title_lbl = QLabel(self.t("app_title"))
        self._header_title_lbl.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self._header_title_lbl.setStyleSheet(f"color: {P['accent']};")
        self._header_title_lbl.setMinimumWidth(self._header_title_lbl.sizeHint().width())
        self._header_title_lbl.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self._header_title_lbl)

        header_layout.addStretch()

        self._tool_search_entry = QLineEdit()
        self._tool_search_entry.setPlaceholderText(self.t("tool_search_placeholder"))
        self._tool_search_entry.setMinimumWidth(120)
        self._tool_search_entry.setMaximumWidth(360)
        self._tool_search_entry.setFixedHeight(34)
        self._tool_search_entry.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._tool_search_entry.setFont(QFont("Segoe UI", 13))
        self._tool_search_entry.setStyleSheet(ss_search())
        self._tool_search_entry.setClearButtonEnabled(True)
        self._tool_search_entry.setText(self._tool_search_query)
        self._tool_search_entry.textChanged.connect(self._on_tool_search_changed)
        header_layout.addWidget(self._tool_search_entry, 1)

        unpack_btn = _make_styled_btn(
            "  " + self.t("cpk_unpack_btn"), P["mid"], P["bg_card_hov"], P["accent"],
            QFont("Segoe UI", 13), width=120, height=34, icon=self._unpack_icon)
        unpack_btn.clicked.connect(self._open_cpk_editor)
        header_layout.addWidget(unpack_btn)

        credits_btn = _make_styled_btn(
            "  Credits", P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=120, height=34, icon=self._credits_icon)
        credits_btn.clicked.connect(self._open_credits)
        header_layout.addWidget(credits_btn)

        settings_btn = _make_styled_btn(
            "  " + self.t("settings"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=130, height=34, icon=self._settings_icon)
        settings_btn.clicked.connect(self._open_settings)
        header_layout.addWidget(settings_btn)

        self._root_layout.addWidget(header)
        self._sync_header_layout()

        highlight_bar = QFrame()
        highlight_bar.setFixedHeight(1)
        highlight_bar.setStyleSheet(f"background-color: {P['highlight']};")
        self._root_layout.addWidget(highlight_bar)

    # Sidebar
    def _build_sidebar(self, parent_layout):
        sidebar = QFrame()
        sidebar.setFixedWidth(210)
        sidebar.setStyleSheet(f"background-color: {P['bg_panel']};")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 0)
        sidebar_layout.setSpacing(1)

        self._cat_buttons = {}
        for cat_key in self._visible_cat_keys():
            i18n_key = self._category_i18n_key(cat_key)
            btn = _SidebarBtn(
                text=self.t(i18n_key),
                icon=self._cat_icons.get(cat_key, QIcon()),
                on_click=lambda c=cat_key: self._select_category(c),
            )
            sidebar_layout.addWidget(btn)
            self._cat_buttons[cat_key] = btn

        sidebar_layout.addStretch()

        # Separator line
        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {P['mid']};")

        sidebar_container = QHBoxLayout()
        sidebar_container.setContentsMargins(0, 0, 0, 0)
        sidebar_container.setSpacing(0)
        sidebar_container.addWidget(sidebar)
        sidebar_container.addWidget(sep)
        parent_layout.addLayout(sidebar_container)

    # Content area
    def _build_content(self, parent_layout):
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self._view_stack = QWidget()
        self._view_stack_layout = QVBoxLayout(self._view_stack)
        self._view_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._view_stack_layout.setSpacing(0)
        self._content_layout.addWidget(self._view_stack, 1)

        parent_layout.addWidget(self._content, 1)

    def _build_cat_frame(self, cat_key):
        i18n_key = self._category_i18n_key(cat_key)
        tool_rows = self._favorite_tool_rows() if cat_key == "FAVORITES" else [
            (cat_key, fh, icon_fn, tk, dk) for fh, icon_fn, tk, dk in TOOLS[cat_key]
        ]
        if cat_key != "FAVORITES":
            tool_rows = self._sort_tool_rows_for_category(tool_rows, cat_key)

        frame = QWidget()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(28, 16, 28, 4)
        header_row.setSpacing(0)

        title_lbl = QLabel(self.t(i18n_key))
        title_lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['accent']};")
        header_row.addWidget(title_lbl)

        header_row.addStretch()

        subtitle_lbl = QLabel(self.t("tools_avail", n=len(tool_rows)))
        subtitle_lbl.setFont(QFont("Segoe UI", 12))
        subtitle_lbl.setStyleSheet(f"color: {P['text_dim']};")
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(subtitle_lbl)

        frame_layout.addLayout(header_row)

        # Scrollable grid of tool cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_home_grid_scrollarea())
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        grid = QGridLayout(scroll_content)
        grid.setContentsMargins(20, 8, 20, 16)
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        for idx, (tool_cat, fh, icon_fn, tk, dk) in enumerate(tool_rows):
            hover_cat = tool_cat if cat_key != "FAVORITES" or tool_cat == "GALLERY" else "FAVORITES"
            pin_cat = "FAVORITES" if cat_key == "FAVORITES" else tool_cat
            ck = f"{tk}_{fh}"
            if ck not in self._tool_icons_cache:
                self._tool_icons_cache[ck] = icon_fn()
            card = ToolCard(scroll_content, self.t(tk), fh, self._tool_icons_cache[ck], dk,
                            on_hover=self._on_hover, on_leave=self._on_leave, app=self,
                            tool_id=dk, favorite=self._is_favorite_tool(dk),
                            favorite_tooltip=self.t(
                                "favorite_remove_tooltip" if self._is_favorite_tool(dk)
                                else "favorite_add_tooltip"
                            ),
                            on_toggle_favorite=self._toggle_favorite_tool,
                            pinned=self._is_pinned_tool(dk, pin_cat),
                            pin_tooltip=self.t(
                                "pin_remove_tooltip" if self._is_pinned_tool(dk, pin_cat)
                                else "pin_add_tooltip"
                            ),
                            on_toggle_pin=self._toggle_pinned_tool,
                            pin_category_key=pin_cat,
                            category_key=hover_cat)
            grid.addWidget(card, idx // 2, idx % 2)

        scroll.setWidget(scroll_content)
        frame_layout.addWidget(scroll, 1)

        return frame

    def _select_category(self, cat_key):
        if not self._confirm_close_embedded_editor():
            return
        self._delete_tool_frame()
        self._current_cat = cat_key
        if self._tool_search_query and self._tool_search_entry:
            self._tool_search_entry.clear()
            return
        self._show_category(cat_key)

    def _on_tool_search_changed(self, text):
        self._tool_search_query = text.strip()
        if self._loading:
            return
        if self._tool_search_query:
            if not self._close_inline_panels_for_search():
                self._tool_search_query = ""
                if self._tool_search_entry:
                    self._tool_search_entry.blockSignals(True)
                    self._tool_search_entry.clear()
                    self._tool_search_entry.blockSignals(False)
                return
            self._show_tool_search_results()
        else:
            self._show_category(self._current_cat)

    def _close_inline_panels_for_search(self):
        if not self._confirm_close_embedded_editor():
            return False
        self._delete_tool_frame()
        if self._settings_win:
            self._settings_win.deleteLater()
            self._settings_win = None
        if self._cpk_editor_win:
            self._cpk_editor_win.deleteLater()
            self._cpk_editor_win = None
        if self._settings.get("show_guide", True):
            self._show_char_panel()
        return True

    def _normalize_search_text(self, text):
        text = str(text or "")
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        text = text.replace("\\", " ")
        return re.sub(r"\s+", " ", text.casefold()).strip()

    def _tool_search_blob(self, row):
        cat_key, file_hint, _icon_fn, title_key, dialog_key = row
        en = TRANSLATIONS.get("en", {})
        parts = [
            file_hint,
            file_hint.replace(".", " "),
            file_hint.replace("_", " "),
            title_key,
            dialog_key,
            cat_key,
            self.t(title_key),
            self.t(dialog_key),
            self.t(self._category_i18n_key(cat_key)),
            en.get(title_key, ""),
            en.get(dialog_key, ""),
            en.get(self._category_i18n_key(cat_key), ""),
        ]
        parts.extend(ext.lstrip(".") for ext in re.findall(r"\.[A-Za-z0-9]+", file_hint))
        return self._normalize_search_text(" ".join(str(part) for part in parts if part))

    def _tool_matches_search(self, row, query):
        terms = [term for term in self._normalize_search_text(query).split(" ") if term]
        if not terms:
            return True
        blob = self._tool_search_blob(row)
        return all(term in blob for term in terms)

    def _filtered_tool_rows(self):
        return [row for row in self._all_tool_rows() if self._tool_matches_search(row, self._tool_search_query)]

    def _show_tool_search_results(self):
        if self._search_frame:
            self._search_frame.deleteLater()
            self._search_frame = None
        self._search_frame = self._build_search_frame()
        for btn in self._cat_buttons.values():
            btn.set_active(False)
        self._show_frame(self._search_frame)

    def _build_search_frame(self):
        tool_rows = self._filtered_tool_rows()

        frame = QWidget()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(28, 16, 28, 4)
        header_row.setSpacing(0)

        title_lbl = QLabel(self.t("tool_search_results_title"))
        title_lbl.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['accent']};")
        header_row.addWidget(title_lbl)

        header_row.addStretch()

        subtitle_lbl = QLabel(self.t("tools_avail", n=len(tool_rows)))
        subtitle_lbl.setFont(QFont("Segoe UI", 12))
        subtitle_lbl.setStyleSheet(f"color: {P['text_dim']};")
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(subtitle_lbl)

        frame_layout.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_home_grid_scrollarea())
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        grid = QGridLayout(scroll_content)
        grid.setContentsMargins(20, 8, 20, 16)
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        if tool_rows:
            for idx, (tool_cat, fh, icon_fn, tk, dk) in enumerate(tool_rows):
                ck = f"{tk}_{fh}"
                if ck not in self._tool_icons_cache:
                    self._tool_icons_cache[ck] = icon_fn()
                card = ToolCard(scroll_content, self.t(tk), fh, self._tool_icons_cache[ck], dk,
                                on_hover=self._on_hover, on_leave=self._on_leave, app=self,
                                tool_id=dk, favorite=self._is_favorite_tool(dk),
                                favorite_tooltip=self.t(
                                    "favorite_remove_tooltip" if self._is_favorite_tool(dk)
                                    else "favorite_add_tooltip"
                                ),
                                on_toggle_favorite=self._toggle_favorite_tool,
                                pinned=self._is_pinned_tool(dk, tool_cat),
                                pin_tooltip=self.t(
                                    "pin_remove_tooltip" if self._is_pinned_tool(dk, tool_cat)
                                    else "pin_add_tooltip"
                                ),
                                on_toggle_pin=self._toggle_pinned_tool,
                                pin_category_key=tool_cat,
                                category_key=tool_cat)
                grid.addWidget(card, idx // 2, idx % 2)
        else:
            empty_lbl = QLabel(self.t("tool_search_no_results"))
            empty_lbl.setFont(QFont("Segoe UI", 14))
            empty_lbl.setStyleSheet(f"color: {P['text_dim']};")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(empty_lbl, 0, 0, 1, 2)

        scroll.setWidget(scroll_content)
        frame_layout.addWidget(scroll, 1)

        return frame

    # Portrait image loader
    def _load_portrait(self, rel_path, size=64, corner_radius=10, border_width=2, draw_border=True):
        from PIL import Image, ImageDraw, ImageChops, ImageColor
        full_path = app_path(rel_path)
        if not os.path.exists(full_path):
            return None
        img = Image.open(full_path).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=corner_radius, fill=255)
        if draw_border:
            result = Image.new("RGB", (size, size), P["bg_panel"])
            result.paste(img.convert("RGB"), mask=mask)
            bd = ImageDraw.Draw(result)
            for i in range(border_width):
                bd.rounded_rectangle(
                    [i, i, size - 1 - i, size - 1 - i],
                    radius=max(1, corner_radius - i),
                    outline=P["secondary"], width=1,
                )
        else:
            try:
                bg_rgb = ImageColor.getrgb(P["bg_panel"])
            except Exception:
                bg_rgb = (30, 30, 40)
            img_alpha = img.split()[3]
            combined = ImageChops.multiply(mask, img_alpha)
            result = Image.new("RGB", (size, size), bg_rgb)
            result.paste(img.convert("RGB"), mask=combined)
        return _pil_to_qpixmap(result)

    # Bottom panel
    def _build_char_panel(self):
        self._char_sep = QWidget()
        self._char_sep.setFixedHeight(1)
        sep_row = QHBoxLayout(self._char_sep)
        sep_row.setContentsMargins(0, 0, 0, 0)
        sep_row.setSpacing(0)
        sep_blank = QWidget()
        sep_blank.setFixedWidth(211)  # sidebar width + its 1px divider
        sep_blank.setStyleSheet("background: transparent;")
        sep_row.addWidget(sep_blank)
        sep_line = QWidget()
        sep_line.setStyleSheet(f"background-color: {P['mid']};")
        sep_row.addWidget(sep_line, 1)
        self._root_layout.addWidget(self._char_sep)

        bottom = QFrame()
        bottom.setFixedHeight(100)
        bottom.setStyleSheet(f"background-color: {P['bg_panel']};")
        self._char_bottom = bottom

        inner_layout = QHBoxLayout(bottom)
        inner_layout.setContentsMargins(18, 8, 18, 8)
        inner_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Reserve horizontal space for the floating portrait (not in layout)
        portrait_spacer = QWidget()
        portrait_spacer.setFixedSize(self._PORTRAIT_SIZE + 16, 1)
        portrait_spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        inner_layout.addWidget(portrait_spacer)

        # Portrait floats as a direct child of _central, above the panel
        self._avatar_label = QLabel(self._central)
        self._avatar_label.setFixedSize(self._PORTRAIT_SIZE, self._PORTRAIT_SIZE)
        self._avatar_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar_label.setStyleSheet(
            f"color: {P['secondary']}; font-size: 26px; font-weight: bold; background: transparent;"
        )
        self._avatar_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._avatar_label.mousePressEvent = self._on_avatar_click
        self._avatar_label.hide()  # shown only after correct positioning

        # Dialog bubble
        bubble = QFrame()
        bubble.setMinimumHeight(50)
        bubble.setStyleSheet(
            f"background-color: {P['bg_card']}; border-radius: 12px; "
            f"border: 1px solid {P['border']};"
        )
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(18, 14, 18, 14)

        self._char_name_label = QLabel(self.t("hover_hint"))
        self._char_name_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._char_name_label.setStyleSheet(f"color: {P['accent']}; background: transparent; border: none;")
        bubble_layout.addWidget(self._char_name_label)

        self._char_quote_label = QLabel(self.t("hover_default"))
        self._char_quote_label.setFont(QFont("Segoe UI", 10))
        self._char_quote_label.setStyleSheet(f"color: {P['text_sec']}; background: transparent; border: none;")
        self._char_quote_label.setWordWrap(True)
        bubble_layout.addWidget(self._char_quote_label)

        inner_layout.addWidget(bubble, 1)

        self._root_layout.addWidget(bottom)

        accent_bottom = QFrame()
        accent_bottom.setFixedHeight(2)
        accent_bottom.setStyleSheet(f"background-color: {P['accent_dim']};")
        self._root_layout.addWidget(accent_bottom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_header_layout()
        self._reposition_portrait()

    def _sync_header_layout(self):
        if not hasattr(self, "_tool_search_entry") or self._tool_search_entry is None:
            return

        width = self.width()
        compact = width < 1120

        self._tool_search_entry.setMaximumWidth(240 if compact else 360)
        self._tool_search_entry.setMinimumWidth(120 if compact else 180)

    def _reposition_portrait(self):
        if not (hasattr(self, "_avatar_label") and self._avatar_label is not None
                and hasattr(self, "_char_bottom") and self._char_bottom is not None):
            return
        if not self._settings.get("show_guide", True):
            return
        if not self._char_bottom.isVisible():
            return
        panel_pos = self._char_bottom.mapTo(self._central, QPoint(0, 0))
        x = panel_pos.x() + 18
        y = panel_pos.y() - self._PORTRAIT_OVERFLOW
        self._avatar_label.move(x, y)
        self._avatar_label.raise_()
        self._avatar_label.show()

    def _hide_char_panel(self):
        if hasattr(self, "_char_sep"):
            self._char_sep.hide()
        if hasattr(self, "_char_bottom"):
            self._char_bottom.hide()
        if hasattr(self, "_avatar_label") and self._avatar_label:
            self._avatar_label.hide()

    def _show_char_panel(self):
        if hasattr(self, "_char_bottom"):
            self._char_bottom.show()
        if hasattr(self, "_char_sep"):
            self._char_sep.show()
        if hasattr(self, "_avatar_label") and self._avatar_label:
            self._avatar_label.show()
            self._reposition_portrait()

    # Category switching
    def _show_category(self, cat_key):
        if self._loading:
            self._current_cat = cat_key
            return
        self._current_cat = cat_key
        i18n_key = self._category_i18n_key(cat_key)
        speaker = self._category_speaker_key(cat_key)

        for k, btn in self._cat_buttons.items():
            btn.set_active(k == cat_key)

        speaker_name = self.t(speaker)
        portrait = self._portrait_images.get(cat_key)
        if portrait:
            self._avatar_label.setPixmap(portrait)
            self._avatar_label.setText("")
        else:
            self._avatar_label.setPixmap(QPixmap())
            self._avatar_label.setText(speaker_name[0] if speaker_name else "")

        self._char_name_label.setText(speaker_name)
        hover_key = i18n_key.replace("cat_", "hover_default_")
        self._start_typing(self.t(hover_key))

        # Show the category frame
        self._show_frame(self._cat_frames.get(cat_key))

    def _show_frame(self, frame):
        """Show a single frame in the view stack, hiding others.
        Widgets are removed from the layout but NOT deleted, so cached
        category frames can be re-added later without being destroyed."""
        while self._view_stack_layout.count():
            item = self._view_stack_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
        if frame:
            self._view_stack_layout.addWidget(frame, 1)
            frame.show()

    def _embedded_editor_is_dirty(self):
        editor = self._embedded_editor
        if editor is None:
            return False
        for attr in ("_dirty", "_unsaved", "_structural_dirty"):
            if bool(getattr(editor, attr, False)):
                return True
        return False

    def _embedded_editor_save_method(self):
        editor = self._embedded_editor
        if editor is None:
            return None
        for name in ("_save_file", "_on_save", "_do_save", "_save_xfbin", "save_file"):
            method = getattr(editor, name, None)
            if not callable(method):
                continue
            try:
                signature = inspect.signature(method)
            except (TypeError, ValueError):
                return method
            required = [
                param for param in signature.parameters.values()
                if param.default is inspect.Parameter.empty
                and param.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                )
            ]
            if not required:
                return method
        return None

    def _confirm_close_embedded_editor(self):
        if not self._embedded_editor_is_dirty():
            return True

        box = QMessageBox(self)
        box.setWindowTitle(self.t("unsaved_changes_title"))
        box.setStyleSheet(ss_dialog())
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(self.t("unsaved_changes_message"))
        box.setInformativeText(self.t("unsaved_changes_detail"))
        save_btn = box.addButton(self.t("unsaved_changes_save"), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton(self.t("unsaved_changes_discard"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(self.t("unsaved_changes_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked == cancel_btn:
            return False
        if clicked == discard_btn:
            return True
        if clicked == save_btn:
            save_method = self._embedded_editor_save_method()
            if save_method is None:
                QMessageBox.warning(
                    self,
                    self.t("unsaved_changes_title"),
                    self.t("unsaved_changes_no_save_method"),
                )
                return False
            try:
                save_method()
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    self.t("dlg_title_error"),
                    self.t("msg_save_error", error=exc),
                )
                return False
            if self._embedded_editor_is_dirty():
                QMessageBox.warning(
                    self,
                    self.t("unsaved_changes_title"),
                    self.t("unsaved_changes_save_cancelled_or_failed"),
                )
                return False
            return True
        return False

    def _delete_tool_frame(self):
        if self._tool_frame:
            self._tool_frame.deleteLater()
            self._tool_frame = None
        self._embedded_editor = None

    # Open tool inline
    def _open_tool_inline(self, name: str, file_hint: str, tool_id: str | None = None):
        if self._loading:
            return
        if not self._confirm_close_embedded_editor():
            return
        self._delete_tool_frame()

        self._hide_char_panel()

        tool_frame = QWidget()
        tool_layout = QVBoxLayout(tool_frame)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(0)
        self._tool_frame = tool_frame

        # Top bar
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background-color: {P['bg_panel']};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 7, 12, 7)

        back_btn = _make_styled_btn(
            "\u2190 " + self.t("back"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=100, height=30)
        back_btn.clicked.connect(self._close_tool_inline)
        bar_layout.addWidget(back_btn)

        tool_name_lbl = QLabel(name)
        tool_name_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        tool_name_lbl.setStyleSheet(f"color: {P['accent']};")
        bar_layout.addWidget(tool_name_lbl)
        bar_layout.addStretch()

        tool_layout.addWidget(bar)

        # Body
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        tool_layout.addWidget(body, 1)
        self._tool_body = body

        if file_hint == "duelPlayerParam":
            self._embed_editor(body, body_layout)
        elif file_hint == "characode.bin":
            self._embed_characode_editor(body, body_layout)
        elif file_hint == "info":
            self._embed_info_editor(body, body_layout)
        elif file_hint == "PlayerColorParam.bin":
            self._embed_costume_editor(body, body_layout)
        elif "awb" in file_hint.lower():
            self._embed_sound_editor(body, body_layout)
        elif file_hint in ("Xcmn00prm.bin", "0xxx00prm.bin", "0xxx00prm.bin, prm_gha.bin"):
            self._embed_skill_editor(body, body_layout)
        elif file_hint == "effectprm.bin":
            self._embed_effect_editor(body, body_layout)
        elif file_hint == "0xxx00_SPM":
            self._embed_spm_editor(body, body_layout)
        elif file_hint == "0xxx00_x":
            self._embed_projectile_editor(body, body_layout)
        elif file_hint == "0xxx00_constParam":
            self._embed_constparam_editor(body, body_layout)
        elif file_hint == "SupportCharaParam.bin":
            self._embed_assist_editor(body, body_layout)
        elif file_hint == "damageprm.bin":
            self._embed_damageprm_editor(body, body_layout)
        elif file_hint == "damageeff.bin":
            self._embed_damageeff_editor(body, body_layout)
        elif file_hint == "btladjprm.bin":
            self._embed_btladjprm_editor(body, body_layout)
        elif file_hint == "MainModeParam.bin":
            self._embed_mainmodeparam_editor(body, body_layout)
        elif file_hint == "SpeakingLineParam.bin":
            self._embed_speaking_editor(body, body_layout)
        elif file_hint == "messageinfo":
            self._embed_messageinfo_editor(body, body_layout)
        elif file_hint == "DictionaryParam.xfbin":
            self._embed_dictionaryparam_editor(body, body_layout)
        elif file_hint == "StageInfo.bin":
            self._embed_stageinfo_editor(body, body_layout)
        elif file_hint == "Xcmnsfprm.bin":
            self._embed_stagemotion_editor(body, body_layout)
        elif file_hint == "CustomCardParam.xfbin":
            self._embed_customcardparam_editor(body, body_layout)
        elif file_hint == "CharViewerParam.xfbin":
            self._embed_charviewer_editor(body, body_layout)
        elif file_hint == "GuideCharParam.xfbin":
            self._embed_guidecharparam_editor(body, body_layout)
        elif file_hint == "CustomizeDefaultParam.xfbin":
            self._embed_customizedefaultparam_editor(body, body_layout)
        elif file_hint == "DlcInfoParam.xfbin":
            self._embed_dlcinfoparam_editor(body, body_layout)
        elif file_hint == "GalleryArtParam.xfbin":
            self._embed_galleryartparam_editor(body, body_layout)
        elif file_hint == "PlayerTitleParam.xfbin":
            self._embed_playertitleparam_editor(body, body_layout)
        elif file_hint in (".xfbin texures", ".xfbin textures"):
            self._embed_texture_editor(body, body_layout)
        elif file_hint == ".xfbin sounds":
            self._embed_xfbin_audio_editor(body, body_layout)
        elif file_hint == "sndcmnparam.xfbin":
            self._embed_sndcmnparam_editor(body, body_layout)
        elif file_hint == "SoundTestParam.xfbin":
            self._embed_soundtestparam_editor(body, body_layout)
        else:
            self._embed_placeholder(body, body_layout, name, file_hint)

        self._show_frame(tool_frame)
        self._mark_tool_used(tool_id)

    def _embed_editor(self, body, layout):
        editor = CharacterStatsEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_characode_editor(self, body, layout):
        editor = CharacodeEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_info_editor(self, body, layout):
        editor = InfoEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_costume_editor(self, body, layout):
        editor = CostumeEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_sound_editor(self, body, layout):
        editor = SoundEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_skill_editor(self, body, layout):
        editor = SkillEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_effect_editor(self, body, layout):
        editor = EffectEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_spm_editor(self, body, layout):
        editor = SpmEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_projectile_editor(self, body, layout):
        editor = ProjectileEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_constparam_editor(self, body, layout):
        editor = ConstParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_assist_editor(self, body, layout):
        editor = AssistEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_damageprm_editor(self, body, layout):
        editor = DamagePrmEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_damageeff_editor(self, body, layout):
        editor = DamageEffEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_btladjprm_editor(self, body, layout):
        editor = BtlAdjPrmEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_mainmodeparam_editor(self, body, layout):
        editor = MainModeParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_speaking_editor(self, body, layout):
        editor = SpeakingEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_messageinfo_editor(self, body, layout):
        editor = MessageInfoEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_dictionaryparam_editor(self, body, layout):
        editor = DictionaryParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_stageinfo_editor(self, body, layout):
        editor = StageInfoEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_stagemotion_editor(self, body, layout):
        editor = StageMotionEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_customcardparam_editor(self, body, layout):
        editor = CustomCardParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_charviewer_editor(self, body, layout):
        editor = CharViewerEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_guidecharparam_editor(self, body, layout):
        editor = GuideCharParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_customizedefaultparam_editor(self, body, layout):
        editor = CustomizeDefaultParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_dlcinfoparam_editor(self, body, layout):
        editor = DlcInfoParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_galleryartparam_editor(self, body, layout):
        editor = GalleryArtParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_playertitleparam_editor(self, body, layout):
        editor = PlayerTitleParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_texture_editor(self, body, layout):
        editor = TextureEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_xfbin_audio_editor(self, body, layout):
        editor = XfbinAudioEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_sndcmnparam_editor(self, body, layout):
        editor = SndCmnParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_soundtestparam_editor(self, body, layout):
        editor = SoundTestParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _add_embedded_editor(self, editor, layout):
        self._embedded_editor = editor
        install_file_drop(editor)
        layout.addWidget(editor, 1)

    def _embed_placeholder(self, body, layout, name, file_hint):
        lbl = QLabel(ui_text("ui_ASBR-Tools_value_value", p0=name, p1=file_hint))
        lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {P['text_dim']};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl, 1)

    def _close_tool_inline(self):
        if not self._confirm_close_embedded_editor():
            return
        self._delete_tool_frame()
        if self._settings.get("show_guide", True):
            self._show_char_panel()
        if self._tool_search_query:
            self._show_tool_search_results()
            return
        cat_frame = self._cat_frames.get(self._current_cat)
        if cat_frame:
            self._show_frame(cat_frame)

    # Typing effect
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
        if self._current_cat == "CHARACTER":
            import wave, array, io
            try:
                import winsound
            except ImportError:
                return
            wav_path = app_path("resources", "DiMolto.wav")
            if not os.path.exists(wav_path):
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

    # CPK Unpacker (inline)
    def _open_cpk_editor(self):
        if self._loading:
            return
        if not self._confirm_close_embedded_editor():
            return

        if self._settings_win:
            self._settings_win.deleteLater()
            self._settings_win = None
        self._delete_tool_frame()

        self._hide_char_panel()

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        self._cpk_editor_win = panel

        # Top bar — same pattern as Settings / Credits / tool editors
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background-color: {P['bg_panel']};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 7, 12, 7)

        back_btn = _make_styled_btn(
            "\u2190 " + self.t("back"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=100, height=30)
        back_btn.clicked.connect(self._close_cpk_editor_inline)
        bar_layout.addWidget(back_btn)

        title_lbl = QLabel(self.t("cpk_title"))
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['accent']};")
        bar_layout.addWidget(title_lbl)
        bar_layout.addStretch()

        panel_layout.addWidget(bar)

        # Embed the CPK editor widget
        editor = CpkEditor(panel, t_func=self.t)
        install_file_drop(editor)
        panel_layout.addWidget(editor, 1)

        self._show_frame(panel)

    def _close_cpk_editor_inline(self):
        if self._cpk_editor_win:
            self._cpk_editor_win.deleteLater()
            self._cpk_editor_win = None
        if self._settings.get("show_guide", True):
            self._show_char_panel()
        if self._tool_search_query:
            self._show_tool_search_results()
            return
        cat_frame = self._cat_frames.get(self._current_cat)
        if cat_frame:
            self._show_frame(cat_frame)

    # Settings (inline panel)
    def _open_settings(self):
        if self._settings_win:
            self._close_settings_inline()
            return

        if not self._confirm_close_embedded_editor():
            return
        self._delete_tool_frame()

        self._hide_char_panel()

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        self._settings_win = panel

        # Top bar
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background-color: {P['bg_panel']};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 7, 12, 7)

        back_btn = _make_styled_btn(
            "\u2190 " + self.t("back"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=100, height=30)
        back_btn.clicked.connect(self._close_settings_inline)
        bar_layout.addWidget(back_btn)

        settings_lbl = QLabel(self.t("settings"))
        settings_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        settings_lbl.setStyleSheet(f"color: {P['accent']};")
        bar_layout.addWidget(settings_lbl)
        bar_layout.addStretch()

        panel_layout.addWidget(bar)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {P['bg_dark']}; width: 10px; }}"
            f"QScrollBar::handle:vertical {{ background: {P['mid']}; border-radius: 5px; min-height: 20px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {P['secondary']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(40, 20, 40, 20)

        # Language section
        lang_card = QFrame()
        lang_card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 12px; "
            f"border: 1px solid {P['border']}; }}"
        )
        lang_card_layout = QVBoxLayout(lang_card)
        lang_card_layout.setContentsMargins(20, 18, 20, 18)

        lang_title = QLabel(self.t("language"))
        lang_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        lang_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        lang_card_layout.addWidget(lang_title)

        lang_group = QButtonGroup(lang_card)
        for code, name in available_languages(TRANSLATIONS):
            rb = QRadioButton(name)
            rb.setFont(QFont("Segoe UI", 14))
            rb.setStyleSheet(
                f"QRadioButton {{ color: {P['text_main']}; border: none; spacing: 8px; }}"
                f"QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 7px; border: 2px solid {P['secondary']}; background: transparent; }}"
                f"QRadioButton::indicator:checked {{ background: {P['accent']}; border: 2px solid {P['accent']}; }}"
            )
            if code == self._lang:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, c=code: self._set_lang(c) if checked else None)
            lang_group.addButton(rb)
            lang_card_layout.addWidget(rb)

        lang_hint = QLabel(self.t("lang_hint"))
        lang_hint.setFont(QFont("Segoe UI", 12))
        lang_hint.setStyleSheet(f"color: {P['text_dim']}; font-style: italic; border: none;")
        lang_hint.setWordWrap(True)
        lang_card_layout.addWidget(lang_hint)

        lang_share = QLabel(self.t("lang_share"))
        lang_share.setFont(QFont("Segoe UI", 12))
        lang_share.setStyleSheet(f"color: {P['text_dim']}; font-style: italic; border: none;")
        lang_share.setWordWrap(True)
        lang_card_layout.addWidget(lang_share)

        scroll_layout.addWidget(lang_card)
        scroll_layout.addSpacing(16)

        # Theme section
        theme_card = QFrame()
        theme_card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 12px; "
            f"border: 1px solid {P['border']}; }}"
        )
        theme_card_layout = QVBoxLayout(theme_card)
        theme_card_layout.setContentsMargins(20, 18, 20, 18)

        theme_title = QLabel(self.t("color_scheme"))
        theme_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        theme_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        theme_card_layout.addWidget(theme_title)

        theme_group = QButtonGroup(theme_card)
        for tk in THEMES:
            theme_data = THEMES[tk]
            row_widget = QWidget()
            row_widget.setStyleSheet("border: none;")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 4, 0, 4)

            rb = QRadioButton(ui_text("ui_ASBR-Tools_value", p0=theme_data['name']))
            rb.setFont(QFont("Segoe UI", 14))
            rb.setStyleSheet(
                f"QRadioButton {{ color: {P['text_main']}; border: none; spacing: 8px; }}"
                f"QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 7px; border: 2px solid {P['secondary']}; background: transparent; }}"
                f"QRadioButton::indicator:checked {{ background: {P['accent']}; border: 2px solid {P['accent']}; }}"
            )
            if tk == self._theme_key:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, t=tk: self._set_theme(t) if checked else None)
            theme_group.addButton(rb)
            row_layout.addWidget(rb, 1)

            for color_key in ("accent", "secondary", "mid"):
                dot = QFrame()
                dot.setFixedSize(16, 16)
                dot.setStyleSheet(
                    f"background-color: {theme_data[color_key]}; border-radius: 4px; border: none;"
                )
                row_layout.addWidget(dot)
                row_layout.addSpacing(2)

            theme_card_layout.addWidget(row_widget)

        scroll_layout.addWidget(theme_card)
        scroll_layout.addSpacing(16)

        # Game files folder section
        game_dir_card = QFrame()
        game_dir_card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 12px; "
            f"border: 1px solid {P['border']}; }}"
        )
        game_dir_layout = QVBoxLayout(game_dir_card)
        game_dir_layout.setContentsMargins(20, 18, 20, 18)

        game_dir_title = QLabel(self.t("game_files_dir_title"))
        game_dir_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        game_dir_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        game_dir_layout.addWidget(game_dir_title)

        game_dir_hint = QLabel(self.t("game_files_dir_hint"))
        game_dir_hint.setFont(QFont("Segoe UI", 12))
        game_dir_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        game_dir_hint.setWordWrap(True)
        game_dir_layout.addWidget(game_dir_hint)
        game_dir_layout.addSpacing(8)

        game_dir_row = QWidget()
        game_dir_row.setStyleSheet("border: none;")
        game_dir_row_layout = QHBoxLayout(game_dir_row)
        game_dir_row_layout.setContentsMargins(0, 0, 0, 0)
        game_dir_row_layout.setSpacing(8)

        self._game_files_dir_edit = QLineEdit(self._settings.get("game_files_dir", ""))
        self._game_files_dir_edit.setReadOnly(True)
        self._game_files_dir_edit.setPlaceholderText(self.t("game_files_dir_placeholder"))
        self._game_files_dir_edit.setFont(QFont("Segoe UI", 11))
        self._game_files_dir_edit.setStyleSheet(
            f"QLineEdit {{ background: {P['bg_dark']}; color: {P['text_main']}; "
            f"border: 1px solid {P['border']}; border-radius: 8px; padding: 7px 9px; }}"
        )
        game_dir_row_layout.addWidget(self._game_files_dir_edit, 1)

        browse_btn = _make_styled_btn(
            self.t("browse"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 12), width=100, height=32)
        browse_btn.clicked.connect(self._select_game_files_dir)
        game_dir_row_layout.addWidget(browse_btn)

        clear_btn = _make_styled_btn(
            self.t("clear"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 12), width=90, height=32)
        clear_btn.clicked.connect(self._clear_game_files_dir)
        game_dir_row_layout.addWidget(clear_btn)

        game_dir_layout.addWidget(game_dir_row)

        scroll_layout.addWidget(game_dir_card)
        scroll_layout.addSpacing(16)

        # Backup section
        backup_card = QFrame()
        backup_card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 12px; "
            f"border: 1px solid {P['border']}; }}"
        )
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setContentsMargins(20, 18, 20, 18)

        backup_title = QLabel(self.t("backup_on_open_title"))
        backup_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        backup_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        backup_layout.addWidget(backup_title)

        backup_checkbox = QCheckBox(self.t("backup_on_open"))
        backup_checkbox.setFont(QFont("Segoe UI", 14))
        backup_checkbox.setChecked(self._settings.get("backup_on_open", True))
        backup_checkbox.setStyleSheet(
            f"QCheckBox {{ color: {P['text_main']}; border: none; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 2px solid {P['secondary']}; background: transparent; }}"
            f"QCheckBox::indicator:checked {{ background: {P['accent']}; border: 2px solid {P['accent']}; }}"
        )
        backup_checkbox.toggled.connect(self._set_backup_on_open)
        backup_layout.addWidget(backup_checkbox)

        backup_hint = QLabel(self.t("backup_on_open_hint"))
        backup_hint.setFont(QFont("Segoe UI", 12))
        backup_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        backup_hint.setWordWrap(True)
        backup_layout.addWidget(backup_hint)

        scroll_layout.addWidget(backup_card)
        scroll_layout.addSpacing(16)

        # Updates section
        updates_card = QFrame()
        updates_card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 12px; "
            f"border: 1px solid {P['border']}; }}"
        )
        updates_layout = QVBoxLayout(updates_card)
        updates_layout.setContentsMargins(20, 18, 20, 18)

        updates_title = QLabel(self.t("updates_title"))
        updates_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        updates_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        updates_layout.addWidget(updates_title)

        updates_hint = QLabel(self.t("updates_hint", version=updater.APP_VERSION))
        updates_hint.setFont(QFont("Segoe UI", 12))
        updates_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        updates_hint.setWordWrap(True)
        updates_layout.addWidget(updates_hint)
        updates_layout.addSpacing(8)

        updates_checkbox = QCheckBox(self.t("updates_check_on_startup"))
        updates_checkbox.setFont(QFont("Segoe UI", 14))
        updates_checkbox.setChecked(self._settings.get("check_updates_on_startup", True))
        updates_checkbox.setStyleSheet(
            f"QCheckBox {{ color: {P['text_main']}; border: none; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 2px solid {P['secondary']}; background: transparent; }}"
            f"QCheckBox::indicator:checked {{ background: {P['accent']}; border: 2px solid {P['accent']}; }}"
        )
        updates_checkbox.toggled.connect(self._set_check_updates_on_startup)
        updates_layout.addWidget(updates_checkbox)

        updates_row = QWidget()
        updates_row.setStyleSheet("border: none;")
        updates_row_layout = QHBoxLayout(updates_row)
        updates_row_layout.setContentsMargins(0, 8, 0, 0)
        updates_row_layout.setSpacing(10)

        check_updates_btn = _make_styled_btn(
            self.t("updates_check_now"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 12), width=150, height=32)
        check_updates_btn.clicked.connect(lambda: self._check_for_updates(manual=True))
        updates_row_layout.addWidget(check_updates_btn)

        self._update_status_label = QLabel(self.t("updates_idle", version=updater.APP_VERSION))
        self._update_status_label.setFont(QFont("Segoe UI", 12))
        self._update_status_label.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        self._update_status_label.setWordWrap(True)
        updates_row_layout.addWidget(self._update_status_label, 1)

        updates_layout.addWidget(updates_row)

        scroll_layout.addWidget(updates_card)
        scroll_layout.addSpacing(16)

        # Guide Character section
        guide_card = QFrame()
        guide_card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 12px; "
            f"border: 1px solid {P['border']}; }}"
        )
        guide_card_layout = QVBoxLayout(guide_card)
        guide_card_layout.setContentsMargins(20, 18, 20, 18)

        guide_title = QLabel(self.t("guide_char_title"))
        guide_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        guide_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        guide_card_layout.addWidget(guide_title)

        guide_hint = QLabel(ui_text("ui_ASBR-Tools_hide_guide_character_if_you_don_t_need_tips"))
        guide_hint.setFont(QFont("Segoe UI", 9))
        guide_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        guide_card_layout.addWidget(guide_hint)
        guide_card_layout.addSpacing(6)

        guide_group = QButtonGroup(guide_card)
        current_show_guide = self._settings.get("show_guide", True)
        for val, label_key in ((True, "guide_show"), (False, "guide_hide")):
            rb = QRadioButton(self.t(label_key))
            rb.setFont(QFont("Segoe UI", 14))
            rb.setStyleSheet(
                f"QRadioButton {{ color: {P['text_main']}; border: none; spacing: 8px; }}"
                f"QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 7px; border: 2px solid {P['secondary']}; background: transparent; }}"
                f"QRadioButton::indicator:checked {{ background: {P['accent']}; border: 2px solid {P['accent']}; }}"
            )
            if val == current_show_guide:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, v=val: self._set_show_guide(v) if checked else None)
            guide_group.addButton(rb)
            guide_card_layout.addWidget(rb)

        scroll_layout.addWidget(guide_card)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        panel_layout.addWidget(scroll, 1)

        self._show_frame(panel)

    def _select_game_files_dir(self):
        current_dir = self._settings.get("game_files_dir", "")
        if not current_dir or not os.path.isdir(current_dir):
            current_dir = os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(
            self, self.t("game_files_dir_choose"), current_dir
        )
        if not folder:
            return

        folder = os.path.normpath(folder)
        self._settings["game_files_dir"] = folder
        save_settings(self._settings)
        if hasattr(self, "_game_files_dir_edit"):
            self._game_files_dir_edit.setText(folder)

    def _clear_game_files_dir(self):
        self._settings["game_files_dir"] = ""
        save_settings(self._settings)
        if hasattr(self, "_game_files_dir_edit"):
            self._game_files_dir_edit.clear()

    def _set_show_guide(self, value: bool):
        self._settings["show_guide"] = value
        save_settings(self._settings)
        if value:
            self._show_char_panel()
        else:
            self._hide_char_panel()

    def _set_backup_on_open(self, value: bool):
        self._settings["backup_on_open"] = value
        save_settings(self._settings)

    def _set_check_updates_on_startup(self, value: bool):
        self._settings["check_updates_on_startup"] = value
        save_settings(self._settings)

    # Credits (inline panel)
    def _open_credits(self):
        if self._settings_win:
            self._close_settings_inline()

        if not self._confirm_close_embedded_editor():
            return
        self._delete_tool_frame()

        self._hide_char_panel()

        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        self._settings_win = panel

        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background-color: {P['bg_panel']};")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 7, 12, 7)

        back_btn = _make_styled_btn(
            "\u2190 " + self.t("back"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=100, height=30)
        back_btn.clicked.connect(self._close_settings_inline)
        bar_layout.addWidget(back_btn)

        title_lbl = QLabel(ui_text("ui_ASBR-Tools_credits"))
        title_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['accent']};")
        bar_layout.addWidget(title_lbl)
        bar_layout.addStretch()
        panel_layout.addWidget(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {P['bg_dark']}; width: 10px; }}"
            f"QScrollBar::handle:vertical {{ background: {P['mid']}; border-radius: 5px; min-height: 20px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {P['secondary']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(40, 30, 40, 30)
        scroll_layout.setSpacing(20)

        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 12px; "
            f"border: 1px solid {P['border']}; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(28, 24, 28, 24)
        card_layout.setSpacing(14)

        _SOCIAL_ICONS = {
            "github":    icon_social_github,
            "nexusmods": icon_social_nexusmods,
            "youtube":   icon_social_youtube,
            "discord":   icon_social_discord,
        }

        def _section_label(text):
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {P['accent']}; border: none; background: transparent;")
            return lbl

        def _credit_entry(name, links, desc=None):
            w = QWidget()
            w.setStyleSheet("background: transparent;")
            vbox = QVBoxLayout(w)
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(2)

            row = QWidget()
            row.setStyleSheet("background: transparent;")
            hbox = QHBoxLayout(row)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.setSpacing(5)

            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Segoe UI", 13))
            name_lbl.setStyleSheet(f"color: {P['text_main']}; border: none; background: transparent;")
            hbox.addWidget(name_lbl)

            for platform, url in links:
                icon_fn = _SOCIAL_ICONS.get(platform.lower())
                btn = QPushButton()
                btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                btn.setFixedSize(24, 24)
                if icon_fn:
                    btn.setIcon(icon_fn())
                    btn.setIconSize(QSize(15, 15))
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; border: none; border-radius: 4px; }}"
                    f"QPushButton:hover {{ background: {P['mid']}; }}"
                )
                btn.setToolTip(url)
                btn.clicked.connect(lambda checked, u=url: QDesktopServices.openUrl(QUrl(u)))
                hbox.addWidget(btn)

            hbox.addStretch()
            vbox.addWidget(row)

            if desc:
                desc_lbl = QLabel(desc)
                desc_lbl.setFont(QFont("Segoe UI", 11))
                desc_lbl.setStyleSheet(f"color: {P['text_sec']}; border: none; background: transparent;")
                desc_lbl.setWordWrap(True)
                vbox.addWidget(desc_lbl)

            return w

        card_layout.addWidget(_section_label("Author"))
        card_layout.addWidget(_credit_entry("ImGoldenWind", [
            ("GitHub",    "https://github.com/ImGoldenWind"),
            ("NexusMods", "https://www.nexusmods.com/profile/ImGoldenWind"),
            ("YouTube",   "https://www.youtube.com/@ImGoldenWind/videos"),
        ]))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {P['border']}; border: none; background: {P['border']}; max-height: 1px;")
        card_layout.addWidget(sep)

        card_layout.addWidget(_section_label("Special Thanks"))
        card_layout.addWidget(_credit_entry("KojoBailey", [
            ("GitHub",    "https://github.com/KojoBailey"),
            ("NexusMods", "https://www.nexusmods.com/profile/KojoBailey"),
            ("YouTube",   "https://www.youtube.com/@KojoBailey"),
        ], desc="for 010 editor templates that I used to develop the editors in this toolbox"))
        card_layout.addWidget(_credit_entry("Xemasklyr", [
            ("NexusMods", "https://www.nexusmods.com/profile/Xemasklyr/mods"),
            ("YouTube",   "https://www.youtube.com/@Xemasklyr/featured"),
        ], desc="for the groundwork on the Char. Skills editor (0xxx00prm.bin)"))
        card_layout.addWidget(_credit_entry("Al-Hydra", [
            ("GitHub",    "https://github.com/Al-Hydra"),
        ], desc="for his texture editor, which I used as a base for the editor in this toolbox"))
        card_layout.addWidget(_credit_entry("LazyBone152", [
            ("GitHub",    "https://github.com/LazyBone152"),
        ], desc="for the 'ACE' program, the code of which I used as the basis for the built-in editor in this toolbox"))
        card_layout.addWidget(_credit_entry("TheLeonX", [
            ("GitHub",    "https://github.com/TheLeonX"),
            ("NexusMods", "https://www.nexusmods.com/profile/TheLeonX/mods"),
            ("YouTube",   "https://www.youtube.com/@TheLeonX/videos"),
        ], desc="for XFBIN_Lib, the idea of the toolbox, the talking character at the bottom and inspiration"))
        card_layout.addWidget(_credit_entry("SutandoTsukai181", [
            ("GitHub",    "https://github.com/mosamadeeb")
        ], desc="for the groundwork on the CPK Unpacker"))
        card_layout.addWidget(_credit_entry("JoJo Modding Community", [
            ("Discord",   "https://discord.gg/bfWPHBwbr9"),
        ], desc="for the inspiration"))

        scroll_layout.addWidget(card)
        scroll_layout.addStretch()

        scroll.setWidget(scroll_content)
        panel_layout.addWidget(scroll, 1)

        self._show_frame(panel)

    def _close_settings_inline(self):
        if self._settings_win:
            self._settings_win.deleteLater()
            self._settings_win = None
        self._update_status_label = None
        if self._settings.get("show_guide", True):
            self._show_char_panel()
        if self._tool_search_query:
            self._show_tool_search_results()
            return
        cat_frame = self._cat_frames.get(self._current_cat)
        if cat_frame:
            self._show_frame(cat_frame)

    def _set_lang(self, code):
        self._lang = code
        self._settings["language"] = code
        save_settings(self._settings)
        self._settings_win = None
        self._rebuild_ui()

    def _set_theme(self, theme_key):
        self._theme_key = theme_key
        self._settings["theme"] = theme_key
        save_settings(self._settings)
        apply_theme(theme_key)
        self._settings_win = None
        self._rebuild_ui()

    def closeEvent(self, event):
        if not self._confirm_close_embedded_editor():
            event.ignore()
            return
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())

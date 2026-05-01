import sys
import os

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QRadioButton,
    QButtonGroup,
)
from PyQt6.QtGui import QFont, QPixmap, QIcon, QCursor, QDesktopServices
from PyQt6.QtCore import Qt, QTimer, QSize, QPoint, QUrl

from core.themes import THEMES, P, apply_theme
from core.translations import TRANSLATIONS, available_languages, ui_text
from core.icons import (icon_settings_gear, icon_cpk_unpack, icon_credits_star, _pil_to_qpixmap,
                        icon_social_github, icon_social_youtube, icon_social_discord, icon_social_nexusmods)
from core.tool_data import TOOLS, CAT_KEYS, CAT_META, CAT_PORTRAIT
from core.settings import load_settings, save_settings
from core.skeleton import reset_palette, SkeletonBar, SkeletonCard
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
                 on_hover=None, on_leave=None, app=None):
        super().__init__(parent)
        self._label = label
        self._file_hint = file_hint
        self._dlg_key = dlg_key
        self._on_hover_cb = on_hover
        self._on_leave_cb = on_leave
        self._app = app

        self._default_style = (
            f"ToolCard {{ background-color: {P['bg_card']}; border-radius: 8px; "
            f"border: 1px solid {P['border']}; }}"
        )
        self._hover_style = (
            f"ToolCard {{ background-color: {P['bg_card_hov']}; border-radius: 8px; "
            f"border: 1px solid {P['border_hov']}; }}"
        )
        self.setStyleSheet(self._default_style)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(125)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 10, 7)
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
        name_lbl.setStyleSheet(f"color: {P['text_main']}; background: transparent; border: none;")
        name_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts.addWidget(name_lbl)

        hint_lbl = QLabel(file_hint)
        hint_lbl.setFont(QFont("Consolas", 10))
        hint_lbl.setStyleSheet(f"color: {P['text_file']}; background: transparent; border: none;")
        hint_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        texts.addWidget(hint_lbl)
        row.addLayout(texts, 1)

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        if self._on_hover_cb:
            self._on_hover_cb(self._dlg_key)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._default_style)
        if self._on_leave_cb:
            self._on_leave_cb()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self._app:
            self._app._open_tool_inline(self._label, self._file_hint)
        super().mousePressEvent(event)


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


# Main App
class App(QMainWindow):
    _PORTRAIT_SIZE = 150
    _PORTRAIT_OVERFLOW = 60  # px the portrait floats above the panel top

    def __init__(self):
        super().__init__()
        self.setWindowTitle(ui_text("ui_ASBR-Tools_asbr_toolbox"))
        self.resize(1920, 1080)
        self.setMinimumSize(1920, 1080)
        _ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ArrowForgeIcon.ico")
        self._app_icon = QIcon(_ico_path)
        self.setWindowIcon(self._app_icon)

        self._settings = load_settings()
        self._lang = self._settings.get("language", "en")
        self._theme_key = self._settings.get("theme", "star_platinum")
        apply_theme(self._theme_key)

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

        self._central = QWidget()
        self.setCentralWidget(self._central)
        self._root_layout = QVBoxLayout(self._central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._rebuild_ui()

    def _rebuild_ui(self):
        self._typing_timer.stop()
        self._typing_job = None

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
        self._pending_cats = list(CAT_KEYS)
        QTimer.singleShot(20, self._build_next_cat_frame)

    def _build_next_cat_frame(self):
        if not self._pending_cats:
            self._loading = False
            self._show_category(self._current_cat)
            QTimer.singleShot(100, self._reposition_portrait)
            return
        cat_key = self._pending_cats.pop(0)
        self._cat_frames[cat_key] = self._build_cat_frame(cat_key)
        QTimer.singleShot(10, self._build_next_cat_frame)

    def t(self, key, **kw):
        text = TRANSLATIONS.get(self._lang, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"].get(key, key))
        return text.format(**kw) if kw else text

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

        title_lbl = QLabel(self.t("app_title"))
        title_lbl.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {P['accent']};")
        header_layout.addWidget(title_lbl)

        sub_lbl = QLabel("    " + self.t("app_sub"))
        sub_lbl.setFont(QFont("Segoe UI", 12))
        sub_lbl.setStyleSheet(f"color: {P['secondary']};")
        header_layout.addWidget(sub_lbl)

        header_layout.addStretch()

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
        for cat_key in CAT_KEYS:
            i18n_key = CAT_META[cat_key][1]
            btn = _SidebarBtn(
                text=self.t(i18n_key),
                icon=self._cat_icons.get(cat_key, QIcon()),
                on_click=lambda c=cat_key: self._show_category(c),
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
        _, i18n_key, _ = CAT_META[cat_key]

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

        subtitle_lbl = QLabel(self.t("tools_avail", n=len(TOOLS[cat_key])))
        subtitle_lbl.setFont(QFont("Segoe UI", 12))
        subtitle_lbl.setStyleSheet(f"color: {P['text_dim']};")
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(subtitle_lbl)

        frame_layout.addLayout(header_row)

        # Scrollable grid of tool cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{"
            f"  background: {P['bg_dark']}; width: 8px;"
            f"  border-radius: 4px; margin: 0px;"
            f"}}"
            f"QScrollBar::handle:vertical {{"
            f"  background: {P['mid']}; border-radius: 4px; min-height: 28px;"
            f"}}"
            f"QScrollBar::handle:vertical:hover {{ background: {P['secondary']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}"
            f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}"
        )
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        grid = QGridLayout(scroll_content)
        grid.setContentsMargins(20, 8, 20, 16)
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        for idx, (fh, icon_fn, tk, dk) in enumerate(TOOLS[cat_key]):
            ck = f"{tk}_{fh}"
            if ck not in self._tool_icons_cache:
                self._tool_icons_cache[ck] = icon_fn()
            card = ToolCard(scroll_content, self.t(tk), fh, self._tool_icons_cache[ck], dk,
                            on_hover=self._on_hover, on_leave=self._on_leave, app=self)
            grid.addWidget(card, idx // 2, idx % 2)

        scroll.setWidget(scroll_content)
        frame_layout.addWidget(scroll, 1)

        return frame

    # Portrait image loader
    def _load_portrait(self, rel_path, size=64, corner_radius=10, border_width=2, draw_border=True):
        from PIL import Image, ImageDraw, ImageChops, ImageColor
        full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)
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
        self._reposition_portrait()

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
        _, i18n_key, speaker = CAT_META[cat_key]

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

    # Open tool inline
    def _open_tool_inline(self, name: str, file_hint: str):
        if self._loading:
            return
        if self._tool_frame:
            self._tool_frame.deleteLater()
            self._tool_frame = None

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

        self._show_frame(tool_frame)

        if file_hint == "duelPlayerParam":
            QTimer.singleShot(30, lambda: self._embed_editor(body, body_layout))
        elif file_hint == "characode.bin":
            QTimer.singleShot(30, lambda: self._embed_characode_editor(body, body_layout))
        elif file_hint == "info":
            QTimer.singleShot(30, lambda: self._embed_info_editor(body, body_layout))
        elif file_hint == "PlayerColorParam.bin":
            QTimer.singleShot(30, lambda: self._embed_costume_editor(body, body_layout))
        elif "awb" in file_hint.lower():
            QTimer.singleShot(30, lambda: self._embed_sound_editor(body, body_layout))
        elif file_hint in ("Xcmn00prm.bin", "0xxx00prm.bin"):
            QTimer.singleShot(30, lambda: self._embed_skill_editor(body, body_layout))
        elif file_hint == "effectprm.bin":
            QTimer.singleShot(30, lambda: self._embed_effect_editor(body, body_layout))
        elif file_hint == "0xxx00_SPM":
            QTimer.singleShot(30, lambda: self._embed_spm_editor(body, body_layout))
        elif file_hint == "0xxx00_x":
            QTimer.singleShot(30, lambda: self._embed_projectile_editor(body, body_layout))
        elif file_hint == "0xxx00_constParam":
            QTimer.singleShot(30, lambda: self._embed_constparam_editor(body, body_layout))
        elif file_hint == "SupportCharaParam.bin":
            QTimer.singleShot(30, lambda: self._embed_assist_editor(body, body_layout))
        elif file_hint == "damageprm.bin":
            QTimer.singleShot(30, lambda: self._embed_damageprm_editor(body, body_layout))
        elif file_hint == "damageeff.bin":
            QTimer.singleShot(30, lambda: self._embed_damageeff_editor(body, body_layout))
        elif file_hint == "btladjprm.bin":
            QTimer.singleShot(30, lambda: self._embed_btladjprm_editor(body, body_layout))
        elif file_hint == "MainModeParam.bin":
            QTimer.singleShot(30, lambda: self._embed_mainmodeparam_editor(body, body_layout))
        elif file_hint == "SpeakingLineParam.bin":
            QTimer.singleShot(30, lambda: self._embed_speaking_editor(body, body_layout))
        elif file_hint == "messageinfo":
            QTimer.singleShot(30, lambda: self._embed_messageinfo_editor(body, body_layout))
        elif file_hint == "DictionaryParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_dictionaryparam_editor(body, body_layout))
        elif file_hint == "StageInfo.bin":
            QTimer.singleShot(30, lambda: self._embed_stageinfo_editor(body, body_layout))
        elif file_hint == "Xcmnsfprm.bin":
            QTimer.singleShot(30, lambda: self._embed_stagemotion_editor(body, body_layout))
        elif file_hint == "CustomCardParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_customcardparam_editor(body, body_layout))
        elif file_hint == "CharViewerParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_charviewer_editor(body, body_layout))
        elif file_hint == "GuideCharParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_guidecharparam_editor(body, body_layout))
        elif file_hint == "CustomizeDefaultParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_customizedefaultparam_editor(body, body_layout))
        elif file_hint == "DlcInfoParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_dlcinfoparam_editor(body, body_layout))
        elif file_hint == "GalleryArtParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_galleryartparam_editor(body, body_layout))
        elif file_hint == "PlayerTitleParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_playertitleparam_editor(body, body_layout))
        elif file_hint in (".xfbin texures", ".xfbin textures"):
            QTimer.singleShot(30, lambda: self._embed_texture_editor(body, body_layout))
        elif file_hint == ".xfbin sounds":
            QTimer.singleShot(30, lambda: self._embed_xfbin_audio_editor(body, body_layout))
        elif file_hint == "sndcmnparam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_sndcmnparam_editor(body, body_layout))
        elif file_hint == "SoundTestParam.xfbin":
            QTimer.singleShot(30, lambda: self._embed_soundtestparam_editor(body, body_layout))
        else:
            QTimer.singleShot(30, lambda: self._embed_placeholder(body, body_layout, name, file_hint))

    def _embed_editor(self, body, layout):
        editor = CharacterStatsEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_characode_editor(self, body, layout):
        editor = CharacodeEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_info_editor(self, body, layout):
        editor = InfoEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_costume_editor(self, body, layout):
        editor = CostumeEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_sound_editor(self, body, layout):
        editor = SoundEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_skill_editor(self, body, layout):
        editor = SkillEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_effect_editor(self, body, layout):
        editor = EffectEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_spm_editor(self, body, layout):
        editor = SpmEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_projectile_editor(self, body, layout):
        editor = ProjectileEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_constparam_editor(self, body, layout):
        editor = ConstParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_assist_editor(self, body, layout):
        editor = AssistEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_damageprm_editor(self, body, layout):
        editor = DamagePrmEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_damageeff_editor(self, body, layout):
        editor = DamageEffEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_btladjprm_editor(self, body, layout):
        editor = BtlAdjPrmEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_mainmodeparam_editor(self, body, layout):
        editor = MainModeParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_speaking_editor(self, body, layout):
        editor = SpeakingEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_messageinfo_editor(self, body, layout):
        editor = MessageInfoEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_dictionaryparam_editor(self, body, layout):
        editor = DictionaryParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_stageinfo_editor(self, body, layout):
        editor = StageInfoEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_stagemotion_editor(self, body, layout):
        editor = StageMotionEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_customcardparam_editor(self, body, layout):
        editor = CustomCardParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_charviewer_editor(self, body, layout):
        editor = CharViewerEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_guidecharparam_editor(self, body, layout):
        editor = GuideCharParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_customizedefaultparam_editor(self, body, layout):
        editor = CustomizeDefaultParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_dlcinfoparam_editor(self, body, layout):
        editor = DlcInfoParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_galleryartparam_editor(self, body, layout):
        editor = GalleryArtParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_playertitleparam_editor(self, body, layout):
        editor = PlayerTitleParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_texture_editor(self, body, layout):
        editor = TextureEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_xfbin_audio_editor(self, body, layout):
        editor = XfbinAudioEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_sndcmnparam_editor(self, body, layout):
        editor = SndCmnParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_soundtestparam_editor(self, body, layout):
        editor = SoundTestParamEditor(body, self.t, embedded=True)
        layout.addWidget(editor, 1)

    def _embed_placeholder(self, body, layout, name, file_hint):
        lbl = QLabel(ui_text("ui_ASBR-Tools_value_value", p0=name, p1=file_hint))
        lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {P['text_dim']};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl, 1)

    def _close_tool_inline(self):
        if self._tool_frame:
            self._tool_frame.deleteLater()
            self._tool_frame = None
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

    def _on_hover(self, dlg_key):
        _, _, speaker_key = CAT_META[self._current_cat]
        speaker_name = self.t(speaker_key)
        portrait = self._portrait_images.get(self._current_cat)
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
            wav_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "DiMolto.wav")
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

        if self._settings_win:
            self._settings_win.deleteLater()
            self._settings_win = None
        if self._tool_frame:
            self._tool_frame.deleteLater()
            self._tool_frame = None

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
        panel_layout.addWidget(editor, 1)

        self._show_frame(panel)

    def _close_cpk_editor_inline(self):
        if self._cpk_editor_win:
            self._cpk_editor_win.deleteLater()
            self._cpk_editor_win = None
        if self._settings.get("show_guide", True):
            self._show_char_panel()
        cat_frame = self._cat_frames.get(self._current_cat)
        if cat_frame:
            self._show_frame(cat_frame)

    # Settings (inline panel)
    def _open_settings(self):
        if self._settings_win:
            self._close_settings_inline()
            return

        if self._tool_frame:
            self._tool_frame.deleteLater()
            self._tool_frame = None

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

    def _set_show_guide(self, value: bool):
        self._settings["show_guide"] = value
        save_settings(self._settings)
        if value:
            self._show_char_panel()
        else:
            self._hide_char_panel()

    # Credits (inline panel)
    def _open_credits(self):
        if self._settings_win:
            self._close_settings_inline()

        if self._tool_frame:
            self._tool_frame.deleteLater()
            self._tool_frame = None

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
        if self._settings.get("show_guide", True):
            self._show_char_panel()
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())

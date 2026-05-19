import os

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget,
)

from core import updater
from core.icons import (
    icon_constraint, icon_social_discord, icon_social_github, icon_social_nexusmods,
    icon_social_youtube,
)
from core.settings import save_settings
from core.style_helpers import (
    ss_locked_theme_name, ss_page_scrollarea, ss_settings_card, ss_settings_check,
    ss_theme_lock_button,
)
from core.themes import P, THEMES, apply_theme, is_theme_available, visible_theme_keys
from core.translations import TRANSLATIONS, available_languages, ui_text
from core.utils.ui_helpers import _make_styled_btn
from core.widgets.tool_card import ToolCard


class SettingsDialogMixin:
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
        bar.setStyleSheet(f"background-color: {P.get('toolbar_bg', P['bg_panel'])};")
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
        scroll.setStyleSheet(ss_page_scrollarea())
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(40, 20, 40, 20)

        def _settings_checkbox(text_key, setting_key, callback, indent=0):
            checkbox = QCheckBox(self.t(text_key))
            checkbox.setFont(QFont("Segoe UI", 14))
            checkbox.setChecked(self._settings.get(setting_key, True))
            style = ss_settings_check()
            if indent:
                style += (
                    f"QCheckBox {{ padding-left: {indent}px; color: {P['text_sec']}; }}"
                )
            checkbox.setStyleSheet(style)
            checkbox.toggled.connect(callback)
            return checkbox

        # Language section
        lang_card = QFrame()
        lang_card.setStyleSheet(ss_settings_card())
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
        theme_card.setStyleSheet(ss_settings_card())
        theme_card_layout = QVBoxLayout(theme_card)
        theme_card_layout.setContentsMargins(20, 18, 20, 18)

        theme_title = QLabel(self.t("color_scheme"))
        theme_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        theme_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        theme_card_layout.addWidget(theme_title)

        theme_group = QButtonGroup(theme_card)

        def add_theme_row(tk):
            theme_data = THEMES[tk]
            is_open = is_theme_available(tk)
            row_widget = QWidget()
            row_widget.setStyleSheet("border: none;")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 4, 0, 4)

            if is_open:
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
            else:
                lock_btn = QPushButton()
                lock_btn.setEnabled(False)
                lock_btn.setFixedSize(22, 22)
                lock_btn.setIcon(icon_constraint())
                lock_btn.setIconSize(QSize(14, 14))
                lock_btn.setStyleSheet(ss_theme_lock_button())
                row_layout.addWidget(lock_btn)

                name_lbl = QLabel(ui_text("ui_ASBR-Tools_value", p0=theme_data['name']))
                name_lbl.setFont(QFont("Segoe UI", 14))
                name_lbl.setStyleSheet(ss_locked_theme_name())
                row_layout.addWidget(name_lbl, 1)

            for color_key in ("accent", "secondary", "mid"):
                dot = QFrame()
                dot.setFixedSize(16, 16)
                dot.setStyleSheet(
                    f"background-color: {theme_data[color_key]}; border-radius: 4px; border: none;"
                )
                row_layout.addWidget(dot)
                row_layout.addSpacing(2)

            theme_card_layout.addWidget(row_widget)

        visible_themes = visible_theme_keys()
        regular_themes = [tk for tk in visible_themes if THEMES[tk].get("category") != "special"]
        special_themes = [tk for tk in visible_themes if THEMES[tk].get("category") == "special"]

        for tk in regular_themes:
            add_theme_row(tk)

        if special_themes:
            special_title = QLabel(self.t("color_scheme_special"))
            special_title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            special_title.setStyleSheet(f"color: {P['text_sec']}; border: none; background: transparent;")
            theme_card_layout.addSpacing(8)
            theme_card_layout.addWidget(special_title)
            for tk in special_themes:
                add_theme_row(tk)

        scroll_layout.addWidget(theme_card)
        scroll_layout.addSpacing(16)

        # Animations section
        animations_card = QFrame()
        animations_card.setStyleSheet(ss_settings_card())
        animations_layout = QVBoxLayout(animations_card)
        animations_layout.setContentsMargins(20, 18, 20, 18)

        animations_title = QLabel(self.t("animations_title"))
        animations_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        animations_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        animations_layout.addWidget(animations_title)

        animations_hint = QLabel(self.t("animations_hint"))
        animations_hint.setFont(QFont("Segoe UI", 12))
        animations_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        animations_hint.setWordWrap(True)
        animations_layout.addWidget(animations_hint)
        animations_layout.addSpacing(8)

        animations_layout.addWidget(_settings_checkbox(
            "animation_card_perspective",
            "animation_card_perspective",
            self._set_animation_card_perspective,
        ))
        animations_layout.addWidget(_settings_checkbox(
            "animation_editor_fade",
            "animation_editor_fade",
            self._set_animation_editor_fade,
        ))
        animations_layout.addWidget(_settings_checkbox(
            "animation_right_panel_fade",
            "animation_right_panel_fade",
            self._set_animation_right_panel_fade,
        ))
        animations_layout.addWidget(_settings_checkbox(
            "animation_sidebar_highlight",
            "animation_sidebar_highlight",
            self._set_animation_sidebar_highlight,
        ))
        theme_personality_checkbox = _settings_checkbox(
            "animation_theme_personality",
            "animation_theme_personality",
            self._set_animation_theme_personality,
        )
        animations_layout.addWidget(theme_personality_checkbox)

        self._theme_personality_motion_checkbox = _settings_checkbox(
            "animation_theme_personality_motion",
            "animation_theme_personality_motion",
            self._set_animation_theme_personality_motion,
            indent=22,
        )
        self._theme_personality_motion_checkbox.setVisible(self._theme_personality_enabled())
        animations_layout.addWidget(self._theme_personality_motion_checkbox)

        scroll_layout.addWidget(animations_card)
        scroll_layout.addSpacing(16)

        # Game files folder section
        game_dir_card = QFrame()
        game_dir_card.setStyleSheet(ss_settings_card())
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
            f"QLineEdit {{ background: {P.get('input_bg', P['bg_dark'])}; color: {P['text_main']}; "
            f"border: 1px solid {P.get('input_border', P['border'])}; border-radius: 8px; padding: 7px 9px; }}"
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
        backup_card.setStyleSheet(ss_settings_card())
        backup_layout = QVBoxLayout(backup_card)
        backup_layout.setContentsMargins(20, 18, 20, 18)

        backup_title = QLabel(self.t("backup_on_open_title"))
        backup_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        backup_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        backup_layout.addWidget(backup_title)

        backup_checkbox = QCheckBox(self.t("backup_on_open"))
        backup_checkbox.setFont(QFont("Segoe UI", 14))
        backup_checkbox.setChecked(self._settings.get("backup_on_open", True))
        backup_checkbox.setStyleSheet(ss_settings_check())
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
        updates_card.setStyleSheet(ss_settings_card())
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
        updates_checkbox.setStyleSheet(ss_settings_check())
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
        guide_card.setStyleSheet(ss_settings_card())
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

    def _set_animation_card_perspective(self, value: bool):
        self._settings["animation_card_perspective"] = value
        save_settings(self._settings)
        for card in self.findChildren(ToolCard):
            card._glow_timer.stop()
            card._reset_hover_motion()
            card.update()

    def _set_animation_editor_fade(self, value: bool):
        self._settings["animation_editor_fade"] = value
        save_settings(self._settings)
        if not value:
            self._stop_tool_open_animation()

    def _set_animation_right_panel_fade(self, value: bool):
        self._settings["animation_right_panel_fade"] = value
        save_settings(self._settings)
        if not value:
            self._stop_frame_transition()

    def _set_animation_sidebar_highlight(self, value: bool):
        self._settings["animation_sidebar_highlight"] = value
        save_settings(self._settings)
        if not value:
            anim = getattr(self, "_sidebar_highlight_anim", None)
            if anim:
                try:
                    anim.stop()
                    anim.deleteLater()
                except RuntimeError:
                    pass
                self._sidebar_highlight_anim = None
            self._move_sidebar_highlight(self._current_cat, animate=False)

    def _set_animation_theme_personality(self, value: bool):
        self._settings["animation_theme_personality"] = value
        save_settings(self._settings)
        checkbox = getattr(self, "_theme_personality_motion_checkbox", None)
        if checkbox is not None:
            try:
                checkbox.setVisible(value)
            except RuntimeError:
                self._theme_personality_motion_checkbox = None
        for card in self.findChildren(ToolCard):
            card._sync_effect_timer()
            card.update()
        if hasattr(self, "_sync_death13_chaos"):
            self._sync_death13_chaos()
        if hasattr(self, "_sync_white_album_effect"):
            self._sync_white_album_effect()

    def _set_animation_theme_personality_motion(self, value: bool):
        self._settings["animation_theme_personality_motion"] = value
        save_settings(self._settings)
        for card in self.findChildren(ToolCard):
            card._sync_effect_timer()
            card.update()
        if hasattr(self, "_sync_white_album_effect"):
            self._sync_white_album_effect()

    def _set_backup_on_open(self, value: bool):
        self._settings["backup_on_open"] = value
        save_settings(self._settings)

    def _set_check_updates_on_startup(self, value: bool):
        self._settings["check_updates_on_startup"] = value
        save_settings(self._settings)

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
        bar.setStyleSheet(f"background-color: {P.get('toolbar_bg', P['bg_panel'])};")
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
        scroll.setStyleSheet(ss_page_scrollarea())
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(40, 30, 40, 30)
        scroll_layout.setSpacing(20)

        card = QFrame()
        card.setStyleSheet(ss_settings_card())
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
        if not is_theme_available(theme_key):
            return
        self._theme_key = theme_key
        self._settings["theme"] = theme_key
        save_settings(self._settings)
        apply_theme(theme_key)
        self._settings_win = None
        self._rebuild_ui()

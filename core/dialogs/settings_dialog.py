import os

from PyQt6.QtCore import QSize, Qt, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices, QFont, QKeySequence
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QKeySequenceEdit, QMessageBox, QPushButton, QRadioButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from core import updater
from core.icons import (
    icon_constraint, icon_social_discord, icon_social_github, icon_social_nexusmods,
    icon_social_youtube,
)
from core.settings import (
    clear_missing_backup_entries,
    delete_backup_entry,
    load_settings,
    restore_backup_entry,
    save_settings,
)
from core.shortcuts import (
    ACTION_BY_ID,
    SHORTCUT_ACTIONS,
    default_shortcut_settings,
    find_shortcut_conflict,
    normalize_sequence,
    normalize_shortcut_settings,
)
from core.style_helpers import (
    ss_btn, ss_input, ss_locked_theme_name, ss_page_scrollarea, ss_settings_card, ss_settings_check,
    ss_settings_tab_widget, ss_settings_top_card, ss_theme_lock_button,
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

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setElideMode(Qt.TextElideMode.ElideRight)
        tabs.tabBar().setFixedHeight(44)
        tabs.setStyleSheet(ss_settings_tab_widget())

        def _make_settings_tab(title_key):
            tab = QWidget()
            tab.setStyleSheet("background: transparent;")
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.setSpacing(0)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setStyleSheet(ss_page_scrollarea())

            scroll_content = QWidget()
            scroll_content.setStyleSheet("background: transparent;")
            scroll_layout = QVBoxLayout(scroll_content)
            scroll_layout.setContentsMargins(40, 0, 40, 20)
            scroll_layout.setSpacing(0)

            scroll.setWidget(scroll_content)
            tab_layout.addWidget(scroll, 1)
            tabs.addTab(tab, self.t(title_key))
            return scroll_layout

        general_layout = _make_settings_tab("settings_tab_general")
        appearance_layout = _make_settings_tab("settings_tab_appearance")
        files_layout = _make_settings_tab("settings_tab_files")
        updates_tab_layout = _make_settings_tab("settings_tab_updates")
        hotkeys_layout = _make_settings_tab("settings_tab_hotkeys")
        experimental_layout = _make_settings_tab("settings_tab_experimental")

        def _settings_checkbox(text_key, setting_key, callback, indent=0, default=True):
            checkbox = QCheckBox(self.t(text_key))
            checkbox.setFont(QFont("Segoe UI", 14))
            checkbox.setChecked(self._settings.get(setting_key, default))
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
        lang_card.setStyleSheet(ss_settings_top_card())
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

        general_layout.addWidget(lang_card)
        general_layout.addSpacing(16)

        # Tool list section
        tool_list_card = QFrame()
        tool_list_card.setStyleSheet(ss_settings_card())
        tool_list_layout = QVBoxLayout(tool_list_card)
        tool_list_layout.setContentsMargins(20, 18, 20, 18)

        tool_list_title = QLabel(self.t("tool_list_title"))
        tool_list_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        tool_list_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        tool_list_layout.addWidget(tool_list_title)

        tool_list_hint = QLabel(self.t("tool_list_hint"))
        tool_list_hint.setFont(QFont("Segoe UI", 12))
        tool_list_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        tool_list_hint.setWordWrap(True)
        tool_list_layout.addWidget(tool_list_hint)
        tool_list_layout.addSpacing(8)

        tool_list_layout.addWidget(_settings_checkbox(
            "recent_tools_on_top",
            "recent_tools_on_top",
            self._set_recent_tools_on_top,
        ))
        tool_list_layout.addWidget(_settings_checkbox(
            "restore_workspace_on_startup",
            "restore_workspace_on_startup",
            self._set_restore_workspace_on_startup,
        ))

        general_layout.addWidget(tool_list_card)
        general_layout.addSpacing(16)

        # Theme section
        theme_card = QFrame()
        theme_card.setStyleSheet(ss_settings_top_card())
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

        appearance_layout.addWidget(theme_card)
        appearance_layout.addSpacing(16)

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

        appearance_layout.addWidget(animations_card)
        appearance_layout.addStretch()

        # Game files folder section
        game_dir_card = QFrame()
        game_dir_card.setStyleSheet(ss_settings_top_card())
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

        files_layout.addWidget(game_dir_card)
        files_layout.addSpacing(16)

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

        files_layout.addWidget(backup_card)
        files_layout.addSpacing(16)
        self._build_backup_manager(files_layout)
        files_layout.addStretch()

        # Updates section
        updates_card = QFrame()
        updates_card.setStyleSheet(ss_settings_top_card())
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

        updates_tab_layout.addWidget(updates_card)
        updates_tab_layout.addStretch()

        self._build_shortcuts_settings_tab(hotkeys_layout)

        # Experimental section
        experimental_card = QFrame()
        experimental_card.setStyleSheet(ss_settings_top_card())
        experimental_card_layout = QVBoxLayout(experimental_card)
        experimental_card_layout.setContentsMargins(20, 18, 20, 18)
        experimental_card_layout.setSpacing(10)

        experimental_title = QLabel(self.t("experimental_title"))
        experimental_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        experimental_title.setStyleSheet(f"color: {P['accent']}; border: none;")
        experimental_card_layout.addWidget(experimental_title)

        experimental_hint = QLabel(self.t("experimental_hint"))
        experimental_hint.setFont(QFont("Segoe UI", 12))
        experimental_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        experimental_hint.setWordWrap(True)
        experimental_card_layout.addWidget(experimental_hint)

        experimental_card_layout.addWidget(_settings_checkbox(
            "experimental_generic_compare_copy",
            "experimental_generic_compare_copy",
            self._set_experimental_generic_compare_copy,
            default=False,
        ))

        generic_compare_hint = QLabel(self.t("experimental_generic_compare_copy_hint"))
        generic_compare_hint.setFont(QFont("Segoe UI", 12))
        generic_compare_hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        generic_compare_hint.setWordWrap(True)
        experimental_card_layout.addWidget(generic_compare_hint)

        experimental_layout.addWidget(experimental_card)
        experimental_layout.addStretch()

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

        general_layout.addWidget(guide_card)
        general_layout.addStretch()

        panel_layout.addWidget(tabs, 1)

        self._show_frame(panel)

    def _build_shortcuts_settings_tab(self, layout):
        self._shortcut_editors = {}
        self._settings["shortcuts"] = normalize_shortcut_settings(self._settings.get("shortcuts", {}))

        intro_card = QFrame()
        intro_card.setStyleSheet(ss_settings_top_card())
        intro_layout = QVBoxLayout(intro_card)
        intro_layout.setContentsMargins(20, 18, 20, 18)
        intro_layout.setSpacing(10)

        title = QLabel(self.t("shortcuts_title"))
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; border: none;")
        intro_layout.addWidget(title)

        hint = QLabel(self.t("shortcuts_hint"))
        hint.setFont(QFont("Segoe UI", 12))
        hint.setStyleSheet(f"color: {P['text_dim']}; border: none;")
        hint.setWordWrap(True)
        intro_layout.addWidget(hint)

        reset_all = QPushButton(self.t("shortcut_reset_all"))
        reset_all.setFixedHeight(30)
        reset_all.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        reset_all.setStyleSheet(ss_btn())
        reset_all.clicked.connect(self._reset_all_shortcuts)
        intro_layout.addWidget(reset_all, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(intro_card)
        layout.addSpacing(16)

        for group_key in ("shortcuts_group_application", "shortcuts_group_editor"):
            card = QFrame()
            card.setStyleSheet(ss_settings_card())
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(20, 18, 20, 18)
            card_layout.setSpacing(8)

            group_title = QLabel(self.t(group_key))
            group_title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
            group_title.setStyleSheet(f"color: {P['accent']}; border: none;")
            card_layout.addWidget(group_title)

            header = QWidget()
            header.setStyleSheet("border: none; background: transparent;")
            header_layout = QHBoxLayout(header)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(8)
            header_layout.addSpacing(260)
            for key in ("shortcut_primary", "shortcut_secondary"):
                label = QLabel(self.t(key))
                label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
                label.setStyleSheet(f"color: {P['text_sec']}; border: none;")
                label.setFixedWidth(150)
                header_layout.addWidget(label)
            header_layout.addStretch()
            card_layout.addWidget(header)

            for action in SHORTCUT_ACTIONS:
                if action.group_key == group_key:
                    card_layout.addWidget(self._make_shortcut_row(action))

            layout.addWidget(card)
            layout.addSpacing(16)

        layout.addStretch()

    def _make_shortcut_row(self, action):
        row = QWidget()
        row.setStyleSheet("border: none; background: transparent;")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel(self.t(action.label_key))
        label.setFont(QFont("Segoe UI", 12))
        label.setStyleSheet(f"color: {P['text_main']}; border: none;")
        label.setFixedWidth(252)
        row_layout.addWidget(label)

        current = self._settings.get("shortcuts", {}).get(action.action_id, [])
        for index in range(2):
            editor = QKeySequenceEdit()
            editor.setFixedWidth(150)
            editor.setFixedHeight(30)
            editor.setFont(QFont("Segoe UI", 10))
            editor.setStyleSheet(ss_input())
            if index < len(current):
                editor.setKeySequence(QKeySequence(current[index]))
            editor.keySequenceChanged.connect(
                lambda sequence, action_id=action.action_id, slot=index, widget=editor:
                    self._set_shortcut_sequence(action_id, slot, sequence, widget)
            )
            self._shortcut_editors[(action.action_id, index)] = editor
            row_layout.addWidget(editor)

        reset_btn = QPushButton(self.t("shortcut_reset"))
        reset_btn.setFixedHeight(30)
        reset_btn.setFont(QFont("Segoe UI", 10))
        reset_btn.setStyleSheet(ss_btn())
        reset_btn.clicked.connect(lambda _checked=False, action_id=action.action_id: self._reset_shortcut(action_id))
        row_layout.addWidget(reset_btn)
        row_layout.addStretch()
        return row

    def _set_shortcut_sequence(self, action_id: str, index: int, sequence, widget):
        current = normalize_shortcut_settings(self._settings.get("shortcuts", {}))
        sequences = list(current.get(action_id, []))
        while len(sequences) <= index:
            sequences.append("")
        sequences[index] = normalize_sequence(sequence)
        sequences = [item for item in sequences if item]
        deduped = []
        for item in sequences:
            if item not in deduped:
                deduped.append(item)
        current[action_id] = deduped

        conflict = find_shortcut_conflict(current)
        if conflict:
            shortcut, first, second = conflict
            QMessageBox.warning(
                self,
                self.t("shortcuts_conflict_title"),
                self.t(
                    "shortcuts_conflict_message",
                    shortcut=shortcut,
                    first=self.t(ACTION_BY_ID[first].label_key),
                    second=self.t(ACTION_BY_ID[second].label_key),
                ),
            )
            self._refresh_shortcut_editors()
            return

        self._settings["shortcuts"] = current
        save_settings(self._settings)
        manager = getattr(self, "_shortcut_manager", None)
        if manager is not None:
            manager.reload()
        self._refresh_shortcut_editors()

    def _reset_shortcut(self, action_id: str):
        current = normalize_shortcut_settings(self._settings.get("shortcuts", {}))
        current[action_id] = default_shortcut_settings().get(action_id, [])
        self._settings["shortcuts"] = current
        save_settings(self._settings)
        manager = getattr(self, "_shortcut_manager", None)
        if manager is not None:
            manager.reload()
        self._refresh_shortcut_editors()

    def _reset_all_shortcuts(self):
        self._settings["shortcuts"] = default_shortcut_settings()
        save_settings(self._settings)
        manager = getattr(self, "_shortcut_manager", None)
        if manager is not None:
            manager.reload()
        self._refresh_shortcut_editors()

    def _refresh_shortcut_editors(self):
        shortcuts = normalize_shortcut_settings(self._settings.get("shortcuts", {}))
        self._settings["shortcuts"] = shortcuts
        for (action_id, index), editor in getattr(self, "_shortcut_editors", {}).items():
            sequences = shortcuts.get(action_id, [])
            value = sequences[index] if index < len(sequences) else ""
            editor.blockSignals(True)
            editor.setKeySequence(QKeySequence(value))
            editor.blockSignals(False)

    def _build_backup_manager(self, layout):
        card = QFrame()
        card.setStyleSheet(ss_settings_card())
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)

        title = QLabel(self.t("qol_backup_manager_title"))
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {P['accent']}; border: none;")
        card_layout.addWidget(title)

        self._backup_manager_search = QLineEdit()
        self._backup_manager_search.setPlaceholderText(self.t("qol_backup_search"))
        self._backup_manager_search.setFixedHeight(30)
        self._backup_manager_search.setFont(QFont("Segoe UI", 11))
        self._backup_manager_search.setStyleSheet(ss_input())
        self._backup_manager_search.textChanged.connect(self._refresh_backup_manager)
        card_layout.addWidget(self._backup_manager_search)

        self._backup_manager_list = QWidget()
        self._backup_manager_list.setStyleSheet("background: transparent; border: none;")
        self._backup_manager_list_layout = QVBoxLayout(self._backup_manager_list)
        self._backup_manager_list_layout.setContentsMargins(0, 0, 0, 0)
        self._backup_manager_list_layout.setSpacing(6)
        card_layout.addWidget(self._backup_manager_list)

        footer = QWidget()
        footer.setStyleSheet("background: transparent; border: none;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.addStretch()
        clear_missing = QPushButton(self.t("qol_backup_clear_missing"))
        clear_missing.setFixedHeight(30)
        clear_missing.setStyleSheet(ss_btn())
        clear_missing.clicked.connect(self._clear_missing_backups)
        footer_layout.addWidget(clear_missing)
        card_layout.addWidget(footer)

        layout.addWidget(card)
        self._refresh_backup_manager()

    def _clear_backup_manager_rows(self):
        layout = getattr(self, "_backup_manager_list_layout", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _refresh_backup_manager(self):
        layout = getattr(self, "_backup_manager_list_layout", None)
        if layout is None:
            return
        self._settings = load_settings()
        self._clear_backup_manager_rows()
        query = ""
        if getattr(self, "_backup_manager_search", None) is not None:
            query = self._backup_manager_search.text().strip().lower()
        history = self._settings.get("backup_history", [])
        shown = 0
        for entry in history:
            source_path = entry.get("source_path", "")
            backup_path = entry.get("backup_path", "")
            haystack = " ".join((source_path, backup_path, entry.get("tool_id", ""), entry.get("reason", ""))).lower()
            if query and query not in haystack:
                continue
            layout.addWidget(self._make_backup_row(entry))
            shown += 1
            if shown >= 30:
                break
        if not shown:
            empty = QLabel(self.t("qol_backup_empty"))
            empty.setFont(QFont("Segoe UI", 11))
            empty.setStyleSheet(f"color: {P['text_dim']}; border: none;")
            layout.addWidget(empty)

    def _make_backup_row(self, entry):
        row = QFrame()
        row.setStyleSheet(f"QFrame {{ background: {P['bg_card']}; border: 1px solid {P['border']}; border-radius: 6px; }}")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(8)

        backup_path = entry.get("backup_path", "")
        source_path = entry.get("source_path", "")
        exists = os.path.isfile(backup_path)
        label = QLabel(self.t(
            "qol_backup_row",
            name=os.path.basename(backup_path) or backup_path,
            reason=entry.get("reason", ""),
            status=self.t("qol_backup_status_ok") if exists else self.t("qol_backup_status_missing"),
        ))
        label.setFont(QFont("Segoe UI", 11))
        label.setToolTip(f"{backup_path}\n{source_path}")
        label.setStyleSheet(f"color: {P['text_main'] if exists else P['text_dim']}; border: none; background: transparent;")
        row_layout.addWidget(label, 1)

        open_btn = QPushButton(self.t("qol_open_folder"))
        open_btn.setFixedHeight(28)
        open_btn.setStyleSheet(ss_btn())
        open_btn.clicked.connect(lambda _checked=False, p=backup_path: self._open_backup_folder(p))
        row_layout.addWidget(open_btn)

        restore_btn = QPushButton(self.t("qol_restore"))
        restore_btn.setFixedHeight(28)
        restore_btn.setEnabled(exists)
        restore_btn.setStyleSheet(ss_btn(accent=True))
        restore_btn.clicked.connect(lambda _checked=False, e=dict(entry): self._restore_backup(e))
        row_layout.addWidget(restore_btn)

        delete_btn = QPushButton(self.t("qol_delete"))
        delete_btn.setFixedHeight(28)
        delete_btn.setStyleSheet(ss_btn(danger=True))
        delete_btn.clicked.connect(lambda _checked=False, p=backup_path: self._delete_backup(p))
        row_layout.addWidget(delete_btn)
        return row

    def _open_backup_folder(self, backup_path):
        folder = os.path.dirname(backup_path)
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _restore_backup(self, entry):
        result = QMessageBox.question(
            self,
            self.t("qol_backup_restore_title"),
            self.t("qol_backup_restore_message", path=entry.get("source_path", "")),
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            restore_backup_entry(entry)
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("qol_backup_restore_error", error=exc))
            return
        self._refresh_backup_manager()

    def _delete_backup(self, backup_path):
        delete_backup_entry(backup_path)
        self._refresh_backup_manager()

    def _clear_missing_backups(self):
        removed = clear_missing_backup_entries()
        QMessageBox.information(self, self.t("qol_backup_manager_title"), self.t("qol_backup_missing_cleared", count=removed))
        self._refresh_backup_manager()

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

    def _set_recent_tools_on_top(self, value: bool):
        self._settings["recent_tools_on_top"] = value
        save_settings(self._settings)
        for cat_key in list(getattr(self, "_cat_frames", {}).keys()):
            if cat_key != self._SECRET_CAT:
                self._rebuild_cat_frame_cache(cat_key)
        if getattr(self, "_settings_win", None) is not None:
            return
        if self._tool_search_query:
            self._show_tool_search_results()
            return
        if self._current_cat in self._cat_frames:
            self._show_category(self._current_cat)

    def _set_restore_workspace_on_startup(self, value: bool):
        self._settings["restore_workspace_on_startup"] = value
        save_settings(self._settings)

    def _set_experimental_generic_compare_copy(self, value: bool):
        self._settings["experimental_generic_compare_copy"] = value
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
        card_layout.addWidget(_credit_entry("Leafpenguins", [
            ("NexusMods", "https://www.nexusmods.com/profile/Leafpenguins"),
        ], desc=self.t("credit_leaf_desc")))
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

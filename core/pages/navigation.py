import fnmatch
import os
import re

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.style_helpers import ss_home_grid_scrollarea
from core.themes import P
from core.translations import TRANSLATIONS
from core.utils.ui_helpers import _make_label_background_transparent
from core.widgets.tool_card import ToolCard


class NavigationMixin:
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

    def _on_tool_search_return_pressed(self):
        query = self._tool_search_entry.text().strip() if self._tool_search_entry else ""
        if not self._run_tool_search_command(query):
            return
        self._tool_search_query = ""
        if self._tool_search_entry:
            self._tool_search_entry.blockSignals(True)
            self._tool_search_entry.clear()
            self._tool_search_entry.blockSignals(False)
        if not self._loading:
            self._show_category(self._current_cat)

    def _run_tool_search_command(self, query):
        command = self._normalize_search_text(query)
        command = command.removeprefix("/").removeprefix(":").strip()
        aliases = {
            "d13 circus": self._test_death13_circus,
            "death13 circus": self._test_death13_circus,
            "death 13 circus": self._test_death13_circus,
            "d13 laugh": self._test_death13_laugh,
            "death13 laugh": self._test_death13_laugh,
            "death 13 laugh": self._test_death13_laugh,
            "d13 robot": self._test_death13_robot,
            "death13 robot": self._test_death13_robot,
            "death 13 robot": self._test_death13_robot,
            "d13 glitch": self._test_death13_glitch,
            "death13 glitch": self._test_death13_glitch,
            "death 13 glitch": self._test_death13_glitch,
            "d13 flash": self._test_death13_flash,
            "death13 flash": self._test_death13_flash,
            "death 13 flash": self._test_death13_flash,
            "d13 chaos": self._test_death13_chaos,
            "death13 chaos": self._test_death13_chaos,
            "death 13 chaos": self._test_death13_chaos,
        }
        action = aliases.get(command)
        if action is None:
            return False
        action()
        return True

    def _ensure_death13_test_ready(self):
        if hasattr(self, "_theme_key"):
            self._theme_key = "Death 13"
        if hasattr(self, "_settings"):
            self._settings["animation_theme_personality"] = True
        from core.themes import apply_theme
        apply_theme("Death 13")
        if hasattr(self, "_sync_death13_chaos"):
            self._sync_death13_chaos()

    def _test_death13_circus(self):
        self._ensure_death13_test_ready()
        if hasattr(self, "_play_death13_named_clip"):
            self._play_death13_named_clip("circus")

    def _test_death13_laugh(self):
        self._ensure_death13_test_ready()
        if hasattr(self, "_play_death13_named_clip"):
            self._play_death13_named_clip("laugh")

    def _test_death13_robot(self):
        self._ensure_death13_test_ready()
        if hasattr(self, "_play_death13_named_clip"):
            self._play_death13_named_clip("robot")

    def _test_death13_glitch(self):
        self._ensure_death13_test_ready()
        if hasattr(self, "_play_death13_glitch_sound"):
            self._play_death13_glitch_sound()

    def _test_death13_flash(self):
        self._ensure_death13_test_ready()
        if hasattr(self, "_flash_death13_overlay"):
            self._flash_death13_overlay()

    def _test_death13_chaos(self):
        self._ensure_death13_test_ready()
        if hasattr(self, "_play_death13_named_clip"):
            self._play_death13_named_clip("circus")
        if hasattr(self, "_flash_death13_overlay"):
            self._flash_death13_overlay()
        if hasattr(self, "_play_death13_glitch_sound"):
            QTimer.singleShot(120, self._play_death13_glitch_sound)

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
        if self._file_hint_matches_query(row[1], query):
            return True
        terms = [term for term in self._normalize_search_text(query).split(" ") if term]
        if not terms:
            return True
        blob = self._tool_search_blob(row)
        return all(term in blob for term in terms)

    def _file_hint_matches_query(self, file_hint, query):
        name = os.path.basename(str(query or "").strip().strip("\"'")).casefold()
        if not name or "." not in name:
            return False

        for hint in re.split(r"[,;|]", str(file_hint or "")):
            hint = hint.strip().casefold()
            if not hint:
                continue
            patterns = {hint}
            if hint.endswith(".bin"):
                patterns.add(f"{hint}.xfbin")
            if "*" not in hint and "?" not in hint:
                patterns.add(f"*{hint}*")
            for pattern in patterns:
                if fnmatch.fnmatchcase(name, pattern):
                    return True
        return False

    def _filtered_tool_rows(self):
        return [row for row in self._all_tool_rows() if self._tool_matches_search(row, self._tool_search_query)]

    def _show_tool_search_results(self):
        if self._search_frame:
            self._search_frame.deleteLater()
            self._search_frame = None
        self._search_frame = self._build_search_frame()
        for btn in self._cat_buttons.values():
            btn.set_active(False)
        highlight = getattr(self, "_sidebar_highlight", None)
        if highlight is not None:
            highlight.hide()
        self._show_frame(self._search_frame, animate=False)

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
        _make_label_background_transparent(title_lbl)
        title_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent; border: none;")
        header_row.addWidget(title_lbl)

        header_row.addStretch()

        subtitle_lbl = QLabel(self.t("tools_avail", n=len(tool_rows)))
        subtitle_lbl.setFont(QFont("Segoe UI", 12))
        _make_label_background_transparent(subtitle_lbl)
        subtitle_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent; border: none;")
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

    def _show_category(self, cat_key):
        if self._loading:
            self._current_cat = cat_key
            return
        self._current_cat = cat_key
        if cat_key == self._SECRET_CAT:
            self._set_sidebar_buttons_hidden(True)
            self._hide_char_panel()
            self._show_frame(self._cat_frames.get(cat_key))
            return

        self._set_sidebar_buttons_hidden(False)
        if self._settings.get("show_guide", True):
            self._show_char_panel()

        i18n_key = self._category_i18n_key(cat_key)
        speaker = self._category_speaker_key(cat_key)

        for k, btn in self._cat_buttons.items():
            btn.set_active(k == cat_key)
        self._move_sidebar_highlight(cat_key)

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

    def _stop_frame_transition(self):
        anim = getattr(self, "_frame_transition_anim", None)
        if anim:
            try:
                anim.stop()
                anim.deleteLater()
            except RuntimeError:
                pass

        overlay = getattr(self, "_frame_transition_overlay", None)
        if overlay is not None:
            try:
                overlay.hide()
                overlay.deleteLater()
            except RuntimeError:
                pass

        self._frame_transition_anim = None
        self._frame_transition_overlay = None
        self._frame_transition_target = None
        self._frame_transition_target_effect = None

    def _show_frame(self, frame, animate=True):
        """Show a single frame in the view stack, hiding others.
        Widgets are removed from the layout but NOT deleted, so cached
        category frames can be re-added later without being destroyed."""
        self._stop_frame_transition()

        old_frame = getattr(self, "_current_frame", None)
        try:
            same_frame = old_frame is frame and frame is not None and frame.isVisible()
            old_can_animate = (
                old_frame is not None
                and old_frame is not frame
                and old_frame.isVisible()
                and old_frame.parentWidget() is self._view_stack
                and old_frame.width() > 0
                and old_frame.height() > 0
            )
        except RuntimeError:
            old_frame = None
            same_frame = False
            old_can_animate = False

        if same_frame:
            return

        overlay = None
        use_animation = (
            animate
            and self._right_panel_fade_enabled()
            and not self._loading
            and frame is not None
            and old_can_animate
        )
        if use_animation:
            pixmap = old_frame.grab()
            if pixmap.isNull():
                use_animation = False
            else:
                overlay = QLabel(self._view_stack)
                overlay.setGeometry(old_frame.geometry())
                overlay.setPixmap(pixmap)
                overlay.show()

        while self._view_stack_layout.count():
            item = self._view_stack_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()

        if frame:
            self._view_stack_layout.addWidget(frame, 1)
            frame.show()
            self._current_frame = frame
            if hasattr(self, "_schedule_background_sync"):
                self._schedule_background_sync()
        else:
            self._current_frame = None
            return

        if not use_animation:
            return

        overlay_effect = QGraphicsOpacityEffect(overlay)
        overlay_effect.setOpacity(1.0)
        overlay.setGraphicsEffect(overlay_effect)
        overlay.raise_()

        anim = QPropertyAnimation(overlay_effect, b"opacity", self)
        anim.setDuration(140)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._frame_transition_anim = anim
        self._frame_transition_overlay = overlay
        self._frame_transition_target = frame
        self._frame_transition_target_effect = None

        def finish_transition():
            if overlay is not None:
                try:
                    overlay.deleteLater()
                except RuntimeError:
                    pass
            if self._frame_transition_anim is anim:
                self._frame_transition_anim = None
                self._frame_transition_overlay = None
                self._frame_transition_target = None
                self._frame_transition_target_effect = None
            try:
                anim.deleteLater()
            except RuntimeError:
                pass

        anim.finished.connect(finish_transition)
        anim.start()

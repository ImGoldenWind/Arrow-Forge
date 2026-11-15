from core.design_tokens import TypeSize
from core.design_tokens import ui_font
from core.ui.editor_widgets import configure_search
import os

from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtGui import QCursor, QFont, QIcon, QPixmap, QTransform
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.icons import (
    _pil_to_qpixmap, icon_cpk_unpack, icon_credits_star, icon_favorite_category,
    icon_settings_gear,
)
from core.runtime_paths import app_path
from core.skeleton import reset_palette
from core.style_helpers import make_empty_state, ss_home_grid_scrollarea, ss_search
from core.themes import P
from core.tool_data import CAT_META, CAT_PORTRAIT
from core.ui.sidebar import _SidebarBtn
from core.utils.ui_helpers import (
    _clear_layout, _make_label_background_transparent, _make_styled_btn,
    _theme_float, _theme_int, _theme_qss_bg, _transparent_icon_pixmap,
)
from core.widgets.tool_card import ToolCard


class AppLayoutMixin:
    def _rebuild_ui(self):
        self._typing_timer.stop()
        self._typing_job = None
        self._update_status_label = None
        self._stop_frame_transition()
        self._stop_tool_open_animation()
        sidebar_anim = getattr(self, "_sidebar_highlight_anim", None)
        if sidebar_anim:
            try:
                sidebar_anim.stop()
                sidebar_anim.deleteLater()
            except RuntimeError:
                pass
        self._sidebar_highlight_anim = None
        self._sidebar = None
        self._sidebar_highlight = None
        self._current_frame = None
        visible_cat_keys = self._visible_cat_keys()
        if self._current_cat not in visible_cat_keys:
            self._current_cat = visible_cat_keys[0] if visible_cat_keys else None

        _clear_layout(self._root_layout)
        if hasattr(self, "_avatar_label") and self._avatar_label is not None:
            self._avatar_label.deleteLater()
            self._avatar_label = None
        if self._background_wallpaper_label is not None:
            self._background_wallpaper_label.deleteLater()
        self._background_wallpaper_label = None
        self._background_wallpaper_source = None
        self._background_wallpaper_path = None
        if self._background_decor_label is not None:
            self._background_decor_label.deleteLater()
        self._background_decor_label = None
        self._background_decor_source = None
        self._background_decor_path = None
        self._apply_window_shell_style()
        self._loading = True
        reset_palette()

        # Rebuild icon caches
        self._cat_icons = {}
        self._tool_icons_cache = {}
        self._cat_icons["FAVORITES"] = icon_favorite_category(size=24)
        for cat, (icon_fn, *_) in CAT_META.items():
            self._cat_icons[cat] = icon_fn(size=24)
        self._cat_icons[self._SECRET_CAT] = icon_credits_star(size=24)
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
        QTimer.singleShot(0, self._sync_background_wallpaper)
        QTimer.singleShot(0, self._sync_background_decoration)
        QTimer.singleShot(80, self._sync_background_wallpaper)
        QTimer.singleShot(80, self._sync_background_decoration)

        # Build category frames incrementally
        self._cat_frames = {}
        self._search_frame = None
        self._pending_cats = visible_cat_keys
        QTimer.singleShot(20, self._build_next_cat_frame)
        if hasattr(self, "_sync_death13_chaos"):
            self._sync_death13_chaos()
        if hasattr(self, "_sync_white_album_effect"):
            self._sync_white_album_effect()

    def _apply_window_shell_style(self, window_bg=None):
        bg = window_bg or _theme_qss_bg('window_bg', 'bg_dark')
        self.setStyleSheet(
            f"QMainWindow {{ background: {bg}; }}"
            f"QToolTip {{ background-color: {P.get('dialog_bg', P.get('bg_panel', '#111111'))}; "
            f"color: {P['text_main']}; border: 1px solid {P['border']}; "
            f"border-radius: 8px; padding: 6px 9px; }}"
            f"QMenu {{ background-color: {P.get('dialog_bg', P.get('bg_panel', '#111111'))}; "
            f"color: {P['text_main']}; border: 1px solid {P['border']}; padding: 6px; }}"
            f"QMenu::item {{ padding: 6px 18px; border-radius: 8px; }}"
            f"QMenu::item:selected {{ background-color: {P.get('list_hover_bg', P['mid'])}; }}"
        )
        self._central.setStyleSheet(f"background: {bg};")

    def _build_next_cat_frame(self):
        if not self._pending_cats:
            self._loading = False
            if self._tool_search_query:
                self._show_tool_search_results()
            elif self._current_cat is None:
                self._show_frame(self._build_empty_catalog_frame(), animate=False)
            else:
                self._show_category(self._current_cat)
            QTimer.singleShot(100, self._reposition_portrait)
            return
        cat_key = self._pending_cats.pop(0)
        self._cat_frames[cat_key] = self._build_cat_frame(cat_key)
        QTimer.singleShot(10, self._build_next_cat_frame)

    def _build_header(self):
        accent_bar = QFrame()
        accent_bar.setFixedHeight(3)
        accent_bar.setStyleSheet(f"background: {_theme_qss_bg('accent_bar', 'accent')};")
        self._root_layout.addWidget(accent_bar)

        header = QFrame()
        header.setFixedHeight(56)
        header.setStyleSheet(f"background: {_theme_qss_bg('header_bg', 'bg_panel')};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 20, 8)
        header_layout.setSpacing(10)

        app_icon_lbl = QLabel()
        app_icon_lbl.setPixmap(_transparent_icon_pixmap(self._app_icon, QSize(32, 32)))
        app_icon_lbl.setFixedSize(32, 32)
        app_icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        app_icon_lbl.setAutoFillBackground(False)
        app_icon_lbl.setStyleSheet("background: transparent; border: none;")
        header_layout.addWidget(app_icon_lbl)

        self._header_title_lbl = QLabel(self.t("app_title"))
        self._header_title_lbl.setFont(ui_font(TypeSize.HERO, QFont.Weight.Bold))
        self._header_title_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._header_title_lbl.setAutoFillBackground(False)
        self._header_title_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent; border: none;")
        self._header_title_lbl.setMinimumWidth(self._header_title_lbl.sizeHint().width())
        self._header_title_lbl.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(self._header_title_lbl)

        header_layout.addStretch()

        self._tool_search_entry = QLineEdit()
        configure_search(self._tool_search_entry)
        self._tool_search_entry.setMinimumWidth(120)
        self._tool_search_entry.setMaximumWidth(360)
        self._tool_search_entry.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._tool_search_entry.setClearButtonEnabled(True)
        self._tool_search_entry.setText(self._tool_search_query)
        self._tool_search_entry.textChanged.connect(self._on_tool_search_changed)
        self._tool_search_entry.returnPressed.connect(self._on_tool_search_return_pressed)
        header_layout.addWidget(self._tool_search_entry, 1)

        unpack_btn = _make_styled_btn(
            "  " + self.t("cpk_unpack_btn"), P["mid"], P["bg_card_hov"], P["accent"],
            ui_font(TypeSize.TITLE), width=120, height=34, icon=self._unpack_icon)
        unpack_btn.clicked.connect(self._open_cpk_editor)
        header_layout.addWidget(unpack_btn)

        credits_btn = _make_styled_btn(
            "  Credits", P["mid"], P["bg_card_hov"], P["secondary"],
            ui_font(TypeSize.TITLE), width=120, height=34, icon=self._credits_icon)
        credits_btn.clicked.connect(self._open_credits)
        header_layout.addWidget(credits_btn)

        settings_btn = _make_styled_btn(
            "  " + self.t("settings"), P["mid"], P["bg_card_hov"], P["secondary"],
            ui_font(TypeSize.TITLE), width=130, height=34, icon=self._settings_icon)
        settings_btn.clicked.connect(self._open_settings)
        header_layout.addWidget(settings_btn)

        self._root_layout.addWidget(header)
        self._sync_header_layout()

        highlight_bar = QFrame()
        highlight_bar.setFixedHeight(1)
        highlight_bar.setStyleSheet(f"background: {_theme_qss_bg('highlight_bar', 'highlight')};")
        self._root_layout.addWidget(highlight_bar)

    def _build_sidebar(self, parent_layout):
        sidebar = QFrame()
        sidebar.setFixedWidth(210)
        sidebar.setStyleSheet(f"background: {_theme_qss_bg('panel_bg', 'bg_panel')};")
        self._sidebar = sidebar

        self._sidebar_highlight = QFrame(sidebar)
        self._sidebar_highlight.setFixedHeight(34)
        self._sidebar_highlight.setStyleSheet(
            f"background: {_theme_qss_bg('sidebar_highlight_bg', 'mid')}; border: none;"
        )
        self._sidebar_highlight.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._sidebar_highlight.hide()
        self._sidebar_highlight.lower()

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 12, 0, 0)
        sidebar_layout.setSpacing(1)

        self._cat_buttons = {}
        for cat_key in self._sidebar_cat_keys():
            i18n_key = self._category_i18n_key(cat_key)
            btn = _SidebarBtn(
                text=self.t(i18n_key),
                icon=self._cat_icons.get(cat_key, QIcon()),
                on_click=lambda c=cat_key: self._select_category(c),
            )
            sidebar_layout.addWidget(btn)
            self._cat_buttons[cat_key] = btn
            btn.raise_()

        sidebar_layout.addStretch()
        QTimer.singleShot(0, self._sync_sidebar_highlight)

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

    def _build_content(self, parent_layout):
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)

        self._view_stack = QWidget()
        bg_decor_path = P.get("background_decor_path")
        bg_wallpaper_path = P.get("background_wallpaper_path")
        self._view_stack.setStyleSheet(
            "background: transparent;"
            if bg_decor_path or bg_wallpaper_path
            else f"background: {_theme_qss_bg('window_bg', 'bg_dark')};"
        )
        self._view_stack_layout = QVBoxLayout(self._view_stack)
        self._view_stack_layout.setContentsMargins(0, 0, 0, 0)
        self._view_stack_layout.setSpacing(0)
        self._content_layout.addWidget(self._view_stack, 1)

        parent_layout.addWidget(self._content, 1)
        self._sync_background_wallpaper()
        self._sync_background_decoration()

    def _sync_background_wallpaper(self):
        if not hasattr(self, "_view_stack"):
            return

        rel_path = P.get("background_wallpaper_path")
        if not rel_path:
            if self._background_wallpaper_label is not None:
                self._background_wallpaper_label.hide()
            return

        full_path = None
        if rel_path:
            full_path = app_path(*rel_path.replace("\\", "/").split("/"))
            if self._background_wallpaper_source is None or self._background_wallpaper_path != full_path:
                source = QPixmap(full_path)
                if source.isNull():
                    return
                self._background_wallpaper_source = source
                self._background_wallpaper_path = full_path

        if (
            self._background_wallpaper_label is not None
            and self._background_wallpaper_label.parent() is not self._view_stack
        ):
            self._background_wallpaper_label.deleteLater()
            self._background_wallpaper_label = None

        if self._background_wallpaper_label is None:
            self._background_wallpaper_label = QLabel(self._view_stack)
            self._background_wallpaper_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._background_wallpaper_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self._background_wallpaper_label.setAutoFillBackground(False)
            self._background_wallpaper_label.setStyleSheet("background: transparent; border: none;")
            effect = QGraphicsOpacityEffect(self._background_wallpaper_label)
            self._background_wallpaper_label.setGraphicsEffect(effect)
        else:
            effect = self._background_wallpaper_label.graphicsEffect()

        opacity = max(0.0, min(1.0, _theme_float("background_wallpaper_opacity", 1.0)))
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(opacity)

        view_size = self._view_stack.size()
        if view_size.width() <= 1 or view_size.height() <= 1:
            QTimer.singleShot(0, self._sync_background_wallpaper)
            return

        scaled = self._background_wallpaper_source.scaled(
            view_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - view_size.width()) // 2)
        y = max(0, (scaled.height() - view_size.height()) // 2)
        cropped = scaled.copy(x, y, view_size.width(), view_size.height())
        self._background_wallpaper_label.setPixmap(cropped)
        self._background_wallpaper_label.resize(view_size)
        self._background_wallpaper_label.move(0, 0)
        self._background_wallpaper_label.lower()
        self._background_wallpaper_label.show()

    def _schedule_background_sync(self):
        QTimer.singleShot(0, self._sync_background_wallpaper)
        QTimer.singleShot(0, self._sync_background_decoration)
        QTimer.singleShot(60, self._sync_background_wallpaper)
        QTimer.singleShot(60, self._sync_background_decoration)

    def _sync_background_decoration(self):
        if not hasattr(self, "_view_stack"):
            return

        rel_path = P.get("background_decor_path")
        if not rel_path:
            if self._background_decor_label is not None:
                self._background_decor_label.hide()
            return

        full_path = app_path(*rel_path.replace("\\", "/").split("/"))
        if self._background_decor_source is None or self._background_decor_path != full_path:
            source = QPixmap(full_path)
            if source.isNull():
                return
            if P.get("background_decor_mirror", "") in {"horizontal", "both"}:
                source = source.transformed(QTransform().scale(-1, 1), Qt.TransformationMode.SmoothTransformation)
            if P.get("background_decor_mirror", "") in {"vertical", "both"}:
                source = source.transformed(QTransform().scale(1, -1), Qt.TransformationMode.SmoothTransformation)
            self._background_decor_source = source
            self._background_decor_path = full_path

        if self._background_decor_label is not None and self._background_decor_label.parent() is not self._view_stack:
            self._background_decor_label.deleteLater()
            self._background_decor_label = None

        if self._background_decor_label is None:
            self._background_decor_label = QLabel(self._view_stack)
            self._background_decor_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self._background_decor_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self._background_decor_label.setAutoFillBackground(False)
            self._background_decor_label.setStyleSheet("background: transparent; border: none;")
            effect = QGraphicsOpacityEffect(self._background_decor_label)
            self._background_decor_label.setGraphicsEffect(effect)
        else:
            effect = self._background_decor_label.graphicsEffect()

        opacity = max(0.0, min(1.0, _theme_float("background_decor_opacity", 0.18)))
        if isinstance(effect, QGraphicsOpacityEffect):
            effect.setOpacity(opacity)

        view_pos = self._view_stack.mapTo(self._central, QPoint(0, 0))
        view_size = self._view_stack.size()
        central_size = self._central.size()
        if view_size.width() <= 1 or view_size.height() <= 1 or central_size.width() <= 1:
            QTimer.singleShot(0, self._sync_background_decoration)
            return

        ratio = max(0.12, min(0.62, _theme_float("background_decor_width_ratio", 0.34)))
        max_size = _theme_int("background_decor_max_size", 430)
        min_size = _theme_int("background_decor_min_size", 250)
        target = min(max_size, max(min_size, int(view_size.width() * ratio), int(view_size.height() * 0.52)))
        pixmap = self._background_decor_source.scaled(
            QSize(target, target),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._background_decor_label.setPixmap(pixmap)
        self._background_decor_label.resize(pixmap.size())
        margin = _theme_int("background_decor_margin", 22)
        x = view_pos.x() + view_size.width() - pixmap.width() - margin
        bottom_limit = view_pos.y() + view_size.height()
        guide_visible = (
            self._settings.get("show_guide", True)
            and hasattr(self, "_char_bottom")
            and self._char_bottom is not None
            and self._char_bottom.isVisible()
        )
        if guide_visible:
            bottom_limit = self._char_bottom.mapTo(self._central, QPoint(0, 0)).y()
            y_offset = _theme_int("background_decor_y_offset", 34)
        else:
            bottom_limit = central_size.height()
            y_offset = _theme_int("background_decor_no_guide_y_offset", 74)
        y = bottom_limit - pixmap.height() - margin + y_offset
        self._background_decor_label.move(max(0, x - view_pos.x()), max(0, y - view_pos.y()))
        self._background_decor_label.lower()
        self._background_decor_label.show()

    def _build_cat_frame(self, cat_key):
        if cat_key == self._SECRET_CAT:
            return self._build_secret_frame()

        i18n_key = self._category_i18n_key(cat_key)
        tool_rows = (
            self._favorite_tool_rows()
            if cat_key == "FAVORITES"
            else self._enabled_tool_rows_for_category(cat_key)
        )
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
        title_lbl.setFont(ui_font(TypeSize.DISPLAY, QFont.Weight.Bold))
        _make_label_background_transparent(title_lbl)
        title_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent; border: none;")
        header_row.addWidget(title_lbl)

        header_row.addStretch()

        subtitle_lbl = QLabel(self.t("tools_avail", n=len(tool_rows)))
        subtitle_lbl.setFont(ui_font(TypeSize.LABEL))
        _make_label_background_transparent(subtitle_lbl)
        subtitle_lbl.setStyleSheet(f"color: {P['text_dim']}; background: transparent; border: none;")
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(subtitle_lbl)

        frame_layout.addLayout(header_row)

        # Scrollable grid of tool cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_home_grid_scrollarea())
        scroll_content = QWidget()
        scroll_content.setMinimumWidth(0)
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

    def _build_empty_catalog_frame(self):
        frame = QWidget()
        frame.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(28, 28, 28, 28)
        card = make_empty_state(
            frame,
            title=self.t("tools_visibility_empty_title"),
            text=self.t("tools_visibility_empty_hint"),
            icon_name="fa6s.sliders",
        )
        layout.addStretch()
        layout.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        return frame

    def _build_secret_frame(self):
        frame = QWidget()
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(28, 16, 28, 4)
        header_row.setSpacing(0)

        title_lbl = QLabel("Pillarmen ass hair")
        title_lbl.setFont(ui_font(TypeSize.DISPLAY, QFont.Weight.Bold))
        _make_label_background_transparent(title_lbl)
        title_lbl.setStyleSheet(f"color: {P['accent']}; background: transparent; border: none;")
        header_row.addWidget(title_lbl)
        header_row.addStretch()
        frame_layout.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(ss_home_grid_scrollarea())
        scroll_content = QWidget()
        scroll_content.setMinimumWidth(0)
        scroll_content.setStyleSheet("background: transparent;")
        grid = QGridLayout(scroll_content)
        grid.setContentsMargins(20, 8, 20, 16)
        grid.setSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)

        card = ToolCard(
            scroll_content,
            "Johhny walking-nator",
            self._computer_name(),
            icon_credits_star(size=20),
            "Johhny walking-nator",
            on_activate=self._start_johhny_sequence,
        )
        grid.addWidget(card, 0, 0)

        scroll.setWidget(scroll_content)
        frame_layout.addWidget(scroll, 1)
        return frame

    def _load_portrait(self, rel_path, size=64, corner_radius=10, border_width=2, draw_border=True):
        from PIL import Image, ImageDraw, ImageChops
        full_path = app_path(rel_path)
        if not os.path.exists(full_path):
            return None
        img = Image.open(full_path).convert("RGBA").resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=corner_radius, fill=255)
        img_alpha = img.split()[3]
        combined = ImageChops.multiply(mask, img_alpha)
        if draw_border:
            result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            result.paste(img, mask=combined)
            bd = ImageDraw.Draw(result)
            for i in range(border_width):
                bd.rounded_rectangle(
                    [i, i, size - 1 - i, size - 1 - i],
                    radius=max(1, corner_radius - i),
                    outline=P["secondary"], width=1,
                )
        else:
            result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            result.paste(img, mask=combined)
        return _pil_to_qpixmap(result)

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
        bottom.setStyleSheet(f"background-color: {P.get('guide_panel_bg', P['bg_panel'])};")
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
        bubble_radius = P.get("guide_bubble_radius", "12px")
        bubble.setStyleSheet(
            f"background-color: {P['bg_card']}; border-radius: {bubble_radius}; "
            f"border: 1px solid {P['border']};"
        )
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(18, 14, 18, 14)

        self._char_name_label = QLabel(self.t("hover_hint"))
        self._char_name_label.setFont(ui_font(TypeSize.BODY, QFont.Weight.Bold))
        self._char_name_label.setStyleSheet(f"color: {P['accent']}; background: transparent; border: none;")
        bubble_layout.addWidget(self._char_name_label)

        self._char_quote_label = QLabel(self.t("hover_default"))
        self._char_quote_label.setFont(ui_font(TypeSize.BODY))
        self._char_quote_label.setStyleSheet(f"color: {P['text_sec']}; background: transparent; border: none;")
        self._char_quote_label.setWordWrap(True)
        bubble_layout.addWidget(self._char_quote_label)

        inner_layout.addWidget(bubble, 1)

        self._root_layout.addWidget(bottom)

        self._char_accent_bottom = QFrame()
        self._char_accent_bottom.setFixedHeight(2)
        self._char_accent_bottom.setStyleSheet(f"background-color: {P['accent_dim']};")
        self._root_layout.addWidget(self._char_accent_bottom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_header_layout()
        self._sync_background_wallpaper()
        self._sync_background_decoration()
        self._reposition_portrait()
        self._center_johhny_overlay()
        if hasattr(self, "_resize_death13_overlay"):
            self._resize_death13_overlay()
        if hasattr(self, "_resize_white_album_overlay"):
            self._resize_white_album_overlay()
        if hasattr(self, "_reposition_unlock_toasts"):
            self._reposition_unlock_toasts()

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
        if hasattr(self, "_char_accent_bottom"):
            self._char_accent_bottom.hide()
        if hasattr(self, "_avatar_label") and self._avatar_label:
            self._avatar_label.hide()
        self._schedule_background_sync()
        if hasattr(self, "_reposition_unlock_toasts"):
            self._reposition_unlock_toasts()

    def _show_char_panel(self):
        if hasattr(self, "_char_bottom"):
            self._char_bottom.show()
        if hasattr(self, "_char_sep"):
            self._char_sep.show()
        if hasattr(self, "_char_accent_bottom"):
            self._char_accent_bottom.show()
        if hasattr(self, "_avatar_label") and self._avatar_label:
            self._avatar_label.show()
            self._reposition_portrait()
        self._schedule_background_sync()
        if hasattr(self, "_reposition_unlock_toasts"):
            self._reposition_unlock_toasts()

    def _set_sidebar_buttons_hidden(self, hidden: bool):
        for btn in getattr(self, "_cat_buttons", {}).values():
            btn.setVisible(not hidden)
        highlight = getattr(self, "_sidebar_highlight", None)
        if highlight is not None:
            highlight.setVisible(not hidden and self._current_cat in self._cat_buttons)

    def _sync_sidebar_highlight(self):
        self._move_sidebar_highlight(self._current_cat, animate=False)

    def _move_sidebar_highlight(self, cat_key, animate=True):
        highlight = getattr(self, "_sidebar_highlight", None)
        btn = getattr(self, "_cat_buttons", {}).get(cat_key)
        if highlight is None or btn is None or not btn.isVisible():
            if highlight is not None:
                highlight.hide()
            return

        anim = getattr(self, "_sidebar_highlight_anim", None)
        if anim:
            try:
                anim.stop()
                anim.deleteLater()
            except RuntimeError:
                pass
            self._sidebar_highlight_anim = None

        target_pos = QPoint(0, btn.y())
        was_visible = highlight.isVisible()
        highlight.setFixedSize(btn.parentWidget().width(), btn.height())
        highlight.show()
        highlight.lower()
        for item in getattr(self, "_cat_buttons", {}).values():
            item.raise_()

        if (
            not animate
            or not self._sidebar_highlight_animation_enabled()
            or not was_visible
            or highlight.pos() == target_pos
        ):
            highlight.move(target_pos)
            return

        anim = QPropertyAnimation(highlight, b"pos", self)
        anim.setDuration(170)
        anim.setStartValue(highlight.pos())
        anim.setEndValue(target_pos)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._sidebar_highlight_anim = anim

        def clear_anim():
            if self._sidebar_highlight_anim is anim:
                self._sidebar_highlight_anim = None
            try:
                anim.deleteLater()
            except RuntimeError:
                pass

        anim.finished.connect(clear_anim)
        anim.start()

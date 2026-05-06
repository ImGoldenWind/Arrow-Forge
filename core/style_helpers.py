"""core/style_helpers.py – Centralised QSS style helpers for every editor widget.

ALL UI elements project-wide must use only the functions defined here.
No inline colour strings or duplicated QSS blocks are permitted in editor files.

Every function reads from the live ``P`` palette and must be called at
widget-construction time (not at module-import time) so theme switches
are reflected correctly.

Usage
    from core.style_helpers import (
        ss_btn, ss_input, ss_table, ss_textedit, ss_listwidget,
        ss_toolbar, ss_dialog, ss_panel, ss_scrollarea,
        ss_sep, ss_accent_sep, ss_sidebar_frame,
        TOOLBAR_H, TOOLBAR_BTN_H, TOOLBAR_SEP_H,
    )
"""
from core.themes import P

# Layout constants
TOOLBAR_H     = 46   # editor toolbar frame height (px)
TOOLBAR_BTN_H = 30   # standard toolbar button height (px)
TOOLBAR_SEP_H = 26   # vertical separator height inside toolbar (px)


# Buttons

def ss_btn(accent: bool = False, danger: bool = False) -> str:
    """Toolbar / action button.

    accent=True  →  primary / global-action button (load, save).
                    Always accent-coloured; disabled state shows P['mid'].
    danger=True  →  destructive action (delete).  Normal background, red hover.
    (default)    →  editor-specific / secondary button.  Neutral background.

    Hierarchy rule
    * Accent  → global actions: Open File, Save File, primary panel actions.
    * Neutral → editor-specific actions: Add, Duplicate, Move, editor actions.
    * Danger  → destructive actions: Delete, Remove.
    """
    if danger:
        return (
            f"QPushButton {{ background-color: {P['mid']}; color: {P['text_main']}; border: none; "
            f"border-radius: 6px; padding: 3px 10px; }}"
            f"QPushButton:hover {{ background-color: {P['accent_dim']}; color: {P['bg_dark']}; }}"
            f"QPushButton:disabled {{ background-color: {P['mid']}; color: {P['text_dim']}; }}"
        )
    if accent:
        return (
            f"QPushButton {{ background-color: {P['accent']}; color: {P['bg_dark']}; border: none; "
            f"border-radius: 6px; font-weight: bold; padding: 3px 10px; }}"
            f"QPushButton:hover {{ background-color: {P['accent_dim']}; }}"
            f"QPushButton:disabled {{ background-color: {P['mid']}; color: {P['text_dim']}; }}"
        )
    return (
        f"QPushButton {{ background-color: {P['mid']}; color: {P['text_main']}; border: none; "
        f"border-radius: 6px; padding: 3px 10px; }}"
        f"QPushButton:hover {{ background-color: {P['accent_dim']}; color: {P['bg_dark']}; }}"
        f"QPushButton:disabled {{ background-color: {P['mid']}; color: {P['text_dim']}; }}"
    )


def ss_toggle_btn() -> str:
    """Checkable tool/action button."""
    return (
        f"QPushButton {{ background-color: {P['mid']}; color: {P['text_main']}; border: none; "
        f"border-radius: 6px; padding: 3px 8px; }}"
        f"QPushButton:checked {{ background-color: {P['accent']}; color: {P['bg_dark']}; font-weight: bold; }}"
        f"QPushButton:hover {{ background-color: {P['accent_dim']}; color: {P['bg_dark']}; }}"
    )


# Inputs

def ss_input() -> str:
    """QLineEdit, QSpinBox, QDoubleSpinBox, and QComboBox — unified."""
    return (
        f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{"
        f"  background-color: {P['bg_card']}; color: {P['text_main']}; "
        f"  border: 1px solid {P['border']}; border-radius: 4px; padding: 3px 6px; }}"
        f"QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{"
        f"  border: 1px solid {P['accent']}; }}"
        f"QSpinBox::up-button, QSpinBox::down-button, "
        f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{"
        f"  width: 0; height: 0; border: none; }}"
        f"QComboBox::drop-down {{ background: {P['mid']}; border: none; width: 20px; }}"
        f"QComboBox QAbstractItemView {{ background: {P['bg_card']}; color: {P['text_main']}; "
        f"  selection-background-color: {P['accent']}; selection-color: {P['bg_dark']}; }}"
    )


def ss_search() -> str:
    """QLineEdit used as a search / filter box in sidebars."""
    return (
        f"QLineEdit {{ background-color: {P['bg_card']}; border: 1px solid {P['border']}; "
        f"color: {P['text_main']}; padding: 2px 6px; border-radius: 4px; }}"
        f"QLineEdit:focus {{ border: 1px solid {P['accent']}; }}"
    )


def ss_textedit() -> str:
    """QTextEdit."""
    return (
        f"QTextEdit {{ background-color: {P['bg_card']}; color: {P['text_main']}; "
        f"border: 1px solid {P['border']}; border-radius: 4px; padding: 4px; }}"
        f"QTextEdit:focus {{ border: 1px solid {P['accent']}; }}"
    )


# Tables & lists

def ss_table() -> str:
    """QTableWidget including internal scrollbars (10 px width)."""
    return (
        f"QTableWidget {{ background-color: {P['bg_card']}; color: {P['text_main']}; "
        f"gridline-color: {P['border']}; border: none; outline: none; }}"
        f"QTableWidget::item {{ padding: 3px 6px; border: none; }}"
        f"QTableWidget::item:selected {{ background-color: {P['accent']}; color: {P['bg_dark']}; }}"
        f"QHeaderView::section {{ background-color: {P['bg_panel']}; color: {P['text_sec']}; "
        f"border: 1px solid {P['border']}; padding: 4px 6px; font-weight: bold; }}"
        f"QScrollBar:vertical {{ background: {P['bg_panel']}; width: 10px; }}"
        f"QScrollBar::handle:vertical {{ background: {P['mid']}; border-radius: 5px; min-height: 20px; }}"
        f"QScrollBar:horizontal {{ background: {P['bg_panel']}; height: 10px; }}"
        f"QScrollBar::handle:horizontal {{ background: {P['mid']}; border-radius: 5px; }}"
    )


def ss_listwidget() -> str:
    """QListWidget."""
    return (
        f"QListWidget {{ background-color: {P['bg_card']}; color: {P['text_main']}; "
        f"border: 1px solid {P['border']}; border-radius: 4px; outline: none; }}"
        f"QListWidget::item {{ padding: 4px 8px; }}"
        f"QListWidget::item:selected {{ background-color: {P['accent']}; color: {P['bg_dark']}; }}"
        f"QListWidget::item:hover {{ background-color: {P['mid']}; }}"
    )


# Containers

def ss_toolbar() -> str:
    """Background + bottom separator for QFrame toolbars."""
    return f"background-color: {P['bg_panel']}; border-bottom: 1px solid {P['border']};"


def ss_bg_dark() -> str:
    """Plain bg_dark background for editor root/content widgets."""
    return f"background-color: {P['bg_dark']};"


def ss_bg_panel() -> str:
    """Plain bg_panel background for toolbars and sidebars."""
    return f"background-color: {P['bg_panel']};"


def ss_transparent() -> str:
    """Transparent widget background."""
    return "background: transparent;"


def ss_panel() -> str:
    """Standard editor section panel (rounded card on bg_panel)."""
    return f"QFrame {{ background-color: {P['bg_panel']}; border-radius: 10px; }}"


def _rgba(hex_color: str, alpha: int) -> str:
    """Convert a #RRGGBB palette colour to rgba() for translucent overlays."""
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return hex_color
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def ss_blocking_overlay() -> str:
    """Full-editor modal overlay that blocks input during long tasks."""
    return f"QFrame#BlockingOverlay {{ background-color: {_rgba(P['bg_dark'], 218)}; }}"


def ss_blocking_overlay_card() -> str:
    """Centered status card inside a blocking overlay."""
    return (
        f"QFrame#BlockingOverlayCard {{ background-color: {P['bg_panel']}; "
        f"border: 1px solid {P['border_hov']}; border-radius: 8px; }}"
    )


def ss_progressbar() -> str:
    """Compact determinate progress bar for long-running editor operations."""
    return (
        f"QProgressBar {{ background-color: {P['bg_card']}; color: {P['text_main']}; "
        f"border: 1px solid {P['border']}; border-radius: 5px; text-align: center; "
        f"height: 12px; }}"
        f"QProgressBar::chunk {{ background-color: {P['accent']}; border-radius: 4px; }}"
    )


def ss_entry_card(selected: bool = False) -> str:
    """Editable entry card used in card-based editors."""
    border = P['accent'] if selected else P['bg_panel']
    return (
        f"QFrame {{ background-color: {P['bg_panel']}; border: 1px solid {border}; "
        f"border-radius: 10px; }}"
        f"QFrame:hover {{ border: 1px solid {P['border_hov']}; }}"
    )


def ss_tool_card(hover: bool = False) -> str:
    """Home-screen tool card."""
    bg = P['bg_card_hov'] if hover else P['bg_card']
    border = P['border_hov'] if hover else P['border']
    return (
        f"ToolCard {{ background-color: {bg}; border-radius: 8px; "
        f"border: 1px solid {border}; }}"
    )


def ss_sidebar_frame() -> str:
    """Left sidebar container frame."""
    return f"QFrame {{ background-color: {P['bg_panel']}; }}"


def ss_scrollarea() -> str:
    """QScrollArea with standard scrollbar styling.

    Use for the main editor scroll area.  Background is bg_dark.
    For transparent / sidebar scroll areas use ``ss_scrollarea_transparent()``.
    """
    return (
        f"QScrollArea {{ background-color: {P['bg_dark']}; border: none; }}"
        f"QScrollBar:vertical {{ background: {P['bg_panel']}; width: 10px; border-radius: 5px; }}"
        f"QScrollBar::handle:vertical {{ background: {P['mid']}; border-radius: 5px; min-height: 20px; }}"
        f"QScrollBar::handle:vertical:hover {{ background: {P['accent_dim']}; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}"
        f"QScrollBar:horizontal {{ background: {P['bg_panel']}; height: 10px; border-radius: 5px; }}"
        f"QScrollBar::handle:horizontal {{ background: {P['mid']}; border-radius: 5px; }}"
        f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; }}"
    )


def ss_scrollarea_transparent() -> str:
    """QScrollArea with transparent background (for sidebars / overlaid areas)."""
    return (
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
        f"QScrollBar::handle:vertical {{ background: {P['mid']}; border-radius: 3px; min-height: 20px; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}"
    )


def ss_home_grid_scrollarea() -> str:
    """Scrollable home-screen tool grid."""
    return (
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


# Separators

def ss_sep() -> str:
    """Inline style string for a 1 px neutral divider (setStyleSheet on QFrame)."""
    return f"background-color: {P['mid']};"


def ss_accent_sep() -> str:
    """Inline style string for a 2 px accent separator below the toolbar."""
    return f"background-color: {P['accent_dim']};"


# Sidebar entry buttons

def ss_sidebar_btn(selected: bool = False) -> str:
    """Sidebar list entry button (transparent background, hover highlight).

    selected=True  → active entry uses bg_card background.
    """
    bg = P['bg_card'] if selected else "transparent"
    return (
        f"QPushButton {{ background-color: {bg}; border-radius: 6px; "
        f"text-align: left; padding: 0px; border: none; }}"
        f"QPushButton:hover {{ background-color: {P['bg_card_hov']}; }}"
    )


def ss_tool_favorite_btn(checked: bool = False) -> str:
    """Small favorite toggle button overlaid on a home-screen tool card."""
    color = P['accent'] if checked else P['text_dim']
    hover_color = P['accent'] if checked else P['text_main']
    bg = P['mid'] if checked else P['bg_panel']
    hover_bg = P['bg_card_hov']
    return (
        f"QPushButton {{ background-color: {bg}; color: {color}; border: 1px solid {P['border']}; "
        f"border-radius: 6px; padding: 0px; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_color}; "
        f"border: 1px solid {P['border_hov']}; }}"
        f"QPushButton:checked {{ background-color: {P['mid']}; color: {P['accent']}; "
        f"border: 1px solid {P['accent']}; }}"
    )


# Labels (style strings only, not widgets)

def ss_section_label() -> str:
    """Style for section header QLabel (secondary colour, transparent bg)."""
    return f"color: {P['secondary']}; background: transparent;"


def ss_field_label() -> str:
    """Style for field-name QLabel above an input (muted secondary colour)."""
    return f"color: {P['text_sec']}; background: transparent;"


def ss_main_label() -> str:
    """Normal emphasis QLabel style."""
    return f"color: {P['text_main']}; background: transparent;"


def ss_tool_file_hint_label() -> str:
    """File hint label inside a home-screen tool card."""
    return f"color: {P['text_file']}; background: transparent; border: none;"


def ss_accent_label() -> str:
    """Accent emphasis QLabel style."""
    return f"color: {P['accent']}; background: transparent;"


def ss_dim_label() -> str:
    """Dim / hint QLabel style."""
    return f"color: {P['text_dim']}; background: transparent;"


def ss_placeholder() -> str:
    """Placeholder label when no file is loaded (dim, transparent)."""
    return f"color: {P['text_dim']}; background-color: transparent;"


def ss_file_label() -> str:
    """Loaded filename display label in toolbar."""
    return f"color: {P['text_dim']}; background: transparent;"


def ss_file_label_loaded() -> str:
    """Loaded filename display label in toolbar with normal text emphasis."""
    return f"color: {P['text_main']}; background: transparent;"


def ss_file_label_dirty() -> str:
    """Loaded filename display label when the file has unsaved changes."""
    return f"color: {P['accent']}; background: transparent; font-weight: bold;"


def ss_error_label() -> str:
    """Error/status label style using the active theme's warning-like accent."""
    return f"color: {P['accent_dim']}; background: transparent;"


def ss_slider() -> str:
    """Horizontal QSlider with themed groove, handle, and filled sub-page."""
    return (
        f"QSlider::groove:horizontal {{ background: {P['mid']}; height: 6px; border-radius: 3px; }}"
        f"QSlider::handle:horizontal {{ background: {P['accent']}; width: 16px; margin: -5px 0; "
        f"border-radius: 8px; }}"
        f"QSlider::handle:horizontal:hover {{ background: {P['accent_dim']}; }}"
        f"QSlider::sub-page:horizontal {{ background: {P['accent_dim']}; border-radius: 3px; }}"
    )


def ss_gradient_slider(track_background: str) -> str:
    """Horizontal QSlider with a caller-provided gradient/track background."""
    return (
        f"QSlider::groove:horizontal {{ height: 10px; background: {track_background}; "
        f"border-radius: 5px; border: 1px solid {P['border']}; }}"
        f"QSlider::handle:horizontal {{ background: {P['bg_panel']}; width: 14px; height: 14px; "
        f"margin: -3px 0; border-radius: 7px; border: 2px solid {P['mid']}; }}"
        f"QSlider::handle:horizontal:hover {{ border-color: {P['accent']}; }}"
        f"QSlider::sub-page:horizontal {{ background: transparent; }}"
        f"QSlider::add-page:horizontal {{ background: transparent; }}"
    )


def ss_audio_format_badge(fmt: str) -> str:
    """Small transparent audio-format badge for AWB entry rows."""
    color = P['accent'] if fmt == "HCA" else (P['secondary'] if fmt == "ADX" else P['text_dim'])
    return f"color: {color}; background: transparent;"


# Checkboxes

def ss_check() -> str:
    """QCheckBox with themed indicator — used in card-based editors."""
    return (
        f"QCheckBox {{ color: {P['text_main']}; spacing: 6px; background: transparent; }}"
        f"QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {P['border']}; "
        f"border-radius: 3px; background: {P['bg_card']}; }}"
        f"QCheckBox::indicator:checked {{ background: {P['accent']}; border-color: {P['accent']}; }}"
    )


# Dialogs

def ss_dialog() -> str:
    """Base background/text for QDialog windows."""
    return f"background-color: {P['bg_panel']}; color: {P['text_main']};"


# Tab widgets

def ss_tab_widget() -> str:
    """QTabWidget with rounded-top-corner background-based tab styling."""
    return (
        f"QTabWidget::pane {{ border: none; background: {P['bg_dark']}; }}"
        f"QTabBar::tab {{ background: {P['bg_panel']}; color: {P['text_dim']}; "
        f"padding: 6px 16px; margin-right: 2px; border-radius: 4px 4px 0 0; }}"
        f"QTabBar::tab:selected {{ background: {P['mid']}; color: {P['accent']}; }}"
        f"QTabBar::tab:hover {{ color: {P['text_main']}; }}"
    )


def ss_tab_bar() -> str:
    """Standalone QTabBar styled like editor tab strips."""
    return (
        f"QTabBar {{ background: transparent; }}"
        f"QTabBar::tab {{ background: {P['bg_panel']}; color: {P['text_dim']}; "
        f"padding: 6px 16px; margin-right: 2px; border-radius: 4px 4px 0 0; }}"
        f"QTabBar::tab:selected {{ background: {P['mid']}; color: {P['accent']}; }}"
        f"QTabBar::tab:hover {{ color: {P['text_main']}; }}"
    )

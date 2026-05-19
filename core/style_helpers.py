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


def _palette_int(key: str, default: int) -> int:
    try:
        return int(float(P.get(key, default)))
    except (TypeError, ValueError):
        return default


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
    radius = P.get("button_radius", "6px")
    border = P.get("button_border", "none")
    button_fg = P.get("button_text", P["text_main"])
    if danger:
        hover_bg = P.get("button_danger_hover", P["accent_dim"])
        hover_fg = P.get("button_danger_hover_text", P.get("button_hover_text", P["bg_dark"]))
        return (
            f"QPushButton {{ background-color: {P['mid']}; color: {button_fg}; border: {border}; "
            f"border-radius: {radius}; padding: 3px 10px; }}"
            f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; }}"
            f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; }}"
            f"QPushButton:pressed {{ background-color: {P.get('bg_card_hov', P['mid'])}; padding-top: 4px; padding-bottom: 2px; }}"
            f"QPushButton:disabled {{ background-color: {P['mid']}; color: {P['text_dim']}; }}"
        )
    if accent:
        hover_bg = P.get("button_accent_hover", P["accent_dim"])
        accent_fg = P.get("button_accent_text", P["bg_dark"])
        hover_fg = P.get("button_accent_hover_text", accent_fg)
        return (
            f"QPushButton {{ background-color: {P['accent']}; color: {accent_fg}; border: {border}; "
            f"border-radius: {radius}; font-weight: bold; padding: 3px 10px; }}"
            f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; }}"
            f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; }}"
            f"QPushButton:pressed {{ background-color: {P.get('button_accent_pressed', hover_bg)}; padding-top: 4px; padding-bottom: 2px; }}"
            f"QPushButton:disabled {{ background-color: {P['mid']}; color: {P['text_dim']}; }}"
        )
    hover_bg = P.get("button_hover", P["accent_dim"])
    hover_fg = P.get("button_hover_text", P["bg_dark"])
    return (
        f"QPushButton {{ background-color: {P['mid']}; color: {button_fg}; border: {border}; "
        f"border-radius: {radius}; padding: 3px 10px; }}"
        f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; }}"
        f"QPushButton:pressed {{ background-color: {P.get('bg_card_hov', P['mid'])}; padding-top: 4px; padding-bottom: 2px; }}"
        f"QPushButton:disabled {{ background-color: {P['mid']}; color: {P['text_dim']}; }}"
    )


def ss_toggle_btn() -> str:
    """Checkable tool/action button."""
    radius = P.get("button_radius", "6px")
    border = P.get("button_border", "none")
    button_fg = P.get("button_text", P["text_main"])
    hover_bg = P.get("button_hover", P["accent_dim"])
    hover_fg = P.get("button_hover_text", P["bg_dark"])
    return (
        f"QPushButton {{ background-color: {P['mid']}; color: {button_fg}; border: {border}; "
        f"border-radius: {radius}; padding: 3px 8px; }}"
        f"QPushButton:checked {{ background-color: {P['accent']}; color: {P.get('button_accent_text', P['bg_dark'])}; font-weight: bold; }}"
        f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; }}"
    )


# Inputs

def ss_input() -> str:
    """QLineEdit, QSpinBox, QDoubleSpinBox, and QComboBox — unified."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    focus = P.get("input_focus_border", P["accent"])
    radius = P.get("input_radius", "4px")
    padding = P.get("input_padding", "3px 6px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    return (
        f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{"
        f"  background-color: {bg}; color: {P['text_main']}; "
        f"  border: 1px solid {border}; border-radius: {radius}; padding: {padding}; "
        f"  selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{"
        f"  background-color: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{"
        f"  border: 1px solid {focus}; background-color: {P.get('input_focus_bg', P.get('bg_card_hov', bg))}; }}"
        f"QSpinBox::up-button, QSpinBox::down-button, "
        f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{"
        f"  width: 0; height: 0; border: none; }}"
        f"QComboBox::drop-down {{ background: {P['mid']}; border: none; width: 20px; }}"
        f"QComboBox QAbstractItemView {{ background: {bg}; color: {P['text_main']}; "
        f"  selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
    )


def ss_search() -> str:
    """QLineEdit used as a search / filter box in sidebars."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    focus = P.get("input_focus_border", P["accent"])
    radius = P.get("input_radius", "4px")
    padding = P.get("input_padding", "2px 6px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    return (
        f"QLineEdit {{ background-color: {bg}; border: 1px solid {border}; "
        f"color: {P['text_main']}; padding: {padding}; border-radius: {radius}; "
        f"selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QLineEdit:hover {{ background-color: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QLineEdit:focus {{ border: 1px solid {focus}; background-color: {P.get('input_focus_bg', P.get('bg_card_hov', bg))}; }}"
    )


def ss_textedit() -> str:
    """QTextEdit."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    focus = P.get("input_focus_border", P["accent"])
    radius = P.get("input_radius", "4px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    return (
        f"QTextEdit {{ background-color: {bg}; color: {P['text_main']}; "
        f"border: 1px solid {border}; border-radius: {radius}; padding: 4px; "
        f"selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QTextEdit:hover {{ background-color: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QTextEdit:focus {{ border: 1px solid {focus}; background-color: {P.get('input_focus_bg', P.get('bg_card_hov', bg))}; }}"
        f"{ss_scrollbars(bg)}"
    )


# Tables & lists

def ss_table() -> str:
    """QTableWidget/QTableView including internal scrollbars (10 px width)."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    header_bg = P.get("table_header_bg", P["bg_panel"])
    header_text = P.get("table_header_text", P["text_sec"])
    return (
        f"QTableWidget, QTableView {{ background-color: {bg}; color: {P['text_main']}; "
        f"gridline-color: {border}; border: none; outline: none; }}"
        f"QTableWidget::item, QTableView::item {{ padding: 3px 6px; border: none; }}"
        f"QTableWidget::item:selected, QTableView::item:selected {{ background-color: {selection_bg}; color: {selection_text}; }}"
        f"QTableWidget::item:hover, QTableView::item:hover {{ background-color: {P.get('list_hover_bg', P['mid'])}; }}"
        f"QHeaderView::section {{ background-color: {header_bg}; color: {header_text}; "
        f"border: 1px solid {border}; padding: 4px 6px; font-weight: bold; }}"
        f"{ss_scrollbars(header_bg)}"
    )


def ss_listwidget() -> str:
    """QListWidget."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    radius = P.get("input_radius", "4px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    hover_bg = P.get("list_hover_bg", P["mid"])
    return (
        f"QListWidget {{ background-color: {bg}; color: {P['text_main']}; "
        f"border: 1px solid {border}; border-radius: {radius}; outline: none; }}"
        f"QListWidget::item {{ padding: 4px 8px; }}"
        f"QListWidget::item:selected {{ background-color: {selection_bg}; color: {selection_text}; }}"
        f"QListWidget::item:hover {{ background-color: {hover_bg}; }}"
        f"{ss_scrollbars(bg)}"
    )


# Containers

def ss_toolbar() -> str:
    """Background + bottom separator for QFrame toolbars."""
    return f"background-color: {P.get('toolbar_bg', P['bg_panel'])}; border-bottom: 1px solid {P['border']};"


def ss_bg_dark() -> str:
    """Plain bg_dark background for editor root/content widgets."""
    return f"background-color: {P['bg_dark']};"


def ss_bg_panel() -> str:
    """Plain bg_panel background for toolbars and sidebars."""
    return f"background-color: {P.get('toolbar_bg', P['bg_panel'])};"


def ss_transparent() -> str:
    """Transparent widget background."""
    return "background: transparent;"


def ss_video_matte() -> str:
    """Black matte background for letterboxed video preview surfaces."""
    return "background-color: #000000;"


def ss_panel() -> str:
    """Standard editor section panel (rounded card on bg_panel)."""
    bg = P.get("panel_card_bg", P["bg_panel"])
    border = P.get("panel_card_border", "transparent")
    radius = P.get("panel_card_radius", "10px")
    return (
        f"QFrame {{ background-color: {bg}; "
        f"border-radius: {radius}; border: 1px solid {border}; }}"
    )


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
    bg = P.get("settings_card_bg", P["bg_panel"])
    border = P.get("settings_card_border", P["border_hov"])
    radius = P.get("settings_card_radius", "8px")
    return (
        f"QFrame#BlockingOverlayCard {{ background-color: {bg}; "
        f"border: 1px solid {border}; border-radius: {radius}; }}"
    )


def ss_progressbar() -> str:
    """Compact determinate progress bar for long-running editor operations."""
    bg = P.get("progress_bg", P["bg_card"])
    border = P.get("progress_border", f"1px solid {P['border']}")
    radius = P.get("progress_radius", "5px")
    chunk = P.get("progress_chunk", P["accent"])
    chunk_radius = P.get("progress_chunk_radius", "4px")
    return (
        f"QProgressBar {{ background-color: {bg}; color: {P['text_main']}; "
        f"border: {border}; border-radius: {radius}; text-align: center; "
        f"height: 12px; }}"
        f"QProgressBar::chunk {{ background: {chunk}; border-radius: {chunk_radius}; }}"
    )


def ss_entry_card(selected: bool = False) -> str:
    """Editable entry card used in card-based editors."""
    bg = P.get("entry_card_bg", P.get("panel_card_bg", P["bg_panel"]))
    border = P.get("entry_card_selected_border", P["accent"]) if selected else P.get("entry_card_border", P["bg_panel"])
    radius = P.get("panel_card_radius", "10px")
    return (
        f"QFrame {{ background-color: {bg}; border: 1px solid {border}; "
        f"border-radius: {radius}; }}"
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
    return f"QFrame {{ background: {P.get('panel_bg', P['bg_panel'])}; }}"


def ss_vertical_scrollbar(
    track_color: str | None = None,
    *,
    handle_color: str | None = None,
    hover_color: str | None = None,
    pressed_color: str | None = None,
    width: int = 10,
    radius: int | None = None,
    min_height: int = 28,
) -> str:
    """Shared vertical scrollbar styling.

    ``track_color`` may be ``"transparent"`` or any palette/CSS colour.
    """
    track = P['bg_panel'] if track_color is None else track_color
    if track != "transparent":
        track = P.get("scrollbar_track", track)
    handle = P.get("scrollbar_handle", P['mid']) if handle_color is None else handle_color
    hover = P.get("scrollbar_handle_hover", P['accent_dim']) if hover_color is None else hover_color
    pressed = P.get("scrollbar_handle_pressed", P['accent']) if pressed_color is None else pressed_color
    r = _palette_int("scrollbar_radius", width // 2) if radius is None else radius
    border = P.get("scrollbar_border", "none")
    return (
        f"QScrollBar:vertical {{ background: {track}; width: {width}px; "
        f"border: {border}; border-radius: {r}px; margin: 2px 2px 2px 2px; }}"
        f"QScrollBar::handle:vertical {{ background: {handle}; border-radius: {max(1, r - 1)}px; "
        f"min-height: {min_height}px; }}"
        f"QScrollBar::handle:vertical:hover {{ background: {hover}; }}"
        f"QScrollBar::handle:vertical:pressed {{ background: {pressed}; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; background: transparent; }}"
        f"QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}"
    )


def ss_horizontal_scrollbar(
    track_color: str | None = None,
    *,
    handle_color: str | None = None,
    hover_color: str | None = None,
    pressed_color: str | None = None,
    height: int = 10,
    radius: int | None = None,
    min_width: int = 28,
) -> str:
    """Shared horizontal scrollbar styling."""
    track = P['bg_panel'] if track_color is None else track_color
    if track != "transparent":
        track = P.get("scrollbar_track", track)
    handle = P.get("scrollbar_handle", P['mid']) if handle_color is None else handle_color
    hover = P.get("scrollbar_handle_hover", P['accent_dim']) if hover_color is None else hover_color
    pressed = P.get("scrollbar_handle_pressed", P['accent']) if pressed_color is None else pressed_color
    r = _palette_int("scrollbar_radius", height // 2) if radius is None else radius
    border = P.get("scrollbar_border", "none")
    return (
        f"QScrollBar:horizontal {{ background: {track}; height: {height}px; "
        f"border: {border}; border-radius: {r}px; margin: 2px 2px 2px 2px; }}"
        f"QScrollBar::handle:horizontal {{ background: {handle}; border-radius: {max(1, r - 1)}px; "
        f"min-width: {min_width}px; }}"
        f"QScrollBar::handle:horizontal:hover {{ background: {hover}; }}"
        f"QScrollBar::handle:horizontal:pressed {{ background: {pressed}; }}"
        f"QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; background: transparent; }}"
        f"QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}"
    )


def ss_scrollbars(
    track_color: str | None = None,
    *,
    handle_color: str | None = None,
    hover_color: str | None = None,
    pressed_color: str | None = None,
    size: int = 10,
    include_horizontal: bool = True,
) -> str:
    """Vertical scrollbar plus optional matching horizontal scrollbar."""
    qss = ss_vertical_scrollbar(
        track_color,
        handle_color=handle_color,
        hover_color=hover_color,
        pressed_color=pressed_color,
        width=size,
    )
    if include_horizontal:
        qss += ss_horizontal_scrollbar(
            track_color,
            handle_color=handle_color,
            hover_color=hover_color,
            pressed_color=pressed_color,
            height=size,
        )
    return qss


def ss_scrollarea() -> str:
    """QScrollArea with standard scrollbar styling.

    Use for the main editor scroll area.  Background is bg_dark.
    For transparent / sidebar scroll areas use ``ss_scrollarea_transparent()``.
    """
    return (
        f"QScrollArea {{ background-color: {P['bg_dark']}; border: none; }}"
        f"{ss_scrollbars(P['bg_panel'])}"
    )


def ss_scrollarea_transparent() -> str:
    """QScrollArea with transparent background (for sidebars / overlaid areas)."""
    return (
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"{ss_vertical_scrollbar('transparent', width=8, hover_color=P['accent_dim'])}"
    )


def ss_page_scrollarea() -> str:
    """Transparent full-page scroll area used by settings/credits/home panels."""
    return (
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"{ss_vertical_scrollbar(P['bg_dark'], width=10, hover_color=P['secondary'])}"
    )


def ss_scrollarea_panel_edge() -> str:
    """Panel-coloured scroll area with a left separator."""
    bg = P.get("panel_bg", P["bg_panel"])
    return (
        f"QScrollArea {{ background: {bg}; border-left: 1px solid {P['border']}; }}"
        f"{ss_vertical_scrollbar(bg, width=8)}"
    )


def ss_scrollarea_card() -> str:
    """Card-framed scroll area for image/preview panes."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    radius = P.get("input_radius", "4px")
    return (
        f"QScrollArea {{ background: {bg}; border: 1px solid {border}; border-radius: {radius}; }}"
        f"{ss_scrollbars(P['bg_dark'], size=8)}"
    )


def ss_home_grid_scrollarea() -> str:
    """Scrollable home-screen tool grid."""
    return (
        f"QScrollArea {{ background: transparent; border: none; }}"
        f"{ss_vertical_scrollbar(P['bg_dark'], width=8, hover_color=P['secondary'])}"
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
    bg = P.get("sidebar_item_selected_bg", P['bg_card']) if selected else "transparent"
    hover = P.get("sidebar_item_hover_bg", P['bg_card_hov'])
    radius = P.get("sidebar_item_radius", "6px")
    return (
        f"QPushButton {{ background-color: {bg}; border-radius: {radius}; "
        f"text-align: left; padding: 0px; border: none; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
    )


def ss_tool_favorite_btn(checked: bool = False) -> str:
    """Small favorite toggle button overlaid on a home-screen tool card."""
    color = P['accent'] if checked else P['text_dim']
    hover_color = P['accent'] if checked else P['text_main']
    bg = P['mid'] if checked else P['bg_panel']
    hover_bg = P['bg_card_hov']
    radius = _palette_int("card_action_radius", 6)
    return (
        f"QPushButton {{ background-color: {bg}; color: {color}; border: 1px solid {P['border']}; "
        f"border-radius: {radius}px; padding: 0px; }}"
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
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    radius = P.get("checkbox_radius", "3px")
    return (
        f"QCheckBox {{ color: {P['text_main']}; spacing: 6px; background: transparent; }}"
        f"QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border}; "
        f"border-radius: {radius}; background: {bg}; }}"
        f"QCheckBox::indicator:hover {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; background: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QCheckBox::indicator:checked {{ background: {P['accent']}; border-color: {P['accent']}; }}"
    )


def ss_settings_card() -> str:
    """Rounded settings section card."""
    bg = P.get("settings_card_bg", P["bg_panel"])
    border = P.get("settings_card_border", P["border"])
    radius = P.get("settings_card_radius", "12px")
    return (
        f"QFrame {{ background-color: {bg}; border-radius: {radius}; "
        f"border: 1px solid {border}; }}"
    )


def ss_settings_check() -> str:
    """Large settings-page checkbox."""
    radius = P.get("checkbox_radius", "4px")
    return (
        f"QCheckBox {{ color: {P['text_main']}; border: none; spacing: 8px; background: transparent; }}"
        f"QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: {radius}; "
        f"border: 2px solid {P['secondary']}; background: transparent; }}"
        f"QCheckBox::indicator:hover {{ border: 2px solid {P.get('input_focus_border', P['accent'])}; background: {P.get('input_hover_bg', P['mid'])}; }}"
        f"QCheckBox::indicator:checked {{ background: {P['accent']}; border: 2px solid {P['accent']}; }}"
    )


def ss_locked_theme_name() -> str:
    """Settings theme name when the selector is still locked."""
    return f"color: {P['text_dim']}; border: none; background: transparent;"


def ss_theme_lock_button() -> str:
    """Small lock glyph replacing a radio indicator for locked themes."""
    return (
        f"QPushButton {{ background: transparent; color: {P['text_dim']}; border: none; "
        f"border-radius: 8px; padding: 0px; }}"
    )


def ss_unlock_toast() -> str:
    """Floating unlock notification."""
    bg = P.get("toast_bg", P.get("dialog_bg", P["bg_panel"]))
    border = P.get("toast_border", P["accent"])
    return (
        f"QFrame#UnlockToast {{ background-color: {bg}; border: 1px solid {border}; "
        f"border-radius: 10px; }}"
        f"QLabel#UnlockToastTitle {{ color: {P['accent']}; background: transparent; border: none; }}"
        f"QLabel#UnlockToastBody {{ color: {P['text_main']}; background: transparent; border: none; }}"
    )


# Dialogs

def ss_dialog() -> str:
    """Base background/text for QDialog windows."""
    bg = P.get('dialog_bg', P['bg_panel'])
    text = P.get('dialog_text', P['text_main'])
    border = P.get('settings_card_border', P['border'])
    radius = P.get('settings_card_radius', '12px')
    return (
        f"QDialog, QMessageBox {{ background-color: {bg}; color: {text}; }}"
        f"QLabel {{ color: {text}; background: transparent; }}"
        f"QFrame {{ background: transparent; }}"
        f"QPushButton {{ background-color: {P['mid']}; color: {P.get('button_text', text)}; "
        f"border: {P.get('button_border', 'none')}; border-radius: {P.get('button_radius', '8px')}; "
        f"padding: 6px 14px; min-height: 24px; }}"
        f"QPushButton:hover {{ background-color: {P.get('button_hover', P['bg_card_hov'])}; color: {P.get('button_hover_text', text)}; }}"
        f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; }}"
        f"QTextEdit, QPlainTextEdit {{ background-color: {P.get('input_bg', bg)}; color: {text}; "
        f"border: 1px solid {border}; border-radius: {radius}; padding: 8px; }}"
    )


# Tab widgets

def ss_tab_widget() -> str:
    """QTabWidget with rounded-top-corner background-based tab styling."""
    tab_bg = P.get("tab_bg", P["bg_panel"])
    tab_hover_bg = P.get("tab_hover_bg", tab_bg)
    tab_selected_bg = P.get("tab_selected_bg", P["mid"])
    tab_text = P.get("tab_text", P["text_dim"])
    tab_selected_text = P.get("tab_selected_text", P["accent"])
    tab_border = P.get("tab_border", "none")
    tab_radius = P.get("tab_radius", "4px")
    return (
        f"QTabWidget::pane {{ border: none; background: {P['bg_dark']}; }}"
        f"QTabBar::tab {{ background: {tab_bg}; color: {tab_text}; border: {tab_border}; "
        f"padding: 6px 16px; margin-right: 2px; border-radius: {tab_radius} {tab_radius} 0 0; }}"
        f"QTabBar::tab:selected {{ background: {tab_selected_bg}; color: {tab_selected_text}; }}"
        f"QTabBar::tab:hover {{ background: {tab_hover_bg}; color: {tab_selected_text}; }}"
    )


def ss_tab_bar() -> str:
    """Standalone QTabBar styled like editor tab strips."""
    tab_bg = P.get("tab_bg", P["bg_panel"])
    tab_hover_bg = P.get("tab_hover_bg", tab_bg)
    tab_selected_bg = P.get("tab_selected_bg", P["mid"])
    tab_text = P.get("tab_text", P["text_dim"])
    tab_selected_text = P.get("tab_selected_text", P["accent"])
    tab_border = P.get("tab_border", "none")
    tab_radius = P.get("tab_radius", "4px")
    return (
        f"QTabBar {{ background: transparent; }}"
        f"QTabBar::tab {{ background: {tab_bg}; color: {tab_text}; border: {tab_border}; "
        f"padding: 6px 16px; margin-right: 2px; border-radius: {tab_radius} {tab_radius} 0 0; }}"
        f"QTabBar::tab:selected {{ background: {tab_selected_bg}; color: {tab_selected_text}; }}"
        f"QTabBar::tab:hover {{ background: {tab_hover_bg}; color: {tab_selected_text}; }}"
    )

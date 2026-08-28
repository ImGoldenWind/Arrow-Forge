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
    disabled_bg = P.get("button_disabled_bg", P.get("bg_card", P["mid"]))
    disabled_fg = P.get("button_disabled_text", P.get("text_sec", P["text_dim"]))
    if danger:
        hover_bg = P.get("button_danger_hover", P["accent_dim"])
        hover_fg = P.get("button_danger_hover_text", P.get("button_hover_text", P["bg_dark"]))
        return (
            f"QPushButton {{ background-color: {P['mid']}; color: {button_fg}; border: {border}; "
            f"border-radius: {radius}; padding: 3px 10px; }}"
            f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; }}"
            f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; }}"
            f"QPushButton:pressed {{ background-color: {P.get('bg_card_hov', P['mid'])}; padding-top: 4px; padding-bottom: 2px; }}"
            f"QPushButton:disabled {{ background-color: {disabled_bg}; color: {disabled_fg}; }}"
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
            f"QPushButton:disabled {{ background-color: {disabled_bg}; color: {disabled_fg}; }}"
        )
    hover_bg = P.get("button_hover", P["accent_dim"])
    hover_fg = P.get("button_hover_text", P["bg_dark"])
    return (
        f"QPushButton {{ background-color: {P['mid']}; color: {button_fg}; border: {border}; "
        f"border-radius: {radius}; padding: 3px 10px; }}"
        f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P['accent'])}; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; }}"
        f"QPushButton:pressed {{ background-color: {P.get('bg_card_hov', P['mid'])}; padding-top: 4px; padding-bottom: 2px; }}"
        f"QPushButton:disabled {{ background-color: {disabled_bg}; color: {disabled_fg}; }}"
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


def ss_icon_tool_btn() -> str:
    """Compact icon-only tool button with neutral checked state."""
    radius = P.get("button_radius", "6px")
    border = P.get("button_border", f"1px solid {P['border']}")
    button_fg = P.get("button_text", P["text_main"])
    hover_bg = P.get("button_hover", P["accent_dim"])
    checked_bg = P.get("bg_card_hov", P["mid"])
    focus = P.get("input_focus_border", P["accent"])
    checked_border = P.get("selection_bg", focus)
    return (
        f"QPushButton {{ background-color: {P['mid']}; color: {button_fg}; border: {border}; "
        f"border-radius: {radius}; padding: 3px; }}"
        f"QPushButton:checked {{ background-color: {checked_bg}; color: {button_fg}; "
        f"border: 2px solid {checked_border}; }}"
        f"QPushButton:focus {{ border: 1px solid {focus}; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; color: {button_fg}; }}"
        f"QPushButton:disabled {{ background-color: {P['mid']}; color: {P['text_dim']}; }}"
    )


def ss_menu() -> str:
    """Compact popup menu used by tool panels."""
    bg = P.get("panel_card_bg", P["bg_panel"])
    border = P.get("panel_card_border", P["border"])
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    return (
        f"QMenu {{ background-color: {bg}; color: {P['text_main']}; "
        f"border: 1px solid {border}; padding: 4px; }}"
        f"QMenu::item {{ padding: 5px 22px 5px 22px; border-radius: 4px; }}"
        f"QMenu::item:selected {{ background-color: {selection_bg}; color: {selection_text}; }}"
        f"QMenu::indicator {{ width: 14px; height: 14px; }}"
    )


def ss_panel_menu_button() -> str:
    """Flat panel menu button that disappears into the panel until hover."""
    hover = P.get("bg_card_hov", P["mid"])
    radius = P.get("button_radius", "6px")
    return (
        f"QPushButton {{ background: transparent; color: {P.get('button_text', P['text_main'])}; "
        f"border: none; border-radius: {radius}; padding: 0px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
        f"QPushButton:pressed {{ background-color: {P.get('mid', hover)}; }}"
        "QPushButton::menu-indicator { image: none; width: 0px; }"
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
    disabled_bg = P.get("input_disabled_bg", P.get("bg_card", bg))
    disabled_fg = P.get("input_disabled_text", P.get("text_sec", P["text_dim"]))
    return (
        f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{"
        f"  background-color: {bg}; color: {P['text_main']}; "
        f"  border: 1px solid {border}; border-radius: {radius}; padding: {padding}; "
        f"  selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QKeySequenceEdit:hover {{"
        f"  background-color: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{"
        f"  border: 1px solid {focus}; background-color: {P.get('input_focus_bg', P.get('bg_card_hov', bg))}; }}"
        f"QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled, QKeySequenceEdit:disabled {{"
        f"  background-color: {disabled_bg}; color: {disabled_fg}; border: 1px solid {border}; }}"
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
    disabled_bg = P.get("input_disabled_bg", P.get("bg_card", bg))
    disabled_fg = P.get("input_disabled_text", P.get("text_sec", P["text_dim"]))
    return (
        f"QLineEdit {{ background-color: {bg}; border: 1px solid {border}; "
        f"color: {P['text_main']}; padding: {padding}; border-radius: {radius}; "
        f"selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QLineEdit:hover {{ background-color: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QLineEdit:focus {{ border: 1px solid {focus}; background-color: {P.get('input_focus_bg', P.get('bg_card_hov', bg))}; }}"
        f"QLineEdit:disabled {{ background-color: {disabled_bg}; color: {disabled_fg}; border: 1px solid {border}; }}"
    )


def ss_textedit() -> str:
    """QTextEdit / QPlainTextEdit."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    focus = P.get("input_focus_border", P["accent"])
    radius = P.get("input_radius", "4px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    return (
        f"QTextEdit, QPlainTextEdit {{ background-color: {bg}; color: {P['text_main']}; "
        f"border: 1px solid {border}; border-radius: {radius}; padding: 4px; "
        f"selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QTextEdit:hover, QPlainTextEdit:hover {{ background-color: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {focus}; background-color: {P.get('input_focus_bg', P.get('bg_card_hov', bg))}; }}"
        f"{ss_scrollbars(bg)}"
    )


# Tables & lists

def ss_table() -> str:
    """QTableWidget/QTableView including internal scrollbars (10 px width)."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    radius = P.get("input_radius", "4px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    header_bg = P.get("table_header_bg", P["bg_panel"])
    header_text = P.get("table_header_text", P["text_sec"])
    hover_bg = P.get("list_hover_bg", P["mid"])
    return (
        f"QTableWidget, QTableView {{ background-color: {bg}; color: {P['text_main']}; "
        f"gridline-color: {border}; border: 1px solid {border}; border-radius: {radius}; outline: none; "
        f"selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QTableWidget::item, QTableView::item {{ min-height: 24px; padding: 4px 7px; border: none; }}"
        f"QTableWidget::item:selected, QTableView::item:selected {{ background-color: {selection_bg}; color: {selection_text}; }}"
        f"QTableWidget::item:hover, QTableView::item:hover {{ background-color: {hover_bg}; }}"
        f"QHeaderView::section {{ background-color: {header_bg}; color: {header_text}; "
        f"border: none; border-right: 1px solid {border}; border-bottom: 1px solid {border}; "
        f"padding: 5px 7px; min-height: 24px; font-weight: bold; }}"
        f"QTableCornerButton::section {{ background-color: {header_bg}; border: none; border-bottom: 1px solid {border}; }}"
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


def ss_treewidget() -> str:
    """QTreeWidget used by compact editor sidebars."""
    bg = P.get("input_bg", P["bg_card"])
    border = P.get("input_border", P["border"])
    radius = P.get("input_radius", "4px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    hover_bg = P.get("list_hover_bg", P["mid"])
    group_text = P.get("tree_group_text", P["text_main"])
    return (
        f"QTreeWidget {{ background-color: {bg}; color: {P['text_main']}; "
        f"border: 1px solid {border}; border-radius: {radius}; outline: none; }}"
        f"QTreeWidget::item {{ min-height: 24px; padding: 2px 6px; }}"
        f"QTreeWidget::item:selected {{ background-color: {selection_bg}; color: {selection_text}; border: none; }}"
        f"QTreeWidget::item:focus {{ border: none; outline: none; }}"
        f"QTreeWidget::item:hover {{ background-color: {hover_bg}; }}"
        f"QTreeWidget::branch {{ background: transparent; border-image: none; image: none; }}"
        f"QTreeWidget::item:has-children {{ color: {group_text}; font-weight: 600; }}"
        f"QHeaderView::section {{ background-color: {P.get('table_header_bg', P['bg_panel'])}; "
        f"color: {P.get('table_header_text', P['text_sec'])}; border: none; "
        f"border-bottom: 1px solid {border}; padding: 5px 7px; font: 10pt 'Segoe UI'; }}"
        f"{ss_vertical_scrollbar(bg, width=10)}"
    )


def ss_sidebar_treewidget() -> str:
    """Flat QTreeWidget embedded directly into a standard sidebar."""
    bg = P.get("panel_bg", P["bg_panel"])
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    hover_bg = P.get("list_hover_bg", P["mid"])
    group_text = P.get("tree_group_text", P["text_main"])
    return (
        f"QTreeWidget {{ background: transparent; color: {P['text_main']}; "
        f"border: none; border-radius: 0; outline: none; }}"
        f"QTreeWidget::viewport {{ background: transparent; border: none; }}"
        f"QTreeWidget::item {{ min-height: 24px; padding: 2px 6px; border: none; }}"
        f"QTreeWidget::item:selected {{ background-color: {selection_bg}; color: {selection_text}; border: none; }}"
        f"QTreeWidget::item:focus {{ border: none; outline: none; }}"
        f"QTreeWidget::item:hover {{ background-color: {hover_bg}; }}"
        f"QTreeWidget::branch {{ background: transparent; border-image: none; image: none; }}"
        f"QTreeWidget::item:has-children {{ color: {group_text}; font-weight: 600; }}"
        f"{ss_vertical_scrollbar(bg, width=10)}"
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


def ss_splitter() -> str:
    """Subtle splitter handles shared by embedded editor panes."""
    handle = P.get("splitter_handle", P["mid"])
    hover = P.get("splitter_handle_hover", P["accent_dim"])
    return (
        f"QSplitter::handle {{ background-color: {handle}; }}"
        f"QSplitter::handle:hover {{ background-color: {hover}; }}"
        f"QSplitter::handle:horizontal {{ width: 2px; margin: 0px; }}"
        f"QSplitter::handle:vertical {{ height: 2px; margin: 0px; }}"
    )


def ss_transparent() -> str:
    """Transparent widget background."""
    return "background: transparent;"


def ss_video_matte() -> str:
    """Black matte background for letterboxed video preview surfaces."""
    return "background-color: #000000;"


def ss_viewport_panel() -> str:
    """3D viewport surface frame."""
    bg = P.get("viewport_bg", P.get("bg_dark", "#000000"))
    border = P.get("input_border", P["border"])
    return (
        f"QFrame, QOpenGLWidget {{ background-color: {bg}; "
        f"border: 1px solid {border}; border-radius: {P.get('input_radius', '6px')}; }}"
    )


def ss_inspector_group() -> str:
    """Compact model-viewer inspector group."""
    bg = P.get("panel_card_bg", P["bg_panel"])
    border = P.get("panel_card_border", P["border"])
    radius = P.get("input_radius", "6px")
    return (
        f"QFrame#ModelInspectorCard {{ background-color: {bg}; border: 1px solid {border}; "
        f"border-radius: {radius}; }}"
        f"QFrame#ModelInspectorCard QLabel {{ border: none; background: transparent; }}"
        f"QTextEdit#ModelInspectorRaw {{ background-color: {bg}; color: {P['text_main']}; "
        f"border: 1px solid {border}; border-radius: {radius}; padding: 8px; }}"
    )


def ss_inspector_input() -> str:
    """Flat controls inside model-viewer inspector cards."""
    bg = P.get("input_bg", P["bg_card"])
    focus = P.get("input_focus_border", P["accent"])
    radius = P.get("input_radius", "4px")
    padding = P.get("input_padding", "3px 6px")
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    return (
        f"QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{"
        f"  background-color: {bg}; color: {P['text_main']}; "
        f"  border: 1px solid transparent; border-radius: {radius}; padding: {padding}; "
        f"  selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{"
        f"  background-color: {P.get('input_hover_bg', P.get('bg_card_hov', bg))}; }}"
        f"QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{"
        f"  border: 1px solid {focus}; background-color: {P.get('input_focus_bg', P.get('bg_card_hov', bg))}; }}"
        f"QSpinBox::up-button, QSpinBox::down-button, "
        f"QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{"
        f"  width: 0; height: 0; border: none; }}"
        f"QComboBox::drop-down {{ background: transparent; border: none; width: 20px; }}"
        f"QComboBox QAbstractItemView {{ background: {bg}; color: {P['text_main']}; "
        f"  selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
    )


def ss_badge_missing() -> str:
    """Small warning badge used for unresolved model texture references."""
    warning = P.get("warning", P["accent_dim"])
    return (
        f"QLabel {{ color: {P.get('button_accent_text', P['bg_dark'])}; "
        f"background-color: {warning}; border-radius: 4px; padding: 1px 5px; }}"
    )


def ss_panel() -> str:
    """Standard editor section panel (rounded card on bg_panel)."""
    bg = P.get("panel_card_bg", P["bg_panel"])
    border = P.get("panel_card_border", "transparent")
    radius = P.get("panel_card_radius", "10px")
    return (
        f"QFrame {{ background-color: {bg}; "
        f"border-radius: {radius}; border: 1px solid {border}; }}"
    )


def ss_glass_panel() -> str:
    """Translucent editor panel for overlays that must reveal content behind them."""
    bg = _rgba(P.get("panel_card_bg", P["bg_panel"]), 184)
    border = _rgba(P.get("panel_card_border", P["border"]), 150)
    radius = P.get("panel_card_radius", "10px")
    return (
        f"QFrame {{ background-color: {bg}; "
        f"border-radius: {radius}; border: 1px solid {border}; }}"
    )


def ss_panel_title() -> str:
    """Small uppercase panel title used inside dense editor panels."""
    return f"color: {P.get('text_sec', P['text_main'])}; background: transparent; font-weight: bold;"


def ss_editor_card(selected: bool = False) -> str:
    """DuelPlayerParam-like editor card with optional selected-row emphasis."""
    bg = P["bg_panel"]
    radius = "10px"
    border = f"1px solid {P.get('accent', P['border'])}" if selected else "none"
    return (
        f"QFrame#EditorCard {{ background-color: {bg}; "
        f"border-radius: {radius}; border: {border}; }}"
    )


def make_editor_card(parent=None, *, margins=(16, 14, 16, 14), spacing=10):
    """Create the standard CharacterStats/MoveList editor card."""
    from PyQt6.QtWidgets import QFrame, QVBoxLayout

    card = QFrame(parent)
    card.setObjectName("EditorCard")
    card.setStyleSheet(ss_editor_card())
    layout = QVBoxLayout(card)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return card, layout


def add_editor_card_title(layout, title, icon_name=None, subtitle=None, *, icon_size=18):
    """Add the standard icon + panel title row used by visual editors."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

    row = QWidget()
    row.setStyleSheet(ss_transparent())
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)

    if icon_name:
        try:
            import qtawesome as qta

            icon = QLabel()
            icon.setFixedSize(icon_size, icon_size)
            icon.setStyleSheet(ss_transparent())
            icon.setPixmap(qta.icon(icon_name, color=P["accent"]).pixmap(icon_size, icon_size))
            row_layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        except Exception:
            pass

    text_box = QWidget()
    text_box.setStyleSheet(ss_transparent())
    text_layout = QVBoxLayout(text_box)
    text_layout.setContentsMargins(0, 0, 0, 0)
    text_layout.setSpacing(2)

    title_lbl = QLabel(str(title))
    title_lbl.setMinimumWidth(0)
    title_lbl.setWordWrap(True)
    title_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
    title_lbl.setStyleSheet(ss_panel_title())
    text_layout.addWidget(title_lbl)

    subtitle_lbl = None
    if subtitle:
        subtitle_lbl = QLabel(str(subtitle))
        subtitle_lbl.setMinimumWidth(0)
        subtitle_lbl.setWordWrap(True)
        subtitle_lbl.setFont(QFont("Segoe UI", 10))
        subtitle_lbl.setStyleSheet(ss_dim_label())
        text_layout.addWidget(subtitle_lbl)

    row_layout.addWidget(text_box, 1)
    layout.addWidget(row)
    return row, title_lbl, subtitle_lbl


def make_empty_state(parent=None, *, title, text="", icon_name="fa6s.folder-open"):
    """Create the standard no-selection/no-file card used in editor bodies."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QSizePolicy
    from core.translations import ui_text

    title = str(title)
    text = str(text or "")
    no_file_titles = {
        ui_text("no_file_loaded").casefold(),
        ui_text("ui_btladjprm_no_file_loaded").casefold(),
        "no file loaded",
    }
    select_entry_text = ui_text("select_entry")
    if title.casefold() in no_file_titles:
        icon_name = "fa6s.folder-open"
    if title == select_entry_text or text == select_entry_text:
        title = select_entry_text
        text = ""
        icon_name = None

    card, layout = make_editor_card(parent, margins=(22, 18, 22, 18), spacing=10)
    card.setMinimumWidth(0)
    card.setMinimumHeight(132)
    card.setMaximumWidth(620)
    card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    _row, title_lbl, subtitle_lbl = add_editor_card_title(layout, title, icon_name, text, icon_size=22)
    title_lbl.setStyleSheet(ss_main_label())
    title_lbl.setMinimumHeight(24)
    if subtitle_lbl is not None:
        subtitle_lbl.setWordWrap(True)
        subtitle_lbl.setMinimumHeight(62)
        subtitle_lbl.setMaximumWidth(560)
        subtitle_lbl.setStyleSheet(ss_field_label())
    card.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
    return card


def make_editor_field(label_text, value_text="", *, height=30, value_font=None, accent=False):
    """Create a label-above-input field matching the card editor language."""
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

    field = QWidget()
    field.setStyleSheet(ss_transparent())
    field_layout = QVBoxLayout(field)
    field_layout.setContentsMargins(0, 0, 0, 0)
    field_layout.setSpacing(4)

    label = QLabel(str(label_text))
    label.setFont(QFont("Segoe UI", 12))
    label.setStyleSheet(ss_field_label())
    field_layout.addWidget(label)

    edit = QLineEdit(str(value_text))
    edit.setFixedHeight(height)
    edit.setFont(value_font or QFont("Consolas", 13))
    edit.setStyleSheet(ss_input() + (f"QLineEdit {{ color: {P['accent']}; font-weight: bold; }}" if accent else ""))
    edit.setCursorPosition(_first_printable_pos(str(value_text)))
    field_layout.addWidget(edit)
    return field, edit


def make_editor_field_shell(label_text, hint_text="", *, label_font_size=12, hint_font_size=9, spacing=3):
    """Create the standard label/hint shell for custom editor controls."""
    from PyQt6.QtGui import QFont
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

    frame = QWidget()
    frame.setMinimumWidth(0)
    frame.setStyleSheet(ss_transparent())
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)

    label = QLabel(str(label_text))
    label.setMinimumWidth(0)
    label.setWordWrap(True)
    label.setFont(QFont("Segoe UI", label_font_size))
    label.setStyleSheet(ss_field_label())
    layout.addWidget(label)

    hint = None
    if hint_text:
        hint = QLabel(str(hint_text))
        hint.setMinimumWidth(0)
        hint.setWordWrap(True)
        hint.setFont(QFont("Segoe UI", hint_font_size))
        hint.setStyleSheet(ss_dim_label())
        layout.addWidget(hint)

    return frame, layout, label, hint


def make_editor_grid_card(
    parent=None,
    *,
    title=None,
    icon_name="fa6s.sliders",
    subtitle=None,
    margins=(16, 14, 16, 14),
    spacing=10,
    grid_margins=None,
    horizontal_spacing=16,
    vertical_spacing=10,
):
    """Create a standard editor card containing a field grid.

    This is the common loaded-state layout used by the Character Stats /
    Move List family: icon title row, then a dense grid of label-over-input
    controls with consistent spacing.
    """
    from PyQt6.QtWidgets import QGridLayout, QWidget

    card, layout = make_editor_card(parent, margins=margins, spacing=spacing)
    if title:
        add_editor_card_title(layout, title, icon_name, subtitle)

    inner = QWidget(card)
    inner.setStyleSheet(ss_transparent())
    grid = QGridLayout(inner)
    if grid_margins is None:
        grid_margins = (0, 4, 0, 0) if title else (12, 12, 12, 12)
    grid.setContentsMargins(*grid_margins)
    grid.setHorizontalSpacing(horizontal_spacing)
    grid.setVerticalSpacing(vertical_spacing)
    layout.addWidget(inner)
    return card, grid


def _first_printable_pos(text: str) -> int:
    for index, char in enumerate(text):
        if char.isprintable() and ord(char) >= 32 and char not in {"\u25a1", "\ufffd"}:
            return index
    return 0


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


def ss_embedded_tool_surface() -> str:
    """Shared visual polish applied by the host around every embedded editor.

    The rules are deliberately palette-driven and mostly target stock Qt
    controls that older editors may not style themselves yet. Editor-local
    styles still win for highly custom widgets.
    """
    bg = P.get("bg_dark", "#000000")
    panel = P.get("panel_bg", P["bg_panel"])
    card = P.get("panel_card_bg", P["bg_panel"])
    border = P.get("panel_card_border", P["border"])
    input_bg = P.get("input_bg", P["bg_card"])
    input_border = P.get("input_border", P["border"])
    selection_bg = P.get("selection_bg", P["accent"])
    selection_text = P.get("selection_text", P["bg_dark"])
    radius = P.get("panel_card_radius", "10px")
    input_radius = P.get("input_radius", "4px")
    tooltip_bg = P.get("toast_bg", P.get("dialog_bg", P["bg_panel"]))
    tooltip_border = P.get("toast_border", P["border_hov"])
    splitter = P.get("splitter_handle", P["mid"])
    splitter_hover = P.get("splitter_handle_hover", P["accent_dim"])
    return (
        f"QWidget#EmbeddedToolFrame, QWidget#EmbeddedToolBody, QWidget#EmbeddedToolEditor {{"
        f"  background: {bg}; color: {P['text_main']}; }}"
        f"QWidget#EmbeddedToolHeader {{ background: {P.get('toolbar_bg', P['bg_panel'])}; }}"
        f"QWidget#EmbeddedToolEditor QSplitter::handle {{ background: {splitter}; }}"
        f"QWidget#EmbeddedToolEditor QSplitter::handle:hover {{ background: {splitter_hover}; }}"
        f"QWidget#EmbeddedToolEditor QSplitter::handle:horizontal {{ width: 2px; margin: 0px; }}"
        f"QWidget#EmbeddedToolEditor QSplitter::handle:vertical {{ height: 2px; margin: 0px; }}"
        f"QWidget#EmbeddedToolEditor QGroupBox {{ color: {P['text_main']}; border: 1px solid {border}; "
        f"  border-radius: {radius}; margin-top: 10px; padding: 10px 8px 8px 8px; background: {card}; }}"
        f"QWidget#EmbeddedToolEditor QGroupBox::title {{ subcontrol-origin: margin; left: 10px; "
        f"  padding: 0px 5px; color: {P.get('text_sec', P['text_main'])}; background: transparent; }}"
        f"QWidget#EmbeddedToolEditor QPlainTextEdit {{ background-color: {input_bg}; color: {P['text_main']}; "
        f"  border: 1px solid {input_border}; border-radius: {input_radius}; padding: 6px; "
        f"  selection-background-color: {selection_bg}; selection-color: {selection_text}; }}"
        f"QWidget#EmbeddedToolEditor QTextBrowser {{ background-color: {input_bg}; color: {P['text_main']}; "
        f"  border: 1px solid {input_border}; border-radius: {input_radius}; padding: 6px; }}"
        f"QWidget#EmbeddedToolEditor QTableWidget, QWidget#EmbeddedToolEditor QTableView, "
        f"QWidget#EmbeddedToolEditor QTreeWidget, QWidget#EmbeddedToolEditor QListWidget {{"
        f"  background-color: {input_bg}; color: {P['text_main']}; border: 1px solid {input_border}; "
        f"  border-radius: {input_radius}; outline: none; }}"
        f"QWidget#EmbeddedToolEditor QTableWidget::item, QWidget#EmbeddedToolEditor QTableView::item, "
        f"QWidget#EmbeddedToolEditor QTreeWidget::item, QWidget#EmbeddedToolEditor QListWidget::item {{"
        f"  padding: 4px 6px; }}"
        f"QWidget#EmbeddedToolEditor QTableWidget::item:selected, QWidget#EmbeddedToolEditor QTableView::item:selected, "
        f"QWidget#EmbeddedToolEditor QTreeWidget::item:selected, QWidget#EmbeddedToolEditor QListWidget::item:selected {{"
        f"  background-color: {selection_bg}; color: {selection_text}; }}"
        f"QWidget#EmbeddedToolEditor QHeaderView::section {{ background-color: {P.get('table_header_bg', panel)}; "
        f"  color: {P.get('table_header_text', P['text_sec'])}; border: 1px solid {input_border}; "
        f"  padding: 5px 7px; font-weight: 600; }}"
        f"QWidget#EmbeddedToolEditor QTabWidget::pane {{ border: none; background: {bg}; }}"
        f"QWidget#EmbeddedToolEditor QToolTip {{ background-color: {tooltip_bg}; color: {P['text_main']}; "
        f"  border: 1px solid {tooltip_border}; padding: 5px 7px; border-radius: 5px; }}"
        f"{ss_progressbar()}"
        f"{ss_blocking_overlay()}"
        f"{ss_blocking_overlay_card()}"
        f"{ss_scrollbars(panel, size=10)}"
    )


def polish_widget_tree(widget) -> None:
    """Apply shared theme polish to a widget subtree without changing behavior."""
    if widget is None:
        return
    existing = widget.styleSheet() or ""
    surface = ss_embedded_tool_surface()
    if surface not in existing:
        widget.setStyleSheet(existing + surface)

    try:
        from PyQt6.QtWidgets import QMenu, QProgressBar
    except Exception:
        return

    for progress in widget.findChildren(QProgressBar):
        if not progress.styleSheet():
            progress.setStyleSheet(ss_progressbar())
    for menu in widget.findChildren(QMenu):
        if not menu.styleSheet():
            menu.setStyleSheet(ss_menu())


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


def ss_sidebar_edge_toggle() -> str:
    """Narrow sidebar edge toggle that visually belongs to the sidebar rail."""
    bg = P.get("toolbar_bg", P.get("panel_bg", P["bg_panel"]))
    hover = P.get("bg_card_hov", P["mid"])
    radius = P.get("button_radius", "6px")
    return (
        f"QPushButton {{ background-color: {bg}; color: {P.get('button_text', P['text_main'])}; "
        f"border: none; border-radius: {radius}; padding: 0px; }}"
        f"QPushButton:hover {{ background-color: {hover}; }}"
        f"QPushButton:pressed {{ background-color: {P.get('mid', hover)}; }}"
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
    return f"color: {P.get('placeholder_text', P.get('text_sec', P['text_dim']))}; background-color: transparent;"


def ss_file_label() -> str:
    """Loaded filename display label in toolbar."""
    return f"color: {P.get('file_label_text', P.get('text_sec', P['text_dim']))}; background: transparent;"


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
        "QSlider { background: transparent; border: none; }"
        f"QSlider::groove:horizontal {{ background: {P['mid']}; height: 6px; border-radius: 3px; }}"
        f"QSlider::handle:horizontal {{ background: {P['accent']}; width: 16px; margin: -5px 0; "
        f"border-radius: 8px; }}"
        f"QSlider::handle:horizontal:hover {{ background: {P['accent_dim']}; }}"
        f"QSlider::sub-page:horizontal {{ background: {P['accent_dim']}; border-radius: 3px; }}"
        "QSlider::add-page:horizontal { background: transparent; border-radius: 3px; }"
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


def ss_settings_top_card() -> str:
    """First settings card joined directly under the tab strip."""
    return ss_settings_card() + "QFrame { border-top: none; }"


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


def ss_settings_tab_widget() -> str:
    """Settings tabs as raised tabs joined directly to the first settings card."""
    pane_bg = P.get("settings_tab_pane_bg", P["bg_dark"])
    tab_bg = P.get("settings_tab_bg", P.get("bg_panel", P["bg_dark"]))
    tab_hover_bg = P.get("settings_tab_hover_bg", P.get("bg_card_hov", P["mid"]))
    tab_selected_bg = P.get("settings_tab_selected_bg", pane_bg)
    tab_text = P.get("settings_tab_text", P.get("tab_text", P["text_dim"]))
    tab_selected_text = P.get("settings_tab_selected_text", P.get("tab_selected_text", P["accent"]))
    tab_border = P.get("settings_tab_line", P.get("border", P["mid"]))
    tab_radius = P.get("settings_tab_radius", "8px")
    return (
        f"QTabWidget {{ background: transparent; border: none; }}"
        f"QTabWidget::pane {{ border: none; background: transparent; top: 0px; }}"
        f"QTabWidget::tab-bar {{ left: 40px; }}"
        f"QTabBar {{ background: transparent; border: none; padding: 0px; min-height: 44px; }}"
        f"QTabBar::tab {{ background: {tab_bg}; color: {tab_text}; "
        f"border: 1px solid {tab_border}; border-bottom: 1px solid {tab_border}; "
        f"height: 34px; padding: 0px 18px; margin: 8px 4px 0px 4px; min-width: 108px; "
        f"border-top-left-radius: {tab_radius}; border-top-right-radius: {tab_radius}; "
        f"border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; "
        f"font-family: 'Segoe UI'; font-size: 13px; font-weight: 500; }}"
        f"QTabBar::tab:selected {{ background: {tab_selected_bg}; color: {tab_selected_text}; "
        f"border: 1px solid {tab_border}; border-bottom: none; }}"
        f"QTabBar::tab:hover:!selected {{ background: {tab_hover_bg}; color: {P['text_main']}; }}"
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
    """QTabWidget styled as a compact editor tab strip."""
    tab_bg = P.get("tab_bg", P["bg_panel"])
    tab_hover_bg = P.get("tab_hover_bg", P.get("bg_card_hov", tab_bg))
    tab_selected_bg = P.get("tab_selected_bg", P["mid"])
    tab_text = P.get("tab_text", P["text_dim"])
    tab_selected_text = P.get("tab_selected_text", P["text_main"])
    tab_border = P.get("tab_border", f"1px solid {P['border']}")
    tab_radius = P.get("tab_radius", "6px")
    tab_bar_bg = P.get("tab_bar_bg", P.get("toolbar_bg", P["bg_panel"]))
    accent = P.get("tab_accent", P["accent"])
    return (
        f"QTabWidget {{ background: {P['bg_dark']}; border: none; }}"
        f"QTabWidget::pane {{ border: none; background: {P['bg_dark']}; top: -1px; }}"
        f"QTabWidget::tab-bar {{ alignment: left; }}"
        f"QTabBar {{ background: {tab_bar_bg}; border: none; padding: 4px 8px 0px 8px; min-height: 34px; }}"
        f"QTabBar::tab {{ background: {tab_bg}; color: {tab_text}; border: {tab_border}; "
        f"border-bottom: 1px solid {P['border']}; padding: 6px 16px; margin-right: 3px; "
        f"min-height: 24px; min-width: 72px; "
        f"border-top-left-radius: {tab_radius}; border-top-right-radius: {tab_radius}; "
        f"border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; }}"
        f"QTabBar::tab:selected {{ background: {tab_selected_bg}; color: {tab_selected_text}; "
        f"border-top: 2px solid {accent}; border-bottom: 1px solid {tab_selected_bg}; "
        f"font-weight: 600; }}"
        f"QTabBar::tab:hover:!selected {{ background: {tab_hover_bg}; color: {P['text_main']}; }}"
        f"QTabBar::tab:disabled {{ color: {P['text_dim']}; background: {P.get('bg_card', tab_bg)}; }}"
    )


def ss_tab_bar() -> str:
    """Standalone QTabBar styled like editor tab strips."""
    tab_bg = P.get("tab_bg", P["bg_panel"])
    tab_hover_bg = P.get("tab_hover_bg", P.get("bg_card_hov", tab_bg))
    tab_selected_bg = P.get("tab_selected_bg", P["mid"])
    tab_text = P.get("tab_text", P["text_dim"])
    tab_selected_text = P.get("tab_selected_text", P["text_main"])
    tab_border = P.get("tab_border", f"1px solid {P['border']}")
    tab_radius = P.get("tab_radius", "6px")
    tab_bar_bg = P.get("tab_bar_bg", P.get("toolbar_bg", P["bg_panel"]))
    accent = P.get("tab_accent", P["accent"])
    return (
        f"QTabBar {{ background: {tab_bar_bg}; border: none; padding: 4px 8px 0px 8px; min-height: 34px; }}"
        f"QTabBar::tab {{ background: {tab_bg}; color: {tab_text}; border: {tab_border}; "
        f"border-bottom: 1px solid {P['border']}; padding: 6px 16px; margin-right: 3px; "
        f"min-height: 24px; min-width: 72px; "
        f"border-top-left-radius: {tab_radius}; border-top-right-radius: {tab_radius}; "
        f"border-bottom-left-radius: 0px; border-bottom-right-radius: 0px; }}"
        f"QTabBar::tab:selected {{ background: {tab_selected_bg}; color: {tab_selected_text}; "
        f"border-top: 2px solid {accent}; border-bottom: 1px solid {tab_selected_bg}; "
        f"font-weight: 600; }}"
        f"QTabBar::tab:hover:!selected {{ background: {tab_hover_bg}; color: {P['text_main']}; }}"
        f"QTabBar::tab:disabled {{ color: {P['text_dim']}; background: {P.get('bg_card', tab_bg)}; }}"
    )

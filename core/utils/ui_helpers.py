from core.design_tokens import TypeSize
from core.design_tokens import ui_font
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCursor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QLabel, QPushButton

from core.themes import P
from core.style_helpers import ss_panel_title

import math


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
    if P.get("font_ui"):
        font.setFamily(P["font_ui"])
    btn.setFont(font)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    if fg == P.get("text_main") and P.get("button_text"):
        fg = P["button_text"]
    hover_bg = P.get("button_hover", hover)
    hover_fg = P.get("button_hover_text", fg)
    radius = P.get("button_radius", "8px")
    border = P.get("button_border", "none")
    style = (
        f"QPushButton {{ background-color: {bg}; color: {fg}; border: {border}; "
        f"border-radius: {radius}; padding: 4px 12px; }}"
        f"QPushButton:hover {{ background-color: {hover_bg}; color: {hover_fg}; }}"
        f"QPushButton:focus {{ border: 1px solid {P.get('input_focus_border', P.get('accent', fg))}; }}"
        f"QPushButton:pressed {{ background-color: {P.get('button_pressed', P.get('bg_card_hov', hover_bg))}; padding-top: 5px; padding-bottom: 3px; }}"
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


def _theme_qss_bg(key, fallback_key):
    return P.get(key, P[fallback_key])


def _theme_float(key, default=1.0):
    try:
        return float(P.get(key, default))
    except (TypeError, ValueError):
        return default


def _theme_int(key, default=0):
    try:
        return int(float(P.get(key, default)))
    except (TypeError, ValueError):
        return default


def _hash01(value):
    return math.sin(value * 12.9898 + 78.233) % 1.0


def _transparent_icon_pixmap(icon, size):
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    icon.paint(painter, pixmap.rect(), Qt.AlignmentFlag.AlignCenter)
    painter.end()
    return pixmap


def _make_label_background_transparent(label):
    label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    label.setAutoFillBackground(False)
    return label


def _add_card_section_title(layout, title):
    label = QLabel(str(title).upper())
    label.setFont(ui_font(TypeSize.TITLE, QFont.Weight.Bold))
    label.setStyleSheet(ss_panel_title())
    layout.addWidget(label)
    return label

from core.design_tokens import TypeSize
from core.design_tokens import ui_font
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QCursor, QFont
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel

from core.themes import P
from core.utils.ui_helpers import _transparent_icon_pixmap


class _SidebarBtn(QFrame):
    def __init__(self, text, icon, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self._active = False
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 8, 0)
        row.setSpacing(10)

        self._icon_lbl = QLabel()
        self._icon_lbl.setPixmap(_transparent_icon_pixmap(icon, QSize(20, 20)))
        self._icon_lbl.setFixedSize(20, 20)
        self._icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._icon_lbl.setAutoFillBackground(False)
        self._icon_lbl.setStyleSheet("background: transparent; border: none;")
        row.addWidget(self._icon_lbl)

        self._text_lbl = QLabel(text)
        self._text_lbl.setFont(ui_font(TypeSize.LABEL, QFont.Weight.Bold))
        self._text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._text_lbl.setAutoFillBackground(False)
        row.addWidget(self._text_lbl, 1)

        self._set_style(active=False, hover=False)

    def _set_style(self, active, hover):
        if active:
            fg = P.get("sidebar_text_active", P["accent"])
        elif hover:
            fg = P.get("sidebar_text_hover", P["text_main"])
        else:
            fg = P.get("sidebar_text", P["text_dim"])
        self.setStyleSheet("background: transparent; border: none;")
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

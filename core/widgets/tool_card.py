from PyQt6.QtCore import QPoint, QRectF, QSize, QTimer, Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QFrame, QSizePolicy

from core.effects.tool_card_effects import ToolCardEffectsMixin
from core.rendering.theme_rendering import ThemeRenderingMixin
from core.rendering.tool_card_painter import ToolCardPaintingMixin
from core.rendering.tool_card_textures import ToolCardTextureMixin
from core.utils.ui_helpers import _theme_int, _transparent_icon_pixmap
from core.widgets.tool_card_interactions import ToolCardInteractionMixin


class ToolCard(
    ToolCardInteractionMixin,
    ToolCardPaintingMixin,
    ToolCardTextureMixin,
    ThemeRenderingMixin,
    ToolCardEffectsMixin,
    QFrame,
):
    def __init__(self, parent, label, file_hint, icon, dlg_key,
                 on_hover=None, on_leave=None, app=None,
                 tool_id=None, favorite=False, favorite_tooltip="",
                 on_toggle_favorite=None, pinned=False, pin_tooltip="",
                 on_toggle_pin=None, pin_category_key=None, category_key=None,
                 on_activate=None):
        super().__init__(parent)
        self._label = label
        self._file_hint = file_hint
        self._dlg_key = dlg_key
        self._on_hover_cb = on_hover
        self._on_leave_cb = on_leave
        self._app = app
        self._on_activate = on_activate
        self._tool_id = tool_id or dlg_key
        self._category_key = category_key
        self._pin_category_key = pin_category_key or category_key
        self._favorite = favorite
        self._pinned = pinned
        self._on_toggle_favorite = on_toggle_favorite
        self._on_toggle_pin = on_toggle_pin
        self._pressed_inside = False
        self._press_action = None
        self._hovered = False
        self._hover_phase = 0.0
        self._bubble_seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(f"{dlg_key}:{label}:{file_hint}"))
        self._tilt_x = 0.0
        self._tilt_y = 0.0
        self._mouse_pos = QPoint(0, 0)
        self._tool_icon = icon
        self._tool_icon_size = _theme_int("tool_card_icon_size", 20)
        self._tool_pixmap = _transparent_icon_pixmap(icon, QSize(self._tool_icon_size, self._tool_icon_size))
        self._texture_cache_key = None
        self._texture_cache_pixmap = None
        self._favorite_tooltip = favorite_tooltip
        self._pin_tooltip = pin_tooltip
        self._favorite_rect = QRectF()
        self._pin_rect = QRectF()
        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(33)
        self._glow_timer.timeout.connect(self._advance_hover_glow)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(125)
        self._position_action_btns()

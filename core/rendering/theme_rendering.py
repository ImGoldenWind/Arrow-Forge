from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QBrush, QColor, QLinearGradient

from core.themes import P


def _theme_int(key, default=0):
    try:
        return int(float(P.get(key, default)))
    except (TypeError, ValueError):
        return default


def _parse_theme_color(value, fallback="#000000"):
    if not isinstance(value, str):
        value = fallback
    raw = value.strip()
    lowered = raw.lower()
    if lowered.startswith("rgba(") and raw.endswith(")"):
        parts = [part.strip() for part in raw[5:-1].split(",")]
        if len(parts) == 4:
            try:
                r = int(float(parts[0]))
                g = int(float(parts[1]))
                b = int(float(parts[2]))
                a_float = float(parts[3])
                a = int(round(a_float * 255)) if 0.0 <= a_float <= 1.0 else int(round(a_float))
                return QColor(r, g, b, max(0, min(255, a)))
            except ValueError:
                pass
    if lowered.startswith("rgb(") and raw.endswith(")"):
        parts = [part.strip() for part in raw[4:-1].split(",")]
        if len(parts) == 3:
            try:
                return QColor(int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
            except ValueError:
                pass
    color = QColor(raw)
    if not color.isValid():
        color = QColor(fallback)
    return color


class ThemeRenderingMixin:
    def _color(self, key, alpha=None, fallback_key=None):
        color = _parse_theme_color(P.get(key, P.get(fallback_key or key, "#000000")))
        if alpha is not None:
            color.setAlpha(max(0, min(255, alpha)))
        return color

    def _card_fill(self, rect):
        prefix = "card_hover" if self._hovered else "card"
        top = P.get(f"{prefix}_gradient_top", P["bg_card_hov" if self._hovered else "bg_card"])
        mid = P.get(f"{prefix}_gradient_mid", P["bg_card_hov" if self._hovered else "bg_card"])
        bottom = P.get(f"{prefix}_gradient_bottom", P["bg_card_hov" if self._hovered else "bg_card"])

        fill_alpha = _theme_int(
            f"{prefix}_fill_alpha",
            _theme_int("card_fill_alpha", 255),
        )

        def fill_color(value):
            color = _parse_theme_color(value)
            if fill_alpha < 255:
                color.setAlpha(max(0, min(255, fill_alpha)))
            return color

        gradient = QLinearGradient(QPointF(rect.topLeft()), QPointF(rect.bottomRight()))
        gradient.setColorAt(0.0, fill_color(top))
        gradient.setColorAt(0.48, fill_color(mid))
        gradient.setColorAt(1.0, fill_color(bottom))
        return QBrush(gradient)

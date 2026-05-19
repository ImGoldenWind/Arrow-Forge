import math

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from core.themes import P


def _color(key, alpha=None, fallback="#FFFFFF"):
    color = QColor(P.get(key, fallback))
    if not color.isValid():
        color = QColor(fallback)
    if alpha is not None:
        color.setAlpha(max(0, min(255, int(alpha))))
    return color


def _theme_int(key, default):
    try:
        return int(float(P.get(key, default)))
    except (TypeError, ValueError):
        return default


def _theme_float(key, default):
    try:
        return float(P.get(key, default))
    except (TypeError, ValueError):
        return default


def _hash01(value):
    return math.sin(value * 12.9898 + 78.233) % 1.0


class WhiteAlbumOverlay(QWidget):
    def __init__(self, parent, app):
        super().__init__(parent)
        self._app = app
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(42)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.hide()

    def start(self):
        self.show()
        self.raise_()
        if self._motion_enabled() and not self._timer.isActive():
            self._timer.start()
        if not self._motion_enabled():
            self._timer.stop()
        self.update()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _motion_enabled(self):
        settings = getattr(self._app, "_settings", {})
        return (
            settings.get("animation_theme_personality", True)
            and settings.get("animation_theme_personality_motion", True)
        )

    def _tick(self):
        if not self._motion_enabled():
            self._timer.stop()
            self.update()
            return
        self._phase = (self._phase + _theme_float("white_album_motion_speed", 0.0018)) % 1.0
        self.update()

    def paintEvent(self, event):
        if P.get("name") != "White Album":
            return

        rect = QRectF(self.rect())
        if rect.width() <= 1 or rect.height() <= 1:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        self._draw_winter_haze(painter, rect)
        self._draw_air_current_snow(painter, rect)
        self._draw_frosted_edges(painter, rect)
        self._draw_edge_cracks(painter, rect)

        painter.end()

    def _draw_winter_haze(self, painter, rect):
        haze_alpha = _theme_int("white_album_haze_alpha", 26)
        if haze_alpha <= 0:
            return

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.setPen(Qt.PenStyle.NoPen)

        cold_depth = QRadialGradient(
            QPointF(rect.left() + rect.width() * 0.72, rect.top() + rect.height() * 0.10),
            max(rect.width(), rect.height()) * 0.82,
        )
        cold_depth.setColorAt(0.00, _color("shine", int(haze_alpha * 1.15)))
        cold_depth.setColorAt(0.32, _color("highlight", int(haze_alpha * 0.42), "#E7F8FF"))
        cold_depth.setColorAt(1.00, _color("highlight", 0, "#E7F8FF"))
        painter.setBrush(cold_depth)
        painter.drawRect(rect)

        band_count = 4
        motion = self._phase if self._motion_enabled() else 0.18
        for idx in range(band_count):
            seed = _hash01(idx * 41.0 + 17.0)
            y = rect.top() + rect.height() * ((0.16 + idx * 0.21 + motion * (0.06 + seed * 0.04)) % 1.0)
            band_h = rect.height() * (0.10 + seed * 0.06)
            x_shift = math.sin((motion * 0.8 + seed) * math.tau) * rect.width() * 0.05
            band = QLinearGradient(
                QPointF(rect.left() - rect.width() * 0.12 + x_shift, y),
                QPointF(rect.right() + rect.width() * 0.12 + x_shift, y + band_h),
            )
            band.setColorAt(0.00, _color("shine", 0))
            band.setColorAt(0.30, _color("card_glow", int(haze_alpha * (0.22 + seed * 0.24)), "#C6E7F4"))
            band.setColorAt(0.55, _color("shine", int(haze_alpha * 0.34)))
            band.setColorAt(1.00, _color("card_glow", 0, "#C6E7F4"))
            painter.setBrush(band)
            painter.drawRect(QRectF(rect.left(), y - band_h * 0.5, rect.width(), band_h))

    def _draw_air_current_snow(self, painter, rect):
        snow_alpha = _theme_int("white_album_snow_alpha", 62)
        count = max(0, min(120, _theme_int("white_album_snow_count", 72)))
        if snow_alpha <= 0 or count <= 0:
            return

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        motion = self._phase if self._motion_enabled() else 0.0
        travel = rect.height() + 40.0
        wind = _theme_float("white_album_wind", 0.18)

        for idx in range(count):
            x_seed = _hash01(idx * 19.19 + 3.0)
            y_seed = _hash01(idx * 31.31 + 7.0)
            size_seed = _hash01(idx * 47.47 + 11.0)
            speed_seed = _hash01(idx * 61.61 + 13.0)
            alpha_seed = _hash01(idx * 73.73 + 17.0)

            progress = (y_seed + motion * (0.18 + speed_seed * 0.30)) % 1.0
            x = rect.left() + rect.width() * (0.02 + x_seed * 0.96)
            x += math.sin((progress * 1.4 + x_seed) * math.tau) * rect.width() * 0.018
            x += progress * rect.width() * wind * (0.18 + speed_seed * 0.34)
            x = rect.left() + ((x - rect.left()) % max(1.0, rect.width()))
            y = rect.top() - 20.0 + progress * travel

            edge_fade = max(0.0, min(progress / 0.10, (1.0 - progress) / 0.10, 1.0))
            local_alpha = int(snow_alpha * (0.20 + alpha_seed * 0.80) * edge_fade)
            if local_alpha <= 4:
                continue

            size = 0.8 + size_seed * 2.8
            center = QPointF(x, y)
            if idx % 9 == 0:
                self._draw_snowflake(painter, center, size * 2.6, local_alpha)
            else:
                glow = QRadialGradient(center, size * 3.1)
                glow.setColorAt(0.00, _color("shine", min(255, int(local_alpha * 1.35))))
                glow.setColorAt(0.34, _color("card_frost", int(local_alpha * 0.54), "#FFFFFF"))
                glow.setColorAt(1.00, _color("card_frost", 0, "#FFFFFF"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(center, size * 3.1, size * 3.1)

    def _draw_snowflake(self, painter, center, radius, alpha):
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(_color("shine", alpha), 0.65)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for arm in range(6):
            angle = (arm / 6.0) * math.tau
            dx = math.cos(angle) * radius
            dy = math.sin(angle) * radius
            painter.drawLine(
                QPointF(center.x() - dx * 0.36, center.y() - dy * 0.36),
                QPointF(center.x() + dx, center.y() + dy),
            )

    def _draw_frosted_edges(self, painter, rect):
        edge_alpha = _theme_int("white_album_edge_frost_alpha", 48)
        if edge_alpha <= 0:
            return

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.setPen(Qt.PenStyle.NoPen)

        top = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.top() + 90))
        top.setColorAt(0.00, _color("shine", int(edge_alpha * 1.25)))
        top.setColorAt(0.36, _color("card_frost_alt", int(edge_alpha * 0.38), "#C7E7F4"))
        top.setColorAt(1.00, _color("shine", 0))
        painter.setBrush(top)
        painter.drawRect(QRectF(rect.left(), rect.top(), rect.width(), 90))

        bottom = QLinearGradient(QPointF(rect.left(), rect.bottom()), QPointF(rect.left(), rect.bottom() - 82))
        bottom.setColorAt(0.00, _color("shine", int(edge_alpha * 0.72)))
        bottom.setColorAt(0.42, _color("card_frost_alt", int(edge_alpha * 0.24), "#C7E7F4"))
        bottom.setColorAt(1.00, _color("shine", 0))
        painter.setBrush(bottom)
        painter.drawRect(QRectF(rect.left(), rect.bottom() - 82, rect.width(), 82))

        for corner, x, y in (
            ("tl", rect.left(), rect.top()),
            ("tr", rect.right(), rect.top()),
            ("bl", rect.left(), rect.bottom()),
            ("br", rect.right(), rect.bottom()),
        ):
            center = QPointF(x, y)
            frost = QRadialGradient(center, 135)
            frost.setColorAt(0.00, _color("shine", int(edge_alpha * 1.12)))
            frost.setColorAt(0.34, _color("card_frost_alt", int(edge_alpha * 0.34), "#C7E7F4"))
            frost.setColorAt(1.00, _color("shine", 0))
            painter.setBrush(frost)
            painter.drawEllipse(center, 135, 135)

    def _draw_edge_cracks(self, painter, rect):
        crack_alpha = _theme_int("white_album_crack_alpha", 34)
        if crack_alpha <= 0:
            return

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(_color("shine", crack_alpha), 0.58)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        anchors = (
            QPointF(rect.left() + rect.width() * 0.13, rect.top() + 12),
            QPointF(rect.left() + rect.width() * 0.77, rect.top() + 9),
            QPointF(rect.left() + 10, rect.top() + rect.height() * 0.76),
            QPointF(rect.right() - 12, rect.top() + rect.height() * 0.34),
        )
        for idx, start in enumerate(anchors):
            path = QPainterPath(start)
            direction = -1.0 if idx % 2 else 1.0
            for step in range(1, 5):
                seed = _hash01(idx * 83.0 + step * 29.0)
                path.lineTo(QPointF(
                    start.x() + direction * (10.0 + step * (8.0 + seed * 8.0)),
                    start.y() + step * (5.0 + seed * 7.0),
                ))
            painter.drawPath(path)


class WhiteAlbumEffectMixin:
    def _init_white_album_effect(self):
        self._white_album_overlay = None

    def _sync_white_album_effect(self):
        overlay = getattr(self, "_white_album_overlay", None)
        enabled = (
            P.get("name") == "White Album"
            and getattr(self, "_settings", {}).get("animation_theme_personality", True)
        )
        if not enabled:
            if overlay is not None:
                overlay.stop()
            return

        if overlay is None:
            overlay = WhiteAlbumOverlay(self._central, self)
            self._white_album_overlay = overlay
        self._resize_white_album_overlay()
        overlay.start()

    def _resize_white_album_overlay(self):
        overlay = getattr(self, "_white_album_overlay", None)
        if overlay is None:
            return
        overlay.setGeometry(self._central.rect())
        if overlay.isVisible():
            overlay.raise_()

    def _shutdown_white_album_effect(self):
        overlay = getattr(self, "_white_album_overlay", None)
        if overlay is not None:
            overlay.stop()

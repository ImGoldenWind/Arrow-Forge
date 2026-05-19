import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QTransform,
)

from core.icons import icon_favorite_star, icon_tool_pin
from core.themes import P
from core.utils.ui_helpers import _hash01, _theme_float, _theme_int


class ToolCardPaintingMixin:
    def _nightmare_chaos_enabled(self):
        return P.get("card_texture") == "nightmare_chaos"

    def _nightmare_text_color(self, slot, fallback_key="text_main", alpha=None):
        palette = [
            part.strip()
            for part in P.get(
                "card_text_palette",
                "card_nightmare_yellow|card_nightmare_toxic|card_nightmare_cyan|card_nightmare_pink",
            ).split("|")
            if part.strip()
        ]
        if not palette:
            return self._color(fallback_key, alpha)

        motion_bucket = int(self._hover_phase * 18) if self._hovered else 0
        idx = int(_hash01(self._bubble_seed + slot * 79.0 + motion_bucket * 17.0) * len(palette)) % len(palette)
        raw = P.get(palette[idx], palette[idx])
        color = QColor(raw)
        if not color.isValid():
            color = self._color(fallback_key)
        if alpha is not None:
            color.setAlpha(max(0, min(255, alpha)))
        return color

    def _draw_nightmare_text(self, painter, rect, text, font, slot, fallback_key, flags):
        painter.setFont(font)
        if not self._nightmare_chaos_enabled():
            painter.setPen(self._color(fallback_key))
            painter.drawText(rect, flags, text)
            return

        base = self._nightmare_text_color(slot, fallback_key)
        painter.setPen(self._color("shadow", 170, "shadow"))
        painter.drawText(rect.translated(1.0, 1.0), flags, text)

        if self._hovered:
            phase_bucket = int(self._hover_phase * 24)
            jitter_x = -2 + int(_hash01(self._bubble_seed + slot * 113.0 + phase_bucket) * 5)
            jitter_y = -1 + int(_hash01(self._bubble_seed + slot * 137.0 + phase_bucket) * 3)
            painter.setPen(self._color("card_nightmare_cyan", 150, "secondary"))
            painter.drawText(rect.translated(jitter_x - 1, jitter_y), flags, text)
            painter.setPen(self._color("card_nightmare_red", 130, "highlight"))
            painter.drawText(rect.translated(-jitter_x + 1, -jitter_y), flags, text)
            if _hash01(self._bubble_seed + slot * 151.0 + phase_bucket) > 0.48:
                painter.setPen(self._color("card_nightmare_toxic", 96, "accent"))
                tear_y = rect.top() + 4 + int(_hash01(self._bubble_seed + slot * 173.0 + phase_bucket) * max(1, rect.height() - 7))
                painter.drawText(
                    QRectF(rect.left() + jitter_x * 2, tear_y, rect.width(), rect.height()),
                    flags,
                    text,
                )

        painter.setPen(base)
        painter.drawText(rect, flags, text)

    def _draw_nightmare_hover_corruption(self, painter, rect, radius, pulse):
        if not (self._nightmare_chaos_enabled() and self._hovered):
            return

        mapped = self._map_from_visual_card(self._mouse_pos)
        cx = max(rect.left(), min(rect.right(), mapped.x()))
        cy = max(rect.top(), min(rect.bottom(), mapped.y()))
        alpha = max(0, min(255, _theme_int("card_nightmare_hover_break_alpha", 118)))
        slice_count = max(4, min(18, _theme_int("card_nightmare_hover_slices", 10)))

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.setPen(Qt.PenStyle.NoPen)

        for idx in range(slice_count):
            seed = _hash01(self._bubble_seed + idx * 43.0 + int(self._hover_phase * 31.0))
            band_y = cy - 38.0 + seed * 76.0
            band_h = 2.0 + _hash01(self._bubble_seed + idx * 59.0) * 8.0
            band_w = rect.width() * (0.18 + _hash01(self._bubble_seed + idx * 71.0) * 0.52)
            drift = math.sin((self._hover_phase * (1.6 + seed) + seed) * math.tau) * (12.0 + seed * 26.0)
            band_x = cx - band_w * 0.5 + drift
            color_key = (
                "card_nightmare_cyan"
                if idx % 4 == 0
                else "card_nightmare_pink"
                if idx % 4 == 1
                else "card_nightmare_toxic"
                if idx % 4 == 2
                else "card_nightmare_red"
            )
            glitch = QLinearGradient(QPointF(band_x, band_y), QPointF(band_x + band_w, band_y))
            glitch.setColorAt(0.00, self._color(color_key, 0, "accent"))
            glitch.setColorAt(0.18, self._color(color_key, int(alpha * (0.42 + seed * 0.52)), "accent"))
            glitch.setColorAt(0.52, self._color("card_nightmare_yellow", int(alpha * 0.22), "shine"))
            glitch.setColorAt(1.00, self._color(color_key, 0, "accent"))
            painter.setBrush(QBrush(glitch))
            painter.drawRect(QRectF(band_x, band_y, band_w, band_h))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        ghost = 1.5 + pulse * 3.0
        painter.setPen(QPen(self._color("card_nightmare_cyan", int(alpha * 0.52), "secondary"), 1.2))
        painter.drawRect(QRectF(cx - 54 - ghost, cy - 24, 108, 48))
        painter.setPen(QPen(self._color("card_nightmare_red", int(alpha * 0.44), "highlight"), 1.0))
        painter.drawRect(QRectF(cx - 50 + ghost, cy - 20 - ghost, 100, 40))

        painter.restore()

    def _draw_card_glass_overlay(self, painter, rect, radius, pulse):
        if str(P.get("card_glass_overlay", "")).lower() not in {"1", "true", "yes"}:
            return
        if P.get("card_glass_overlay_style") == "frosted":
            self._draw_card_frosted_overlay(painter, rect, radius)
            return

        alpha = max(0, min(255, _theme_int("card_glass_overlay_alpha", 82)))
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        top_rect = QRectF(
            rect.left() + 8,
            rect.top() + 7,
            rect.width() - 16,
            rect.height() * 0.42,
        )
        top_gloss = QLinearGradient(QPointF(top_rect.left(), top_rect.top()), QPointF(top_rect.left(), top_rect.bottom()))
        top_gloss.setColorAt(0.0, self._color("shine", int(alpha * 1.30), "shine"))
        top_gloss.setColorAt(0.48, self._color("shine", int(alpha * 0.42), "shine"))
        top_gloss.setColorAt(1.0, self._color("shine", 0, "shine"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(top_gloss))
        painter.drawRoundedRect(top_rect, max(4, radius - 5), max(4, radius - 5))

        wet_lens = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom()))
        wet_lens.setColorAt(0.0, self._color("shine", int(alpha * 0.72), "shine"))
        wet_lens.setColorAt(0.22, self._color("shine", 0, "shine"))
        wet_lens.setColorAt(0.68, self._color("card_glow_secondary", int(alpha * 0.26), "highlight"))
        wet_lens.setColorAt(1.0, self._color("shine", int(alpha * 0.46), "shine"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(wet_lens), 1.35))
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 1, radius - 1)

        horizon_y = rect.top() + rect.height() * 0.52
        horizon = QLinearGradient(QPointF(rect.left() + 10, horizon_y), QPointF(rect.right() - 10, horizon_y))
        horizon.setColorAt(0.0, self._color("shine", 0, "shine"))
        horizon.setColorAt(0.32, self._color("shine", int(alpha * 0.42), "shine"))
        horizon.setColorAt(0.68, self._color("card_glow_secondary", int(alpha * 0.36), "highlight"))
        horizon.setColorAt(1.0, self._color("shine", 0, "shine"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(horizon), 1.2 + pulse * 0.35))
        painter.drawLine(QPointF(rect.left() + 12, horizon_y), QPointF(rect.right() - 12, horizon_y))

        side = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))
        side.setColorAt(0.0, self._color("shine", int(alpha * 0.58), "shine"))
        side.setColorAt(0.44, self._color("shine", int(alpha * 0.18), "shine"))
        side.setColorAt(1.0, self._color("shine", 0, "shine"))
        painter.setPen(QPen(QBrush(side), 1.5))
        painter.drawLine(
            QPointF(rect.left() + 2, rect.top() + radius),
            QPointF(rect.left() + 2, rect.bottom() - radius),
        )

        bottom_rect = QRectF(rect.left() + 9, rect.bottom() - rect.height() * 0.32, rect.width() - 18, rect.height() * 0.26)
        bottom_glow = QLinearGradient(QPointF(bottom_rect.left(), bottom_rect.top()), QPointF(bottom_rect.left(), bottom_rect.bottom()))
        bottom_glow.setColorAt(0.0, self._color("card_glow_secondary", 0, "highlight"))
        bottom_glow.setColorAt(0.48, self._color("card_glow_secondary", int(alpha * 0.24), "highlight"))
        bottom_glow.setColorAt(1.0, self._color("shine", int(alpha * 0.38), "shine"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(bottom_glow))
        painter.drawRoundedRect(bottom_rect, max(4, radius - 7), max(4, radius - 7))

        painter.restore()

    def _draw_card_frosted_overlay(self, painter, rect, radius):
        alpha = max(0, min(255, _theme_int("card_glass_overlay_alpha", 38)))
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        top_edge = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top()))
        top_edge.setColorAt(0.00, self._color("shine", 0, "shine"))
        top_edge.setColorAt(0.28, self._color("shine", int(alpha * 0.72), "shine"))
        top_edge.setColorAt(0.72, self._color("shine", int(alpha * 0.58), "shine"))
        top_edge.setColorAt(1.00, self._color("shine", 0, "shine"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(top_edge), 0.85))
        painter.drawLine(
            QPointF(rect.left() + radius * 0.72, rect.top() + 1.0),
            QPointF(rect.right() - radius * 0.72, rect.top() + 1.0),
        )

        inner = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))
        inner.setColorAt(0.00, self._color("shine", int(alpha * 0.36), "shine"))
        inner.setColorAt(0.34, self._color("shine", int(alpha * 0.10), "shine"))
        inner.setColorAt(1.00, self._color("shine", 0, "shine"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(inner))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), max(1, radius - 1), max(1, radius - 1))

        painter.restore()

    def _card_transform(self, rect):
        src_quad = QPolygonF([
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ])
        dst_quad = self._card_quad(rect)
        transform = QTransform()
        if (
            self._hovered
            and self._perspective_enabled()
            and QTransform.quadToQuad(src_quad, dst_quad, transform)
        ):
            return transform
        return QTransform()

    def _map_from_visual_card(self, point):
        rect = self.rect().adjusted(5, 5, -5, -5)
        transform = self._card_transform(rect)
        if transform.isIdentity():
            return QPointF(point)
        inverse, invertible = transform.inverted()
        if not invertible:
            return QPointF(point)
        return inverse.map(QPointF(point))

    def _draw_card_action(self, painter, rect, icon_fn, checked, action):
        hovered = self._hovered and self._action_at(self._mouse_pos) == action
        bg_key = "mid" if checked else "bg_panel"
        if hovered:
            bg_key = "bg_card_hov"
        border_key = "accent" if checked else "border_hov" if hovered else "border"
        fg_key = "accent" if checked else "text_main" if hovered else "text_dim"

        bg = self._color(bg_key)
        border = self._color(border_key)
        action_radius = _theme_int("card_action_radius", 6)
        painter.setPen(QPen(border, 1.0))
        if str(P.get("card_action_glossy", "")).lower() in {"1", "true", "yes"}:
            fill = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))
            fill.setColorAt(0.0, self._color("shine", 216, "shine"))
            fill.setColorAt(0.38, bg)
            fill.setColorAt(1.0, self._color("card_glow" if hovered or checked else "mid", 128, "mid"))
            painter.setBrush(QBrush(fill))
        else:
            painter.setBrush(bg)
        painter.drawRoundedRect(rect, action_radius, action_radius)
        if str(P.get("card_action_glossy", "")).lower() in {"1", "true", "yes"}:
            painter.setPen(QPen(self._color("shine", 150, "shine"), 0.8))
            painter.drawLine(
                QPointF(rect.left() + action_radius * 0.55, rect.top() + 2),
                QPointF(rect.right() - action_radius * 0.55, rect.top() + 2),
            )

        icon_rect = rect.adjusted(6, 6, -6, -6).toRect()
        icon = icon_fn(
            filled=checked,
            size=14,
            color=P["accent"] if checked else P["text_main"] if hovered else P["text_dim"],
        )
        icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)

    def _draw_card_content(self, painter):
        content_top = (self.height() - 36) / 2
        icon_size = max(20, getattr(self, "_tool_icon_size", 20))
        icon_rect = QRectF(16, (self.height() - icon_size) / 2, icon_size, icon_size)
        text_x = icon_rect.right() + 14
        text_w = max(80, self.width() - text_x - 70)

        painter.drawPixmap(icon_rect.toRect(), self._tool_pixmap)

        self._draw_nightmare_text(
            painter,
            QRectF(text_x, content_top - 1, text_w, 22),
            self._label,
            QFont(P.get("font_ui", "Segoe UI"), 11, QFont.Weight.Bold),
            1,
            "text_main",
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )

        self._draw_nightmare_text(
            painter,
            QRectF(text_x, content_top + 20, text_w, 20),
            self._file_hint,
            QFont(P.get("font_mono", "Consolas"), 10),
            2,
            "text_file",
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )

        self._draw_card_action(
            painter,
            self._pin_rect,
            icon_tool_pin,
            self._pinned,
            "pin",
        )
        self._draw_card_action(
            painter,
            self._favorite_rect,
            icon_favorite_star,
            self._favorite,
            "favorite",
        )

    def _card_quad(self, rect):
        corners = [
            QPointF(rect.left(), rect.top()),
            QPointF(rect.right(), rect.top()),
            QPointF(rect.right(), rect.bottom()),
            QPointF(rect.left(), rect.bottom()),
        ]
        if not self._hovered:
            return QPolygonF(corners)

        center = QPointF(rect.center())
        rx = math.radians(-self._tilt_y * 4.2)
        ry = math.radians(self._tilt_x * 4.2)
        cos_x, sin_x = math.cos(rx), math.sin(rx)
        cos_y, sin_y = math.cos(ry), math.sin(ry)
        camera = 800.0
        projected = []
        for corner in corners:
            x = corner.x() - center.x()
            y = corner.y() - center.y()
            y1 = y * cos_x
            z1 = y * sin_x
            x2 = x * cos_y + z1 * sin_y
            z2 = -x * sin_y + z1 * cos_y
            scale = camera / max(1.0, camera - z2)
            projected.append(QPointF(center.x() + x2 * scale, center.y() + y1 * scale))
        return QPolygonF(projected)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(5, 5, -5, -5)
        radius = _theme_int("card_radius", 8)
        perspective = self._perspective_enabled()
        pulse = 0.5 + 0.5 * math.sin(self._hover_phase * math.tau)
        transform = self._card_transform(rect)

        painter.save()
        if not transform.isIdentity():
            painter.setTransform(transform, True)
        if str(P.get("card_glass_shadow", "")).lower() in {"1", "true", "yes"}:
            shadow_alpha = _theme_int("card_glass_shadow_alpha", 36)
            painter.setPen(Qt.PenStyle.NoPen)
            if P.get("card_shadow_style") == "diffuse":
                for step, scale in enumerate((0.22, 0.16, 0.10), start=1):
                    painter.setBrush(self._color("shadow", int(shadow_alpha * scale), "shadow"))
                    painter.drawRoundedRect(
                        rect.adjusted(-step, 3 + step * 2, step, 3 + step * 2),
                        radius + step,
                        radius + step,
                    )
            else:
                painter.setBrush(self._color("shadow", shadow_alpha, "shadow"))
                painter.drawRoundedRect(rect.adjusted(1, 5, -1, 5), radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._card_fill(rect))
        painter.drawRoundedRect(rect, radius, radius)
        self._draw_card_texture(painter, rect, radius, pulse)
        self._draw_card_glass_overlay(painter, rect, radius, pulse)

        hover_chrome = str(P.get("card_hover_chrome", "true")).lower() not in {"0", "false", "no"}
        if self._hovered and perspective and hover_chrome:
            dx = self._mouse_pos.x() - self.width() / 2
            dy = self._mouse_pos.y() - self.height() / 2
            angle = math.atan2(dy, dx) - math.pi / 2
            shine_len = max(self.width(), self.height())
            shine = QLinearGradient(
                rect.center().x() - math.cos(angle) * shine_len,
                rect.center().y() - math.sin(angle) * shine_len,
                rect.center().x() + math.cos(angle) * shine_len,
                rect.center().y() + math.sin(angle) * shine_len,
            )
            shine_strength = _theme_float("shine_strength", 1.0)
            shine_alpha = int(max(18, min(105, (self._mouse_pos.y() / max(1, self.height())) * 82 * shine_strength)))
            shine.setColorAt(0.0, self._color("shine", shine_alpha))
            shine.setColorAt(0.42, self._color("shine", int(shine_alpha * 0.28)))
            shine.setColorAt(0.82, self._color("shine", 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(shine))
            painter.drawRoundedRect(rect, radius, radius)

            painter.setBrush(Qt.BrushStyle.NoBrush)
            border_width = _theme_float("border_glow_width", 3.3)
            painter.setPen(QPen(self._color("border_hov", int(95 + pulse * 105)), border_width + pulse * 0.7))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
            painter.setPen(QPen(self._color("border_hov", int(190 + pulse * 65)), 1.25))
            painter.drawRoundedRect(rect, radius, radius)

            light = self._color("highlight", int(42 + pulse * 38))
            shade = self._color("shadow", int(28 + pulse * 22))
            if self._tilt_x >= 0:
                painter.setPen(QPen(light, 2.0))
                painter.drawLine(rect.topRight() + QPoint(-1, radius), rect.bottomRight() + QPoint(-1, -radius))
                painter.setPen(QPen(shade, 1.5))
                painter.drawLine(rect.topLeft() + QPoint(1, radius), rect.bottomLeft() + QPoint(1, -radius))
            else:
                painter.setPen(QPen(light, 2.0))
                painter.drawLine(rect.topLeft() + QPoint(1, radius), rect.bottomLeft() + QPoint(1, -radius))
                painter.setPen(QPen(shade, 1.5))
                painter.drawLine(rect.topRight() + QPoint(-1, radius), rect.bottomRight() + QPoint(-1, -radius))
            if self._tilt_y <= 0:
                painter.setPen(QPen(light, 1.7))
                painter.drawLine(rect.topLeft() + QPoint(radius, 1), rect.topRight() + QPoint(-radius, 1))
            else:
                painter.setPen(QPen(light, 1.7))
                painter.drawLine(rect.bottomLeft() + QPoint(radius, -1), rect.bottomRight() + QPoint(-radius, -1))
            self._draw_nightmare_hover_corruption(painter, rect, radius, pulse)
        elif self._hovered:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._color("border_hov"), _theme_float("card_hover_border_width", 1.0)))
            painter.drawRoundedRect(rect, radius, radius)
            self._draw_nightmare_hover_corruption(painter, rect, radius, pulse)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._color("border"), 1.0))
            painter.drawRoundedRect(rect, radius, radius)

        self._draw_card_content(painter)
        painter.restore()
        painter.end()

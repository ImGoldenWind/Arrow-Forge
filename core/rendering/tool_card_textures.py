import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QPolygonF, QRadialGradient,
)

from core.runtime_paths import app_path
from core.themes import P
from core.utils.ui_helpers import _hash01, _theme_float, _theme_int


class ToolCardTextureMixin:
    def _draw_card_texture(self, painter, rect, radius, pulse):
        if not self._theme_personality_enabled():
            return
        texture = P.get("card_texture")
        if texture == "bubbles":
            self._draw_bubble_texture(painter, rect, radius, pulse)
        elif texture == "rain":
            self._draw_rain_texture(painter, rect, radius, pulse)
        elif texture == "mouse_glow":
            self._draw_mouse_glow_texture(painter, rect, radius, pulse)
        elif texture == "image_overlay":
            self._draw_image_overlay_texture(painter, rect, radius, pulse)
        elif texture == "gold_luxury":
            self._draw_gold_luxury_texture(painter, rect, radius, pulse)
        elif texture == "stone_threads":
            self._draw_stone_thread_texture(painter, rect, radius, pulse)
        elif texture == "terminal_crt":
            self._draw_terminal_crt_texture(painter, rect, radius, pulse)
        elif texture == "star_particles":
            self._draw_star_particle_texture(painter, rect, radius, pulse)
        elif texture == "diamond_facets":
            self._draw_diamond_facets_texture(painter, rect, radius, pulse)
        elif texture == "aero_glass":
            self._draw_aero_glass_texture(painter, rect, radius, pulse)
        elif texture == "frosted_glass":
            self._draw_frosted_glass_texture(painter, rect, radius, pulse)
        elif texture == "clay_plastic":
            self._draw_clay_plastic_texture(painter, rect, radius, pulse)
        elif texture == "nightmare_chaos":
            self._draw_nightmare_chaos_texture(painter, rect, radius, pulse)

    def _draw_bubble_texture(self, painter, rect, radius, pulse):
        alpha = _theme_int("card_bubble_alpha", 0)
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)

        motion_enabled = self._theme_personality_motion_enabled()
        seed_phase = (self._bubble_seed % 997) / 997.0
        texture_phase = (self._hover_phase + seed_phase) % 1.0 if motion_enabled else seed_phase
        texture_pulse = pulse if motion_enabled else 0.5
        travel = rect.height() + 62
        bubble_specs = (
            (0.08, 0.12, 18, "card_bubble", 5.5, 0.00, 0.82),
            (0.19, 0.72, 12, "card_bubble_alt", -3.5, 0.15, 1.38),
            (0.33, 1.04, 24, "card_bubble", 6.5, 0.36, 1.10),
            (0.48, 0.38, 15, "card_bubble_alt", 4.0, 0.62, 0.96),
            (0.62, 0.84, 36, "card_bubble", 7.5, 0.56, 0.68),
            (0.73, 0.18, 20, "card_bubble_alt", -5.0, 0.27, 1.24),
            (0.84, 1.16, 14, "card_bubble", 4.0, 0.44, 1.56),
            (0.91, 0.58, 27, "card_bubble_alt", -6.5, 0.79, 0.88),
        )
        for idx, (x_ratio, static_y_ratio, size, color_key, sway, phase_offset, speed) in enumerate(bubble_specs):
            bubble_seed = ((self._bubble_seed * (idx + 11)) % 101) / 101.0
            seeded_x = min(0.96, max(0.04, x_ratio + (bubble_seed - 0.5) * 0.08))
            seeded_phase = (phase_offset + bubble_seed * 0.19) % 1.0
            seeded_speed = speed * (0.88 + bubble_seed * 0.28)
            seeded_sway = sway * (0.75 + bubble_seed * 0.55)
            if motion_enabled:
                progress = (texture_phase * seeded_speed + seeded_phase) % 1.0
                y = rect.bottom() + size / 2 - progress * travel
                x = rect.left() + rect.width() * seeded_x + math.sin((progress + seeded_phase) * math.tau) * seeded_sway
                edge_fade = min(progress / 0.16, (1.0 - progress) / 0.12, 1.0)
                edge_fade = max(0.0, edge_fade)
            else:
                progress = static_y_ratio
                y = rect.top() + rect.height() * static_y_ratio
                x = rect.left() + rect.width() * seeded_x
                edge_fade = 1.0

            bubble_alpha = int((alpha + (18 if self._hovered else 0) + texture_pulse * 14) * edge_fade)
            if bubble_alpha <= 0:
                continue
            center = QPointF(x, y)
            radial = QRadialGradient(center, size / 2)
            edge = self._color(color_key, bubble_alpha, "highlight")
            inner = self._color("shine", int(bubble_alpha * 0.65))
            clear = self._color(color_key, 0, "highlight")
            radial.setColorAt(0.0, clear)
            radial.setColorAt(0.72, inner)
            radial.setColorAt(0.86, edge)
            radial.setColorAt(1.0, clear)
            painter.setPen(QPen(edge, 0.9))
            painter.setBrush(QBrush(radial))
            painter.drawEllipse(center, size / 2, size / 2)

        painter.restore()

    def _draw_aero_glass_texture(self, painter, rect, radius, pulse):
        alpha = max(0, min(255, _theme_int("card_aero_alpha", 58)))
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        top_gloss = QLinearGradient(
            QPointF(rect.left(), rect.top()),
            QPointF(rect.left(), rect.bottom()),
        )
        top_gloss.setColorAt(0.0, self._color("card_aero_glass", int(alpha * 1.35), "shine"))
        top_gloss.setColorAt(0.20, self._color("card_aero_glass", int(alpha * 0.58), "shine"))
        top_gloss.setColorAt(0.48, self._color("card_aero_alt", int(alpha * 0.20), "highlight"))
        top_gloss.setColorAt(1.0, self._color("card_aero", 0, "accent"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(top_gloss))
        painter.drawRect(rect)

        water_pool = QRadialGradient(
            QPointF(rect.left() + rect.width() * 0.18, rect.bottom() + rect.height() * 0.18),
            rect.width() * 0.92,
        )
        water_pool.setColorAt(0.0, self._color("card_aero", int(alpha * 0.72), "accent"))
        water_pool.setColorAt(0.46, self._color("card_aero_alt", int(alpha * 0.24), "highlight"))
        water_pool.setColorAt(1.0, self._color("card_aero", 0, "accent"))
        painter.setBrush(QBrush(water_pool))
        painter.drawRect(rect)

        sky_bloom = QRadialGradient(
            QPointF(rect.right() - rect.width() * 0.14, rect.top() + rect.height() * 0.12),
            rect.width() * 0.62,
        )
        sky_bloom.setColorAt(0.0, self._color("card_aero_glass", int(alpha * 0.96), "shine"))
        sky_bloom.setColorAt(0.36, self._color("card_aero_alt", int(alpha * 0.22), "highlight"))
        sky_bloom.setColorAt(1.0, self._color("card_aero_glass", 0, "shine"))
        painter.setBrush(QBrush(sky_bloom))
        painter.drawRect(rect)

        caustic_alpha = max(0, min(255, _theme_int("card_aero_caustic_alpha", 34)))
        if caustic_alpha > 0:
            motion_enabled = self._theme_personality_motion_enabled()
            seed_phase = (self._bubble_seed % 877) / 877.0
            phase = (self._hover_phase * 1.15 + seed_phase) % 1.0 if motion_enabled else seed_phase
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for idx in range(6):
                lane_seed = _hash01(self._bubble_seed + idx * 29.0)
                wave_seed = _hash01(self._bubble_seed + idx * 47.0)
                lane = 0.20 + idx * 0.105 + lane_seed * 0.035
                y = rect.top() + rect.height() * lane
                drift = math.sin((phase * (0.55 + wave_seed * 0.36) + lane_seed) * math.tau)
                y += drift * (4.0 + wave_seed * 4.5)
                start = QPointF(rect.left() - 18.0, y)
                c1 = QPointF(rect.left() + rect.width() * 0.24, y - 12.0 + lane_seed * 20.0)
                c2 = QPointF(rect.left() + rect.width() * 0.58, y + 13.0 - wave_seed * 18.0)
                end = QPointF(rect.right() + 18.0, y + math.sin((phase + idx * 0.23) * math.tau) * 8.0)
                caustic = QPainterPath()
                caustic.moveTo(start)
                caustic.cubicTo(c1, c2, end)
                color_key = "card_aero_caustic" if idx % 2 else "card_aero_glass"
                line_alpha = int(caustic_alpha * (0.48 + lane_seed * 0.46) * (0.82 + pulse * 0.18))
                pen = QPen(self._color(color_key, line_alpha, "highlight"), 0.85 + wave_seed * 0.75)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawPath(caustic)

        bubble_alpha = max(0, min(255, _theme_int("card_aero_bubble_alpha", 42)))
        if bubble_alpha > 0:
            motion_enabled = self._theme_personality_motion_enabled()
            seed_phase = (self._bubble_seed % 997) / 997.0
            phase = (self._hover_phase * 0.86 + seed_phase) % 1.0 if motion_enabled else seed_phase
            travel = rect.height() + 54.0
            for idx in range(12):
                x_seed = _hash01(self._bubble_seed + idx * 17.17)
                y_seed = _hash01(self._bubble_seed + idx * 31.31)
                size_seed = _hash01(self._bubble_seed + idx * 43.43)
                speed_seed = _hash01(self._bubble_seed + idx * 59.59)
                size = 5.0 + size_seed * 18.0
                x = rect.left() + rect.width() * (0.06 + x_seed * 0.88)
                if motion_enabled:
                    progress = (phase * (0.34 + speed_seed * 0.54) + y_seed) % 1.0
                    y = rect.bottom() + size * 0.5 - progress * travel
                    x += math.sin((progress + x_seed) * math.tau) * (3.0 + size_seed * 4.0)
                    edge_fade = min(progress / 0.14, (1.0 - progress) / 0.12, 1.0)
                    edge_fade = max(0.0, edge_fade)
                else:
                    y = rect.top() + rect.height() * (0.18 + y_seed * 0.68)
                    edge_fade = 1.0

                local_alpha = int((bubble_alpha + (14 if self._hovered else 0)) * (0.42 + size_seed * 0.58) * edge_fade)
                if local_alpha <= 0:
                    continue
                center = QPointF(x, y)
                bubble = QRadialGradient(center, size * 0.52)
                bubble.setColorAt(0.00, self._color("card_aero_glass", 0, "shine"))
                bubble.setColorAt(0.52, self._color("card_aero_alt", int(local_alpha * 0.18), "highlight"))
                bubble.setColorAt(0.78, self._color("card_aero_glass", int(local_alpha * 0.88), "shine"))
                bubble.setColorAt(1.00, self._color("card_aero", 0, "accent"))
                painter.setPen(QPen(self._color("card_aero_glass", int(local_alpha * 0.78), "shine"), 0.85))
                painter.setBrush(QBrush(bubble))
                painter.drawEllipse(center, size * 0.5, size * 0.5)

        if self._hovered:
            hover_alpha = max(0, min(255, _theme_int("card_aero_hover_glow_alpha", 46)))
            if hover_alpha > 0:
                mapped = self._map_from_visual_card(self._mouse_pos)
                center = QPointF(
                    max(rect.left(), min(rect.right(), mapped.x())),
                    max(rect.top(), min(rect.bottom(), mapped.y())),
                )
                hover_glow = QRadialGradient(center, max(rect.width(), rect.height()) * 0.72)
                hover_glow.setColorAt(0.0, self._color("card_aero_glass", int(hover_alpha * 1.12), "shine"))
                hover_glow.setColorAt(0.30, self._color("card_aero_alt", int(hover_alpha * 0.48), "highlight"))
                hover_glow.setColorAt(1.0, self._color("card_aero", 0, "accent"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(hover_glow))
                painter.drawRect(rect)

        rim = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom()))
        rim.setColorAt(0.0, self._color("card_aero_glass", int(alpha * 0.82), "shine"))
        rim.setColorAt(0.34, self._color("card_aero_glass", 0, "shine"))
        rim.setColorAt(0.72, self._color("card_aero_alt", int(alpha * 0.24), "highlight"))
        rim.setColorAt(1.0, self._color("card_aero_glass", int(alpha * 0.52), "shine"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(rim), 1.2))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        painter.restore()

    def _draw_frosted_glass_texture(self, painter, rect, radius, pulse):
        alpha = max(0, min(255, _theme_int("card_frost_alpha", 38)))
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.setPen(Qt.PenStyle.NoPen)

        soft_lift = QLinearGradient(
            QPointF(rect.left(), rect.top()),
            QPointF(rect.left(), rect.bottom()),
        )
        soft_lift.setColorAt(0.00, self._color("card_frost", int(alpha * 1.18), "shine"))
        soft_lift.setColorAt(0.18, self._color("card_frost", int(alpha * 0.56), "shine"))
        soft_lift.setColorAt(0.52, self._color("card_frost_alt", int(alpha * 0.18), "highlight"))
        soft_lift.setColorAt(1.00, self._color("card_frost", 0, "shine"))
        painter.setBrush(QBrush(soft_lift))
        painter.drawRect(rect)

        depth = QRadialGradient(
            QPointF(rect.right() - rect.width() * 0.12, rect.top() + rect.height() * 0.10),
            rect.width() * 0.82,
        )
        depth.setColorAt(0.00, self._color("card_frost", int(alpha * 0.58), "shine"))
        depth.setColorAt(0.42, self._color("card_frost_alt", int(alpha * 0.18), "highlight"))
        depth.setColorAt(1.00, self._color("card_frost", 0, "shine"))
        painter.setBrush(QBrush(depth))
        painter.drawRect(rect)

        vignette_alpha = max(0, min(255, _theme_int("card_frost_vignette_alpha", 42)))
        if vignette_alpha > 0:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
            vignette = QRadialGradient(QPointF(rect.center()), max(rect.width(), rect.height()) * 0.72)
            vignette.setColorAt(0.00, self._color("card_frost_shadow", 0, "shadow"))
            vignette.setColorAt(0.72, self._color("card_frost_shadow", 0, "shadow"))
            vignette.setColorAt(1.00, self._color("card_frost_shadow", vignette_alpha, "shadow"))
            painter.setBrush(QBrush(vignette))
            painter.drawRect(rect)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        line_alpha = max(0, min(255, _theme_int("card_frost_line_alpha", 26)))
        if line_alpha > 0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            motion_enabled = self._theme_personality_motion_enabled()
            seed_phase = (self._bubble_seed % 991) / 991.0
            phase = (self._hover_phase * 0.18 + seed_phase) % 1.0 if motion_enabled else seed_phase
            for idx in range(4):
                lane_seed = _hash01(self._bubble_seed + idx * 37.0)
                y = rect.top() + rect.height() * (0.18 + idx * 0.17 + lane_seed * 0.035)
                y += math.sin((phase + lane_seed) * math.tau) * 1.8
                start = QPointF(rect.left() + rect.width() * 0.06, y)
                end = QPointF(rect.right() - rect.width() * 0.06, y + (lane_seed - 0.5) * 6.0)
                highlight = QLinearGradient(start, end)
                highlight.setColorAt(0.00, self._color("card_frost", 0, "shine"))
                highlight.setColorAt(0.50, self._color("card_frost", int(line_alpha * (0.42 + lane_seed * 0.44)), "shine"))
                highlight.setColorAt(1.00, self._color("card_frost", 0, "shine"))
                pen = QPen(QBrush(highlight), 0.72)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.drawLine(start, end)

        grain_alpha = max(0, min(255, _theme_int("card_frost_grain_alpha", 14)))
        if grain_alpha > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            for idx in range(18):
                x_seed = _hash01(self._bubble_seed + idx * 17.0)
                y_seed = _hash01(self._bubble_seed + idx * 29.0)
                a_seed = _hash01(self._bubble_seed + idx * 43.0)
                local_alpha = int(grain_alpha * (0.28 + a_seed * 0.72))
                if local_alpha <= 0:
                    continue
                center = QPointF(
                    rect.left() + rect.width() * (0.06 + x_seed * 0.88),
                    rect.top() + rect.height() * (0.10 + y_seed * 0.80),
                )
                painter.setBrush(self._color("card_frost", local_alpha, "shine"))
                painter.drawEllipse(center, 0.72, 0.72)

        snow_alpha = max(0, min(255, _theme_int("card_frost_snow_alpha", 0)))
        snow_count = max(0, min(28, _theme_int("card_frost_snow_count", 0)))
        if snow_alpha > 0 and snow_count > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            motion_enabled = self._theme_personality_motion_enabled()
            seed_phase = (self._bubble_seed % 997) / 997.0
            phase = (self._hover_phase * 0.24 + seed_phase) % 1.0 if motion_enabled else seed_phase
            travel = rect.height() + 14.0
            for idx in range(snow_count):
                x_seed = _hash01(self._bubble_seed + idx * 19.19)
                y_seed = _hash01(self._bubble_seed + idx * 31.31)
                size_seed = _hash01(self._bubble_seed + idx * 47.47)
                speed_seed = _hash01(self._bubble_seed + idx * 61.61)
                alpha_seed = _hash01(self._bubble_seed + idx * 73.73)
                size = 0.9 + size_seed * 2.2
                if motion_enabled:
                    progress = (phase * (0.18 + speed_seed * 0.24) + y_seed) % 1.0
                    y = rect.top() - 7.0 + progress * travel
                    x = rect.left() + rect.width() * (0.04 + x_seed * 0.92)
                    x += math.sin((progress + x_seed) * math.tau) * (2.0 + speed_seed * 5.0)
                    edge_fade = min(progress / 0.12, (1.0 - progress) / 0.12, 1.0)
                    edge_fade = max(0.0, edge_fade)
                else:
                    x = rect.left() + rect.width() * (0.04 + x_seed * 0.92)
                    y = rect.top() + rect.height() * (0.08 + y_seed * 0.84)
                    edge_fade = 1.0

                local_alpha = int(snow_alpha * (0.30 + alpha_seed * 0.70) * edge_fade)
                if local_alpha <= 0:
                    continue
                center = QPointF(x, y)
                if idx % 6 == 0:
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    pen = QPen(self._color("shine", min(255, int(local_alpha * 1.18)), "shine"), 0.52)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    painter.setPen(pen)
                    arm_len = size * 2.4
                    for arm in range(6):
                        angle = (arm / 6.0) * math.tau
                        dx = math.cos(angle) * arm_len
                        dy = math.sin(angle) * arm_len
                        painter.drawLine(
                            QPointF(center.x() - dx * 0.25, center.y() - dy * 0.25),
                            QPointF(center.x() + dx, center.y() + dy),
                        )
                    painter.setPen(Qt.PenStyle.NoPen)
                else:
                    flake = QRadialGradient(center, size * 2.6)
                    flake.setColorAt(0.00, self._color("shine", min(255, int(local_alpha * 1.20)), "shine"))
                    flake.setColorAt(0.36, self._color("card_frost", int(local_alpha * 0.55), "shine"))
                    flake.setColorAt(1.00, self._color("card_frost", 0, "shine"))
                    painter.setBrush(QBrush(flake))
                    painter.drawEllipse(center, size * 2.6, size * 2.6)

        sparkle_alpha = max(0, min(255, _theme_int("card_frost_sparkle_alpha", 0)))
        if sparkle_alpha > 0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            motion_enabled = self._theme_personality_motion_enabled()
            seed_phase = (self._bubble_seed % 677) / 677.0
            phase = (self._hover_phase * 0.42 + seed_phase) % 1.0 if motion_enabled else seed_phase
            for idx in range(5):
                x_seed = _hash01(self._bubble_seed + idx * 89.0)
                y_seed = _hash01(self._bubble_seed + idx * 97.0)
                blink_seed = _hash01(self._bubble_seed + idx * 109.0)
                blink = 0.5 + 0.5 * math.sin((phase + blink_seed) * math.tau)
                local_alpha = int(sparkle_alpha * (0.18 + blink * 0.82))
                if local_alpha <= 4:
                    continue
                center = QPointF(
                    rect.left() + rect.width() * (0.12 + x_seed * 0.76),
                    rect.top() + rect.height() * (0.16 + y_seed * 0.66),
                )
                arm = 2.2 + blink_seed * 2.6
                painter.setPen(QPen(self._color("shine", local_alpha, "shine"), 0.55))
                painter.drawLine(QPointF(center.x() - arm, center.y()), QPointF(center.x() + arm, center.y()))
                painter.drawLine(QPointF(center.x(), center.y() - arm), QPointF(center.x(), center.y() + arm))

        crack_alpha = max(0, min(255, _theme_int("card_frost_crack_alpha", 0)))
        if crack_alpha > 0:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._color("card_frost", crack_alpha, "shine"), 0.55))
            for idx, origin in enumerate((0.16, 0.78)):
                seed = _hash01(self._bubble_seed + idx * 131.0)
                start = QPointF(
                    rect.left() + rect.width() * origin,
                    rect.top() + rect.height() * (0.12 + seed * 0.16),
                )
                crack = QPainterPath(start)
                for step in range(1, 4):
                    step_seed = _hash01(self._bubble_seed + idx * 151.0 + step * 17.0)
                    crack.lineTo(QPointF(
                        start.x() + rect.width() * (0.05 * step + (step_seed - 0.5) * 0.035),
                        start.y() + rect.height() * (0.05 * step + (seed - 0.5) * 0.025),
                    ))
                painter.drawPath(crack)

        if self._hovered:
            hover_alpha = max(0, min(255, _theme_int("card_frost_hover_bloom_alpha", 0)))
            if hover_alpha > 0:
                mapped = self._map_from_visual_card(self._mouse_pos)
                center = QPointF(
                    max(rect.left(), min(rect.right(), mapped.x())),
                    max(rect.top(), min(rect.bottom(), mapped.y())),
                )
                frost_bloom = QRadialGradient(center, max(rect.width(), rect.height()) * 0.58)
                frost_bloom.setColorAt(0.00, self._color("shine", int(hover_alpha * 0.86), "shine"))
                frost_bloom.setColorAt(0.36, self._color("card_frost_alt", int(hover_alpha * 0.32), "highlight"))
                frost_bloom.setColorAt(1.00, self._color("card_frost", 0, "shine"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(frost_bloom))
                painter.drawRect(rect)

        rim = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom()))
        rim.setColorAt(0.00, self._color("card_frost", int(alpha * 1.10), "shine"))
        rim.setColorAt(0.42, self._color("card_frost", 0, "shine"))
        rim.setColorAt(1.00, self._color("card_frost", int(alpha * 0.50), "shine"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(rim), 1.0))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        painter.restore()

    def _draw_clay_plastic_texture(self, painter, rect, radius, pulse):
        alpha = max(0, min(255, _theme_int("card_clay_alpha", 62)))
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        top_lift = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))
        top_lift.setColorAt(0.00, self._color("card_clay_highlight", int(alpha * 1.35), "shine"))
        top_lift.setColorAt(0.24, self._color("card_clay_highlight", int(alpha * 0.58), "shine"))
        top_lift.setColorAt(0.56, self._color("card_clay_blush", int(alpha * 0.20), "highlight"))
        top_lift.setColorAt(1.00, self._color("card_clay_highlight", 0, "shine"))
        painter.setBrush(QBrush(top_lift))
        painter.drawRect(rect)

        soft_reflection = QRadialGradient(
            QPointF(rect.left() + rect.width() * 0.20, rect.top() + rect.height() * 0.12),
            rect.width() * 0.78,
        )
        soft_reflection.setColorAt(0.00, self._color("card_clay_highlight", int(alpha * 0.88), "shine"))
        soft_reflection.setColorAt(0.34, self._color("card_clay_peach", int(alpha * 0.24), "highlight"))
        soft_reflection.setColorAt(1.00, self._color("card_clay_highlight", 0, "shine"))
        painter.setBrush(QBrush(soft_reflection))
        painter.drawRect(rect)

        jelly_alpha = max(0, min(255, _theme_int("card_clay_jelly_alpha", 30)))
        if jelly_alpha > 0:
            motion_enabled = self._theme_personality_motion_enabled()
            seed_phase = (self._bubble_seed % 613) / 613.0
            phase = (self._hover_phase * 0.24 + seed_phase) % 1.0 if motion_enabled else seed_phase
            for idx in range(3):
                lane_seed = _hash01(self._bubble_seed + idx * 41.0)
                y = rect.top() + rect.height() * (0.20 + idx * 0.16 + lane_seed * 0.04)
                y += math.sin((phase + lane_seed) * math.tau) * 2.6
                start = QPointF(rect.left() + rect.width() * 0.08, y)
                end = QPointF(rect.right() - rect.width() * 0.08, y + (lane_seed - 0.5) * 8.0)
                line = QLinearGradient(start, end)
                line.setColorAt(0.00, self._color("card_clay_highlight", 0, "shine"))
                line.setColorAt(0.46, self._color("card_clay_highlight", int(jelly_alpha * (0.56 + lane_seed * 0.34)), "shine"))
                line.setColorAt(0.70, self._color("card_clay_blush", int(jelly_alpha * 0.36), "highlight"))
                line.setColorAt(1.00, self._color("card_clay_highlight", 0, "shine"))
                pen = QPen(QBrush(line), 1.05 + lane_seed * 0.55)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(pen)
                painter.drawLine(start, end)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        lower_shadow = QRadialGradient(
            QPointF(rect.right() - rect.width() * 0.10, rect.bottom() + rect.height() * 0.18),
            rect.width() * 0.86,
        )
        lower_shadow.setColorAt(0.00, self._color("card_clay_shadow", int(alpha * 0.50), "shadow"))
        lower_shadow.setColorAt(0.48, self._color("card_clay_shadow", int(alpha * 0.18), "shadow"))
        lower_shadow.setColorAt(1.00, self._color("card_clay_shadow", 0, "shadow"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(lower_shadow))
        painter.drawRect(rect)

        edge_shadow = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom()))
        edge_shadow.setColorAt(0.00, self._color("card_clay_shadow", 0, "shadow"))
        edge_shadow.setColorAt(0.68, self._color("card_clay_shadow", int(alpha * 0.10), "shadow"))
        edge_shadow.setColorAt(1.00, self._color("card_clay_shadow", int(alpha * 0.36), "shadow"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(edge_shadow), 2.0))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        rim = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom()))
        rim.setColorAt(0.00, self._color("card_clay_highlight", int(alpha * 0.86), "shine"))
        rim.setColorAt(0.30, self._color("card_clay_highlight", int(alpha * 0.18), "shine"))
        rim.setColorAt(0.76, self._color("card_clay_blush", int(alpha * 0.16), "highlight"))
        rim.setColorAt(1.00, self._color("card_clay_highlight", int(alpha * 0.34), "shine"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(rim), 1.25))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)

        grain_alpha = max(0, min(255, _theme_int("card_clay_grain_alpha", 5)))
        if grain_alpha > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            for idx in range(14):
                x_seed = _hash01(self._bubble_seed + idx * 23.0)
                y_seed = _hash01(self._bubble_seed + idx * 37.0)
                a_seed = _hash01(self._bubble_seed + idx * 61.0)
                painter.setBrush(self._color("card_clay_highlight", int(grain_alpha * (0.35 + a_seed * 0.65)), "shine"))
                painter.drawEllipse(
                    QPointF(
                        rect.left() + rect.width() * (0.08 + x_seed * 0.84),
                        rect.top() + rect.height() * (0.10 + y_seed * 0.78),
                    ),
                    0.72,
                    0.72,
                )

        painter.restore()

    def _draw_nightmare_chaos_texture(self, painter, rect, radius, pulse):
        alpha = max(0, min(255, _theme_int("card_nightmare_alpha", 84)))
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setPen(Qt.PenStyle.NoPen)

        motion_enabled = self._theme_personality_motion_enabled()
        seed_phase = (self._bubble_seed % 997) / 997.0
        phase = (self._hover_phase * (1.25 if self._hovered else 0.54) + seed_phase) % 1.0 if motion_enabled else seed_phase
        corruption = 1.0 + (0.28 if self._hovered else 0.0) + pulse * (0.18 if motion_enabled else 0.0)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        wash_specs = (
            (0.06, 0.12, 0.74, "card_nightmare_toxic", 1.08),
            (0.58, 0.03, 0.54, "card_nightmare_cyan", 0.72),
            (0.42, 0.62, 0.74, "card_nightmare_red", 0.88),
            (0.12, 0.54, 0.48, "card_nightmare_pink", 0.66),
        )
        for idx, (x_ratio, y_ratio, span, color_key, strength) in enumerate(wash_specs):
            wobble = math.sin((phase * (0.52 + idx * 0.17) + idx * 0.21) * math.tau)
            x = rect.left() + rect.width() * (x_ratio + wobble * 0.025)
            y = rect.top() + rect.height() * (y_ratio - wobble * 0.018)
            w = rect.width() * span
            h = rect.height() * (0.28 + _hash01(self._bubble_seed + idx * 37.0) * 0.26)
            slant = rect.width() * (0.10 + _hash01(self._bubble_seed + idx * 53.0) * 0.18)
            wash = QLinearGradient(QPointF(x, y), QPointF(x + w, y + h))
            wash.setColorAt(0.00, self._color(color_key, 0, "accent"))
            wash.setColorAt(0.18, self._color(color_key, int(alpha * 0.52 * strength * corruption), "accent"))
            wash.setColorAt(0.44, self._color("card_nightmare_yellow", int(alpha * 0.12 * strength), "shine"))
            wash.setColorAt(0.74, self._color(color_key, int(alpha * 0.18 * strength), "accent"))
            wash.setColorAt(1.00, self._color(color_key, 0, "accent"))
            painter.setBrush(QBrush(wash))
            painter.drawPolygon(QPolygonF([
                QPointF(x - slant, y),
                QPointF(x + w, y + h * 0.10),
                QPointF(x + w + slant, y + h),
                QPointF(x, y + h * 0.82),
            ]))

        stripe_count = max(0, min(18, _theme_int("card_nightmare_stripes", 7)))
        if stripe_count > 0:
            stripe_w = max(10.0, rect.width() / (stripe_count + 2.0))
            for idx in range(stripe_count):
                stripe_seed = _hash01(self._bubble_seed + idx * 11.71)
                x = rect.left() - rect.width() * 0.36 + idx * stripe_w * 1.42
                x += math.sin((phase * (0.8 + stripe_seed) + stripe_seed) * math.tau) * 9.0
                color_key = "card_nightmare_red" if idx % 3 == 0 else "card_nightmare_toxic" if idx % 3 == 1 else "card_nightmare_cyan"
                stripe = QLinearGradient(QPointF(x, rect.top()), QPointF(x + stripe_w, rect.bottom()))
                stripe.setColorAt(0.00, self._color(color_key, 0, "accent"))
                stripe.setColorAt(0.32, self._color(color_key, int(alpha * (0.14 + stripe_seed * 0.18)), "accent"))
                stripe.setColorAt(0.52, self._color("card_nightmare_yellow", int(alpha * 0.10), "shine"))
                stripe.setColorAt(1.00, self._color(color_key, 0, "accent"))
                painter.setBrush(QBrush(stripe))
                painter.drawPolygon(QPolygonF([
                    QPointF(x, rect.top() - 8),
                    QPointF(x + stripe_w * 0.58, rect.top() - 8),
                    QPointF(x + stripe_w * 1.34, rect.bottom() + 8),
                    QPointF(x + stripe_w * 0.58, rect.bottom() + 8),
                ]))

        tear_count = max(3, min(12, _theme_int("card_nightmare_tears", 7)))
        for idx in range(tear_count):
            y_seed = _hash01(self._bubble_seed + idx * 23.17)
            x_seed = _hash01(self._bubble_seed + idx * 41.41)
            color_seed = _hash01(self._bubble_seed + idx * 67.67)
            y = rect.top() + rect.height() * (0.08 + y_seed * 0.84)
            h = 2.0 + _hash01(self._bubble_seed + idx * 73.73) * 7.0
            drift = math.sin((phase * (1.2 + color_seed) + y_seed) * math.tau) * (6.0 + color_seed * 18.0)
            x = rect.left() - 12.0 + x_seed * rect.width() * 0.20 + drift
            w = rect.width() * (0.38 + _hash01(self._bubble_seed + idx * 89.89) * 0.74)
            color_key = "card_nightmare_cyan" if color_seed < 0.34 else "card_nightmare_toxic" if color_seed < 0.68 else "card_nightmare_red"
            tear = QLinearGradient(QPointF(x, y), QPointF(x + w, y))
            tear.setColorAt(0.00, self._color(color_key, 0, "accent"))
            tear.setColorAt(0.18, self._color(color_key, int(alpha * 0.52 * corruption), "accent"))
            tear.setColorAt(0.50, self._color("card_nightmare_yellow", int(alpha * 0.20), "shine"))
            tear.setColorAt(0.82, self._color(color_key, int(alpha * 0.28), "accent"))
            tear.setColorAt(1.00, self._color(color_key, 0, "accent"))
            painter.setBrush(QBrush(tear))
            painter.drawRect(QRectF(x, y, w, h))

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        scan_alpha = max(0, min(255, _theme_int("card_nightmare_scanline_alpha", 26)))
        if scan_alpha > 0:
            scan_a = int(scan_alpha * (0.72 + pulse * 0.28))
            painter.setPen(QPen(self._color("card_nightmare_cyan", scan_a, "secondary"), 0.7))
            offset = int(phase * 8) % 8 if motion_enabled else int(seed_phase * 8) % 8
            for y in range(int(rect.top()) + offset, int(rect.bottom()), 8):
                painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.setPen(QPen(self._color("card_nightmare_noise", int(scan_a * 0.58), "shine"), 1.0))
            for idx in range(28):
                n = _hash01(self._bubble_seed + idx * 13.37)
                if n < 0.36 and not self._hovered:
                    continue
                x = rect.left() + _hash01(self._bubble_seed + idx * 19.19) * rect.width()
                y = rect.top() + _hash01(self._bubble_seed + idx * 31.31) * rect.height()
                painter.drawPoint(QPointF(x, y))

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        patch_count = max(0, min(18, _theme_int("card_nightmare_patches", 8)))
        for idx in range(patch_count):
            x_seed = _hash01(self._bubble_seed + idx * 17.03)
            y_seed = _hash01(self._bubble_seed + idx * 29.09)
            tone_seed = _hash01(self._bubble_seed + idx * 47.47)
            x = rect.left() + rect.width() * (0.02 + x_seed * 0.88)
            y = rect.top() + rect.height() * (0.04 + y_seed * 0.82)
            cell = 3.0 + tone_seed * 5.0
            cols = 2 + int(_hash01(self._bubble_seed + idx * 61.61) * 4)
            rows = 1 + int(_hash01(self._bubble_seed + idx * 73.73) * 3)
            color_key = "card_nightmare_yellow" if idx % 4 == 0 else "card_nightmare_pink" if idx % 4 == 1 else "card_nightmare_cyan"
            painter.save()
            painter.translate(QPointF(x, y))
            painter.rotate(-18.0 + tone_seed * 36.0)
            painter.setPen(Qt.PenStyle.NoPen)
            for row in range(rows):
                for col in range(cols):
                    if (row + col + idx) % 2:
                        continue
                    painter.setBrush(self._color(color_key, int(alpha * (0.14 + tone_seed * 0.18)), "accent"))
                    painter.drawRect(QRectF(col * cell, row * cell, cell * 0.92, cell * 0.92))
            painter.restore()

        shape_count = max(4, min(14, _theme_int("card_nightmare_shapes", 8)))
        for idx in range(shape_count):
            x_seed = _hash01(self._bubble_seed + idx * 101.1)
            y_seed = _hash01(self._bubble_seed + idx * 131.3)
            size_seed = _hash01(self._bubble_seed + idx * 151.5)
            rot = (phase * (18 + idx * 7) + x_seed * 360) % 360
            center = QPointF(
                rect.left() + rect.width() * (0.08 + x_seed * 0.84),
                rect.top() + rect.height() * (0.12 + y_seed * 0.74),
            )
            size = 7.0 + size_seed * 22.0
            color_key = ("card_nightmare_pink", "card_nightmare_toxic", "card_nightmare_cyan", "card_nightmare_red")[idx % 4]
            painter.save()
            painter.translate(center)
            painter.rotate(rot)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._color(color_key, int(alpha * (0.28 + size_seed * 0.38)), "accent"), 0.8 + size_seed * 0.6))
            if idx % 3 == 0:
                painter.drawRect(QRectF(-size * 0.55, -size * 0.36, size * 1.1, size * 0.72))
            elif idx % 3 == 1:
                smile = QPainterPath()
                smile.moveTo(-size * 0.44, -size * 0.10)
                smile.cubicTo(-size * 0.18, size * 0.46, size * 0.24, size * 0.46, size * 0.50, -size * 0.08)
                painter.drawPath(smile)
                painter.drawRect(QRectF(-size * 0.30, -size * 0.28, 3.0, 2.0))
                painter.drawLine(QPointF(size * 0.22, -size * 0.28), QPointF(size * 0.34, -size * 0.16))
                painter.drawLine(QPointF(size * 0.34, -size * 0.28), QPointF(size * 0.22, -size * 0.16))
            else:
                shard = QPolygonF([
                    QPointF(-size * 0.45, size * 0.36),
                    QPointF(-size * 0.10, -size * 0.48),
                    QPointF(size * 0.58, -size * 0.12),
                    QPointF(size * 0.14, size * 0.42),
                ])
                painter.drawPolygon(shard)
            painter.restore()

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        edge_alpha = max(0, min(255, _theme_int("card_nightmare_edge_alpha", 58)))
        if edge_alpha > 0:
            edge_offset = 1.0 + (2.0 * pulse if self._hovered else 0.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self._color("card_nightmare_cyan", edge_alpha, "secondary"), 0.75))
            painter.drawLine(QPointF(rect.left() + radius + edge_offset, rect.top() + 1), QPointF(rect.right() - radius, rect.top() + 1))
            painter.drawLine(QPointF(rect.left() + 1 + edge_offset, rect.top() + radius), QPointF(rect.left() + 1 + edge_offset, rect.bottom() - radius))
            painter.setPen(QPen(self._color("card_nightmare_red", int(edge_alpha * 0.72), "highlight"), 0.75))
            painter.drawLine(QPointF(rect.left() + radius, rect.bottom() - 1 - edge_offset), QPointF(rect.right() - radius - edge_offset, rect.bottom() - 1 - edge_offset))
            painter.drawLine(QPointF(rect.right() - 1, rect.top() + radius + edge_offset), QPointF(rect.right() - 1, rect.bottom() - radius))

        painter.restore()

    def _draw_rain_texture(self, painter, rect, radius, pulse):
        if not self._theme_personality_motion_enabled():
            return

        alpha = _theme_int("card_rain_alpha", 0)
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)

        seed_phase = (self._bubble_seed % 997) / 997.0
        texture_phase = self._hover_phase * 5.2 + seed_phase
        rain_count = max(8, min(28, _theme_int("card_rain_count", 18)))
        travel_y = rect.height() + 150
        travel_x = 58
        active_portion = 0.74

        def draw_row(count, row_offset, opacity_scale, speed_scale, length_scale):
            for idx in range(count):
                drop_seed = _hash01(self._bubble_seed + row_offset * 97.0 + idx * 19.17)
                delay_seed = _hash01(self._bubble_seed + row_offset * 131.0 + idx * 31.31)
                speed_seed = _hash01(self._bubble_seed + row_offset * 173.0 + idx * 43.43)
                lane_seed = _hash01(self._bubble_seed + row_offset * 211.0 + idx * 59.59)

                x_ratio = ((idx + lane_seed * 0.72) / max(1, count)) % 1.0
                length = (30 + drop_seed * 30) * length_scale
                speed = (0.78 + speed_seed * 0.58) * speed_scale
                cycle = (texture_phase * speed + delay_seed) % 1.0
                if cycle > active_portion:
                    continue

                progress = cycle / active_portion
                stem_opacity = min(progress / 0.10, (1.0 - progress) / 0.18, 1.0)
                stem_opacity = max(0.0, stem_opacity)
                rain_alpha = int(alpha * opacity_scale * stem_opacity)
                if rain_alpha <= 0:
                    continue

                x = rect.left() - travel_x + rect.width() * x_ratio + progress * travel_x
                y = rect.top() - length - 36 + progress * travel_y
                start = QPointF(x - length * 0.20, y - length * 0.50)
                end = QPointF(x + length * 0.20, y + length * 0.50)

                color_key = "card_rain_alt" if (idx + row_offset) % 4 == 0 else "card_rain"
                head = self._color(color_key, rain_alpha, "text_sec")
                tail = self._color(color_key, 0, "text_sec")
                stem = QLinearGradient(start, end)
                stem.setColorAt(0.0, tail)
                stem.setColorAt(0.62, self._color(color_key, int(rain_alpha * 0.42), "text_sec"))
                stem.setColorAt(1.0, head)
                painter.setPen(QPen(QBrush(stem), 0.7 + drop_seed * 0.45))
                painter.drawLine(start, end)

        draw_row(max(5, rain_count // 2), 1, 0.38, 0.78, 0.72)
        draw_row(rain_count, 2, 1.0, 1.0, 1.0)

        painter.restore()

    def _draw_mouse_glow_texture(self, painter, rect, radius, pulse):
        if not self._hovered:
            return

        alpha = _theme_int("card_mouse_glow_alpha", 0)
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)

        mapped = self._map_from_visual_card(self._mouse_pos)
        center = QPointF(
            max(rect.left(), min(rect.right(), mapped.x())),
            max(rect.top(), min(rect.bottom(), mapped.y())),
        )
        radius_px = max(58.0, min(rect.width(), rect.height()) * 0.78)
        glow = QRadialGradient(center, radius_px)
        glow.setColorAt(0.0, self._color("card_mouse_glow", int(alpha + pulse * 16), "accent"))
        glow.setColorAt(0.34, self._color("card_mouse_glow_alt", int(alpha * 0.32), "highlight"))
        glow.setColorAt(1.0, self._color("card_mouse_glow", 0, "accent"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawRoundedRect(rect, radius, radius)

        painter.restore()

    def _draw_image_overlay_texture(self, painter, rect, radius, pulse):
        texture = self._image_overlay_pixmap(rect.size())
        if texture is None:
            return

        opacity = max(0.0, min(1.0, _theme_float("card_texture_opacity", 0.18)))
        if opacity <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)

        painter.setOpacity(opacity)
        painter.drawPixmap(rect, texture)

        tint_opacity = max(0.0, min(1.0, _theme_float("card_texture_tint_opacity", 0.0)))
        tint_color = QColor(P.get("card_texture_tint", P.get("secondary", "#FFFFFF")))
        if tint_opacity > 0 and tint_color.isValid():
            tint_color.setAlpha(int(255 * tint_opacity))
            painter.setOpacity(1.0)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SoftLight)
            painter.fillRect(rect, tint_color)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.restore()

    def _draw_gold_luxury_texture(self, painter, rect, radius, pulse):
        alpha = max(0, min(255, _theme_int("card_gold_alpha", 54)))
        if alpha <= 0:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        corner = QRadialGradient(
            QPointF(rect.left() + rect.width() * 0.12, rect.bottom() + rect.height() * 0.05),
            rect.width() * 0.72,
        )
        corner.setColorAt(0.0, self._color("card_gold", int(alpha * 0.72), "accent"))
        corner.setColorAt(0.42, self._color("card_gold", int(alpha * 0.18), "accent"))
        corner.setColorAt(1.0, self._color("card_gold", 0, "accent"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(corner))
        painter.drawRect(rect)

        crown = QRadialGradient(
            QPointF(rect.right() + rect.width() * 0.08, rect.top() - rect.height() * 0.18),
            rect.width() * 0.58,
        )
        crown.setColorAt(0.0, self._color("card_gold_flash", int(alpha * 0.36), "shine"))
        crown.setColorAt(0.52, self._color("card_gold", int(alpha * 0.09), "accent"))
        crown.setColorAt(1.0, self._color("card_gold", 0, "accent"))
        painter.setBrush(QBrush(crown))
        painter.drawRect(rect)

        edge = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.top()))
        edge.setColorAt(0.0, self._color("card_gold", 0, "accent"))
        edge.setColorAt(0.18, self._color("card_gold_flash", int(alpha * 0.58), "shine"))
        edge.setColorAt(0.50, self._color("card_gold", int(alpha * 0.18), "accent"))
        edge.setColorAt(0.82, self._color("card_gold_flash", int(alpha * 0.42), "shine"))
        edge.setColorAt(1.0, self._color("card_gold", 0, "accent"))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(edge), 0.9))
        painter.drawLine(rect.topLeft() + QPoint(radius, 1), rect.topRight() + QPoint(-radius, 1))

        painter.restore()

    def _draw_terminal_crt_texture(self, painter, rect, radius, pulse):
        texture = self._terminal_crt_pixmap(rect.size())
        if texture is None:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(rect, texture)

        if self._theme_personality_motion_enabled():
            blink = int(self._hover_phase * 8 + (self._bubble_seed % 3)) % 2 == 0
            if blink:
                cursor_alpha = max(0, min(255, _theme_int("card_terminal_cursor_alpha", 118)))
                cursor_x = rect.right() - 34
                cursor_y = rect.top() + 17 + ((_hash01(self._bubble_seed) * 3) // 1) * 16
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._color("card_terminal_cursor", cursor_alpha, "accent"))
                painter.drawRect(QRectF(cursor_x, cursor_y, 8, 12))

        painter.restore()

    def _terminal_crt_pixmap(self, size):
        if size.width() <= 1 or size.height() <= 1:
            return None

        alpha = max(0, min(255, _theme_int("card_terminal_alpha", 72)))
        if alpha <= 0:
            return None

        cache_key = (
            "terminal_crt",
            size.width(),
            size.height(),
            alpha,
            P.get("card_terminal_scanline"),
            P.get("card_terminal_noise"),
            P.get("card_terminal_warning"),
            P.get("accent"),
            P.get("font_mono"),
            self._bubble_seed,
        )
        if self._texture_cache_key == cache_key and self._texture_cache_pixmap is not None:
            return self._texture_cache_pixmap

        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        w = size.width()
        h = size.height()
        rect = QRectF(0, 0, w, h)
        scanline = self._color("card_terminal_scanline", int(alpha * 0.34), "accent")
        for y in range(1, h, 4):
            painter.setPen(QPen(scanline, 1.0))
            painter.drawLine(0, y, w, y)

        painter.setPen(QPen(self._color("card_terminal_grid", int(alpha * 0.16), "accent"), 0.7))
        for x in range(24 + int(_hash01(self._bubble_seed) * 18), w, 96):
            painter.drawLine(x, 0, x, h)

        noise = self._color("card_terminal_noise", int(alpha * 0.22), "accent")
        painter.setPen(QPen(noise, 1.0))
        for idx in range(34):
            x = int(_hash01(self._bubble_seed + idx * 17.0) * w)
            y = int(_hash01(self._bubble_seed + idx * 31.0) * h)
            painter.drawPoint(x, y)

        frame = self._color("card_terminal_frame", int(alpha * 0.68), "accent")
        painter.setPen(QPen(frame, 1.0))
        corner = 18
        painter.drawLine(8, 8, 8 + corner, 8)
        painter.drawLine(8, 8, 8, 8 + corner)
        painter.drawLine(w - 8, 8, w - 8 - corner, 8)
        painter.drawLine(w - 8, 8, w - 8, 8 + corner)
        painter.drawLine(8, h - 8, 8 + corner, h - 8)
        painter.drawLine(8, h - 8, 8, h - 8 - corner)
        painter.drawLine(w - 8, h - 8, w - 8 - corner, h - 8)
        painter.drawLine(w - 8, h - 8, w - 8, h - 8 - corner)

        painter.setFont(QFont(P.get("font_mono", "Consolas"), 7, QFont.Weight.Bold))
        text_alpha = int(alpha * 0.74)
        painter.setPen(self._color("card_terminal_text", text_alpha, "accent"))
        node = int(_hash01(self._bubble_seed + 9.0) * 900 + 100)
        mem = int(_hash01(self._bubble_seed + 19.0) * 88 + 11)
        rx = int(_hash01(self._bubble_seed + 29.0) * 9000 + 1000)
        painter.drawText(QRectF(14, 12, w - 28, 12), Qt.AlignmentFlag.AlignLeft, f"> CONNECTED :: NODE-{node}")
        painter.drawText(QRectF(14, 28, w - 28, 12), Qt.AlignmentFlag.AlignLeft, f"MEM:{mem:02d}%  RX:{rx:04d}  TRACE:OK")

        if _hash01(self._bubble_seed + 43.0) > 0.56:
            painter.setPen(self._color("card_terminal_warning", int(alpha * 0.82), "warning"))
            painter.drawText(QRectF(w - 116, h - 24, 100, 12), Qt.AlignmentFlag.AlignRight, "WARN: LATENCY")

        vignette = QRadialGradient(QPointF(w * 0.5, h * 0.48), max(w, h) * 0.70)
        vignette.setColorAt(0.0, self._color("card_terminal_vignette", 0, "accent"))
        vignette.setColorAt(0.78, self._color("card_terminal_vignette", 0, "accent"))
        vignette.setColorAt(1.0, self._color("card_terminal_vignette", int(alpha * 0.36), "accent"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(vignette))
        painter.drawRect(rect)

        painter.end()
        self._texture_cache_key = cache_key
        self._texture_cache_pixmap = pixmap
        return pixmap

    def _draw_stone_thread_texture(self, painter, rect, radius, pulse):
        texture = self._stone_thread_pixmap(rect.size())
        if texture is None:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(rect, texture)
        painter.restore()

    def _stone_thread_pixmap(self, size):
        if size.width() <= 1 or size.height() <= 1:
            return None

        alpha = max(0, min(255, _theme_int("card_thread_alpha", 72)))
        if alpha <= 0:
            return None

        thread_count = max(4, min(16, _theme_int("card_thread_count", 9)))
        cache_key = (
            "stone_threads",
            size.width(),
            size.height(),
            thread_count,
            alpha,
            P.get("card_thread"),
            P.get("card_thread_alt"),
            P.get("card_thread_flash"),
            P.get("card_thread_weave"),
            P.get("card_thread_knot_alpha"),
            self._bubble_seed,
        )
        if self._texture_cache_key == cache_key and self._texture_cache_pixmap is not None:
            return self._texture_cache_pixmap

        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)

        weave = max(0.0, min(1.0, _theme_float("card_thread_weave", 0.72)))
        margin = 26.0
        rect = QRectF(0, 0, size.width(), size.height())

        def thread_points(idx, variant):
            lane_seed = _hash01(self._bubble_seed + idx * 31.17 + variant * 101.0)
            wave_seed = _hash01(self._bubble_seed + idx * 43.23 + variant * 29.0)
            bend_seed = _hash01(self._bubble_seed + idx * 59.71 + variant * 17.0)
            points = []
            samples = 13
            diagonal = idx % 3 == 0
            for step in range(samples):
                t = step / (samples - 1)
                if diagonal:
                    x = rect.left() - margin + (rect.width() + margin * 2.0) * t
                    y = rect.top() + rect.height() * (0.10 + lane_seed * 0.82)
                    y += (t - 0.5) * rect.height() * (0.38 + bend_seed * 0.34)
                else:
                    x = rect.left() - margin + (rect.width() + margin * 2.0) * t
                    y = rect.top() + rect.height() * (0.08 + lane_seed * 0.86)
                wave = math.sin((t * (2.0 + wave_seed * 2.5) + lane_seed + variant * 0.17) * math.tau)
                counter = math.sin((t * (4.0 + bend_seed * 2.0) + wave_seed) * math.tau)
                y += (wave * 6.0 + counter * 1.8) * weave
                points.append(QPointF(x, y))
            return points

        def smooth_path(points):
            stroke = QPainterPath()
            stroke.moveTo(points[0])
            for idx in range(1, len(points) - 1):
                mid = QPointF(
                    (points[idx].x() + points[idx + 1].x()) * 0.5,
                    (points[idx].y() + points[idx + 1].y()) * 0.5,
                )
                stroke.quadTo(points[idx], mid)
            stroke.lineTo(points[-1])
            return stroke

        def draw_thread(points, color_key, line_alpha, width):
            if len(points) < 2 or line_alpha <= 0:
                return
            pen = QPen(self._color(color_key, line_alpha, "accent"), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(smooth_path(points))

        for idx in range(thread_count):
            points = thread_points(idx, 0)
            color_key = "card_thread_alt" if idx % 4 == 0 else "card_thread"
            depth = 0.58 + _hash01(self._bubble_seed + idx * 79.0) * 0.42
            draw_thread(points, color_key, int(alpha * 0.12 * depth), 2.1)
            draw_thread(points, color_key, int(alpha * 0.72 * depth), 0.68 + depth * 0.34)

        knot_alpha = max(0, min(255, _theme_int("card_thread_knot_alpha", 52)))
        painter.setPen(Qt.PenStyle.NoPen)
        for idx in range(max(2, thread_count // 3)):
            x_seed = _hash01(self._bubble_seed + idx * 97.0)
            y_seed = _hash01(self._bubble_seed + idx * 113.0)
            point = QPointF(
                rect.left() + rect.width() * (0.10 + x_seed * 0.80),
                rect.top() + rect.height() * (0.16 + y_seed * 0.68),
            )
            knot = QRadialGradient(point, 9.0)
            knot.setColorAt(0.0, self._color("card_thread_flash", int(knot_alpha * 0.72), "shine"))
            knot.setColorAt(0.44, self._color("card_thread", int(knot_alpha * 0.32), "accent"))
            knot.setColorAt(1.0, self._color("card_thread", 0, "accent"))
            painter.setBrush(QBrush(knot))
            painter.drawEllipse(point, 9.0, 9.0)

        painter.end()
        self._texture_cache_key = cache_key
        self._texture_cache_pixmap = pixmap
        return pixmap

    def _draw_star_particle_texture(self, painter, rect, radius, pulse):
        if not self._theme_personality_motion_enabled():
            return

        alpha = _theme_int("card_particle_alpha", 0)
        if alpha <= 0:
            return

        particle_count = max(6, min(28, _theme_int("card_particle_count", 18)))
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)

        seed_phase = (self._bubble_seed % 997) / 997.0
        hover_boost = 1.0 if self._hovered else 0.56
        phase = self._hover_phase * (1.8 if self._hovered else 0.95) + seed_phase
        for idx in range(particle_count):
            x_seed = _hash01(self._bubble_seed + idx * 17.13)
            y_seed = _hash01(self._bubble_seed + idx * 29.71)
            speed_seed = _hash01(self._bubble_seed + idx * 41.43)
            delay_seed = _hash01(self._bubble_seed + idx * 53.97)
            alpha_seed = _hash01(self._bubble_seed + idx * 67.31)
            size_seed = _hash01(self._bubble_seed + idx * 79.79)
            origin_seed = _hash01(self._bubble_seed + idx * 89.11)

            base = QPointF(
                rect.left() + rect.width() * (0.16 + x_seed * 0.68),
                rect.top() + rect.height() * (0.18 + y_seed * 0.64),
            )
            direction = -1.0 if idx % 2 == 0 else 1.0
            angle = (phase * (0.42 + speed_seed * 0.78) + delay_seed) * math.tau * direction
            orbit_x = (10.0 + origin_seed * 22.0) * math.cos(angle)
            orbit_y = (5.0 + origin_seed * 13.0) * math.sin(angle * 0.82 + origin_seed * math.tau)
            drift_x = math.sin(angle * 0.37 + origin_seed * 8.0) * 5.0
            center = QPointF(base.x() + orbit_x + drift_x, base.y() + orbit_y)

            twinkle = 0.45 + 0.55 * math.sin(angle * 1.7 + alpha_seed * math.tau)
            particle_alpha = int(alpha * hover_boost * (0.42 + alpha_seed * 0.52) * max(0.0, twinkle))
            if particle_alpha <= 10:
                continue

            size = 2.4 + size_seed * 4.8
            color_key = "card_particle_alt" if idx % 5 == 0 else "card_particle"
            color = self._color(color_key, particle_alpha, "accent")
            glow_color = self._color(color_key, int(particle_alpha * 0.22), "accent")

            glow = QRadialGradient(center, size * 3.0)
            glow.setColorAt(0.0, glow_color)
            glow.setColorAt(1.0, self._color(color_key, 0, "accent"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(center, size * 3.0, size * 3.0)

            painter.save()
            painter.translate(center)
            painter.rotate(math.degrees(angle) % 360)
            star = QPainterPath()
            star.moveTo(0, -size)
            star.lineTo(size * 0.24, -size * 0.24)
            star.lineTo(size, 0)
            star.lineTo(size * 0.24, size * 0.24)
            star.lineTo(0, size)
            star.lineTo(-size * 0.24, size * 0.24)
            star.lineTo(-size, 0)
            star.lineTo(-size * 0.24, -size * 0.24)
            star.closeSubpath()
            painter.setBrush(color)
            painter.setPen(QPen(self._color("shine", int(particle_alpha * 0.55), "shine"), 0.45))
            painter.drawPath(star)
            painter.restore()

        painter.restore()

    def _draw_diamond_facets_texture(self, painter, rect, radius, pulse):
        texture = self._diamond_facets_pixmap(rect.size())
        if texture is None:
            return

        path = QPainterPath()
        path.addRoundedRect(QRectF(rect), radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(rect, texture)
        if self._theme_personality_motion_enabled():
            self._draw_diamond_sheen(painter, rect, pulse)
        painter.restore()

    def _draw_diamond_sheen(self, painter, rect, pulse):
        alpha = max(0, min(255, _theme_int("card_diamond_sheen_alpha", 72)))
        if alpha <= 0:
            return

        facet_target = max(18, min(72, _theme_int("card_diamond_facets", 42)))
        triangles = self._diamond_facet_triangles(rect.size(), facet_target)
        seed_phase = (self._bubble_seed % 743) / 743.0
        phase = (self._hover_phase * 1.45 + seed_phase) % 1.0
        w = max(1.0, float(rect.width()))
        h = max(1.0, float(rect.height()))

        def shifted(point):
            return QPointF(rect.left() + point.x(), rect.top() + point.y())

        def lerp(a, b, t):
            return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)

        seen = set()
        edges = []
        for tri_idx, tri in enumerate(triangles):
            for edge_idx, (a, b) in enumerate(((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))):
                key = tuple(sorted((
                    (round(a.x() * 10), round(a.y() * 10)),
                    (round(b.x() * 10), round(b.y() * 10)),
                )))
                if key in seen:
                    continue
                seen.add(key)
                edges.append((a, b, tri_idx, edge_idx))

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for edge_idx, (raw_a, raw_b, tri_idx, local_idx) in enumerate(edges):
            a = shifted(raw_a)
            b = shifted(raw_b)
            mid_x = (raw_a.x() + raw_b.x()) * 0.5 / w
            mid_y = (raw_a.y() + raw_b.y()) * 0.5 / h
            lane = (mid_x * 0.68 + mid_y * 0.32 + _hash01(self._bubble_seed + edge_idx * 17.0) * 0.10) % 1.0
            intensity = 0.0
            for wave_offset, wave_strength in ((0.0, 1.0), (0.38, 0.62)):
                wave_phase = (phase + wave_offset) % 1.0
                distance = abs(((lane - wave_phase + 0.5) % 1.0) - 0.5)
                intensity = max(intensity, max(0.0, 1.0 - distance / 0.165) * wave_strength)
            if intensity <= 0.0:
                continue

            intensity = (intensity ** 1.35) * (0.80 + pulse * 0.20)
            center_t = (_hash01(self._bubble_seed + tri_idx * 73.0 + local_idx * 29.0) + phase * 0.36) % 1.0
            span = 0.30 + _hash01(self._bubble_seed + edge_idx * 43.0) * 0.24
            start = max(0.0, center_t - span * 0.5)
            end = min(1.0, center_t + span * 0.5)
            if end - start < 0.04:
                continue

            seg_a = lerp(a, b, start)
            seg_b = lerp(a, b, end)
            glow_alpha = int(alpha * intensity * 0.82)
            hot_alpha = int(alpha * intensity * 1.48)
            glow_pen = QPen(self._color("card_diamond", glow_alpha, "accent"), 2.7)
            glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(glow_pen)
            painter.drawLine(seg_a, seg_b)
            hot_pen = QPen(self._color("card_diamond_flash", hot_alpha, "shine"), 0.85 + intensity * 0.85)
            hot_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(hot_pen)
            painter.drawLine(seg_a, seg_b)
        painter.restore()

    def _diamond_facet_triangles(self, size, facet_target):
        w = size.width()
        h = size.height()

        def dist2(a, b):
            dx = a.x() - b.x()
            dy = a.y() - b.y()
            return dx * dx + dy * dy

        def lerp(a, b, t):
            return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)

        def tri_area(tri):
            a, b, c = tri
            return abs((b.x() - a.x()) * (c.y() - a.y()) - (c.x() - a.x()) * (b.y() - a.y())) * 0.5

        def longest_edge(tri):
            a, b, c = tri
            edges = ((dist2(a, b), a, b, c), (dist2(b, c), b, c, a), (dist2(c, a), c, a, b))
            return max(edges, key=lambda item: item[0])[1:]

        triangles = [
            (QPointF(0, 0), QPointF(w, 0), QPointF(w, h)),
            (QPointF(0, 0), QPointF(w, h), QPointF(0, h)),
        ]
        split_step = 0
        while len(triangles) < facet_target:
            split_idx = max(
                range(len(triangles)),
                key=lambda idx: tri_area(triangles[idx]) * (0.84 + _hash01(self._bubble_seed + idx * 31.0) * 0.32),
            )
            tri = triangles.pop(split_idx)
            edge_a, edge_b, opposite = longest_edge(tri)
            split_t = 0.32 + _hash01(self._bubble_seed + split_step * 83.0 + split_idx * 19.0) * 0.36
            split_point = lerp(edge_a, edge_b, split_t)
            drift = (_hash01(self._bubble_seed + split_step * 47.0) - 0.5) * min(w, h) * 0.035
            if 3 < split_point.x() < w - 3 and 3 < split_point.y() < h - 3:
                split_point = QPointF(split_point.x() + drift, split_point.y() - drift * 0.55)
            triangles.append((opposite, edge_a, split_point))
            triangles.append((opposite, split_point, edge_b))
            split_step += 1
        return triangles

    def _diamond_facets_pixmap(self, size):
        if size.width() <= 1 or size.height() <= 1:
            return None

        facet_target = max(18, min(72, _theme_int("card_diamond_facets", 42)))
        alpha = max(0, min(255, _theme_int("card_diamond_alpha", 58)))
        cache_key = (
            "diamond_facets",
            size.width(),
            size.height(),
            facet_target,
            alpha,
            P.get("card_diamond"),
            P.get("card_diamond_alt"),
            P.get("card_diamond_flash"),
            P.get("card_diamond_shadow"),
            self._bubble_seed,
        )
        if self._texture_cache_key == cache_key and self._texture_cache_pixmap is not None:
            return self._texture_cache_pixmap

        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        triangles = self._diamond_facet_triangles(size, facet_target)

        palette = (
            ("card_diamond_shadow", "card_diamond"),
            ("card_diamond", "card_diamond_flash"),
            ("card_diamond_alt", "card_diamond_flash"),
            ("card_diamond_shadow", "card_diamond_alt"),
            ("card_diamond", "card_diamond_alt"),
        )

        def draw_triangle(tri, idx):
            shade = _hash01(self._bubble_seed + idx * 97.0)
            glint = _hash01(self._bubble_seed + idx * 53.0 + 11.0)
            pair = palette[int(shade * len(palette)) % len(palette)]
            color_a = self._color(pair[0], int(alpha * (0.24 + shade * 0.34)), "accent")
            color_b = self._color(pair[1], int(alpha * (0.46 + (1.0 - shade) * 0.46)), "shine")
            if shade < 0.16:
                color_b = self._color("card_diamond_shadow", int(alpha * 0.78), "bg_dark")
            elif glint > 0.88:
                color_b = self._color("card_diamond_flash", int(alpha * 1.08), "shine")

            center = QPointF(
                (tri[0].x() + tri[1].x() + tri[2].x()) / 3.0,
                (tri[0].y() + tri[1].y() + tri[2].y()) / 3.0,
            )
            far = tri[int(_hash01(self._bubble_seed + idx * 13.0) * 3) % 3]
            gradient = QLinearGradient(center, far)
            gradient.setColorAt(0.0, color_a)
            gradient.setColorAt(0.66, color_b)
            gradient.setColorAt(1.0, self._color("card_diamond_flash", int(alpha * (0.12 + glint * 0.18)), "shine"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawPolygon(QPolygonF(tri))

        for tri_idx, tri in enumerate(triangles):
            draw_triangle(tri, tri_idx)

        edge_alpha = int(alpha * 0.42)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for idx, tri in enumerate(triangles):
            edge_tone = _hash01(self._bubble_seed + idx * 67.0)
            pen_color = self._color("card_diamond_flash", int(edge_alpha * (0.35 + edge_tone * 0.65)), "shine")
            painter.setPen(QPen(pen_color, 0.36 if edge_tone < 0.82 else 0.7))
            a, b, c = tri
            painter.drawLine(a, b)
            if edge_tone > 0.32:
                painter.drawLine(b, c)
            if edge_tone > 0.58:
                painter.drawLine(c, a)

        painter.end()
        self._texture_cache_key = cache_key
        self._texture_cache_pixmap = pixmap
        return pixmap

    def _image_overlay_pixmap(self, size):
        if size.width() <= 1 or size.height() <= 1:
            return None

        rel_path = P.get("card_texture_path", "")
        if not rel_path:
            return None

        full_path = app_path(*rel_path.replace("\\", "/").split("/"))
        cache_key = ("image_overlay", full_path, size.width(), size.height())
        if self._texture_cache_key == cache_key and self._texture_cache_pixmap is not None:
            return self._texture_cache_pixmap

        source = QPixmap(full_path)
        if source.isNull():
            return None

        scaled = source.scaled(
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        if scaled.size() != size:
            x = max(0, (scaled.width() - size.width()) // 2)
            y = max(0, (scaled.height() - size.height()) // 2)
            scaled = scaled.copy(x, y, size.width(), size.height())

        pixmap = scaled
        self._texture_cache_key = cache_key
        self._texture_cache_pixmap = pixmap
        return pixmap

import qtawesome as qta
from PIL import Image
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPen, QPixmap,
    QRadialGradient,
)
from core.themes import P


def _icon_color(fallback=None):
    return P.get("icon_color", fallback or P["accent"])


def _palette_int(key: str, default: int) -> int:
    try:
        return int(float(P.get(key, default)))
    except (TypeError, ValueError):
        return default


def _is_aero_icon_style() -> bool:
    return P.get("icon_style") == "aero_glass"


def _aero_icon(name: str, color=None, size: int | None = None) -> QIcon:
    px = max(32, size or _palette_int("icon_aero_size", 64))
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    rect = QRectF(3, 3, px - 6, px - 6)
    center = QPointF(px * 0.50, px * 0.50)

    shadow = QRadialGradient(QPointF(px * 0.50, px * 0.66), px * 0.45)
    shadow.setColorAt(0.0, QColor(30, 131, 166, 54))
    shadow.setColorAt(0.62, QColor(30, 131, 166, 18))
    shadow.setColorAt(1.0, QColor(30, 131, 166, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(shadow))
    painter.drawEllipse(QRectF(4, 8, px - 8, px - 8))

    fill = QRadialGradient(QPointF(px * 0.36, px * 0.26), px * 0.62)
    fill.setColorAt(0.00, QColor(255, 255, 255, 232))
    fill.setColorAt(0.34, QColor(P.get("icon_badge_top", "#DDFBFF")))
    fill.setColorAt(0.72, QColor(P.get("icon_badge_mid", "#8BE5F4")))
    fill.setColorAt(1.00, QColor(P.get("icon_badge_bottom", "#38A9D0")))
    painter.setBrush(QBrush(fill))
    painter.setPen(QPen(QColor(P.get("icon_badge_border", "#FFFFFF")), max(1.0, px * 0.030)))
    painter.drawEllipse(rect)

    gloss_rect = QRectF(px * 0.16, px * 0.12, px * 0.68, px * 0.38)
    gloss = QLinearGradient(QPointF(gloss_rect.left(), gloss_rect.top()), QPointF(gloss_rect.left(), gloss_rect.bottom()))
    gloss.setColorAt(0.0, QColor(255, 255, 255, 214))
    gloss.setColorAt(0.66, QColor(255, 255, 255, 62))
    gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setBrush(QBrush(gloss))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(gloss_rect)

    rim = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.right(), rect.bottom()))
    rim.setColorAt(0.0, QColor(255, 255, 255, 210))
    rim.setColorAt(0.52, QColor(255, 255, 255, 24))
    rim.setColorAt(1.0, QColor(P.get("icon_badge_rim", "#6ED7EF")))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QBrush(rim), max(1.0, px * 0.020)))
    painter.drawEllipse(rect.adjusted(1, 1, -1, -1))

    glyph_size = int(px * 0.60)
    glyph_rect = QRectF(
        center.x() - glyph_size * 0.5,
        center.y() - glyph_size * 0.45,
        glyph_size,
        glyph_size,
    ).toRect()
    shadow_glyph = qta.icon(name, color=QColor(255, 255, 255, 138))
    shadow_glyph.paint(painter, glyph_rect.translated(1, 2), Qt.AlignmentFlag.AlignCenter)
    glyph = qta.icon(name, color=color or P.get("icon_glyph_color", "#075C82"))
    glyph.paint(painter, glyph_rect, Qt.AlignmentFlag.AlignCenter)

    painter.end()
    return QIcon(pixmap)


def _themed_icon(name: str, *, color=None, size: int | None = None) -> QIcon:
    if _is_aero_icon_style():
        return _aero_icon(name, color or P.get("icon_glyph_color", _icon_color()), size)
    return qta.icon(name, color=color or _icon_color())


# PIL → QPixmap helper (used by portrait loader in ASBR-Tools.py)
def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


# Category icons (sidebar + CAT_META)
def icon_person(size=24, color=None):
    return _themed_icon("fa6s.user", color=color, size=size)

def icon_swords(size=24, color=None):
    return _themed_icon("fa6s.khanda", color=color, size=size)

def icon_arrow(size=24, color=None):
    return _themed_icon("fa6s.person-running", color=color, size=size)

def icon_play(size=24, color=None):
    return _themed_icon("fa6s.gamepad", color=color, size=size)

def icon_grid(size=24, color=None):
    return _themed_icon("fa6s.display", color=color, size=size)

def icon_package(size=24, color=None):
    return _themed_icon("fa6s.box", color=color, size=size)

def icon_gallery_cat(size=24, color=None):
    return _themed_icon("fa6s.images", color=color, size=size)

def icon_profile_cat(size=24, color=None):
    return _themed_icon("fa6s.address-card", color=color, size=size)

def icon_multiplayer_cat(size=24, color=None):
    return _themed_icon("fa6s.network-wired", color=color, size=size)

def icon_audio_assets(size=24, color=None):
    return _themed_icon("fa6s.compact-disc", color=color, size=size)

def icon_settings_gear(size=24, color=None):
    return _themed_icon("fa6s.gear", color=color, size=size)

def icon_cpk_unpack(size=24, color=None):
    return _themed_icon("fa6s.box-open", color=color, size=size)

def icon_credits_star(size=24, color=None):
    return _themed_icon("fa6s.star", color=color, size=size)

def icon_favorite_category(size=24, color=None):
    return _themed_icon("fa6s.star", color=color, size=size)

def icon_favorite_star(filled=False, size=16, color=None):
    icon_color = color or (_icon_color() if filled else P["text_dim"])
    return qta.icon("fa6s.star", color=icon_color)

def icon_tool_pin(filled=False, size=16, color=None):
    icon_color = color or (_icon_color() if filled else P["text_dim"])
    return qta.icon("fa6s.thumbtack", color=icon_color)


# Tool card icons
def icon_stats():
    return _themed_icon("fa6s.chart-bar")

def icon_id():
    return _themed_icon("fa6s.id-card")

def icon_costume():
    return _themed_icon("fa6s.shirt")

def icon_sound():
    return _themed_icon("fa6s.volume-high")

def icon_skill():
    return _themed_icon("fa6s.star")

def icon_hit():
    return _themed_icon("fa6s.hand-fist")

def icon_damage():
    return _themed_icon("fa6s.bolt")

def icon_balance():
    return _themed_icon("fa6s.scale-balanced")

def icon_battle_result():
    return _themed_icon("fa6s.ranking-star")

def icon_arcade_reward():
    return _themed_icon("fa6s.coins")

def icon_net_result():
    return _themed_icon("fa6s.globe")

def icon_cpu_ai():
    return _themed_icon("fa6s.brain")

def icon_projectile():
    return _themed_icon("fa6s.circle-dot")

def icon_effect():
    return _themed_icon("fa6s.wand-magic-sparkles")

def icon_movelist():
    return _themed_icon("fa6s.list")

def icon_command_list_param():
    return _themed_icon("fa6s.keyboard")

def icon_constraint():
    return _themed_icon("fa6s.lock")

def icon_story():
    return _themed_icon("fa6s.book")

def icon_dialogue():
    return _themed_icon("fa6s.comments")

def icon_assist():
    return _themed_icon("fa6s.people-group")

def icon_game_text():
    return _themed_icon("fa6s.font")

def icon_term_list():
    return _themed_icon("fa6s.list-check")

def icon_stage():
    return _themed_icon("fa6s.mountain")

def icon_ui():
    return _themed_icon("fa6s.table-cells")

def icon_gimmick():
    return _themed_icon("fa6s.gear")

def icon_texture():
    return _themed_icon("fa6s.images")

def icon_xfbin():
    return _themed_icon("fa6s.file-audio")

def icon_char_viewer():
    return _themed_icon("fa6s.eye")

def icon_guide_char():
    return _themed_icon("fa6s.graduation-cap")

def icon_dictionary():
    return _themed_icon("fa6s.book-open")

def icon_custom_card():
    return _themed_icon("fa6s.address-card")

def icon_custom_default():
    return _themed_icon("fa6s.sliders")

def icon_dlc_info():
    return _themed_icon("fa6s.puzzle-piece")

def icon_gallery():
    return _themed_icon("fa6s.palette")

def icon_player_title():
    return _themed_icon("fa6s.trophy")

def icon_sound_param():
    return _themed_icon("fa6s.music")

def icon_sound_test():
    return _themed_icon("fa6s.headphones")

def icon_usm_video():
    return _themed_icon("fa6s.film")


# Social / credit icons
def icon_social_github():
    return _themed_icon("fa6b.github")

def icon_social_youtube():
    return _themed_icon("fa6b.youtube")

def icon_social_discord():
    return _themed_icon("fa6b.discord")

def icon_social_nexusmods():
    return _themed_icon("fa6s.cube")

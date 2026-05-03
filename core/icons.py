import qtawesome as qta
from PIL import Image
from PyQt6.QtGui import QPixmap, QImage
from core.themes import P


# PIL → QPixmap helper (used by portrait loader in ASBR-Tools.py)
def _pil_to_qpixmap(img: Image.Image) -> QPixmap:
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    qimg = QImage(data, img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimg)


# Category icons (sidebar + CAT_META)
def icon_person(size=24, color=None):
    return qta.icon("fa6s.user", color=color or P["accent"])

def icon_swords(size=24, color=None):
    return qta.icon("fa6s.khanda", color=color or "#E05555")

def icon_arrow(size=24, color=None):
    return qta.icon("fa6s.person-running", color=color or "#55BBE0")

def icon_play(size=24, color=None):
    return qta.icon("fa6s.gamepad", color=color or "#55E0A0")

def icon_grid(size=24, color=None):
    return qta.icon("fa6s.display", color=color or "#E0B055")

def icon_package(size=24, color=None):
    return qta.icon("fa6s.box", color=color or "#AA77EE")

def icon_gallery_cat(size=24, color=None):
    return qta.icon("fa6s.images", color=color or "#DD77BB")

def icon_profile_cat(size=24, color=None):
    return qta.icon("fa6s.address-card", color=color or "#FFCC44")

def icon_audio_assets(size=24, color=None):
    return qta.icon("fa6s.compact-disc", color=color or "#55DDCC")

def icon_settings_gear(size=24, color=None):
    return qta.icon("fa6s.gear", color=color or P["secondary"])

def icon_cpk_unpack(size=24, color=None):
    return qta.icon("fa6s.box-open", color=color or P["accent"])

def icon_credits_star(size=24, color=None):
    return qta.icon("fa6s.star", color=color or P["secondary"])

def icon_favorite_category(size=24, color=None):
    return qta.icon("fa6s.star", color=color or P["accent"])

def icon_favorite_star(filled=False, size=16, color=None):
    return qta.icon("fa6s.star", color=color or (P["accent"] if filled else P["text_dim"]))

def icon_tool_pin(filled=False, size=16, color=None):
    return qta.icon("fa6s.thumbtack", color=color or (P["accent"] if filled else P["text_dim"]))


# Tool card icons
def icon_stats():
    return qta.icon("fa6s.chart-bar", color=P["accent"])

def icon_id():
    return qta.icon("fa6s.id-card", color=P["secondary"])

def icon_costume():
    return qta.icon("fa6s.shirt", color="#E0A0E0")

def icon_sound():
    return qta.icon("fa6s.volume-high", color="#80D0FF")

def icon_skill():
    return qta.icon("fa6s.star", color=P["accent"])

def icon_hit():
    return qta.icon("fa6s.hand-fist", color="#FF6655")

def icon_damage():
    return qta.icon("fa6s.bolt", color="#FF8844")

def icon_balance():
    return qta.icon("fa6s.scale-balanced", color="#AABB55")

def icon_projectile():
    return qta.icon("fa6s.circle-dot", color="#55CCFF")

def icon_effect():
    return qta.icon("fa6s.wand-magic-sparkles", color="#DDAA55")

def icon_movelist():
    return qta.icon("fa6s.list", color="#A0A0DD")

def icon_constraint():
    return qta.icon("fa6s.lock", color="#CC88DD")

def icon_story():
    return qta.icon("fa6s.book", color="#66DD88")

def icon_dialogue():
    return qta.icon("fa6s.comments", color="#88BBEE")

def icon_assist():
    return qta.icon("fa6s.people-group", color="#DDDD55")

def icon_game_text():
    return qta.icon("fa6s.font", color="#DDCC66")

def icon_stage():
    return qta.icon("fa6s.mountain", color="#EEAA55")

def icon_ui():
    return qta.icon("fa6s.table-cells", color="#BBBB55")

def icon_gimmick():
    return qta.icon("fa6s.gear", color="#EE7755")

def icon_texture():
    return qta.icon("fa6s.images", color="#AA77EE")

def icon_xfbin():
    return qta.icon("fa6s.file-audio", color="#55DDCC")

def icon_char_viewer():
    return qta.icon("fa6s.eye", color="#77CCEE")

def icon_guide_char():
    return qta.icon("fa6s.graduation-cap", color="#88EE88")

def icon_dictionary():
    return qta.icon("fa6s.book-open", color="#AADDCC")

def icon_custom_card():
    return qta.icon("fa6s.address-card", color="#EE9944")

def icon_custom_default():
    return qta.icon("fa6s.sliders", color="#99BBDD")

def icon_dlc_info():
    return qta.icon("fa6s.puzzle-piece", color="#DD88AA")

def icon_gallery():
    return qta.icon("fa6s.palette", color="#DD77BB")

def icon_player_title():
    return qta.icon("fa6s.trophy", color="#FFCC44")

def icon_sound_param():
    return qta.icon("fa6s.music", color="#77AAFF")

def icon_sound_test():
    return qta.icon("fa6s.headphones", color="#55EEBB")


# Social / credit icons
def icon_social_github():
    return qta.icon("fa6b.github", color="#8A939A")

def icon_social_youtube():
    return qta.icon("fa6b.youtube", color="#FF0000")

def icon_social_discord():
    return qta.icon("fa6b.discord", color="#5865F2")

def icon_social_nexusmods():
    return qta.icon("fa6s.cube", color="#DA8A2C")

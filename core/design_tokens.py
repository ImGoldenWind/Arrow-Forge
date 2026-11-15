"""Arrow Forge presentation tokens. Geometry is in Qt logical pixels, fonts in pt."""
from dataclasses import dataclass
from enum import Enum, IntEnum
from types import MappingProxyType

from PyQt6.QtGui import QFont

from core.themes import P


class TypeSize(IntEnum):
    MICRO = 6
    TINY = 7
    CAPTION = 8
    HINT = 9
    BODY = 10
    CODE = 11
    LABEL = 12
    TITLE = 13
    SUBHEADING = 14
    SECTION = 15
    LARGE = 16
    ANNOUNCEMENT = 17
    DISPLAY = 18
    PAGE_TITLE = 20
    HERO = 22


class Size(IntEnum):
    HAIRLINE = 1
    ACCENT_LINE = 2
    GAP_XS = 2
    GAP_SM = 4
    GAP = 8
    CARD_GAP = 10
    PAGE_INSET = 12
    GRID_GAP = 16
    ICON = 18
    EMPTY_ICON = 22
    TOOLBAR_SEPARATOR = 26
    INSPECTOR_CONTROL = 26
    COMPACT_CONTROL = 28
    CONTROL = 30
    SEARCH = 32
    TABLE_ROW = 32
    LARGE_CONTROL = 36
    LIST_ROW = 44
    TOOLBAR = 46
    CARD_RADIUS = 10
    SCROLLBAR = 10
    SIDEBAR_DEFAULT = 260
    CARD_MAX_WIDTH = 980
    COMPACT_BREAKPOINT = 780
    LIST_GAP = 1


class Insets:
    NONE = (0, 0, 0, 0)
    TOOLBAR = (12, 8, 12, 8)
    SIDEBAR = (8, 8, 8, 4)
    ACTIONS = (0, 2, 0, 4)
    LIST_ROW = (10, 3, 10, 3)
    PAGE = (12, 12, 12, 12)
    CARD = (16, 14, 16, 14)
    GRID_TITLE = (0, 4, 0, 0)
    DISPLAY_VALUE = (2, 4, 0, 0)
    EMPTY_STATE = (22, 18, 22, 18)
    FIELD_GUTTER = (8, 0, 8, 0)


class SkeletonMetrics:
    BAR_HEIGHT = 14
    BAR_RADIUS = 6
    HEADER_HEIGHT = Size.LARGE_CONTROL
    HEADER_RADIUS = 5
    LABEL_HEIGHT = 11
    LABEL_RADIUS = 3
    FIELD_HEIGHT = Size.CONTROL
    FIELD_RADIUS = 4
    CARD_RADIUS = 8


class Radius(Enum):
    BUTTON = ("button_radius", "6px")
    INPUT = ("input_radius", "4px")
    CARD = ("panel_card_radius", "10px")
    LIST_ROW = ("sidebar_item_radius", "6px")
    CHECKBOX = ("checkbox_radius", "3px")


class IconButtonRole(Enum):
    TOOLBAR = (30, 30, 14)
    INLINE_PICKER = (26, 26, 12)
    TIMELINE_TOOL = (54, 48, 19)
    SIDEBAR_TOGGLE = (20, 58, 12)


def radius(role: Radius) -> str:
    key, fallback = role.value
    return P.get(key, fallback)


class Padding:
    BUTTON_Y = 3
    BUTTON_X = 10
    COMPACT_BUTTON_X = 6
    PRESSED_TOP = 4
    PRESSED_BOTTOM = 2
    INPUT = "3px 6px"
    SEARCH = "2px 6px"
    TABLE_CELL = "4px 7px"
    TABLE_HEADER = "5px 7px"
    COMBO_ARROW = 20


class ColorRole(Enum):
    """Ordered aliases into the existing live palette; no second palette."""
    WINDOW = ("bg_dark",)
    TOOLBAR = ("toolbar_bg", "bg_panel")
    CARD = ("panel_card_bg", "bg_panel")
    BORDER = ("border",)
    TEXT = ("text_main",)
    SECONDARY_TEXT = ("text_sec",)
    MUTED_TEXT = ("text_dim",)
    ACCENT = ("accent",)
    BUTTON = ("mid",)
    BUTTON_TEXT = ("button_text", "text_main")
    BUTTON_HOVER = ("button_hover", "accent_dim")
    BUTTON_HOVER_TEXT = ("button_hover_text", "bg_dark")
    BUTTON_PRESSED = ("bg_card_hov", "mid")
    BUTTON_DISABLED = ("button_disabled_bg", "bg_card")
    BUTTON_DISABLED_TEXT = ("button_disabled_text", "text_sec", "text_dim")
    PRIMARY_TEXT = ("button_accent_text", "bg_dark")
    PRIMARY_HOVER = ("button_accent_hover", "accent_dim")
    PRIMARY_HOVER_TEXT = ("button_accent_hover_text", "button_accent_text", "bg_dark")
    PRIMARY_PRESSED = ("button_accent_pressed", "button_accent_hover", "accent_dim")
    DANGER_HOVER = ("button_danger_hover", "accent_dim")
    DANGER_HOVER_TEXT = ("button_danger_hover_text", "button_hover_text", "bg_dark")
    INPUT = ("input_bg", "bg_card")
    INPUT_BORDER = ("input_border", "border")
    INPUT_HOVER = ("input_hover_bg", "bg_card_hov", "input_bg", "bg_card")
    INPUT_FOCUS = ("input_focus_bg", "bg_card_hov", "input_bg", "bg_card")
    FOCUS_BORDER = ("input_focus_border", "accent")
    INPUT_DISABLED = ("input_disabled_bg", "bg_card", "input_bg")
    INPUT_DISABLED_TEXT = ("input_disabled_text", "text_sec", "text_dim")
    SELECTION = ("selection_bg", "accent")
    SELECTION_TEXT = ("selection_text", "bg_dark")
    FILE = ("file_label_text", "text_sec", "text_dim")
    LIST_SELECTED = ("sidebar_item_selected_bg", "bg_card")
    LIST_HOVER = ("sidebar_item_hover_bg", "bg_card_hov")
    HEADER = ("table_header_bg", "bg_panel")
    HEADER_TEXT = ("table_header_text", "text_sec")
    ITEM_HOVER = ("list_hover_bg", "mid")


def color(role: ColorRole) -> str:
    for key in role.value:
        if key in P:
            return P[key]
    raise KeyError(f"Missing theme color for {role.name}: {role.value}")


class FontRole(Enum):
    BUTTON = ("ui", TypeSize.BODY, QFont.Weight.Normal)
    SEARCH = ("ui", TypeSize.TITLE, QFont.Weight.Normal)
    INPUT = ("mono", TypeSize.TITLE, QFont.Weight.Normal)
    FILE = ("mono", TypeSize.LABEL, QFont.Weight.Normal)
    FIELD_LABEL = ("ui", TypeSize.LABEL, QFont.Weight.Normal)
    HINT = ("ui", TypeSize.HINT, QFont.Weight.Normal)
    CARD_TITLE = ("ui", TypeSize.TITLE, QFont.Weight.Bold)
    LIST_CODE = ("mono", TypeSize.CODE, QFont.Weight.Normal)
    DISPLAY = ("ui", TypeSize.DISPLAY, QFont.Weight.Bold)
    LARGE_VALUE = ("mono", TypeSize.LARGE, QFont.Weight.Normal)


def font(role: FontRole) -> QFont:
    family, size, weight = role.value
    return mono_font(size, weight) if family == "mono" else ui_font(size, weight)


@dataclass(frozen=True)
class LayoutSpec:
    margins: tuple[int, int, int, int]
    spacing: int = 0
    horizontal: int | None = None
    vertical: int | None = None


class LayoutRole(Enum):
    ROOT = "root"
    TOOLBAR = "toolbar"
    SIDEBAR = "sidebar"
    ACTIONS = "actions"
    LIST = "list"
    LIST_ROW = "list_row"
    PAGE = "page"
    CARD = "card"
    FIELD = "field"
    TITLE = "title"
    TITLE_TEXT = "title_text"
    GRID = "grid"
    PAGE_GRID = "page_grid"
    GRID_TITLED = "grid_titled"
    SKELETON_FIELD = "skeleton_field"
    SIDEBAR_TABS = "sidebar_tabs"
    EMPTY_STATE = "empty_state"
    COMPACT_FIELD = "compact_field"


_LAYOUTS = MappingProxyType({
    LayoutRole.ROOT: LayoutSpec(Insets.NONE),
    LayoutRole.TOOLBAR: LayoutSpec(Insets.TOOLBAR, Size.GAP_SM),
    LayoutRole.SIDEBAR: LayoutSpec(Insets.SIDEBAR, Size.GAP_SM),
    LayoutRole.ACTIONS: LayoutSpec(Insets.ACTIONS, Size.GAP_SM),
    LayoutRole.LIST: LayoutSpec(Insets.NONE, Size.LIST_GAP),
    LayoutRole.LIST_ROW: LayoutSpec(Insets.LIST_ROW),
    LayoutRole.PAGE: LayoutSpec(Insets.PAGE, Size.GAP),
    LayoutRole.CARD: LayoutSpec(Insets.CARD, Size.CARD_GAP),
    LayoutRole.FIELD: LayoutSpec(Insets.NONE, Size.GAP_SM),
    LayoutRole.TITLE: LayoutSpec(Insets.NONE, Size.GAP),
    LayoutRole.TITLE_TEXT: LayoutSpec(Insets.NONE, Size.GAP_XS),
    LayoutRole.GRID: LayoutSpec(Insets.NONE, horizontal=Size.GRID_GAP, vertical=Size.CARD_GAP),
    LayoutRole.PAGE_GRID: LayoutSpec(Insets.PAGE, horizontal=Size.GRID_GAP, vertical=Size.CARD_GAP),
    LayoutRole.GRID_TITLED: LayoutSpec(Insets.GRID_TITLE, horizontal=Size.GRID_GAP, vertical=Size.CARD_GAP),
    LayoutRole.SKELETON_FIELD: LayoutSpec(Insets.FIELD_GUTTER, Size.GAP_SM),
    LayoutRole.SIDEBAR_TABS: LayoutSpec(Insets.SIDEBAR),
    LayoutRole.EMPTY_STATE: LayoutSpec(Insets.EMPTY_STATE, Size.CARD_GAP),
    LayoutRole.COMPACT_FIELD: LayoutSpec(Insets.NONE, Size.GAP_XS),
})


def layout_spec(role: LayoutRole) -> LayoutSpec:
    return _LAYOUTS[role]


# Preview colors represent the edited image, independent of the selected theme.
HUE_GRADIENT = (
    "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff0000, stop:0.167 #ffff00, "
    "stop:0.333 #00ff00, stop:0.500 #00ffff, stop:0.667 #0000ff, stop:0.833 #ff00ff, stop:1 #ff0000)"
)
LIGHTNESS_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #000000, stop:0.5 #888888, stop:1 #ffffff)"


def ui_font(size=TypeSize.BODY, weight=QFont.Weight.Normal):
    return QFont(P.get("font_ui", "Segoe UI"), int(size), weight)


def mono_font(size=TypeSize.TITLE, weight=QFont.Weight.Normal):
    return QFont(P.get("font_mono", "Consolas"), int(size), weight)


def error_color():
    return P.get("error", "#ef6262")

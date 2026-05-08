# Color Themes
THEMES = {
"Soft & Wet": {
        "name":        "Soft & Wet",
        "bg_dark":     "#F4F7FB",
        "bg_panel":    "#FFFFFF", 
        "bg_card":     "#EEF2F9",
        "bg_card_hov": "#E0E7F1",
        "accent":      "#8E44AD",
        "accent_dim":  "#A569BD",
        "secondary":   "#5DADE2",
        "highlight":   "#D2B4DE",
        "mid":         "#D5D8DC",
        "border":      "#DCDFE6",
        "border_hov":  "#8E44AD",
        "text_main":   "#2C3E50",
        "text_sec":    "#566573",
        "text_dim":    "#7F8C8D",
        "text_file":   "#2980B9"
    },
"Wonder of U": {
        "name":        "Wonder of U",
        "bg_dark":     "#0F0F12",
        "bg_panel":    "#16161D",
        "bg_card":     "#1C1C24",
        "bg_card_hov": "#252530",
        "accent":      "#E74C3C",
        "accent_dim":  "#922B21",
        "secondary":   "#FFFFFF",
        "highlight":   "#FFFFFF",
        "mid":         "#2C2C34",
        "border":      "#2D2D3A",
        "border_hov":  "#4A4A5E",
        "text_main":   "#E0E0E0",
        "text_sec":    "#A0A0A0",
        "text_dim":    "#606060",
        "text_file":   "#BDC3C7"
    },
"Star Platinum": {
        "name":        "Star Platinum",
        "bg_dark":     "#120B21",
        "bg_panel":    "#1A122E",
        "bg_card":     "#241A3D",
        "bg_card_hov": "#2E224D",
        "accent":      "#F1C40F",
        "accent_dim":  "#B7950B",
        "secondary":   "#ECF0F1",
        "highlight":   "#9B59B6",
        "mid":         "#4A235A",
        "border":      "#3A2A5C",
        "border_hov":  "#F1C40F",
        "text_main":   "#FFFFFF",
        "text_sec":    "#D2B4DE",
        "text_dim":    "#8E44AD",
        "text_file":   "#F4D03F"
    },
"Crazy Diamond": {
        "name":        "Crazy Diamond",
        "bg_dark":     "#210B15",
        "bg_panel":    "#2E1220",
        "bg_card":     "#3D1A2B",
        "bg_card_hov": "#4D2237",
        "accent":      "#48C9B0",
        "accent_dim":  "#1ABC9C",
        "secondary":   "#FFB6C1",
        "highlight":   "#F06292",
        "mid":         "#641E3A",
        "border":      "#5C2A42",
        "border_hov":  "#48C9B0",
        "text_main":   "#FCE4EC",
        "text_sec":    "#F8BBD0",
        "text_dim":    "#D81B60",
        "text_file":   "#80DEEA"
    },
"GER": {
        "name":        "Gold Experience Requiem",
        "bg_dark":     "#0D0B05",
        "bg_panel":    "#151208", 
        "bg_card":     "#1E1A0C",
        "bg_card_hov": "#2B2612",
        "accent":      "#FFEA00",
        "accent_dim":  "#C7B300",
        "secondary":   "#AF7AC5",
        "highlight":   "#FF9100",
        "mid":         "#3F381B",
        "border":      "#4F4622",
        "border_hov":  "#FFEA00",
        "text_main":   "#FFFBE6",
        "text_sec":    "#D4C892",
        "text_dim":    "#8C8258",
        "text_file":   "#D291FF"
    },
"Stone Free": {
        "name":        "Stone Free",
        "bg_dark":     "#0A111A",
        "bg_panel":    "#0F1724",
        "bg_card":     "#161F2E",
        "bg_card_hov": "#1D293B",
        "accent":      "#00D2FF",
        "accent_dim":  "#0099CC",
        "secondary":   "#357ABD",
        "highlight":   "#00F2A1",
        "mid":         "#273951",
        "border":      "#273951",
        "border_hov":  "#00D2FF",
        "text_main":   "#E6F7FF",
        "text_sec":    "#A3C8E0", 
        "text_dim":    "#6F94B0",
        "text_file":   "#80E5FF"
    }
}

# Active palette — mutable, updated on theme switch
DEFAULT_THEME = "Wonder of U"

THEME_ALIASES = {
    "soft_wet": "Soft & Wet",
    "soft_&_wet": "Soft & Wet",
    "wonder_of_u": "Wonder of U",
    "star_platinum": "Star Platinum",
    "crazy_diamond": "Crazy Diamond",
    "gold_experience_requiem": "GER",
    "ger": "GER",
    "stone_free": "Stone Free",
}


def normalize_theme_key(theme_key: str | None) -> str:
    if theme_key in THEMES:
        return theme_key
    if isinstance(theme_key, str):
        normalized = theme_key.strip().lower().replace(" ", "_")
        return THEME_ALIASES.get(normalized, DEFAULT_THEME)
    return DEFAULT_THEME


P: dict[str, str] = dict(THEMES[DEFAULT_THEME])


def apply_theme(theme_key: str):
    global P
    theme_key = normalize_theme_key(theme_key)
    P.clear()
    P.update(THEMES[theme_key])
    return theme_key

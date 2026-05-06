# i18n
import json
import os

from core.runtime_paths import app_path

def _locales_dir():
    """Return the external locales directory for source and packaged builds."""
    return app_path("locales")

def load_translations():
    """Scan locales/ for *.json files and return {code: {key: text, ...}, ...}."""
    translations = {}
    loc_dir = _locales_dir()
    if not os.path.isdir(loc_dir):
        return {"en": {}}
    for fname in os.listdir(loc_dir):
        if fname.endswith(".json"):
            code = fname[:-5]  # "en.json" -> "en"
            path = os.path.join(loc_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    translations[code] = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
    return translations

def available_languages(translations):
    """Return list of (code, display_name) sorted alphabetically by display name."""
    langs = []
    for code, data in translations.items():
        name = data.get("lang_name", code)
        langs.append((code, name))
    langs.sort(key=lambda x: x[1])
    return langs

TRANSLATIONS = load_translations()

def _settings_path():
    return app_path("asbr_settings.json")

def current_language(default="en"):
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("language", default)
    except (json.JSONDecodeError, OSError):
        return default

def ui_text(key, **kw):
    lang = current_language()
    en = TRANSLATIONS.get("en", {})
    text = TRANSLATIONS.get(lang, en).get(key, en.get(key, key))
    return text.format(**kw) if kw else text

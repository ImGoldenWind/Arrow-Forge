import json
import os
import sys


def _settings_path():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "asbr_settings.json")


def load_settings() -> dict:
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"language": "en", "theme": "star_platinum"}


def save_settings(data: dict):
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

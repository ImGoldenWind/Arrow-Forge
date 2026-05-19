import os

from core.settings import save_settings
from core.tool_data import CAT_KEYS, CAT_META, TOOLS
from core.translations import TRANSLATIONS


class AppStateMixin:
    def _tool_lookup(self):
        lookup = {}
        for cat_key in CAT_KEYS:
            for fh, icon_fn, tk, dk in TOOLS[cat_key]:
                lookup[dk] = (cat_key, fh, icon_fn, tk, dk)
        return lookup

    def _normalise_favorites(self, favorites):
        lookup = self._tool_lookup()
        result = []
        seen = set()
        if not isinstance(favorites, list):
            return result
        for tool_id in favorites:
            if not isinstance(tool_id, str):
                continue
            if tool_id in lookup and tool_id not in seen:
                result.append(tool_id)
                seen.add(tool_id)
        return result

    def _normalise_recent_tools(self, recent_tools):
        lookup = self._tool_lookup()
        result = []
        seen = set()
        if not isinstance(recent_tools, list):
            return result
        for tool_id in recent_tools:
            if not isinstance(tool_id, str):
                continue
            if tool_id in lookup and tool_id not in seen:
                result.append(tool_id)
                seen.add(tool_id)
        return result

    def _normalise_pinned_tools(self, pinned_tools):
        lookup = self._tool_lookup()
        valid_categories = set(CAT_KEYS) | {"FAVORITES"}
        result = {}
        if not isinstance(pinned_tools, dict):
            return result
        for cat_key, tool_ids in pinned_tools.items():
            if cat_key not in valid_categories or not isinstance(tool_ids, list):
                continue
            clean_ids = []
            seen = set()
            for tool_id in tool_ids:
                if not isinstance(tool_id, str) or tool_id in seen or tool_id not in lookup:
                    continue
                if cat_key == "FAVORITES":
                    if tool_id not in self._favorite_tools:
                        continue
                elif lookup[tool_id][0] != cat_key:
                    continue
                clean_ids.append(tool_id)
                seen.add(tool_id)
            if clean_ids:
                result[cat_key] = clean_ids
        return result

    def _sort_tool_rows_for_category(self, rows, cat_key):
        pinned_rank = {
            tool_id: idx for idx, tool_id in enumerate(self._pinned_tools.get(cat_key, []))
        }
        recent_rank = {tool_id: idx for idx, tool_id in enumerate(self._recent_tools)}
        return [
            row for _idx, row in sorted(
                enumerate(rows),
                key=lambda item: (
                    0 if item[1][4] in pinned_rank else 1,
                    pinned_rank.get(item[1][4], len(pinned_rank)),
                    recent_rank.get(item[1][4], len(recent_rank)),
                    item[0],
                ),
            )
        ]

    def _visible_cat_keys(self):
        keys = (["FAVORITES"] if self._favorite_tools else []) + list(CAT_KEYS)
        if self._secret_unlocked:
            keys.append(self._SECRET_CAT)
        return keys

    def _sidebar_cat_keys(self):
        if self._current_cat == self._SECRET_CAT:
            return []
        return self._visible_cat_keys()

    def _category_i18n_key(self, cat_key):
        if cat_key == self._SECRET_CAT:
            return "Pillarmen ass hair"
        if cat_key == "FAVORITES":
            return "cat_FAVORITES"
        return CAT_META[cat_key][1]

    def _category_speaker_key(self, cat_key):
        if cat_key == self._SECRET_CAT:
            return "Johhny walking-nator"
        if cat_key == "FAVORITES":
            return "speaker_FAVORITES"
        return CAT_META[cat_key][2]

    def _computer_name(self):
        return (
            os.environ.get("COMPUTERNAME")
            or os.environ.get("HOSTNAME")
            or os.environ.get("USERDOMAIN")
            or ""
        )

    def _favorite_tool_rows(self):
        lookup = self._tool_lookup()
        rows = [lookup[tool_id] for tool_id in self._favorite_tools if tool_id in lookup]
        return self._sort_tool_rows_for_category(rows, "FAVORITES")

    def _all_tool_rows(self):
        rows = []
        for cat_key in CAT_KEYS:
            rows.extend((cat_key, fh, icon_fn, tk, dk) for fh, icon_fn, tk, dk in TOOLS[cat_key])
        return rows

    def _is_favorite_tool(self, tool_id):
        return tool_id in self._favorite_tools

    def _is_pinned_tool(self, tool_id, cat_key):
        return tool_id in self._pinned_tools.get(cat_key, [])

    def _rebuild_cat_frame_cache(self, cat_key):
        old_frame = self._cat_frames.get(cat_key)
        if old_frame:
            if old_frame is self._current_frame:
                self._current_frame = None
            old_frame.deleteLater()
        self._cat_frames[cat_key] = self._build_cat_frame(cat_key)

    def _mark_tool_used(self, tool_id):
        lookup = self._tool_lookup()
        if tool_id not in lookup:
            return

        recent_tools = [tool_id] + [
            item for item in self._recent_tools
            if item != tool_id and item in lookup
        ]
        if recent_tools == self._recent_tools:
            return

        self._recent_tools = recent_tools
        self._settings["recent_tools"] = self._recent_tools
        save_settings(self._settings)

        cat_key = lookup[tool_id][0]
        if cat_key in self._cat_frames:
            self._rebuild_cat_frame_cache(cat_key)
        if tool_id in self._favorite_tools and "FAVORITES" in self._cat_frames:
            self._rebuild_cat_frame_cache("FAVORITES")

    def _toggle_favorite_tool(self, tool_id):
        if tool_id in self._favorite_tools:
            self._favorite_tools = [item for item in self._favorite_tools if item != tool_id]
            fav_pins = [item for item in self._pinned_tools.get("FAVORITES", []) if item != tool_id]
            if fav_pins:
                self._pinned_tools["FAVORITES"] = fav_pins
            else:
                self._pinned_tools.pop("FAVORITES", None)
        else:
            self._favorite_tools.append(tool_id)
        self._settings["favorite_tools"] = self._favorite_tools
        self._settings["pinned_tools"] = self._pinned_tools
        save_settings(self._settings)
        if self._current_cat == "FAVORITES" and not self._favorite_tools:
            self._current_cat = "CHARACTER"
        self._rebuild_ui()

    def _toggle_pinned_tool(self, tool_id, cat_key):
        lookup = self._tool_lookup()
        valid_categories = set(CAT_KEYS) | {"FAVORITES"}
        if cat_key not in valid_categories or tool_id not in lookup:
            return
        if cat_key == "FAVORITES":
            if tool_id not in self._favorite_tools:
                return
        elif lookup[tool_id][0] != cat_key:
            return

        pinned = [item for item in self._pinned_tools.get(cat_key, []) if item in lookup]
        if tool_id in pinned:
            pinned = [item for item in pinned if item != tool_id]
        else:
            pinned.append(tool_id)

        if pinned:
            self._pinned_tools[cat_key] = pinned
        else:
            self._pinned_tools.pop(cat_key, None)
        self._settings["pinned_tools"] = self._pinned_tools
        save_settings(self._settings)

        if self._tool_search_query:
            self._show_tool_search_results()
            return
        if cat_key in self._cat_frames:
            self._rebuild_cat_frame_cache(cat_key)
        if self._current_cat == cat_key:
            self._show_category(cat_key)

    def t(self, key, **kw):
        text = TRANSLATIONS.get(self._lang, TRANSLATIONS["en"]).get(key, TRANSLATIONS["en"].get(key, key))
        return text.format(**kw) if kw else text

    def _card_perspective_enabled(self):
        return self._settings.get("animation_card_perspective", True)

    def _editor_fade_enabled(self):
        return self._settings.get("animation_editor_fade", True)

    def _right_panel_fade_enabled(self):
        return self._settings.get("animation_right_panel_fade", True)

    def _sidebar_highlight_animation_enabled(self):
        return self._settings.get("animation_sidebar_highlight", True)

    def _theme_personality_enabled(self):
        return self._settings.get("animation_theme_personality", True)

    def _theme_personality_motion_enabled(self):
        return self._settings.get("animation_theme_personality_motion", True)

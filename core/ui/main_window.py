import os

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from core.animations.johhny_sequence import JohhnySequenceMixin
from core.dialogs.settings_dialog import SettingsDialogMixin
from core.dialogs.update_dialogs import UpdateDialogsMixin
from core.effects.death13_chaos import Death13ChaosMixin
from core.effects.white_album import WhiteAlbumEffectMixin
from core.pages.cpk_panel import CpkPanelMixin
from core.pages.navigation import NavigationMixin
from core.quiet_unlocks import install as install_quiet_marks
from core.runtime_paths import app_path
from core.settings import load_settings, save_settings
from core.shortcuts import ShortcutManager
from core.themes import apply_theme, normalize_theme_key
from core.translations import ui_text
from core.ui.app_state import AppStateMixin
from core.ui.editor_panel import EditorPanelMixin
from core.ui.layout import AppLayoutMixin
from core.ui.opengl_surface import prepare_opengl_window
from core.widgets.unlock_toast import UnlockToast
from core.workers.update_controller import UpdateControllerMixin


class App(
    AppStateMixin,
    UpdateControllerMixin,
    UpdateDialogsMixin,
    AppLayoutMixin,
    NavigationMixin,
    EditorPanelMixin,
    JohhnySequenceMixin,
    Death13ChaosMixin,
    WhiteAlbumEffectMixin,
    CpkPanelMixin,
    SettingsDialogMixin,
    QMainWindow,
):
    _PORTRAIT_SIZE = 150
    _PORTRAIT_OVERFLOW = 60  # px the portrait floats above the panel top
    _SECRET_CAT = "PILLARMEN_ASS_HAIR"

    def __init__(self):
        super().__init__()
        prepare_opengl_window(self)
        self.setWindowTitle(ui_text("ui_ASBR-Tools_asbr_toolbox"))
        self.resize(1280, 720)
        self.setMinimumSize(960, 540)
        _ico_path = app_path("ArrowForgeIcon.ico")
        self._app_icon = QIcon(_ico_path)
        self.setWindowIcon(self._app_icon)

        self._settings = load_settings()
        self._lang = self._settings.get("language", "en")
        self._theme_key = normalize_theme_key(self._settings.get("theme"))
        apply_theme(self._theme_key)
        if self._settings.get("theme") != self._theme_key:
            self._settings["theme"] = self._theme_key
            save_settings(self._settings)
        self._disabled_tools = self._normalise_disabled_tools(self._settings.get("disabled_tools", []))
        self._favorite_tools = self._normalise_favorites(self._settings.get("favorite_tools", []))
        self._recent_tools = self._normalise_recent_tools(self._settings.get("recent_tools", []))
        self._pinned_tools = self._normalise_pinned_tools(self._settings.get("pinned_tools", {}))
        if (
            self._settings.get("disabled_tools", []) != self._disabled_tools
            or self._settings.get("favorite_tools", []) != self._favorite_tools
            or self._settings.get("recent_tools", []) != self._recent_tools
            or self._settings.get("pinned_tools", {}) != self._pinned_tools
        ):
            self._settings["disabled_tools"] = self._disabled_tools
            self._settings["favorite_tools"] = self._favorite_tools
            self._settings["recent_tools"] = self._recent_tools
            self._settings["pinned_tools"] = self._pinned_tools
            save_settings(self._settings)

        self._current_cat = "CHARACTER"
        self._typing_job = None
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(5)
        self._typing_timer.timeout.connect(self._type_tick)
        self._settings_win = None
        self._tool_frame = None
        self._cpk_editor_win = None
        self._loading = False
        self._portrait_images = {}
        self._cat_icons = {}
        self._tool_icons_cache = {}
        self._cat_frames = {}
        self._cat_buttons = {}
        self._pending_cats = []
        self._tool_search_query = ""
        self._tool_search_entry = None
        self._search_frame = None
        self._update_check_worker = None
        self._update_download_worker = None
        self._update_progress_dialog = None
        self._update_status_label = None
        self._embedded_editor = None
        self._workspace_restore_attempted = False
        self._workspace_restore_in_progress = False
        self._secret_unlocked = False
        self._moveset_avatar_clicks = 0
        self._johhny_overlay = None
        self._johhny_movie = None
        self._johhny_sound_effect = None
        self._johhny_opacity_anim = None
        self._johhny_loops = 0
        self._johhny_prev_frame = -1
        self._johhny_closing = False
        self._current_frame = None
        self._frame_transition_anim = None
        self._frame_transition_overlay = None
        self._frame_transition_target = None
        self._frame_transition_target_effect = None
        self._sidebar = None
        self._sidebar_highlight = None
        self._sidebar_highlight_anim = None
        self._tool_open_anim = None
        self._tool_open_effect = None
        self._background_decor_label = None
        self._background_decor_source = None
        self._background_decor_path = None
        self._background_wallpaper_label = None
        self._background_wallpaper_source = None
        self._background_wallpaper_path = None
        self._unlock_toasts = []

        self._central = QWidget()
        self._central.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCentralWidget(self._central)
        self._root_layout = QVBoxLayout(self._central)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self._init_white_album_effect()
        self._rebuild_ui()
        self._central.setFocus()
        self._shortcut_manager = ShortcutManager(self)
        QTimer.singleShot(900, self._restore_workspace_on_startup)
        self._init_death13_chaos()
        self._sync_white_album_effect()
        install_quiet_marks(self)
        QTimer.singleShot(1600, self._settle_quiet_marks)
        QTimer.singleShot(1400, self._auto_check_for_updates)

    def _mark_quietly(self, theme_key: str) -> bool:
        from core.continuity import all_foundation_marked, set_mark

        changed = set_mark(theme_key)
        if changed:
            self._show_unlock_toast(theme_key)
        if theme_key != "Spice Girl" and all_foundation_marked():
            if set_mark("Spice Girl"):
                QTimer.singleShot(650, lambda: self._show_unlock_toast("Spice Girl"))
        return changed

    def _settle_quiet_marks(self):
        from core.continuity import all_foundation_marked, has_mark, set_mark

        if all_foundation_marked() and not has_mark("Spice Girl") and set_mark("Spice Girl"):
            self._show_unlock_toast("Spice Girl")

    def _show_unlock_toast(self, theme_key: str):
        titles = {
            "Death 13": self.t("unlock_notice_death13_title"),
            "Baby Face": self.t("unlock_notice_baby_face_title"),
            "Chariot Requiem": self.t("unlock_notice_chariot_requiem_title"),
            "Spice Girl": self.t("unlock_notice_spice_girl_title"),
            "Geb": self.t("unlock_notice_geb_title"),
        }
        title = titles.get(theme_key, theme_key)
        toast = UnlockToast(self, title, self.t("unlock_notice_body"))
        live_toasts = []
        for item in self._unlock_toasts:
            try:
                if item is not None and not item.isHidden():
                    live_toasts.append(item)
            except RuntimeError:
                pass
        self._unlock_toasts = live_toasts[:2]
        index = len(self._unlock_toasts)
        self._unlock_toasts.append(toast)
        toast.destroyed.connect(lambda _=None, t=toast: self._forget_unlock_toast(t))
        toast.show_animated(index=index, bottom_offset=self._unlock_toast_bottom_offset())

    def _restore_workspace_on_startup(self):
        if getattr(self, "_workspace_restore_attempted", False):
            return
        if not self._settings.get("restore_workspace_on_startup", True):
            self._workspace_restore_attempted = True
            return
        if getattr(self, "_embedded_editor", None) is not None or getattr(self, "_loading", False):
            QTimer.singleShot(300, self._restore_workspace_on_startup)
            return
        workspace = self._settings.get("workspace", {})
        tool_id = workspace.get("active_tool_id", "")
        if not tool_id:
            self._workspace_restore_attempted = True
            return
        file_path = workspace.get("active_file_path", "")
        if file_path and not os.path.isfile(file_path):
            self._settings["workspace"] = {}
            save_settings(self._settings)
            self._workspace_restore_attempted = True
            return
        lookup = self._tool_lookup()
        row = lookup.get(tool_id)
        if not row or not self._is_tool_enabled(tool_id):
            self._workspace_restore_attempted = True
            return
        _cat_key, file_hint, _icon_fn, tool_label_key, _desc_key = row
        self._workspace_restore_attempted = True
        self._workspace_restore_in_progress = True
        try:
            self._open_tool_inline(self.t(tool_label_key), file_hint, tool_id)
            if file_path and self._embedded_editor is not None:
                self._load_embedded_editor_path(file_path, confirm=False, warn=False)
        finally:
            self._workspace_restore_in_progress = False

    def _unlock_toast_bottom_offset(self) -> int:
        if not self._settings.get("show_guide", True):
            return 0
        total = 0
        for attr in ("_char_sep", "_char_bottom", "_char_accent_bottom"):
            widget = getattr(self, attr, None)
            if widget is None:
                continue
            try:
                if not widget.isHidden():
                    total += widget.height()
            except RuntimeError:
                pass
        return total

    def _reposition_unlock_toasts(self):
        live_toasts = []
        for item in getattr(self, "_unlock_toasts", []):
            try:
                if item is not None and not item.isHidden():
                    live_toasts.append(item)
            except RuntimeError:
                pass
        self._unlock_toasts = live_toasts
        bottom_offset = self._unlock_toast_bottom_offset()
        for index, toast in enumerate(self._unlock_toasts):
            try:
                toast.move_to_anchor(index=index, bottom_offset=bottom_offset)
            except RuntimeError:
                pass

    def _forget_unlock_toast(self, toast):
        try:
            self._unlock_toasts.remove(toast)
        except ValueError:
            pass

    def closeEvent(self, event):
        if not self._confirm_close_embedded_editor():
            event.ignore()
            return
        if hasattr(self, "_shutdown_death13_chaos"):
            self._shutdown_death13_chaos()
        if hasattr(self, "_shutdown_white_album_effect"):
            self._shutdown_white_album_effect()
        super().closeEvent(event)

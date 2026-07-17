import inspect
import os
from unittest.mock import patch

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.command_palette import Command, CommandPalette
from core.dialogs.qol_dialogs import ChangeSummaryDialog, CompareCopyDialog
from core.editor_diff import ChangeItem
from core.file_drop import install_file_drop
from core.qol_state import with_recent_file, with_workspace
from core.settings import save_settings
from core.style_helpers import ss_dialog
from core.themes import P
from core.translations import ui_text
from core.utils.ui_helpers import _make_styled_btn
from editors.anmofs_editor import AnmofsEditor
from editors.asb_acf_editor import AsbAcfEditor
from editors.arcaderewardparam_editor import ArcadeRewardParamEditor
from editors.assist_editor import AssistEditor
from editors.battleresultparam_editor import BattleResultParamEditor
from editors.btladjprm_editor import BtlAdjPrmEditor
from editors.char_stats_editor import CharacterStatsEditor
from editors.characode_editor import CharacodeEditor
from editors.charviewer_editor import CharViewerEditor
from editors.commandlistparam_editor import CommandListParamEditor
from editors.constparam_editor import ConstParamEditor
from editors.costume_editor import CostumeEditor
from editors.cpu_editor import CpuEditor
from editors.customcardparam_editor import CustomCardParamEditor
from editors.customizedefaultparam_editor import CustomizeDefaultParamEditor
from editors.damageeff_editor import DamageEffEditor
from editors.damageprm_editor import DamagePrmEditor
from editors.dictionaryparam_editor import DictionaryParamEditor
from editors.dlcinfoparam_editor import DlcInfoParamEditor
from editors.duelsettingparam_editor import DuelSettingParamEditor
from editors.effect_editor import EffectEditor
from editors.font_editor import FontEditor
from editors.galleryartparam_editor import GalleryArtParamEditor
from editors.gimmickdmgparam_editor import GimmickDmgParamEditor
from editors.guidecharparam_editor import GuideCharParamEditor
from editors.lipsync_editor import LipSyncEditor
from editors.info_editor import InfoEditor
from editors.mainmodeparam_editor import MainModeParamEditor
from editors.messageinfo_editor import MessageInfoEditor
from editors.model_viewer_editor import ModelViewerEditor
from editors.netrankparam_editor import NetRankParamEditor
from editors.netresultparam_editor import NetResultParamEditor
from editors.onlinemissionparam_editor import OnlineMissionParamEditor
from editors.playertitleparam_editor import PlayerTitleParamEditor
from editors.projectile_editor import ProjectileEditor
from editors.skill_editor import SkillEditor
from editors.sndcmnparam_editor import SndCmnParamEditor
from editors.sound_editor import SoundEditor
from editors.soundtestparam_editor import SoundTestParamEditor
from editors.speaking_editor import SpeakingEditor
from editors.spm_editor import SpmEditor
from editors.stageinfo_editor import StageInfoEditor
from editors.stagemotion_editor import StageMotionEditor
from editors.supportitemparam_editor import SupportItemParamEditor
from editors.termlistparam_editor import TermListParamEditor
from editors.texture_editor import TextureEditor
from editors.trophyparam_editor import TrophyParamEditor
from editors.tutorialparam_editor import TutorialParamEditor
from editors.usm_video_editor import UsmVideoEditor
from editors.xfbin_audio_editor import XfbinAudioEditor


class EditorPanelMixin:
    def _method_without_required_args(self, target, names):
        if target is None:
            return None
        for name in names:
            method = getattr(target, name, None)
            if not callable(method):
                continue
            try:
                signature = inspect.signature(method)
            except (TypeError, ValueError):
                return method
            required = [
                param for param in signature.parameters.values()
                if param.default is inspect.Parameter.empty
                and param.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                )
            ]
            if not required:
                return method
        return None

    def _embedded_editor_is_dirty(self):
        editor = self._embedded_editor
        if editor is None:
            return False
        for attr in ("_dirty", "_unsaved", "_structural_dirty"):
            if bool(getattr(editor, attr, False)):
                return True
        return False

    def _embedded_editor_save_method(self):
        return self._method_without_required_args(
            self._embedded_editor,
            ("_save_file", "_on_save", "_do_save", "_save_xfbin", "save_file"),
        )

    def _save_embedded_editor(self) -> bool:
        editor = self._embedded_editor
        method = self._embedded_editor_save_method()
        if editor is None or method is None:
            return False
        if not self._confirm_editor_change_summary(editor):
            return False
        previous_skip = getattr(editor, "_host_change_summary_confirmed", False)
        setattr(editor, "_host_change_summary_confirmed", True)
        try:
            method()
        finally:
            setattr(editor, "_host_change_summary_confirmed", previous_skip)
        return True

    def _install_embedded_editor_save_summary(self, editor):
        for attr in ("_save_btn", "_btn_save", "_save_button", "save_button"):
            button = getattr(editor, attr, None)
            if not isinstance(button, QPushButton):
                continue
            try:
                button.clicked.disconnect()
            except TypeError:
                pass
            button.clicked.connect(self._save_embedded_editor)

    def _embedded_editor_open_method(self):
        return self._method_without_required_args(
            self._embedded_editor,
            ("_load_file", "_open_file", "_on_open", "_do_open", "_open_xfbin", "open_file", "load_file"),
        )

    def _embedded_editor_load_path_method(self):
        target = self._embedded_editor
        if target is None:
            return None
        for name in ("_load_file", "load_file", "open_file", "_load", "_do_load", "_start_load", "_load_cpk"):
            method = getattr(target, name, None)
            if not callable(method):
                continue
            try:
                signature = inspect.signature(method)
            except (TypeError, ValueError):
                return method
            params = list(signature.parameters.values())
            if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params):
                return method
            accepts_path = any(
                param.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                )
                for param in params
            )
            if accepts_path:
                return method
        return None

    def _handle_shortcut_action(self, action_id: str) -> bool:
        if action_id == "app.back":
            return self._shortcut_back()
        if action_id == "app.settings":
            self._open_settings()
            return True
        if action_id == "app.tool_search":
            return self._focus_tool_search()
        if action_id == "app.command_palette":
            self._open_command_palette()
            return True
        if action_id == "editor.focus_search":
            return self._focus_editor_search()
        if action_id == "editor.open":
            method = self._embedded_editor_open_method()
            if method is not None:
                method()
                return True
            return False
        if action_id == "editor.save":
            return self._save_embedded_editor()

        editor = self._embedded_editor
        shortcut_action = getattr(editor, "shortcut_action", None)
        if callable(shortcut_action):
            return bool(shortcut_action(action_id))
        return False

    def _build_command_palette_commands(self) -> list[Command]:
        commands: list[Command] = []

        def add(action_id, label_key, run, keywords=(), enabled=True, shortcut=""):
            commands.append(Command(
                id=action_id,
                label=self.t(label_key),
                keywords=tuple(keywords),
                enabled=bool(enabled),
                run=run,
                shortcut=shortcut,
            ))

        add("app.settings", "shortcut_action_app_settings", self._open_settings, ("settings",))
        add("app.tool_search", "shortcut_action_app_tool_search", self._focus_tool_search, ("search", "tools"))
        add("app.back", "shortcut_action_app_back", self._shortcut_back, ("close", "back"))
        add("editor.open", "shortcut_action_editor_open", lambda: self._handle_shortcut_action("editor.open"), ("file",), self._embedded_editor is not None)
        add("editor.save", "shortcut_action_editor_save", lambda: self._handle_shortcut_action("editor.save"), ("file",), self._embedded_editor is not None)
        add("editor.compare", "qol_compare_from_file", self._open_editor_compare, ("diff", "copy"), self._editor_supports_compare())
        for action_id, label_key in (
            ("editor.undo", "shortcut_action_editor_undo"),
            ("editor.redo", "shortcut_action_editor_redo"),
            ("editor.new", "shortcut_action_editor_new"),
            ("editor.duplicate", "shortcut_action_editor_duplicate"),
            ("editor.delete", "shortcut_action_editor_delete"),
        ):
            add(action_id, label_key, lambda aid=action_id: self._handle_shortcut_action(aid), ("editor",), self._embedded_editor is not None)

        lookup = self._tool_lookup()
        for tool_id, (cat_key, file_hint, _icon_fn, tool_label_key, desc_key) in lookup.items():
            commands.append(Command(
                id=f"tool.{tool_id}",
                label=self.t(tool_label_key),
                keywords=(self.t(desc_key), file_hint, self.t(self._category_i18n_key(cat_key))),
                enabled=True,
                run=lambda name=self.t(tool_label_key), hint=file_hint, tid=tool_id: self._open_tool_inline(name, hint, tid),
            ))

        current_tool_id = getattr(self, "_current_tool_id", None)
        for entry in self._settings.get("recent_files_by_tool", {}).get(current_tool_id, []):
            path = entry.get("path", "")
            commands.append(Command(
                id=f"recent.{path}",
                label=self.t("qol_recent_file_command", name=entry.get("name", path)),
                keywords=(path, "recent"),
                enabled=bool(path),
                run=lambda p=path: self._open_recent_editor_file(p),
            ))

        return commands

    def _open_command_palette(self):
        dialog = CommandPalette(
            self,
            self.t("command_palette_title"),
            self.t("command_palette_placeholder"),
            self._build_command_palette_commands(),
        )
        dialog.exec()

    def _shortcut_back(self) -> bool:
        if getattr(self, "_settings_win", None) is not None:
            self._close_settings_inline()
            return True
        if getattr(self, "_tool_frame", None) is not None:
            self._close_tool_inline()
            return True
        entry = getattr(self, "_tool_search_entry", None)
        if getattr(self, "_tool_search_query", "") and entry is not None:
            entry.clear()
            return True
        return False

    def _focus_tool_search(self) -> bool:
        entry = getattr(self, "_tool_search_entry", None)
        if entry is None:
            return False
        try:
            entry.setFocus(Qt.FocusReason.ShortcutFocusReason)
            entry.selectAll()
            return True
        except RuntimeError:
            return False

    def _focus_editor_search(self) -> bool:
        editor = self._embedded_editor
        if editor is not None:
            for name in ("_search_entry", "_search", "_search_box", "_filter_edit"):
                widget = getattr(editor, name, None)
                if isinstance(widget, QLineEdit):
                    widget.setFocus(Qt.FocusReason.ShortcutFocusReason)
                    widget.selectAll()
                    return True
            focus_widget = QApplication.focusWidget()
            if focus_widget is not None and editor.isAncestorOf(focus_widget):
                for widget in editor.findChildren(QLineEdit):
                    placeholder = widget.placeholderText().lower()
                    if "search" in placeholder or "поиск" in placeholder:
                        widget.setFocus(Qt.FocusReason.ShortcutFocusReason)
                        widget.selectAll()
                return True
        return self._focus_tool_search()

    def _on_embedded_editor_file_loaded(self, editor, path: str):
        if editor is not self._embedded_editor:
            return
        tool_id = getattr(self, "_current_tool_id", None)
        changed = False
        changed = with_recent_file(self._settings, tool_id, path) or changed
        changed = with_workspace(self._settings, tool_id, path) or changed
        if changed:
            save_settings(self._settings)
        self._refresh_editor_toolbar_actions()

    def _open_recent_editor_file(self, path: str):
        if not os.path.isfile(path):
            QMessageBox.warning(self, self.t("qol_recent_missing_title"), self.t("qol_recent_missing_message", path=path))
            return
        self._load_embedded_editor_path(path, confirm=True, warn=True)

    def _load_embedded_editor_path(self, path: str, *, confirm: bool = True, warn: bool = True) -> bool:
        if not path or self._embedded_editor is None:
            return False
        if confirm and not self._confirm_close_embedded_editor():
            return False
        if not os.path.isfile(path):
            if warn:
                QMessageBox.warning(self, self.t("qol_recent_missing_title"), self.t("qol_recent_missing_message", path=path))
            return False
        method = self._embedded_editor_load_path_method()
        if method is not None:
            method(path)
        else:
            method = self._embedded_editor_open_method()
            if method is None:
                if warn:
                    QMessageBox.warning(self, self.t("qol_recent_unavailable_title"), self.t("qol_recent_unavailable_message"))
                return False

            def _selected_file(*_args, **_kwargs):
                return path, ""

            def _selected_files(*_args, **_kwargs):
                return [path], ""

            with (
                patch.object(QFileDialog, "getOpenFileName", _selected_file),
                patch.object(QFileDialog, "getOpenFileNames", _selected_files),
            ):
                method()

        editor = self._embedded_editor
        if editor is not None:
            self._on_embedded_editor_file_loaded(editor, path)
        self._refresh_editor_toolbar_actions()
        return True

    def _restore_workspace_file(self):
        workspace = self._settings.get("workspace", {})
        path = workspace.get("active_file_path", "")
        if not path:
            return
        if not os.path.isfile(path):
            QMessageBox.warning(self, self.t("qol_restore_missing_title"), self.t("qol_restore_missing_message", path=path))
            self._settings["workspace"] = {}
            save_settings(self._settings)
            self._refresh_editor_toolbar_actions()
            return
        self._load_embedded_editor_path(path, confirm=True, warn=True)

    def _forget_workspace_file(self):
        self._settings["workspace"] = {}
        save_settings(self._settings)
        self._refresh_editor_toolbar_actions()

    def _editor_supports_compare(self) -> bool:
        if not self._settings.get("experimental_generic_compare_copy", False):
            return False
        return self._editor_supports_detailed_compare() or self._editor_supports_generic_compare()

    def _editor_supports_detailed_compare(self) -> bool:
        editor = self._embedded_editor
        return all(callable(getattr(editor, name, None)) for name in (
            "load_comparison_state",
            "get_current_state",
            "describe_state_diff",
            "copy_from_state",
        ))

    def _editor_supports_generic_compare(self) -> bool:
        return self._embedded_editor_load_path_method() is not None or self._embedded_editor_open_method() is not None

    def _embedded_editor_current_path(self) -> str:
        editor = self._embedded_editor
        if editor is None:
            return ""
        for attr in ("_filepath", "_xfbin_path", "_path"):
            path = getattr(editor, attr, None)
            if path:
                return str(path)
        doc = getattr(editor, "_doc", None)
        path = getattr(doc, "path", None)
        return str(path) if path else ""

    def _describe_generic_file_diff(self, current_path: str, external_path: str):
        before_label = self.t("qol_compare_no_loaded_file")
        if current_path and os.path.isfile(current_path):
            before_label = os.path.basename(current_path)
            with open(current_path, "rb") as current_file, open(external_path, "rb") as external_file:
                if current_file.read() == external_file.read() and not self._embedded_editor_is_dirty():
                    return []
        return [ChangeItem(
            "__whole_file__",
            "changed",
            self.t("qol_compare_whole_file"),
            before_label,
            os.path.basename(external_path),
            True,
        )]

    def _load_editor_compare_file(self, path: str):
        if not self._load_embedded_editor_path(path, confirm=False, warn=False):
            raise RuntimeError(self.t("qol_recent_unavailable_message"))

    def _open_editor_compare(self):
        editor = self._embedded_editor
        if editor is None or not self._editor_supports_compare():
            return
        detailed_compare = self._editor_supports_detailed_compare()
        current_path = self._embedded_editor_current_path()
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("qol_compare_open_title"),
            current_path,
            self.t("qol_compare_file_filter"),
        )
        if not path:
            return
        try:
            if detailed_compare:
                current = editor.get_current_state()
                external = editor.load_comparison_state(path)
                changes = editor.describe_state_diff(current, external)
            else:
                external = path
                changes = self._describe_generic_file_diff(current_path, path)
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("qol_compare_error", error=exc))
            return
        if not changes:
            QMessageBox.information(self, self.t("qol_compare_title"), self.t("qol_compare_no_changes"))
            return
        dialog = CompareCopyDialog(self, self.t, changes)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if detailed_compare:
                editor.copy_from_state(external, dialog.selected_item_ids)
            elif "__whole_file__" in dialog.selected_item_ids:
                if not self._confirm_close_embedded_editor():
                    return
                self._load_editor_compare_file(path)
        except Exception as exc:
            QMessageBox.critical(self, self.t("dlg_title_error"), self.t("qol_compare_copy_error", error=exc))
            return

    def _confirm_editor_change_summary(self, editor) -> bool:
        if getattr(editor, "_host_change_summary_confirmed", False):
            return True
        tool_id = getattr(self, "_current_tool_id", "")
        disabled = self._settings.get("change_summary_disabled_by_tool", {})
        if tool_id and disabled.get(tool_id):
            return True
        get_summary = getattr(editor, "get_change_summary", None)
        if callable(get_summary):
            changes = get_summary()
        else:
            changes = self._generic_editor_change_summary(editor)
        if not changes:
            return True
        dialog = ChangeSummaryDialog(self, self.t, changes)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if dialog.skip_future and tool_id:
            disabled = dict(disabled)
            disabled[tool_id] = True
            self._settings["change_summary_disabled_by_tool"] = disabled
            save_settings(self._settings)
        return True

    def _generic_editor_change_summary(self, editor):
        if editor is not self._embedded_editor or not self._embedded_editor_is_dirty():
            return []
        current_path = self._embedded_editor_current_path()
        before_label = os.path.basename(current_path) if current_path else self.t("qol_compare_no_loaded_file")
        return [ChangeItem(
            "__whole_file__",
            "changed",
            self.t("qol_compare_whole_file"),
            before_label,
            self.t("qol_diff_modified"),
            False,
        )]

    def _confirm_close_embedded_editor(self):
        if not self._embedded_editor_is_dirty():
            return True

        box = QMessageBox(self)
        box.setWindowTitle(self.t("unsaved_changes_title"))
        box.setStyleSheet(ss_dialog())
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(self.t("unsaved_changes_message"))
        box.setInformativeText(self.t("unsaved_changes_detail"))
        save_btn = box.addButton(self.t("unsaved_changes_save"), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton(self.t("unsaved_changes_discard"), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = box.addButton(self.t("unsaved_changes_cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec()

        clicked = box.clickedButton()
        if clicked == cancel_btn:
            return False
        if clicked == discard_btn:
            return True
        if clicked == save_btn:
            if self._embedded_editor_save_method() is None:
                QMessageBox.warning(
                    self,
                    self.t("unsaved_changes_title"),
                    self.t("unsaved_changes_no_save_method"),
                )
                return False
            try:
                self._save_embedded_editor()
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    self.t("dlg_title_error"),
                    self.t("msg_save_error", error=exc),
                )
                return False
            if self._embedded_editor_is_dirty():
                QMessageBox.warning(
                    self,
                    self.t("unsaved_changes_title"),
                    self.t("unsaved_changes_save_cancelled_or_failed"),
                )
                return False
            return True
        return False

    def _delete_tool_frame(self):
        self._stop_tool_open_animation()
        if self._tool_frame:
            self._tool_frame.deleteLater()
            self._tool_frame = None
        self._tool_bar = None
        self._tool_bar_layout = None
        self._tool_toolbar_action_widgets = []
        self._tool_body = None
        self._embedded_editor = None
        self._current_tool_id = None

    def _stop_tool_open_animation(self):
        anim = getattr(self, "_tool_open_anim", None)
        if anim is not None:
            try:
                anim.stop()
                anim.deleteLater()
            except RuntimeError:
                pass

        frame = getattr(self, "_tool_frame", None)
        effect = getattr(self, "_tool_open_effect", None)
        if frame is not None and effect is not None:
            try:
                if frame.graphicsEffect() is effect:
                    effect.setOpacity(1.0)
                    frame.setGraphicsEffect(None)
            except RuntimeError:
                pass

        self._tool_open_anim = None
        self._tool_open_effect = None

    def _start_tool_open_fade(self):
        self._stop_tool_open_animation()
        if not self._editor_fade_enabled():
            return
        frame = getattr(self, "_tool_frame", None)
        if frame is None or not frame.isVisible():
            return

        effect = QGraphicsOpacityEffect(frame)
        effect.setOpacity(0.0)
        frame.setGraphicsEffect(effect)

        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(170)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._tool_open_anim = anim
        self._tool_open_effect = effect

        def finish_fade():
            try:
                if frame.graphicsEffect() is effect:
                    effect.setOpacity(1.0)
                    frame.setGraphicsEffect(None)
            except RuntimeError:
                pass
            if self._tool_open_anim is anim:
                self._tool_open_anim = None
                self._tool_open_effect = None
            try:
                anim.deleteLater()
            except RuntimeError:
                pass

        anim.finished.connect(finish_fade)
        anim.start()

    def _open_tool_inline(self, name: str, file_hint: str, tool_id: str | None = None):
        if self._loading:
            return
        if not self._confirm_close_embedded_editor():
            return
        self._delete_tool_frame()
        self._current_tool_id = tool_id

        self._hide_char_panel()

        tool_frame = QWidget()
        tool_layout = QVBoxLayout(tool_frame)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.setSpacing(0)
        self._tool_frame = tool_frame

        # Top bar
        bar = QFrame()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background-color: {P.get('toolbar_bg', P['bg_panel'])};")
        self._tool_bar = bar
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 7, 12, 7)
        self._tool_bar_layout = bar_layout
        self._tool_toolbar_action_widgets = []

        back_btn = _make_styled_btn(
            "\u2190 " + self.t("back"), P["mid"], P["bg_card_hov"], P["secondary"],
            QFont("Segoe UI", 13), width=100, height=30)
        back_btn.clicked.connect(self._close_tool_inline)
        bar_layout.addWidget(back_btn)

        tool_name_lbl = QLabel(name)
        tool_name_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        tool_name_lbl.setStyleSheet(f"color: {P['accent']};")
        bar_layout.addWidget(tool_name_lbl)
        bar_layout.addStretch()

        tool_layout.addWidget(bar)

        # Body
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        tool_layout.addWidget(body, 1)
        self._tool_body = body

        if file_hint == "duelPlayerParam":
            self._embed_editor(body, body_layout)
        elif file_hint == "characode.bin":
            self._embed_characode_editor(body, body_layout)
        elif file_hint == "info":
            self._embed_info_editor(body, body_layout)
        elif file_hint == "PlayerColorParam.bin":
            self._embed_costume_editor(body, body_layout)
        elif "awb" in file_hint.lower():
            self._embed_sound_editor(body, body_layout)
        elif file_hint in ("Xcmn00prm.bin", "0xxx00prm.bin", "0xxx00prm.bin, prm_gha.bin"):
            self._embed_skill_editor(body, body_layout)
        elif tool_id == "dlg_cpu_ai" or ("cpu" in file_hint.lower() and "xfbin" in file_hint.lower()):
            self._embed_cpu_editor(body, body_layout)
        elif file_hint == "effectprm.bin":
            self._embed_effect_editor(body, body_layout)
        elif file_hint == "0xxx00_SPM":
            self._embed_spm_editor(body, body_layout)
        elif tool_id == "dlg_lip_sync" or "_lip" in file_hint.lower():
            self._embed_lipsync_editor(body, body_layout)
        elif tool_id == "dlg_anmofs" or "anmofs" in file_hint.lower():
            self._embed_anmofs_editor(body, body_layout)
        elif file_hint == "0xxx00_x":
            self._embed_projectile_editor(body, body_layout)
        elif file_hint == "0xxx00_constParam":
            self._embed_constparam_editor(body, body_layout)
        elif file_hint == "SupportCharaParam.bin":
            self._embed_assist_editor(body, body_layout)
        elif file_hint == "damageprm.bin":
            self._embed_damageprm_editor(body, body_layout)
        elif file_hint == "damageeff.bin":
            self._embed_damageeff_editor(body, body_layout)
        elif file_hint == "btladjprm.bin":
            self._embed_btladjprm_editor(body, body_layout)
        elif tool_id == "dlg_duel_setting" or file_hint in ("DuelSettingParam.bin", "DuelSettingsParam.bin"):
            self._embed_duelsettingparam_editor(body, body_layout)
        elif tool_id == "dlg_battle_result" or file_hint in (
            "BattleResultParam.bin",
            "BattleResultParam.bin / ArcadeResultParam.bin",
            "BattleResultParam.bin, ArcadeResultParam.bin",
        ):
            self._embed_battleresultparam_editor(body, body_layout)
        elif tool_id == "dlg_arcade_reward" or file_hint in (
            "ArcadeRewardParam.bin",
            "CumulativeRewardParam.bin",
            "ArcadeRewardParam.bin, CumulativeRewardParam.bin",
        ):
            self._embed_arcaderewardparam_editor(body, body_layout)
        elif file_hint == "NetRankParam.bin":
            self._embed_netrankparam_editor(body, body_layout)
        elif file_hint == "NetResultParam.bin":
            self._embed_netresultparam_editor(body, body_layout)
        elif file_hint == "OnlineMissionParam.bin":
            self._embed_onlinemissionparam_editor(body, body_layout)
        elif file_hint == "MainModeParam.bin":
            self._embed_mainmodeparam_editor(body, body_layout)
        elif file_hint == "SupportItemParam.bin":
            self._embed_supportitemparam_editor(body, body_layout)
        elif file_hint == "SpeakingLineParam.bin":
            self._embed_speaking_editor(body, body_layout)
        elif file_hint == "messageinfo":
            self._embed_messageinfo_editor(body, body_layout)
        elif file_hint == "DictionaryParam.xfbin":
            self._embed_dictionaryparam_editor(body, body_layout)
        elif file_hint == "StageInfo.bin":
            self._embed_stageinfo_editor(body, body_layout)
        elif file_hint == "Xcmnsfprm.bin":
            self._embed_stagemotion_editor(body, body_layout)
        elif file_hint == "gimmickDmgParam.bin.xfbin":
            self._embed_gimmickdmgparam_editor(body, body_layout)
        elif file_hint == "CustomCardParam.xfbin":
            self._embed_customcardparam_editor(body, body_layout)
        elif file_hint == "CharViewerParam.xfbin":
            self._embed_charviewer_editor(body, body_layout)
        elif file_hint == "GuideCharParam.xfbin":
            self._embed_guidecharparam_editor(body, body_layout)
        elif file_hint == "CustomizeDefaultParam.xfbin":
            self._embed_customizedefaultparam_editor(body, body_layout)
        elif file_hint == "DlcInfoParam.xfbin":
            self._embed_dlcinfoparam_editor(body, body_layout)
        elif file_hint == "GalleryArtParam.xfbin":
            self._embed_galleryartparam_editor(body, body_layout)
        elif file_hint == "PlayerTitleParam.xfbin":
            self._embed_playertitleparam_editor(body, body_layout)
        elif file_hint == "TrophyParam.bin":
            self._embed_trophyparam_editor(body, body_layout)
        elif file_hint in (".xfbin texures", ".xfbin textures"):
            self._embed_texture_editor(body, body_layout)
        elif tool_id == "dlg_font" or file_hint == "font/*.xfbin":
            self._embed_font_editor(body, body_layout)
        elif tool_id == "dlg_model_viewer" or file_hint == "bod*.xfbin models":
            self._embed_model_viewer_editor(body, body_layout)
        elif file_hint == ".xfbin sounds":
            self._embed_xfbin_audio_editor(body, body_layout)
        elif file_hint == ".usm":
            self._embed_usm_video_editor(body, body_layout)
        elif file_hint == "sndcmnparam.xfbin":
            self._embed_sndcmnparam_editor(body, body_layout)
        elif file_hint == "ASB.acf":
            self._embed_asb_acf_editor(body, body_layout)
        elif file_hint == "SoundTestParam.xfbin":
            self._embed_soundtestparam_editor(body, body_layout)
        elif file_hint == "CommandListParam.bin":
            self._embed_commandlistparam_editor(body, body_layout)
        elif file_hint == "TermListParam.bin":
            self._embed_termlistparam_editor(body, body_layout)
        elif file_hint == "TutorialParam.bin":
            self._embed_tutorialparam_editor(body, body_layout)
        else:
            self._embed_placeholder(body, body_layout, name, file_hint)

        self._show_frame(tool_frame, animate=False)
        self._refresh_editor_toolbar_actions()
        if not getattr(self, "_workspace_restore_in_progress", False):
            QTimer.singleShot(0, self._start_tool_open_fade)
        self._mark_tool_used(tool_id)
        if tool_id:
            workspace = self._settings.get("workspace", {})
            should_update_workspace = (
                workspace.get("active_tool_id") != tool_id
                or not workspace.get("active_file_path")
            )
            if should_update_workspace and with_workspace(self._settings, tool_id, None):
                save_settings(self._settings)

    def _refresh_editor_toolbar_actions(self):
        layout = getattr(self, "_tool_bar_layout", None)
        if layout is None:
            return
        for widget in getattr(self, "_tool_toolbar_action_widgets", []):
            try:
                layout.removeWidget(widget)
                widget.deleteLater()
            except RuntimeError:
                pass
        self._tool_toolbar_action_widgets = []
        if self._embedded_editor is None:
            return

        def add_widget(widget):
            self._tool_toolbar_action_widgets.append(widget)
            layout.addWidget(widget)

        tool_id = getattr(self, "_current_tool_id", None)
        workspace = self._settings.get("workspace", {})
        restore_path = workspace.get("active_file_path", "") if workspace.get("active_tool_id") == tool_id else ""
        current_path = self._embedded_editor_current_path()
        if restore_path and os.path.normcase(restore_path) != os.path.normcase(current_path):
            restore_btn = _make_styled_btn(
                self.t("qol_restore_last_file"), P["mid"], P["bg_card_hov"], P["accent"],
                QFont("Segoe UI", 11), width=150, height=30)
            restore_btn.clicked.connect(self._restore_workspace_file)
            add_widget(restore_btn)

            forget_btn = _make_styled_btn(
                self.t("qol_forget"), P["mid"], P["bg_card_hov"], P["secondary"],
                QFont("Segoe UI", 11), width=90, height=30)
            forget_btn.clicked.connect(self._forget_workspace_file)
            add_widget(forget_btn)

        recent_entries = self._settings.get("recent_files_by_tool", {}).get(tool_id, [])
        if recent_entries:
            recent_menu = QMenu(self)
            for entry in recent_entries:
                path = entry.get("path", "")
                action = recent_menu.addAction(entry.get("name") or path)
                action.setToolTip(path)
                action.setEnabled(bool(path and os.path.isfile(path) and self._embedded_editor_load_path_method()))
                action.triggered.connect(lambda _checked=False, p=path: self._open_recent_editor_file(p))
            recent_btn = _make_styled_btn(
                self.t("qol_recent_files"), P["mid"], P["bg_card_hov"], P["secondary"],
                QFont("Segoe UI", 11), width=110, height=30)
            recent_btn.setMenu(recent_menu)
            add_widget(recent_btn)

        if self._editor_supports_compare():
            compare_btn = _make_styled_btn(
                self.t("qol_compare_from_file"), P["mid"], P["bg_card_hov"], P["secondary"],
                QFont("Segoe UI", 11), width=140, height=30)
            compare_btn.clicked.connect(self._open_editor_compare)
            add_widget(compare_btn)

    def _embed_editor(self, body, layout):
        editor = CharacterStatsEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_characode_editor(self, body, layout):
        editor = CharacodeEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_info_editor(self, body, layout):
        editor = InfoEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_costume_editor(self, body, layout):
        editor = CostumeEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_sound_editor(self, body, layout):
        editor = SoundEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_skill_editor(self, body, layout):
        editor = SkillEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_cpu_editor(self, body, layout):
        editor = CpuEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_effect_editor(self, body, layout):
        editor = EffectEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_spm_editor(self, body, layout):
        editor = SpmEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_lipsync_editor(self, body, layout):
        editor = LipSyncEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_anmofs_editor(self, body, layout):
        editor = AnmofsEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_projectile_editor(self, body, layout):
        editor = ProjectileEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_constparam_editor(self, body, layout):
        editor = ConstParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_assist_editor(self, body, layout):
        editor = AssistEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_damageprm_editor(self, body, layout):
        editor = DamagePrmEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_damageeff_editor(self, body, layout):
        editor = DamageEffEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_btladjprm_editor(self, body, layout):
        editor = BtlAdjPrmEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_duelsettingparam_editor(self, body, layout):
        editor = DuelSettingParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_battleresultparam_editor(self, body, layout):
        editor = BattleResultParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_arcaderewardparam_editor(self, body, layout):
        editor = ArcadeRewardParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_netrankparam_editor(self, body, layout):
        editor = NetRankParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_netresultparam_editor(self, body, layout):
        editor = NetResultParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_onlinemissionparam_editor(self, body, layout):
        editor = OnlineMissionParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_mainmodeparam_editor(self, body, layout):
        editor = MainModeParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_supportitemparam_editor(self, body, layout):
        editor = SupportItemParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_speaking_editor(self, body, layout):
        editor = SpeakingEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_messageinfo_editor(self, body, layout):
        editor = MessageInfoEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_dictionaryparam_editor(self, body, layout):
        editor = DictionaryParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_stageinfo_editor(self, body, layout):
        editor = StageInfoEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_stagemotion_editor(self, body, layout):
        editor = StageMotionEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_gimmickdmgparam_editor(self, body, layout):
        editor = GimmickDmgParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_customcardparam_editor(self, body, layout):
        editor = CustomCardParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_charviewer_editor(self, body, layout):
        editor = CharViewerEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_guidecharparam_editor(self, body, layout):
        editor = GuideCharParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_customizedefaultparam_editor(self, body, layout):
        editor = CustomizeDefaultParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_dlcinfoparam_editor(self, body, layout):
        editor = DlcInfoParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_galleryartparam_editor(self, body, layout):
        editor = GalleryArtParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_playertitleparam_editor(self, body, layout):
        editor = PlayerTitleParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_trophyparam_editor(self, body, layout):
        editor = TrophyParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_texture_editor(self, body, layout):
        editor = TextureEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_font_editor(self, body, layout):
        editor = FontEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_model_viewer_editor(self, body, layout):
        editor = ModelViewerEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_xfbin_audio_editor(self, body, layout):
        editor = XfbinAudioEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_usm_video_editor(self, body, layout):
        editor = UsmVideoEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_sndcmnparam_editor(self, body, layout):
        editor = SndCmnParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_asb_acf_editor(self, body, layout):
        editor = AsbAcfEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_soundtestparam_editor(self, body, layout):
        editor = SoundTestParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_commandlistparam_editor(self, body, layout):
        editor = CommandListParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_termlistparam_editor(self, body, layout):
        editor = TermListParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_tutorialparam_editor(self, body, layout):
        editor = TutorialParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _add_embedded_editor(self, editor, layout):
        self._embedded_editor = editor
        editor._tool_id = getattr(self, "_current_tool_id", None)
        install_file_drop(editor)
        layout.addWidget(editor, 1)
        self._install_embedded_editor_save_summary(editor)

    def _embed_placeholder(self, body, layout, name, file_hint):
        lbl = QLabel(ui_text("ui_ASBR-Tools_value_value", p0=name, p1=file_hint))
        lbl.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {P['text_dim']};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl, 1)

    def _close_tool_inline(self):
        if not self._confirm_close_embedded_editor():
            return
        self._delete_tool_frame()
        if self._settings.get("show_guide", True):
            self._show_char_panel()
        if self._tool_search_query:
            self._show_tool_search_results()
            return
        cat_frame = self._cat_frames.get(self._current_cat)
        if cat_frame:
            self._show_frame(cat_frame)

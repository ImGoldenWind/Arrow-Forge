import inspect

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget,
)

from core.file_drop import install_file_drop
from core.style_helpers import ss_dialog
from core.themes import P
from core.translations import ui_text
from core.utils.ui_helpers import _make_styled_btn
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
from editors.effect_editor import EffectEditor
from editors.galleryartparam_editor import GalleryArtParamEditor
from editors.guidecharparam_editor import GuideCharParamEditor
from editors.info_editor import InfoEditor
from editors.mainmodeparam_editor import MainModeParamEditor
from editors.messageinfo_editor import MessageInfoEditor
from editors.netresultparam_editor import NetResultParamEditor
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
from editors.termlistparam_editor import TermListParamEditor
from editors.texture_editor import TextureEditor
from editors.usm_video_editor import UsmVideoEditor
from editors.xfbin_audio_editor import XfbinAudioEditor


class EditorPanelMixin:
    def _embedded_editor_is_dirty(self):
        editor = self._embedded_editor
        if editor is None:
            return False
        for attr in ("_dirty", "_unsaved", "_structural_dirty"):
            if bool(getattr(editor, attr, False)):
                return True
        return False

    def _embedded_editor_save_method(self):
        editor = self._embedded_editor
        if editor is None:
            return None
        for name in ("_save_file", "_on_save", "_do_save", "_save_xfbin", "save_file"):
            method = getattr(editor, name, None)
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
            save_method = self._embedded_editor_save_method()
            if save_method is None:
                QMessageBox.warning(
                    self,
                    self.t("unsaved_changes_title"),
                    self.t("unsaved_changes_no_save_method"),
                )
                return False
            try:
                save_method()
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
        self._tool_body = None
        self._embedded_editor = None

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
        elif tool_id == "dlg_battle_result" or file_hint in (
            "BattleResultParam.bin",
            "BattleResultParam.bin / ArcadeResultParam.bin",
            "BattleResultParam.bin, ArcadeResultParam.bin",
        ):
            self._embed_battleresultparam_editor(body, body_layout)
        elif tool_id == "dlg_arcade_reward" or file_hint == "ArcadeRewardParam.bin":
            self._embed_arcaderewardparam_editor(body, body_layout)
        elif file_hint == "NetResultParam.bin":
            self._embed_netresultparam_editor(body, body_layout)
        elif file_hint == "MainModeParam.bin":
            self._embed_mainmodeparam_editor(body, body_layout)
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
        elif file_hint in (".xfbin texures", ".xfbin textures"):
            self._embed_texture_editor(body, body_layout)
        elif file_hint == ".xfbin sounds":
            self._embed_xfbin_audio_editor(body, body_layout)
        elif file_hint == ".usm":
            self._embed_usm_video_editor(body, body_layout)
        elif file_hint == "sndcmnparam.xfbin":
            self._embed_sndcmnparam_editor(body, body_layout)
        elif file_hint == "SoundTestParam.xfbin":
            self._embed_soundtestparam_editor(body, body_layout)
        elif file_hint == "CommandListParam.bin":
            self._embed_commandlistparam_editor(body, body_layout)
        elif file_hint == "TermListParam.bin":
            self._embed_termlistparam_editor(body, body_layout)
        else:
            self._embed_placeholder(body, body_layout, name, file_hint)

        self._show_frame(tool_frame, animate=False)
        QTimer.singleShot(0, self._start_tool_open_fade)
        self._mark_tool_used(tool_id)

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

    def _embed_battleresultparam_editor(self, body, layout):
        editor = BattleResultParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_arcaderewardparam_editor(self, body, layout):
        editor = ArcadeRewardParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_netresultparam_editor(self, body, layout):
        editor = NetResultParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_mainmodeparam_editor(self, body, layout):
        editor = MainModeParamEditor(body, self.t, embedded=True)
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

    def _embed_texture_editor(self, body, layout):
        editor = TextureEditor(body, self.t, embedded=True)
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

    def _embed_soundtestparam_editor(self, body, layout):
        editor = SoundTestParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_commandlistparam_editor(self, body, layout):
        editor = CommandListParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _embed_termlistparam_editor(self, body, layout):
        editor = TermListParamEditor(body, self.t, embedded=True)
        self._add_embedded_editor(editor, layout)

    def _add_embedded_editor(self, editor, layout):
        self._embedded_editor = editor
        install_file_drop(editor)
        layout.addWidget(editor, 1)

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

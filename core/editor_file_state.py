import os

from core.style_helpers import (
    ss_file_label,
    ss_file_label_dirty,
    ss_file_label_loaded,
)


DIRTY_PREFIX = "\u25cf "


def file_display_name(path_or_name: str | None, *, dirty: bool = False, empty_text: str = "") -> str:
    if not path_or_name:
        return empty_text
    name = os.path.basename(path_or_name)
    return f"{DIRTY_PREFIX}{name}" if dirty else name


def set_file_label(label, path_or_name: str | None = None, *, dirty: bool = False, empty_text: str = "") -> None:
    label.setText(file_display_name(path_or_name, dirty=dirty, empty_text=empty_text))
    label.setStyleSheet(ss_file_label_dirty() if dirty else ss_file_label_loaded())
    if path_or_name:
        label.setToolTip(path_or_name)


def set_file_label_empty(label, text: str) -> None:
    label.setText(text)
    label.setStyleSheet(ss_file_label())
    label.setToolTip("")

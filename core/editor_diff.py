from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChangeItem:
    item_id: str
    kind: str
    label: str
    before: str = ""
    after: str = ""
    copyable: bool = True

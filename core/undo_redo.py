from __future__ import annotations

import copy


class EditorHistory:
    """Small snapshot history used by opt-in editors."""

    def __init__(self, limit: int = 80):
        self.limit = max(1, int(limit))
        self._undo: list[object] = []
        self._redo: list[object] = []

    def clear(self):
        self._undo.clear()
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, state):
        snapshot = copy.deepcopy(state)
        if self._undo and self._undo[-1] == snapshot:
            return
        self._undo.append(snapshot)
        if len(self._undo) > self.limit:
            del self._undo[0]
        self._redo.clear()

    def undo(self, current_state):
        if not self._undo:
            return None
        self._redo.append(copy.deepcopy(current_state))
        return copy.deepcopy(self._undo.pop())

    def redo(self, current_state):
        if not self._redo:
            return None
        self._undo.append(copy.deepcopy(current_state))
        if len(self._undo) > self.limit:
            del self._undo[0]
        return copy.deepcopy(self._redo.pop())

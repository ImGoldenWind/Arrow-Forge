from typing import Iterable


class IterativeDict(dict):
    """An ordered dict that auto-assigns sequential integer values to new keys."""

    def __init__(self):
        super().__init__()
        self._next = 0

    def get_or_next(self, key):
        """Return the stored index for `key`, or assign the next sequential index."""
        val = super().get(key)
        if val is None:
            val = self[key] = self._next
            self._next += 1
        return val

    def update_or_next(self, other: Iterable):
        """Register every element of `other`, assigning indices to new ones."""
        for k in other:
            self.get_or_next(k)

    def clear(self):
        super().clear()
        self._next = 0

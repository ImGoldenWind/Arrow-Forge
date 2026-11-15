"""Format-independent opened/saved snapshots for identity-based record editors."""
import copy


class RecordSession:
    def __init__(self, result, fields):
        self.result, self.fields = result, tuple(fields)
        self.original_entries = copy.deepcopy(result['entries'])
        # Keep row objects alive so deleted identities cannot be reused.
        self._originals = {id(e): (e, copy.deepcopy(e), i) for i, e in enumerate(result['entries'])}
        self.mark_saved()

    def original(self, entry):
        pair = self._originals.get(id(entry))
        return pair[1] if pair and pair[0] is entry else None

    def original_index(self, entry):
        pair = self._originals.get(id(entry))
        return pair[2] if pair and pair[0] is entry else None

    def modified(self, entry):
        original = self.original(entry)
        return original is None or any(entry[k] != original[k] for k in self.fields)

    def mark_saved(self):
        self._saved = copy.deepcopy(self.result)

    def dirty(self):
        return self.result != self._saved

"""Pure filename matching helpers for texture batch replacement."""

from dataclasses import dataclass
import os
import re


def export_filename(name, extension, used):
    """Keep asset names inside the selected directory and avoid collisions."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .') or 'texture'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(n) for n in range(1, 10)),
                                    *('LPT' + str(n) for n in range(1, 10))}:
        name = '_' + name
    name = name[:180]
    result, number = name + extension, 1
    while result.casefold() in used:
        result = f'{name}_{number}{extension}'
        number += 1
    used.add(result.casefold())
    return result


IMPORTABLE_TEXTURE_EXTENSIONS = frozenset({
    ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".tga", ".nut",
})


@dataclass(frozen=True)
class BatchMatch:
    entry: object
    status: str
    source_path: str | None = None
    candidates: tuple[str, ...] = ()


def filename_key(path_or_name: str) -> str:
    """Return a case-insensitive basename with only the final extension removed."""
    return os.path.splitext(os.path.basename(path_or_name))[0].casefold()


def match_texture_files(entries, paths) -> tuple[list[BatchMatch], list[str]]:
    """Match entries to importable files by basename, ignoring extension.

    Duplicate importable candidates are deliberately not resolved. Unsupported
    inputs are returned separately so the preview can report them.
    """
    by_name: dict[str, list[str]] = {}
    unsupported: list[str] = []
    for path in paths:
        path = os.path.normpath(os.fspath(path))
        ext = os.path.splitext(path)[1].casefold()
        if ext not in IMPORTABLE_TEXTURE_EXTENSIONS:
            unsupported.append(path)
            continue
        by_name.setdefault(filename_key(path), []).append(path)

    results = []
    for entry in entries:
        entry_name = getattr(entry, "name", "") or ""
        candidates = tuple(sorted(by_name.get(filename_key(entry_name), ()), key=str.casefold))
        if not candidates:
            results.append(BatchMatch(entry, "missing"))
        elif len(candidates) > 1:
            results.append(BatchMatch(entry, "duplicate", candidates=candidates))
        else:
            results.append(BatchMatch(entry, "matched", source_path=candidates[0]))
    return results, sorted(unsupported, key=str.casefold)

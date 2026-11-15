"""Format-aware operations shared by Char Skills UI and regression tests."""
from __future__ import annotations

import copy
import json
import math
import struct
from pathlib import Path

from parsers.skill_parser import (
    ANM_SPEED_FUNC_NAMES, GION_FUNC_NAMES, MOT_HDR_SIZE, MOT_SUB_SIZE,
    function_name, motion_subentry_size, parse_motion_subentry,
)

START_FRAME = 9998
END_FRAME = 9999


def frame_label(frame):
    return {START_FRAME: "Start", END_FRAME: "End"}.get(int(frame), str(int(frame)))


def timeline_frame(sub, maximum):
    frame = int(sub.get("frame_w", 0))
    return 0 if frame == START_FRAME else maximum if frame == END_FRAME else frame


def shift_frames(entry, delta, first=0, last=9997):
    """Shift numbered frames atomically; Start/End and command order survive."""
    updates = []
    for sub in entry.get("subentries", []):
        frame = int(sub.get("frame_w", 0))
        if 0 <= frame <= 9997 and first <= frame <= last:
            value = frame + int(delta)
            if not 0 <= value <= 9997:
                raise ValueError("Shifted frames must be between 0 and 9997")
            updates.append((sub, value))
    for sub, value in updates:
        sub.update(frame_w=value, frame_str=str(value))
    return len(updates)


def validate_skills(result):
    issues = []

    def issue(severity, location, message):
        issues.append(dict(severity=severity, location=location, message=message))

    def string(value, size, location):
        try:
            encoded = str(value).encode("ascii")
            if b"\0" in encoded or len(encoded) > size:
                raise ValueError()
        except (UnicodeEncodeError, ValueError):
            issue("error", location, f"{location}: requires ASCII, no NUL, at most {size} bytes")

    def number(value, lo, hi, location):
        try:
            valid = lo <= int(value) <= hi and int(value) == value
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            issue("error", location, f"{location}: integer must be in {lo}..{hi}")

    for key in ("mot", "gha"):
        seen = set()
        for i, entry in enumerate(result.get(key, {}).get("entries", [])):
            loc = f"{key}[{i}] {entry.get('event_id', '')}"
            for field in ("event_id", "anim_id"):
                string(entry.get(field, ""), 32, f"{loc}.{field}")
            name = entry.get("event_id", "")
            if name and name in seen:
                issue("warning", loc, f"{loc}: duplicate event ID")
            seen.add(name)
            if len(entry.get('subentries', [])) > 256:
                issue('warning', loc, f'{loc}: the native player dispatcher executes only the first 256 commands')
            for field in ("enable_face_animation", "no_frame_skip", "fix_position", "frame_skip", "file_id"):
                number(entry.get(field, 0), 0, 0xFFFFFFFF, f"{loc}.{field}")
            for j, sub in enumerate(entry.get("subentries", [])):
                sloc = f"{loc}.command[{j}]"
                string(sub.get("bone", ""), 32, f"{sloc}.bone")
                number(sub.get("dtype", 0), 0, 0xFFFFFFFF, f"{sloc}.opcode")
                number(sub.get("frame_w", 0), 0, 65535, f"{sloc}.frame")
                if int(sub.get('frame_w', 0)) > 9999:
                    issue('warning', sloc, f'{sloc}: reserved frame marker preserved')
                name = function_name(sub.get("dtype", 0))
                opcode = int(sub.get('dtype', 0)) & 0xFFFF
                if opcode in (0x6C, 0xEB):
                    following = entry.get('subentries', [])[j + 1:j + 2]
                    if not following:
                        issue('warning', sloc, f'{sloc}: fog Begin needs a following command containing its color data')
                    elif (int(following[0].get('dtype', 0)) & 0xFFFF) != (0x6D if opcode == 0x6C else 0xEC):
                        issue('warning', sloc, f'{sloc}: fog Begin reads color from the next command, regardless of its function')
                    raw = sub.get('raw_bytes', b'')
                    if len(raw) >= 0x3C and struct.unpack_from('<i', raw, 0x38)[0] <= 0:
                        issue('warning', sloc, f'{sloc}: fog duration should be positive; the native handler divides by it')
                if name.startswith("0x"):
                    issue("warning", sloc, f"{sloc}: unnamed opcode {name}; raw bytes preserved")
                for field in (("speed_multiplier",) if name in ANM_SPEED_FUNC_NAMES else
                              ("gion_scale",) if name in GION_FUNC_NAMES else ()):
                    if not math.isfinite(float(sub.get(field, 0))):
                        issue("error", sloc, f"{sloc}.{field}: requires a finite value")
                if name in GION_FUNC_NAMES:
                    string(sub.get("gion_id", ""), 32, f"{sloc}.gion_id")
                if motion_subentry_size(sub.get("dtype", 0)) > MOT_SUB_SIZE:
                    string(sub.get("dmg_label", ""), 32, f"{sloc}.descriptor")
                    if sub.get("dmg_label", "").startswith("DAMAGE_ID"):
                        for field in ("dmg", "grd"):
                            number(sub.get(field, 0), 0, 0xFFFFFFFF, f"{sloc}.{field}")
                        number(sub.get("push", 0), -0x80000000, 0x7FFFFFFF, f"{sloc}.push")
                        for field in ("x", "y"):
                            if not math.isfinite(float(sub.get(field, 0))):
                                issue("error", sloc, f"{sloc}.{field}: requires a finite value")
    for i, entry in enumerate(result.get("sklslot", {}).get("entries", [])):
        for field, size in (("slot_name", 64), ("xfbin", 32), ("skill_id", 33)):
            string(entry.get(field, ""), size, f"slot[{i}].{field}")
    for i, entry in enumerate(result.get("load", {}).get("entries", [])):
        for field in ("category", "code"):
            string(entry.get(field, ""), 32, f"load[{i}].{field}")
        number(entry.get("type", 0), 0, 0xFFFFFFFF, f"load[{i}].type")
        if i:
            number(entry.get("flag", 0), 0, 0xFFFFFFFF, f"load[{i}].flag")
    return issues


def resource_roots(prm_path, configured=""):
    parent = Path(prm_path).resolve().parent
    candidates = [parent.parent, parent]
    if configured:
        config = Path(configured).resolve()
        candidates.extend((config, config.parent if config.name.lower() == "spc" else config / "data_win32"))
    return list(dict.fromkeys(candidates))


def resolve_resource(roots, folder, name, code):
    """Resolve only inside explicitly selected asset roots (never arbitrary paths)."""
    name = name.replace("<codeModel>", code).replace("<code>", code)
    if not name or name == "END" or "<" in name:
        return None
    if not name.lower().endswith(".xfbin"):
        name += ".xfbin"
    for root in roots:
        root = Path(root).resolve()
        for candidate in (root / folder / name, root / name):
            candidate = candidate.resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                return str(candidate)
    return None


def related_resources(prm_path, result, configured=""):
    code = Path(prm_path).name.split("prm", 1)[0]
    roots = resource_roots(prm_path, configured)
    rows = []
    for entry in result.get("load", {}).get("entries", []):
        name = entry.get("code", "")
        if name:
            rows.append(dict(kind=entry["type"], folder=entry["category"], name=name,
                             path=resolve_resource(roots, entry["category"], name, code)))
    for entry in result.get("sklslot", {}).get("entries", []):
        name = entry.get("xfbin", "")
        if name and name != "END":
            rows.append(dict(kind="slot", folder="skill", name=name,
                             path=resolve_resource(roots, "skill", name, code)))
    return rows


def export_move(entry):
    """JSON includes opaque command bytes so unknown parameters survive transfer."""
    from parsers.skill_parser import write_mot
    clone = copy.deepcopy(entry)
    write_mot([clone], None)
    return json.dumps({
        "format": "arrow-forge-move", "version": 1,
        "header": clone["header_bytes"].hex(),
        "commands": [sub["raw_bytes"].hex() for sub in clone["subentries"]],
    }, indent=2)


def import_move(text):
    if len(text) > 8_000_000:
        raise ValueError("Move JSON is too large")
    payload = json.loads(text)
    if payload.get("format") != "arrow-forge-move" or payload.get("version") != 1:
        raise ValueError("Unsupported move JSON format/version")
    header = bytes.fromhex(payload["header"])
    if len(header) != MOT_HDR_SIZE or len(payload["commands"]) > 10000:
        raise ValueError("Invalid move header or command count")
    subs = []
    for value in payload["commands"]:
        raw = bytes.fromhex(value)
        if len(raw) < MOT_SUB_SIZE:
            raise ValueError("Truncated command in move JSON")
        sub = parse_motion_subentry(raw)
        if sub["raw_size"] != len(raw):
            raise ValueError("Command length does not match opcode")
        sub["sub_off"] = None
        subs.append(sub)
    from parsers.skill_parser import MOT_HEADER_FIELDS, _cstr, _u32le
    entry = dict(offset=None, header_bytes=header, event_id=_cstr(header, 0, 32),
                 anim_id=_cstr(header, 32, 32), subentries=subs, n_subs=len(subs))
    entry.update({key: _u32le(header, rel) for key, rel in MOT_HEADER_FIELDS.items()})
    errors = [i for i in validate_skills({"mot": {"entries": [entry]}}) if i["severity"] == "error"]
    if errors:
        raise ValueError(errors[0]["message"])
    return entry

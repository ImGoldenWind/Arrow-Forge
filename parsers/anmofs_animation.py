"""Receiver animation cues from the attacking PRM, independent of offset keys.

Native 3EF208: PL_ANM_ + command name, +38 one-based start, +3C end,
+4C speed. Only explicit receiver-animation/speed commands are simulated.
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import math
import re
import struct

from parsers.skill_tools import resolve_resource


@dataclass(frozen=True)
class AnimationCue:
    frame: float
    kind: str
    event_id: str = ''
    clip: object = None
    start: float = 0
    end: float | None = None
    speed: float = 1


@lru_cache(maxsize=24)
def _motion_file(path, modified, size):
    from parsers.skill_parser import parse_prm_xfbin
    _, result = parse_prm_xfbin(path)
    return tuple(entry for kind in ('mot', 'gha') for entry in result.get(kind, {}).get('entries', []))


def motion_catalog(roots, code):
    entries, sources, errors = [], [], []
    for suffix in ('prm.bin', 'prm_gha.bin'):
        path = resolve_resource(roots, 'spc', code + suffix, code)
        if not path:
            continue
        try:
            stat = Path(path).stat()
            entries.extend(_motion_file(path, stat.st_mtime_ns, stat.st_size))
            sources.append(path)
        except Exception as exc:
            errors.append(f'{Path(path).name}: {exc}')
    return entries, sources, errors


def attacking_motion(roots, owner, name):
    """Stand/form banks have their own PRMs; require an exact motion match."""
    sources, errors = [], []
    codes = [owner]
    if re.match(r'[0-9][A-Za-z0-9]{5}', name) and name[:6] != owner:
        codes.append(name[:6])
    for code in codes:
        entries, paths, problems = motion_catalog(roots, code)
        sources.extend(paths)
        errors.extend(problems)
        motion = next((entry for entry in entries if entry['anim_id'] == name), None)
        if motion is not None:
            return motion, sources, errors, code
    return None, sources, errors, owner


def clip_for_event(event_id, entries, clips, code):
    """Resolve receiver event -> receiver PRM animation; retain exact case."""
    names = {clip.name: clip for clip in clips}
    events = {}
    for entry in entries:
        events.setdefault(entry['event_id'], entry['anim_id'])
    seen = set()
    name = event_id
    while name and name not in seen:
        seen.add(name)
        if name in names:
            return names[name]
        name = events.get(name, '').replace('<code>', code)
        if name and name not in names and not name.startswith('PL_ANM_'):
            name = 'PL_ANM_' + name
    return None


def file_duration(clip):
    return clip.frame_count * max(1, int(clip.chunk.frame_size)) / 100


@lru_cache(maxsize=16)
def _animation_file(path, modified, size):
    from parsers.model_xfbin_parser import load_animation_clips
    return tuple(load_animation_clips([path]))


def attack_clip(roots, code, motion_name):
    for name in dict.fromkeys((motion_name.split('_', 1)[0], code + 'ghh1', code + 'mot1')):
        path = resolve_resource(roots, 'spc', name, code)
        if path:
            stat = Path(path).stat()
            for clip in _animation_file(path, stat.st_mtime_ns, stat.st_size):
                if clip.name == motion_name:
                    return clip
    return None


def attack_duration(roots, code, motion_name):
    clip = attack_clip(roots, code, motion_name)
    return file_duration(clip) if clip is not None else None


def build_cues(motion, receiver_entries, clips, receiver, duration=None):
    cues, unresolved = [], []
    for sub in motion.get('subentries', []) if motion else []:
        kind = sub.get('func_name')
        if kind not in ('ME_ENEMY_SET_ANIMATION', 'ME_ENEMY_ANM_SPEED_SET'):
            continue
        frame = sub['frame_w']
        if frame == 9998:
            frame = 0
        elif frame == 9999:
            if duration is None:
                unresolved.append('End')
                continue
            frame = duration
        elif frame > 9999:
            unresolved.append(str(frame))
            continue
        raw = sub['raw_bytes']
        speed = struct.unpack_from('<f', raw, 0x4c)[0]
        if not math.isfinite(speed):
            unresolved.append(f'{frame}: speed')
            continue
        if kind == 'ME_ENEMY_ANM_SPEED_SET':
            cues.append(AnimationCue(frame, 'speed', speed=speed))
            continue
        event = 'PL_ANM_' + sub['bone']
        clip = clip_for_event(event, receiver_entries, clips, receiver)
        if clip is None:
            unresolved.append(event)
        start, end = struct.unpack_from('<ii', raw, 0x38)
        cues.append(AnimationCue(frame, 'clip', event, clip, max(0, start - 1),
                                 end if end > 0 else None, speed))
    # Stable sorting preserves repeated commands at the same tick.
    return sorted(cues, key=lambda cue: cue.frame), list(dict.fromkeys(unresolved))


def _advance(position, elapsed, speed, cue):
    end = min(cue.end, file_duration(cue.clip)) if cue.end is not None else file_duration(cue.clip)
    start = min(cue.start, end)
    position += elapsed * speed
    if cue.clip.looped and end > start:
        return start + (position - start) % (end - start)
    return max(start, min(position, end))


def reaction_pose(cues, frame):
    """Seekable animation state; repeated set-animation commands restart it."""
    active, position, previous, speed = None, 0.0, 0.0, 1.0
    for cue in cues:
        if cue.frame > frame:
            break
        if active and active.clip is not None:
            position = _advance(position, cue.frame - previous, speed, active)
        if cue.kind == 'clip':
            active, position, speed = cue, cue.start, cue.speed
        else:
            speed = cue.speed
        previous = cue.frame
    if active is None or active.clip is None:
        return None, 0.0, active
    position = _advance(position, frame - previous, speed, active)
    sample = position * 100 / max(1, int(active.clip.chunk.frame_size))
    return active.clip, sample, active

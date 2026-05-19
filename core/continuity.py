import base64
import getpass
import hashlib
import hmac
import json
import os
import platform
import secrets
import time

from core.runtime_paths import source_root, user_config_path


_TAGS = {
    "Death 13": "n13",
    "Baby Face": "b5f",
    "Chariot Requiem": "c0r",
    "Geb": "g3b",
    "Spice Girl": "s9g",
}
_FOUNDATION = ("Death 13", "Baby Face", "Chariot Requiem", "Geb")
_PEPPER = b"af.ui.cache.v3:polnareff-landed-on-his-feet"


def _sink_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return os.path.join(base, "Microsoft", "CLR_v4.0", "UsageLogs", "qt_renderer.db")
    return user_config_path("cache", "qt_renderer.db")


def marked_names() -> tuple[str, ...]:
    return tuple(_TAGS)


def foundation_names() -> tuple[str, ...]:
    return _FOUNDATION


def _grain() -> bytes:
    parts = [
        platform.node(),
        getpass.getuser(),
        os.path.abspath(source_root()).casefold(),
    ]
    return hashlib.sha256(("\n".join(parts)).encode("utf-8", "ignore") + _PEPPER).digest()


def _seal(blob: dict) -> str:
    body = json.dumps(blob, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(_grain(), body, hashlib.sha256).hexdigest()


def _pack(blob: dict) -> bytes:
    blob = dict(blob)
    blob["sig"] = _seal({k: v for k, v in blob.items() if k != "sig"})
    raw = json.dumps(blob, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw)


def _blank() -> dict:
    return {"v": 2, "n": secrets.token_hex(10), "t": [], "m": int(time.time())}


def _read() -> dict:
    try:
        with open(_sink_path(), "rb") as fh:
            raw = base64.urlsafe_b64decode(fh.read().strip() or b"e30=")
        blob = json.loads(raw.decode("utf-8"))
        if not isinstance(blob, dict):
            return _blank()
        sig = blob.get("sig", "")
        body = {k: v for k, v in blob.items() if k != "sig"}
        if not hmac.compare_digest(str(sig), _seal(body)):
            return _blank()
        if not isinstance(blob.get("t"), list):
            blob["t"] = []
        return blob
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return _blank()


def _write(blob: dict) -> None:
    sink = _sink_path()
    os.makedirs(os.path.dirname(sink), exist_ok=True)
    tmp = sink + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(_pack(blob))
    os.replace(tmp, sink)


def has_mark(name: str) -> bool:
    token = _TAGS.get(name)
    if token is None:
        return False
    return token in set(_read().get("t", []))


def set_mark(name: str) -> bool:
    token = _TAGS.get(name)
    if token is None:
        return False
    blob = _read()
    marks = set(str(item) for item in blob.get("t", []))
    if token in marks:
        return False
    marks.add(token)
    blob["t"] = sorted(marks)
    blob["m"] = int(time.time())
    _write(blob)
    return True


def all_foundation_marked() -> bool:
    return all(has_mark(name) for name in _FOUNDATION)

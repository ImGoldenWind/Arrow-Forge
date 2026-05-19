import atexit
import hashlib
import os
import tempfile
import zlib

from PyQt6.QtGui import QPixmap

from core.runtime_paths import app_path


_SECRET_ASSETS = {
    "d13_face": ("resources/payloads/0f3a8c11.afs", ".jpg"),
    "d13_laugh": ("resources/payloads/31b4de09.afs", ".wav"),
    "d13_circus": ("resources/payloads/5c91a42f.afs", ".wav"),
    "d13_robot": ("resources/payloads/86ef210d.afs", ".wav"),
    "mystery_go": ("resources/payloads/a07d6c54.afs", ".wav"),
    "jwalker": ("resources/payloads/d40b91aa.afs", ".gif"),
}

_MATERIALIZED = {}
_TEMP_PATHS = set()


def _key_material():
    parts = ("AF", "13", "dream", "toolbox", "requiem", "sleep")
    return "::".join(parts).encode("utf-8")


def _xor_stream(data):
    key = _key_material()
    out = bytearray()
    counter = 0
    for offset in range(0, len(data), 32):
        block = hashlib.blake2s(key + counter.to_bytes(4, "little"), digest_size=32).digest()
        chunk = data[offset:offset + 32]
        out.extend(byte ^ block[idx] for idx, byte in enumerate(chunk))
        counter += 1
    return bytes(out)


def secret_asset_bytes(asset_id):
    rel_path, _suffix = _SECRET_ASSETS[asset_id]
    with open(app_path(*rel_path.split("/")), "rb") as fh:
        encoded = fh.read()
    return zlib.decompress(_xor_stream(encoded))


def materialize_secret_asset(asset_id):
    cached = _MATERIALIZED.get(asset_id)
    if cached and os.path.exists(cached):
        return cached

    _rel_path, suffix = _SECRET_ASSETS[asset_id]
    fd, path = tempfile.mkstemp(prefix="af_payload_", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(secret_asset_bytes(asset_id))
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise

    _MATERIALIZED[asset_id] = path
    _TEMP_PATHS.add(path)
    return path


def secret_asset_pixmap(asset_id):
    pixmap = QPixmap()
    pixmap.loadFromData(secret_asset_bytes(asset_id))
    return pixmap


def cleanup_secret_assets():
    for path in list(_TEMP_PATHS):
        try:
            os.remove(path)
        except OSError:
            pass
        _TEMP_PATHS.discard(path)
    _MATERIALIZED.clear()


atexit.register(cleanup_secret_assets)

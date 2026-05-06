import datetime as _dt
import json
import re
import urllib.error
import urllib.request


APP_VERSION = "1.1"
GITHUB_REPO = "ImGoldenWind/Arrow-Forge"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"ArrowForge-Updater/{APP_VERSION}"


class UpdateError(Exception):
    pass


def _request_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No GitHub release was found.") from exc
        raise UpdateError(f"GitHub returned HTTP {exc.code}.") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(str(exc)) from exc


def _version_parts(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(version or ""))
    if not parts:
        return (0,)
    return tuple(int(part) for part in parts)


def _is_newer(latest: str, current: str) -> bool:
    latest_parts = _version_parts(latest)
    current_parts = _version_parts(current)
    max_len = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (max_len - len(latest_parts))
    current_parts += (0,) * (max_len - len(current_parts))
    return latest_parts > current_parts


def _asset_score(asset: dict) -> int:
    name = str(asset.get("name", "")).lower()
    if name.endswith(".zip"):
        return 30
    if name.endswith(".exe"):
        return 20
    return 0


def _select_release_asset(release: dict) -> dict | None:
    assets = [asset for asset in release.get("assets", []) if asset.get("browser_download_url")]
    assets = [asset for asset in assets if _asset_score(asset) > 0]
    if not assets:
        return None
    return max(assets, key=_asset_score)


def check_for_update(current_version: str = APP_VERSION) -> dict:
    release = _request_json(LATEST_RELEASE_API)
    latest_version = str(release.get("tag_name") or "").lstrip("vV")
    asset = _select_release_asset(release)
    update_available = bool(latest_version and _is_newer(latest_version, current_version))

    return {
        "update_available": update_available,
        "current_version": current_version,
        "latest_version": latest_version,
        "release_name": release.get("name") or release.get("tag_name") or latest_version,
        "release_url": release.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest",
        "published_at": release.get("published_at") or "",
        "body": release.get("body") or "",
        "asset_name": asset.get("name") if asset else "",
        "asset_url": asset.get("browser_download_url") if asset else "",
        "asset_size": int(asset.get("size") or 0) if asset else 0,
        "asset_digest": asset.get("digest") or "",
    }


def should_check_today(last_check: str | None) -> bool:
    today = _dt.date.today().isoformat()
    return last_check != today


def today_string() -> str:
    return _dt.date.today().isoformat()


def human_size(size: int) -> str:
    size = int(size or 0)
    if size <= 0:
        return ""
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"



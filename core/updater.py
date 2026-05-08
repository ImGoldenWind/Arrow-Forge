import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile

from core.runtime_paths import app_root


APP_VERSION = "1.1.1"
GITHUB_REPO = "ImGoldenWind/Arrow-Forge"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
USER_AGENT = f"ArrowForge-Updater/{APP_VERSION}"
DOWNLOAD_CHUNK_SIZE = 1024 * 1024 * 4
PROGRESS_MIN_BYTES = 1024 * 1024
PROGRESS_MIN_INTERVAL = 0.1
DOWNLOAD_STALL_SECONDS = 60


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


def _emit_progress(progress_callback, done: int, total: int) -> tuple[int, float]:
    now = time.monotonic()
    if progress_callback:
        progress_callback(done, total)
    return done, now


def _download_file_with_curl(url: str, dest_path: str, progress_callback=None, total_hint: int = 0) -> int | None:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return None

    cmd = [
        curl,
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--retry", "3",
        "--retry-delay", "1",
        "--connect-timeout", "15",
        "--speed-limit", "1024",
        "--speed-time", str(DOWNLOAD_STALL_SECONDS),
        "--user-agent", USER_AGENT,
        "--header", "Accept: application/octet-stream",
        "--output", dest_path,
        url,
    ]
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return None

    total = int(total_hint or 0)
    last_progress = 0
    last_progress_time = 0.0
    _emit_progress(progress_callback, 0, total)

    while process.poll() is None:
        done = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
        now = time.monotonic()
        if (
            progress_callback
            and (
                done - last_progress >= PROGRESS_MIN_BYTES
                or now - last_progress_time >= PROGRESS_MIN_INTERVAL
            )
        ):
            last_progress, last_progress_time = _emit_progress(progress_callback, done, total)
        time.sleep(0.05)

    _stdout, stderr = process.communicate()
    if process.returncode != 0:
        try:
            os.remove(dest_path)
        except OSError:
            pass
        message = (stderr or "").strip()
        raise UpdateError(message or f"curl failed with exit code {process.returncode}.")

    downloaded = os.path.getsize(dest_path)
    _emit_progress(progress_callback, downloaded, total or downloaded)
    return downloaded


def _download_file(url: str, dest_path: str, progress_callback=None, timeout: int = 30, total_hint: int = 0) -> int:
    try:
        curl_downloaded = _download_file_with_curl(
            url, dest_path, progress_callback=progress_callback, total_hint=total_hint
        )
        if curl_downloaded is not None:
            return curl_downloaded
    except UpdateError:
        if os.path.exists(dest_path):
            try:
                os.remove(dest_path)
            except OSError:
                pass

    req = urllib.request.Request(url, headers={
        "Accept": "application/octet-stream",
        "User-Agent": USER_AGENT,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or total_hint or 0)
            downloaded = 0
            last_progress = 0
            last_progress_time = 0.0
            _emit_progress(progress_callback, 0, total)
            with open(dest_path, "wb") as out:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if (
                        progress_callback
                        and (
                            downloaded == total
                            or downloaded - last_progress >= PROGRESS_MIN_BYTES
                            or now - last_progress_time >= PROGRESS_MIN_INTERVAL
                        )
                    ):
                        last_progress, last_progress_time = _emit_progress(
                            progress_callback, downloaded, total
                        )
            _emit_progress(progress_callback, downloaded, total)
            return downloaded
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError(str(exc)) from exc


def _validate_zip_members(zip_path: str, dest_dir: str) -> None:
    dest_real = os.path.realpath(dest_dir)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                if member.filename.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:", member.filename):
                    raise UpdateError(f"Unsafe path in update archive: {member.filename}")
                target = os.path.realpath(os.path.join(dest_dir, member.filename))
                if target != dest_real and not target.startswith(dest_real + os.sep):
                    raise UpdateError(f"Unsafe path in update archive: {member.filename}")
    except zipfile.BadZipFile as exc:
        raise UpdateError("The downloaded update archive is not a valid zip file.") from exc


def _extract_zip_with_tar(zip_path: str, dest_dir: str) -> bool:
    tar = shutil.which("tar")
    if not tar:
        return False
    try:
        completed = subprocess.run(
            [tar, "-xf", zip_path, "-C", dest_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return completed.returncode == 0


def _safe_extract_zip(zip_path: str, dest_dir: str) -> None:
    _validate_zip_members(zip_path, dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    if _extract_zip_with_tar(zip_path, dest_dir):
        return
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise UpdateError("The downloaded update archive is not a valid zip file.") from exc


def _find_update_source(extract_dir: str, exe_name: str) -> str:
    direct_exe = os.path.join(extract_dir, exe_name)
    if os.path.isfile(direct_exe):
        return extract_dir

    matches = []
    for dirpath, _dirnames, filenames in os.walk(extract_dir):
        if exe_name in filenames:
            rel_depth = os.path.relpath(dirpath, extract_dir).count(os.sep)
            matches.append((rel_depth, dirpath))
    if matches:
        matches.sort(key=lambda item: item[0])
        return matches[0][1]

    raise UpdateError(f"The update archive does not contain {exe_name}.")


def _bat_path(path: str) -> str:
    return os.path.abspath(path).replace("%", "%%")


def _write_apply_script(update_dir: str, source_dir: str, install_dir: str, restart_exe: str) -> str:
    script_path = os.path.join(update_dir, "apply_update.bat")
    pid = os.getpid()
    script = f'''@echo off
setlocal
set "UPDATE_DIR={_bat_path(update_dir)}"
set "SOURCE_DIR={_bat_path(source_dir)}"
set "INSTALL_DIR={_bat_path(install_dir)}"
set "RESTART_EXE={_bat_path(restart_exe)}"

powershell -NoProfile -ExecutionPolicy Bypass -Command "try {{ Wait-Process -Id {pid} -Timeout 60 }} catch {{ }}" >nul 2>nul
timeout /t 1 /nobreak >nul

robocopy "%SOURCE_DIR%" "%INSTALL_DIR%" /E /COPY:DAT /DCOPY:DAT /MT:16 /R:3 /W:1 /NFL /NDL /NJH /NJS /NP /XF asbr_settings.json >nul
set "ROBOCOPY_EXIT=%ERRORLEVEL%"
if %ROBOCOPY_EXIT% GEQ 8 (
    start "" "https://github.com/{GITHUB_REPO}/releases/latest"
    exit /b %ROBOCOPY_EXIT%
)

start "" /D "%INSTALL_DIR%" "%RESTART_EXE%"
start "" /min cmd /c "timeout /t 3 /nobreak >nul & rmdir /s /q ""%UPDATE_DIR%"""
exit /b 0
'''
    with open(script_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(script)
    return script_path


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


def download_and_prepare_update(info: dict, progress_callback=None) -> dict:
    asset_url = info.get("asset_url")
    asset_name = info.get("asset_name") or "ArrowForge-update"
    if not asset_url:
        raise UpdateError("This release does not have a downloadable zip or exe asset.")

    install_dir = app_root()
    exe_name = os.path.basename(sys.executable) if getattr(sys, "frozen", False) else "ASBR-Tools.exe"
    restart_exe = os.path.join(install_dir, exe_name)
    update_dir = tempfile.mkdtemp(prefix="arrowforge-update-")
    download_path = os.path.join(update_dir, asset_name)

    try:
        _download_file(
            asset_url,
            download_path,
            progress_callback=progress_callback,
            total_hint=int(info.get("asset_size") or 0),
        )

        ext = os.path.splitext(asset_name)[1].lower()
        if ext == ".zip":
            extract_dir = os.path.join(update_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            _safe_extract_zip(download_path, extract_dir)
            source_dir = _find_update_source(extract_dir, exe_name)
        elif ext == ".exe":
            source_dir = os.path.join(update_dir, "extracted")
            os.makedirs(source_dir, exist_ok=True)
            shutil.copy2(download_path, os.path.join(source_dir, exe_name))
        else:
            raise UpdateError(f"Unsupported update asset type: {asset_name}")

        script_path = _write_apply_script(update_dir, source_dir, install_dir, restart_exe)
        return {
            "update_dir": update_dir,
            "download_path": download_path,
            "source_dir": source_dir,
            "script_path": script_path,
            "restart_exe": restart_exe,
        }
    except Exception:
        shutil.rmtree(update_dir, ignore_errors=True)
        raise


def launch_prepared_update(script_path: str) -> None:
    if not script_path or not os.path.isfile(script_path):
        raise UpdateError("The update script was not created.")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/c", "start", "", "/min", script_path],
        cwd=os.path.dirname(script_path),
        creationflags=creationflags,
    )


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

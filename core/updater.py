import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile


APP_VERSION = "1.0"
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


def download_asset(update_info: dict, progress_callback=None) -> str:
    url = update_info.get("asset_url")
    if not url:
        raise UpdateError("The latest release does not include a downloadable updater asset.")

    filename = os.path.basename(urllib.parse.urlparse(url).path) or "ArrowForge-update"
    temp_dir = tempfile.mkdtemp(prefix="arrow_forge_update_")
    destination = os.path.join(temp_dir, filename)

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    sha256 = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=30) as response, open(destination, "wb") as output:
            total = int(response.headers.get("Content-Length") or update_info.get("asset_size") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                sha256.update(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)
    except OSError as exc:
        raise UpdateError(str(exc)) from exc

    digest = str(update_info.get("asset_digest") or "")
    if digest.startswith("sha256:"):
        expected = digest.split(":", 1)[1].lower()
        actual = sha256.hexdigest().lower()
        if actual != expected:
            raise UpdateError("Downloaded update failed SHA-256 verification.")

    return destination


def _find_update_exe(folder: str) -> str:
    preferred = []
    fallback = []
    for dirpath, _, filenames in os.walk(folder):
        for filename in filenames:
            if not filename.lower().endswith(".exe"):
                continue
            path = os.path.join(dirpath, filename)
            if filename.lower() == "asbr-tools.exe":
                preferred.append(path)
            else:
                fallback.append(path)
    candidates = preferred or fallback
    if not candidates:
        raise UpdateError("The downloaded update does not contain an executable file.")
    return candidates[0]


def stage_update_package(package_path: str) -> tuple[str, str]:
    if package_path.lower().endswith(".exe"):
        return os.path.dirname(package_path), package_path

    if not zipfile.is_zipfile(package_path):
        raise UpdateError("Unsupported update package format.")

    extract_dir = os.path.join(os.path.dirname(package_path), "extracted")
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            target_root = os.path.abspath(extract_dir)
            for member in archive.infolist():
                target_path = os.path.abspath(os.path.join(extract_dir, member.filename))
                if not target_path.startswith(target_root + os.sep) and target_path != target_root:
                    raise UpdateError("The update archive contains an unsafe path.")
            archive.extractall(extract_dir)
    except (OSError, zipfile.BadZipFile) as exc:
        raise UpdateError(str(exc)) from exc

    exe_path = _find_update_exe(extract_dir)
    return os.path.dirname(exe_path), exe_path


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False) and sys.platform.startswith("win"))


def launch_self_update(source_dir: str, source_exe: str) -> str:
    if not can_self_update():
        raise UpdateError("Automatic replacement is available only in the packaged Windows build.")

    target_exe = sys.executable
    target_dir = os.path.dirname(target_exe)
    exe_name = os.path.basename(target_exe)
    script_path = os.path.join(tempfile.mkdtemp(prefix="arrow_forge_installer_"), "apply_update.ps1")
    log_path = os.path.join(os.path.dirname(script_path), "update.log")

    script = r'''
param(
    [int]$TargetPid,
    [string]$SourceDir,
    [string]$SourceExe,
    [string]$TargetDir,
    [string]$ExeName,
    [string]$LogPath
)

function Write-UpdateLog([string]$Message) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Value "$stamp $Message"
}

try {
    Write-UpdateLog "Waiting for process $TargetPid"
    try { Wait-Process -Id $TargetPid -Timeout 90 } catch {}
    Start-Sleep -Milliseconds 700

    $sourceExeFull = (Resolve-Path -LiteralPath $SourceExe).Path
    $targetExe = Join-Path $TargetDir $ExeName

    Get-ChildItem -LiteralPath $SourceDir -Force | ForEach-Object {
        if ($_.Name -ieq "asbr_settings.json") { return }
        if ($_.FullName -ieq $sourceExeFull) { return }
        $dest = Join-Path $TargetDir $_.Name
        Copy-Item -LiteralPath $_.FullName -Destination $dest -Recurse -Force
    }

    Copy-Item -LiteralPath $sourceExeFull -Destination $targetExe -Force
    Write-UpdateLog "Updated $targetExe"
    Start-Process -FilePath $targetExe -WorkingDirectory $TargetDir
} catch {
    Write-UpdateLog "ERROR: $($_.Exception.Message)"
}
'''

    with open(script_path, "w", encoding="utf-8") as script_file:
        script_file.write(script)

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", script_path,
        "-TargetPid", str(os.getpid()),
        "-SourceDir", source_dir,
        "-SourceExe", source_exe,
        "-TargetDir", target_dir,
        "-ExeName", exe_name,
        "-LogPath", log_path,
    ]
    kwargs = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen(command, cwd=target_dir, **kwargs)
    return log_path


def cleanup_download(path: str) -> None:
    folder = os.path.dirname(path)
    if os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)

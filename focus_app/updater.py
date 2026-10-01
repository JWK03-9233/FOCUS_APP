"""GitHub Releases로 새 버전을 확인하고, 내려받아 설치합니다.

Qt에 의존하지 않습니다. 네트워크·파일 작업은 오래 걸릴 수 있으므로 UI에서는
백그라운드 스레드에서 호출합니다.

설치 방식 (PyInstaller 단일 폴더 배포본 전용):
1. 릴리스의 ``FocusApp-v<버전>-win64.zip``을 임시 폴더에 내려받고 SHA-256을 확인합니다.
2. 압축을 풀어 ``FocusApp.exe``가 든 폴더를 찾습니다.
3. 숨김 PowerShell 스크립트를 띄운 뒤 앱을 종료합니다. 스크립트는 앱 프로세스가 끝나기를
   기다렸다가 새 파일을 설치 폴더에 덮어쓰고 앱을 다시 실행합니다.
설정과 세션은 %APPDATA%에 있으므로 업데이트해도 그대로 유지됩니다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from focus_app.version import APP_NAME, GITHUB_OWNER, GITHUB_REPO, __version__

log = logging.getLogger(__name__)

ASSET_SUFFIX = "-win64.zip"
EXE_NAME = f"{APP_NAME}.exe"
LATEST_URL = "https://api.github.com/repos/{owner}/{repo}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
CHUNK = 64 * 1024


class UpdateError(Exception):
    """사용자에게 그대로 보여줄 수 있는 업데이트 오류."""


def parse_version(text: str) -> Tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2). 숫자가 없으면 (0,)."""
    nums = [int(n) for n in re.findall(r"\d+", (text or "").split("-")[0].split("+")[0])]
    return tuple(nums[:3]) or (0,)


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


@dataclass(frozen=True)
class ReleaseInfo:
    version: str  # "0.3.0"
    tag: str  # "v0.3.0"
    notes: str  # 릴리스 설명 (마크다운)
    page_url: str  # 릴리스 웹 페이지
    asset_name: str = ""
    asset_url: str = ""  # API 다운로드 주소 (비공개 저장소도 토큰으로 받을 수 있음)
    asset_size: int = 0
    sha256: str = ""  # GitHub가 제공하는 digest (없을 수 있음)

    @property
    def newer(self) -> bool:
        return is_newer(self.version)

    @property
    def installable(self) -> bool:
        return bool(self.asset_url)


# ---------------------------------------------------------------------- 네트워크
def _request(url: str, token: str = "", accept: str = "application/vnd.github+json") -> urllib.request.Request:
    req = urllib.request.Request(url)
    req.add_header("Accept", accept)
    req.add_header("User-Agent", f"{APP_NAME}/{__version__}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if token:
        # 리다이렉트(S3 등)에는 인증 헤더가 따라가지 않아야 다운로드가 실패하지 않음
        req.add_unredirected_header("Authorization", f"Bearer {token.strip()}")
    return req


def _http_error(exc: urllib.error.HTTPError, token: str) -> UpdateError:
    if exc.code == 404:
        if token:
            return UpdateError("릴리스를 찾지 못했습니다. 아직 배포된 버전이 없거나 토큰 권한이 부족합니다.")
        return UpdateError(
            "릴리스를 찾지 못했습니다. 아직 배포된 버전이 없거나, 비공개 저장소라면 설정에 GitHub 토큰이 필요합니다."
        )
    if exc.code in (401, 403):
        if exc.headers.get("X-RateLimit-Remaining") == "0":
            return UpdateError("GitHub 요청 한도를 넘었습니다. 잠시 뒤 다시 시도하세요.")
        return UpdateError("GitHub 인증에 실패했습니다. 설정의 GitHub 토큰을 확인하세요.")
    return UpdateError(f"GitHub 응답 오류 ({exc.code})")


def fetch_latest(token: str = "", timeout: float = 10.0) -> ReleaseInfo:
    """가장 최근 릴리스 정보를 가져옵니다."""
    url = LATEST_URL.format(owner=GITHUB_OWNER, repo=GITHUB_REPO)
    try:
        with urllib.request.urlopen(_request(url, token), timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, token) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("업데이트 서버에 연결하지 못했습니다. 인터넷 연결을 확인하세요.") from exc
    except ValueError as exc:
        raise UpdateError("업데이트 정보를 읽지 못했습니다.") from exc
    return release_from_json(data)


def release_from_json(data: dict) -> ReleaseInfo:
    tag = str(data.get("tag_name") or "")
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    asset = next(
        (a for a in data.get("assets") or [] if str(a.get("name", "")).lower().endswith(ASSET_SUFFIX)),
        None,
    )
    sha = ""
    if asset and str(asset.get("digest") or "").startswith("sha256:"):
        sha = str(asset["digest"]).split(":", 1)[1].lower()
    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=str(data.get("body") or ""),
        page_url=str(data.get("html_url") or RELEASES_PAGE),
        asset_name=str(asset.get("name", "")) if asset else "",
        asset_url=str(asset.get("url", "")) if asset else "",
        asset_size=int(asset.get("size") or 0) if asset else 0,
        sha256=sha,
    )


def download(
    info: ReleaseInfo,
    dest_dir: Path,
    token: str = "",
    progress: Optional[Callable[[int, int], None]] = None,
    cancelled: Optional[Callable[[], bool]] = None,
    timeout: float = 30.0,
) -> Path:
    """릴리스 zip을 내려받고 (가능하면) SHA-256을 확인합니다."""
    if not info.installable:
        raise UpdateError("이 릴리스에는 설치 파일이 없습니다.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / (info.asset_name or "update.zip")
    digest = hashlib.sha256()
    done = 0
    try:
        req = _request(info.asset_url, token, accept="application/octet-stream")
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(target, "wb") as out:
            total = int(resp.headers.get("Content-Length") or info.asset_size or 0)
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError("업데이트를 취소했습니다.")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, token) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise UpdateError("내려받는 중 연결이 끊겼습니다. 다시 시도하세요.") from exc
    if info.asset_size and done != info.asset_size:
        raise UpdateError("내려받은 파일 크기가 맞지 않습니다. 다시 시도하세요.")
    if info.sha256 and digest.hexdigest().lower() != info.sha256:
        raise UpdateError("내려받은 파일이 손상되었습니다 (체크섬 불일치). 다시 시도하세요.")
    return target


def extract(zip_path: Path, dest_dir: Path) -> Path:
    """zip을 풀고 FocusApp.exe가 들어 있는 폴더를 돌려줍니다."""
    dest_dir = dest_dir.resolve()
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                path = (dest_dir / member).resolve()
                if dest_dir != path and dest_dir not in path.parents:
                    raise UpdateError("설치 파일에 잘못된 경로가 들어 있습니다.")
            zf.extractall(dest_dir)
    except zipfile.BadZipFile as exc:
        raise UpdateError("설치 파일이 손상되었습니다.") from exc
    for exe in dest_dir.rglob(EXE_NAME):
        return exe.parent
    raise UpdateError(f"설치 파일 안에서 {EXE_NAME}를 찾지 못했습니다.")


# ---------------------------------------------------------------------- 설치
def is_frozen() -> bool:
    """PyInstaller로 만든 exe로 실행 중인지 (자동 설치는 이때만 가능)."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_write(directory: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".focusapp-write-test-", delete=True):
            return True
    except OSError:
        return False


def make_work_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="FocusApp-update-"))


def _ps_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def build_install_script(pid: int, new_dir: Path, target_dir: Path, work_dir: Path, log_path: Path) -> str:
    """앱이 끝나기를 기다렸다가 파일을 덮어쓰고 다시 실행하는 PowerShell 스크립트."""
    exe = target_dir / EXE_NAME
    return f"""
$ErrorActionPreference = 'Stop'
$log = {_ps_quote(log_path)}
function Log($m) {{ Add-Content -LiteralPath $log -Value ((Get-Date -Format s) + ' ' + $m) -Encoding UTF8 }}
try {{
    Log 'update: waiting for pid {pid}'
    for ($i = 0; $i -lt 120 -and (Get-Process -Id {pid} -ErrorAction SilentlyContinue); $i++) {{ Start-Sleep -Milliseconds 500 }}
    Start-Sleep -Milliseconds 500
    $ok = $false
    for ($try = 1; $try -le 10 -and -not $ok; $try++) {{
        try {{
            Copy-Item -Path (Join-Path {_ps_quote(new_dir)} '*') -Destination {_ps_quote(target_dir)} -Recurse -Force
            $ok = $true
        }} catch {{
            Log ('update: copy attempt ' + $try + ' failed: ' + $_.Exception.Message)
            Start-Sleep -Seconds 1
        }}
    }}
    if ($ok) {{ Log 'update: files replaced' }} else {{ Log 'update: FAILED, starting previous version' }}
}} catch {{
    Log ('update: error ' + $_.Exception.Message)
}} finally {{
    Start-Process -FilePath {_ps_quote(exe)}
    Remove-Item -LiteralPath {_ps_quote(work_dir)} -Recurse -Force -ErrorAction SilentlyContinue
}}
"""


def launch_installer(new_dir: Path, work_dir: Path, log_path: Path) -> None:
    """숨은 PowerShell로 설치 스크립트를 실행합니다. 호출 뒤 앱은 바로 종료해야 합니다."""
    target = install_dir()
    if not can_write(target):
        raise UpdateError(f"설치 폴더에 쓸 권한이 없습니다:\n{target}\n\n관리자 권한으로 실행하거나 직접 설치하세요.")
    script = build_install_script(os.getpid(), new_dir, target, work_dir, log_path)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    powershell = shutil.which("powershell") or "powershell"
    flags = 0
    if sys.platform.startswith("win"):
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
        creationflags=flags,
        close_fds=True,
    )
    log.info("업데이트 설치 스크립트 실행: %s -> %s", new_dir, target)

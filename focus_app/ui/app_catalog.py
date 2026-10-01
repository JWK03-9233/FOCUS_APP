"""허용 앱을 고를 때 보여줄 앱 목록과 아이콘.

설치된 앱은 Windows 설정의 '설치된 앱'과 같은 범위를 목표로 합니다:
시작 메뉴 바로가기 + Microsoft Store 앱 + 설치 정보(레지스트리) + App Paths.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QFileInfo, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from focus_app import winapi
from focus_app.config import KNOWN_APP_NAMES, friendly_name, normalize_exe
from focus_app.enforcer import SYSTEM_EXES

# 시작 메뉴 바로가기 중 앱 목록에 넣지 않을 것 (제거 프로그램, 설명서 등)
_SKIP_WORDS = ("uninstall", "제거", "setup", "installer", "help", "readme", "도움말", "manual", "update")


@dataclass(frozen=True)
class AppEntry:
    exe: str  # 소문자 실행 파일 이름 (예: "chrome.exe")
    name: str  # 화면 표시 이름 (예: "Google Chrome")
    path: str = ""  # 아이콘용 경로: 실행 파일, 또는 Store 앱의 로고 이미지(.png)
    running: bool = False
    usable: bool = True  # False면 실행 파일을 못 찾아 목록에는 보이지만 고를 수 없음


def running_apps() -> List[AppEntry]:
    """지금 창이 열려 있는 앱 (시스템 요소와 이 앱 자신 제외)."""
    own = winapi.current_pid()
    result: Dict[str, AppEntry] = {}
    for info in winapi.list_visible_windows():
        exe = normalize_exe(info.exe_name)
        if not exe or exe in SYSTEM_EXES or info.pid == own or exe in result:
            continue
        result[exe] = AppEntry(exe=exe, name=friendly_name(exe), path=info.exe_path, running=True)
    return list(result.values())


def _start_menu_dirs() -> List[Path]:
    dirs = []
    for env in ("ProgramData", "APPDATA"):
        base = os.environ.get(env)
        if base:
            dirs.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [d for d in dirs if d.is_dir()]


# 실행 파일 이름이 이런 것이면 앱이 아니라 설치·제거·업데이트 도구로 봄
_SKIP_EXE_WORDS = (
    "unins", "uninst", "setup", "install", "update", "updater", "crashpad", "crashreport", "helper",
    "server", "process", "agent", "dialog",
)

# 설치 프로그램이 아이콘용으로 남겨 둔 복사본이 있는 폴더
_SKIP_DIR_WORDS = ("\\windows\\installer\\", "\\package cache\\")


def is_gui_exe(path: str) -> bool:
    """창을 띄우는 프로그램인지 (PE 헤더의 Subsystem이 Windows GUI). 명령줄 도구는 False."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        if head[:2] != b"MZ":
            return False
        pe = int.from_bytes(head[0x3C:0x40], "little")
        if head[pe:pe + 4] != b"PE\0\0":
            return False
        subsystem = int.from_bytes(head[pe + 24 + 68:pe + 24 + 70], "little")
        return subsystem == 2  # IMAGE_SUBSYSTEM_WINDOWS_GUI
    except (OSError, ValueError):
        return False


def _usable_exe(path: str) -> Optional[str]:
    """앱 목록에 넣을 만한 실제 실행 파일 경로면 정리해서 돌려줍니다."""
    if not path:
        return None
    path = os.path.expandvars(path.strip().strip('"'))
    if "," in path and not path.lower().endswith(".exe"):
        path = path.rsplit(",", 1)[0].strip().strip('"')  # DisplayIcon 값 예: "C:\\Apps\\b.exe,0"
    if not path.lower().endswith(".exe") or not os.path.isfile(path):
        return None
    exe = normalize_exe(path)
    if exe in SYSTEM_EXES or any(w in exe for w in _SKIP_EXE_WORDS):
        return None
    path = path.replace("/", "\\")
    if any(w in path.lower() for w in _SKIP_DIR_WORDS):
        return None
    return path


_WEB_APP_PROXIES = ("chrome_proxy.exe", "msedge_proxy.exe", "brave_proxy.exe", "whale_proxy.exe")


def _start_menu_apps() -> List[AppEntry]:
    out = []
    for base in _start_menu_dirs():
        for lnk in base.rglob("*.lnk"):
            name = lnk.stem.strip()
            if any(w in name.lower() for w in _SKIP_WORDS):
                continue
            try:
                target = QFileInfo(str(lnk)).symLinkTarget()
            except Exception:  # noqa: BLE001 - 깨진 바로가기는 건너뜀
                continue
            # 브라우저가 만든 웹 앱 바로가기는 모두 같은 공용 실행 파일(chrome_proxy 등)을 가리켜 앱으로 구분할 수 없음
            if normalize_exe(target) in _WEB_APP_PROXIES:
                continue
            # 앱을 지워도 시작 메뉴 바로가기가 남는 경우가 많음 -> 실제 exe가 있을 때만
            path = _usable_exe(target)
            if path:
                out.append(AppEntry(exe=normalize_exe(path), name=name, path=path))
    return out


_UNINSTALL_KEYS = [
    ("HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKEY_LOCAL_MACHINE", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
]
_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
_UPDATE_RELEASE_TYPES = ("update", "hotfix", "security update", "service pack")


def unusable_key(name: str) -> str:
    """실행 파일을 못 찾은 앱을 목록에서 구분할 때 쓰는 이름 (숨기기 저장용)."""
    return "?" + "".join("_" if c in "\\/" else c for c in name.strip().lower())


def _clean_path(value: str) -> str:
    """레지스트리 값(따옴표, '경로,아이콘번호', 환경 변수)을 실제 파일 경로로."""
    path = os.path.expandvars((value or "").strip().strip('"'))
    if "," in path and not os.path.exists(path):
        path = path.rsplit(",", 1)[0].strip().strip('"')
    return path.replace("/", "\\")


def _similarity(a: str, b: str) -> int:
    """표시 이름과 실행 파일 이름이 얼마나 닮았는지 (클수록 닮음)."""
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())  # noqa: E731
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0
    if a == b:
        return 100
    if a in b or b in a:
        return 60 + min(len(a), len(b))
    return sum(1 for ch in set(a) if ch in b)


def _best_exe_in(folder: str, name: str) -> Optional[str]:
    """설치 폴더에서 이 앱의 실행 파일로 가장 그럴듯한 것 (바로 아래, 없으면 한 단계 아래 폴더까지)."""
    if not folder or not os.path.isdir(folder):
        return None
    root = Path(folder)
    for pattern in ("*.exe", "*/*.exe"):
        try:
            found = [p for p in (_usable_exe(str(f)) for f in root.glob(pattern)) if p and is_gui_exe(p)]
        except OSError:
            found = []
        if found:
            def score(p: str):
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                return (_similarity(name, Path(p).stem), size)

            return max(found, key=score)
    return None


def _registry_apps() -> List[AppEntry]:
    """Windows 설정의 '설치된 앱'에 나오는 일반(Win32) 프로그램 전부 + App Paths.

    실행 파일은 DisplayIcon → 설치 폴더 → 제거 프로그램 폴더 순으로 찾고, 끝내 못 찾으면
    목록에는 보이되 고를 수 없는 항목(usable=False)으로 넣습니다.
    """
    if not sys.platform.startswith("win"):
        return []
    import winreg

    def value(key, name):
        try:
            return str(winreg.QueryValueEx(key, name)[0] or "")
        except OSError:
            return ""

    out: List[AppEntry] = []
    for hive_name, path in _UNINSTALL_KEYS:
        try:
            root = winreg.OpenKey(getattr(winreg, hive_name), path)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    sub = winreg.OpenKey(root, winreg.EnumKey(root, i))
                except OSError:
                    continue
                with sub:
                    name = value(sub, "DisplayName").strip()
                    # Windows 설정에도 안 나오는 숨은 구성 요소·업데이트 항목만 제외
                    if not name or value(sub, "SystemComponent") == "1" or value(sub, "ParentKeyName"):
                        continue
                    if value(sub, "ReleaseType").lower() in _UPDATE_RELEASE_TYPES:
                        continue
                    icon = _clean_path(value(sub, "DisplayIcon"))
                    exe_path = _usable_exe(icon) if icon.lower().endswith(".exe") else None
                    if exe_path and not is_gui_exe(exe_path):
                        exe_path = None
                    if not exe_path:
                        folders = [_clean_path(value(sub, "InstallLocation"))]
                        if icon:
                            folders.append(str(Path(icon).parent))
                        uninst = _clean_path(value(sub, "UninstallString").split(" /")[0].split(" -")[0])
                        if uninst.lower().endswith(".exe"):
                            folders.append(str(Path(uninst).parent))
                        for folder in folders:
                            low = folder.lower()
                            if not folder or any(w in low + "\\" for w in _SKIP_DIR_WORDS) or low.rstrip("\\").endswith(
                                ("\\windows", "\\system32", "\\syswow64")
                            ):
                                continue
                            exe_path = _best_exe_in(folder, name)
                            if exe_path:
                                break
                    if exe_path:
                        out.append(AppEntry(exe=normalize_exe(exe_path), name=name, path=exe_path))
                    else:
                        out.append(AppEntry(exe=unusable_key(name), name=name, usable=False))

    windir = os.environ.get("WINDIR", r"C:\Windows").lower()
    for hive_name in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        try:
            root = winreg.OpenKey(getattr(winreg, hive_name), _APP_PATHS_KEY)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i)) as sub:
                        exe_path = _usable_exe(value(sub, ""))
                except OSError:
                    continue
                if not exe_path or not is_gui_exe(exe_path):
                    continue
                exe = normalize_exe(exe_path)
                # Office 내부 도구(mso*.exe)와 공용 구성 요소 폴더의 도구는 앱이 아님
                low = exe_path.lower()
                if exe.startswith("mso") or "common files" in low or "windows mail" in low:
                    continue
                # Windows 폴더의 도구는 잘 알려진 앱(메모장·그림판 등)만
                if low.startswith(windir) and exe not in KNOWN_APP_NAMES:
                    continue
                out.append(AppEntry(exe=exe, name=friendly_name(exe_path), path=exe_path))
    return out


# Microsoft Store(MSIX) 앱: 시작 메뉴에 보이는 앱마다 패키지 매니페스트에서 실제 실행 파일을 찾음
_STORE_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$pk = @{}
Get-AppxPackage | ForEach-Object { $pk[$_.PackageFamilyName] = $_ }
$out = foreach ($s in Get-StartApps) {
  if ($s.AppID -notmatch '!') { continue }
  $parts = $s.AppID.Split('!', 2)
  $p = $pk[$parts[0]]
  if (-not $p) { continue }
  try { [xml]$m = Get-Content -LiteralPath (Join-Path $p.InstallLocation 'AppxManifest.xml') -Raw -Encoding UTF8 } catch { continue }
  $app = @($m.Package.Applications.Application) | Where-Object { $_.Id -eq $parts[1] } | Select-Object -First 1
  if (-not $app -or -not $app.Executable) { continue }
  [pscustomobject]@{ name = $s.Name; exe = [string]$app.Executable; dir = $p.InstallLocation;
                     logo = [string]$app.VisualElements.Square44x44Logo }
}
@($out) | ConvertTo-Json -Compress
"""


def _store_logo(package_dir: str, logo: str) -> str:
    """매니페스트의 로고 경로(Assets\\X.png)를 실제 파일로. 실제로는 X.targetsize-48.png 같은 이름으로 있음."""
    if not logo:
        return ""
    target = Path(package_dir) / logo
    if target.is_file():
        return str(target)
    try:
        files = [f for f in target.parent.glob(target.stem + "*.png") if "contrast" not in f.name.lower()]
    except OSError:
        return ""
    if not files:
        return ""

    def rank(f: Path) -> tuple:
        n = f.name.lower()
        plain = "altform" not in n
        return (
            plain and "targetsize-48" in n,
            plain and "scale-200" in n,
            plain and "scale-100" in n,
            plain,
            -len(n),
        )

    return str(max(files, key=rank))


def _store_apps() -> List[AppEntry]:
    if not sys.platform.startswith("win"):
        return []
    import base64
    import json
    import subprocess

    encoded = base64.b64encode(_STORE_SCRIPT.encode("utf-16-le")).decode("ascii")
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=90,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        data = json.loads(r.stdout.decode("utf-8-sig", errors="replace") or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    out: List[AppEntry] = []
    for d in data:
        exe = normalize_exe(str(d.get("exe", "")))
        name = str(d.get("name", "")).strip()
        if not exe.endswith(".exe") or not name or exe in SYSTEM_EXES:
            continue
        icon = _store_logo(str(d.get("dir", "")), str(d.get("logo", "")))
        out.append(AppEntry(exe=exe, name=name, path=icon or str(Path(str(d.get("dir", ""))) / str(d.get("exe", "")))))
    return out


def scan_installed_apps() -> List[AppEntry]:
    """설치된 앱 목록 = Windows 설정의 '설치된 앱'과 같은 범위.

    시작 메뉴 바로가기 + Microsoft Store 앱 + 설치 정보(레지스트리) + App Paths. 수 초 걸릴 수 있습니다.
    같은 실행 파일은 앞의 출처 이름을 씁니다. 실행 파일을 못 찾은 항목은 맨 뒤에 (고를 수 없음).
    """
    result: Dict[str, AppEntry] = {}
    unusable: Dict[str, AppEntry] = {}
    for source in (_start_menu_apps, _store_apps, _registry_apps):
        try:
            entries = source()
        except Exception:  # noqa: BLE001 - 한 출처가 실패해도 나머지는 보여 줌
            continue
        for e in entries:
            if e.usable:
                result.setdefault(e.exe, e)
            else:
                unusable.setdefault(e.exe, e)
    usable_names = {e.name.strip().lower() for e in result.values()}
    rest = [e for e in unusable.values() if e.name.strip().lower() not in usable_names]
    return sorted(result.values(), key=lambda e: e.name.lower()) + sorted(rest, key=lambda e: e.name.lower())


class InstalledAppsCache:
    """설치된 앱 목록을 백그라운드에서 한 번만 읽어 둡니다."""

    def __init__(self) -> None:
        self._apps: Optional[List[AppEntry]] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def preload(self) -> None:
        with self._lock:
            if self._apps is not None or self._thread is not None:
                return
            self._thread = threading.Thread(target=self._load, name="installed-apps", daemon=True)
            self._thread.start()

    def _load(self) -> None:
        try:
            apps = scan_installed_apps()
        except Exception:  # noqa: BLE001
            apps = []
        with self._lock:
            self._apps = apps

    def get(self) -> Optional[List[AppEntry]]:
        """준비되었으면 목록, 아직 읽는 중이면 None."""
        with self._lock:
            return None if self._apps is None else list(self._apps)

    def set(self, apps: List[AppEntry]) -> None:  # 테스트용
        with self._lock:
            self._apps = list(apps)


installed_apps = InstalledAppsCache()

_icon_provider: Optional[QFileIconProvider] = None
_icon_cache: Dict[str, QIcon] = {}


def find_installed_path(exe: str) -> str:
    """설치된 앱 목록에서 실행 파일 경로를 찾습니다 (목록을 아직 못 읽었으면 빈 문자열)."""
    exe = normalize_exe(exe)
    for e in installed_apps.get() or []:
        if e.exe == exe:
            return e.path
    return ""


_LETTER_COLORS = ["#4f7cff", "#2e9e5b", "#d9822b", "#9b59b6", "#16a2b8", "#e05d7b", "#7f8c8d"]


def letter_icon(name: str, size: int = 48) -> QIcon:
    """경로를 몰라 진짜 아이콘을 못 얻을 때 쓰는, 첫 글자가 들어간 둥근 아이콘."""
    letter = (name.strip()[:1] or "?").upper()
    color = QColor(_LETTER_COLORS[sum(map(ord, name)) % len(_LETTER_COLORS)])
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.22, size * 0.22)
    font = QFont()
    font.setPixelSize(int(size * 0.5))
    font.setBold(True)
    p.setFont(font)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)
    p.end()
    return QIcon(pm)


def app_icon(path: str, name: str = "") -> QIcon:
    """실행 파일 경로의 아이콘. 경로를 모르면 이름 첫 글자 아이콘."""
    global _icon_provider
    if _icon_provider is None:
        _icon_provider = QFileIconProvider()
    key = (path or "?" + name).lower()
    if key not in _icon_cache:
        if path and path.lower().endswith(".png") and os.path.exists(path):
            _icon_cache[key] = QIcon(path)  # Store 앱 로고
        elif path and os.path.exists(path):
            _icon_cache[key] = _icon_provider.icon(QFileInfo(path))
        else:
            _icon_cache[key] = letter_icon(name or Path(path).stem or "?")
    return _icon_cache[key]

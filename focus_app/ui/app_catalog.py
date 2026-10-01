"""허용 앱을 고를 때 보여줄 앱 목록 (실행 중인 앱 + 시작 메뉴에 설치된 앱)과 아이콘."""

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
    path: str = ""  # 실행 파일 전체 경로 (아이콘 표시용)
    running: bool = False


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


# 앱이 아닌 것: 런타임·드라이버 등 (설치 정보의 표시 이름 기준)
_SKIP_NAME_WORDS = ("redistributable", "runtime", "driver", "sdk", "microsoft 365 -", "visual c++")
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


def _registry_apps() -> List[AppEntry]:
    """Windows '설치된 앱' 목록(제거 정보)과 App Paths에서 찾기.

    시작 메뉴 바로가기를 만들지 않는 앱(예: 사용자 폴더에 설치한 SumatraPDF)도 여기에는 등록됩니다.
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
                    # 숨은 구성 요소·업데이트 항목은 제외
                    if not name or value(sub, "SystemComponent") == "1" or value(sub, "ParentKeyName"):
                        continue
                    if any(w in name.lower() for w in _SKIP_WORDS + _SKIP_NAME_WORDS):
                        continue
                    exe_path = _usable_exe(value(sub, "DisplayIcon"))
                    if not exe_path:
                        # 아이콘 정보가 없으면 설치 폴더 바로 아래의 실행 파일이 하나뿐일 때만 사용
                        loc = value(sub, "InstallLocation").strip().strip('"')
                        if loc and os.path.isdir(loc):
                            exes = [p for p in (_usable_exe(str(f)) for f in Path(loc).glob("*.exe")) if p]
                            exe_path = exes[0] if len(exes) == 1 else None
                    if exe_path and is_gui_exe(exe_path):
                        out.append(AppEntry(exe=normalize_exe(exe_path), name=name, path=exe_path))

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
                if exe_path.lower().startswith(windir) and exe not in KNOWN_APP_NAMES:
                    continue
                out.append(AppEntry(exe=exe, name=friendly_name(exe_path), path=exe_path))
    return out


def scan_installed_apps() -> List[AppEntry]:
    """설치된 앱 목록: 시작 메뉴 바로가기 + Windows 설치 정보(레지스트리). 수 초 걸릴 수 있습니다.

    같은 앱은 시작 메뉴 이름을 우선합니다 (보통 더 읽기 쉬움).
    """
    result: Dict[str, AppEntry] = {}
    for source in (_start_menu_apps, _registry_apps):
        try:
            entries = source()
        except Exception:  # noqa: BLE001 - 한 출처가 실패해도 나머지는 보여 줌
            continue
        for e in entries:
            result.setdefault(e.exe, e)
    return sorted(result.values(), key=lambda e: e.name.lower())


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
        if path and os.path.exists(path):
            _icon_cache[key] = _icon_provider.icon(QFileInfo(path))
        else:
            _icon_cache[key] = letter_icon(name or Path(path).stem or "?")
    return _icon_cache[key]

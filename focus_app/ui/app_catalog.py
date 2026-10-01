"""허용 앱을 고를 때 보여줄 앱 목록 (실행 중인 앱 + 시작 메뉴에 설치된 앱)과 아이콘."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QFileInfo, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from focus_app import winapi
from focus_app.config import friendly_name, normalize_exe
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


def scan_installed_apps() -> List[AppEntry]:
    """시작 메뉴 바로가기(.lnk)를 실행 파일로 풀어 설치된 앱 목록을 만듭니다. 수 초 걸릴 수 있습니다."""
    result: Dict[str, AppEntry] = {}
    for base in _start_menu_dirs():
        for lnk in base.rglob("*.lnk"):
            name = lnk.stem.strip()
            if any(w in name.lower() for w in _SKIP_WORDS):
                continue
            try:
                target = QFileInfo(str(lnk)).symLinkTarget()
            except Exception:  # noqa: BLE001 - 깨진 바로가기는 건너뜀
                continue
            if not target.lower().endswith(".exe"):
                continue
            exe = normalize_exe(target)
            if exe in SYSTEM_EXES or exe in result:
                continue
            result[exe] = AppEntry(exe=exe, name=name, path=target.replace("/", "\\"))
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

"""설정과 프로필을 JSON 파일로 저장/불러오기.

Qt에 의존하지 않으므로 단위 테스트가 가능합니다.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from focus_app.version import APP_ID


def data_dir() -> Path:
    """사용자별 쓰기 가능한 데이터 폴더.

    Windows: %APPDATA%/FocusApp, 그 외: $XDG_DATA_HOME/FocusApp.
    테스트용으로 FOCUSAPP_DATA_DIR 환경 변수로 덮어쓸 수 있습니다.
    """
    override = os.environ.get("FOCUSAPP_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_ID
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_ID
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_ID
    base.mkdir(parents=True, exist_ok=True)
    return base


def normalize_exe(name: str) -> str:
    """실행 파일 이름을 비교용으로 정규화 (경로 제거, 소문자)."""
    name = (name or "").strip().strip('"')
    name = name.replace("/", "\\").rsplit("\\", 1)[-1]
    return name.lower()


# 자주 쓰는 앱의 읽기 쉬운 이름 (시작 메뉴 등에서 이름을 얻지 못했을 때 사용)
KNOWN_APP_NAMES: Dict[str, str] = {
    "notepad.exe": "메모장",
    "calc.exe": "계산기",
    "calculatorapp.exe": "계산기",
    "mspaint.exe": "그림판",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "outlook.exe": "Outlook",
    "onenote.exe": "OneNote",
    "olk.exe": "Outlook (새 버전)",
    "teams.exe": "Teams",
    "ms-teams.exe": "Teams",
    "acrobat.exe": "Adobe Acrobat",
    "acrord32.exe": "Adobe Acrobat Reader",
    "code.exe": "Visual Studio Code",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "whale.exe": "네이버 웨일",
    "hwp.exe": "한글",
    "notion.exe": "Notion",
    "obsidian.exe": "Obsidian",
    "slack.exe": "Slack",
    "kakaotalk.exe": "카카오톡",
    "zoom.exe": "Zoom",
    "windowsterminal.exe": "터미널",
    "sumatrapdf.exe": "SumatraPDF",
    "wt.exe": "Windows 터미널",
    "snippingtool.exe": "캡처 도구",
    "gom.exe": "곰플레이어",
    "itunes.exe": "iTunes",
    "appletv.exe": "Apple TV",
    "mscopilot.exe": "Copilot",
    "honeyview.exe": "꿀뷰",
    "skype.exe": "Skype",
}


def friendly_name(exe_name: str) -> str:
    """실행 파일 이름을 사람이 읽기 쉬운 이름으로 바꿉니다 (예: "winword.exe" -> "Word")."""
    exe = normalize_exe(exe_name)
    if exe in KNOWN_APP_NAMES:
        return KNOWN_APP_NAMES[exe]
    stem = exe[:-4] if exe.endswith(".exe") else exe
    return stem[:1].upper() + stem[1:] if stem else exe


@dataclass
class Profile:
    name: str
    allowed_apps: List[str] = field(default_factory=list)  # 실행 파일 이름 (예: "code.exe")
    block_everything: bool = True  # False면 이 프로필에서는 차단하지 않음 (자유 시간)

    def normalized_apps(self) -> List[str]:
        seen: List[str] = []
        for app in self.allowed_apps:
            n = normalize_exe(app)
            if n and n not in seen:
                seen.append(n)
        return seen

    def allows(self, exe_name: str) -> bool:
        if not self.block_everything:
            return True
        return normalize_exe(exe_name) in self.normalized_apps()

    def add_app(self, exe_name: str) -> bool:
        n = normalize_exe(exe_name)
        if not n or n in self.normalized_apps():
            return False
        self.allowed_apps.append(n)
        return True

    def remove_app(self, exe_name: str) -> None:
        n = normalize_exe(exe_name)
        self.allowed_apps = [a for a in self.allowed_apps if normalize_exe(a) != n]


def default_profiles() -> List[Profile]:
    return [
        Profile(
            "공부용",
            allowed_apps=["notepad.exe", "acrobat.exe", "winword.exe", "onenote.exe", "calc.exe"],
        ),
        Profile(
            "업무용",
            allowed_apps=["code.exe", "excel.exe", "winword.exe", "outlook.exe", "teams.exe", "notepad.exe"],
        ),
        Profile("자유 시간", allowed_apps=[], block_everything=False),
    ]


DEFAULT_DURATION_PRESETS: List[int] = [25, 50, 90, 120, 180]
MAX_DURATION_PRESETS = 8


def clean_presets(values: Any) -> List[int]:
    """시간 목록을 1~1440분 정수로 정리합니다 (중복 제거, 오름차순, 최대 8개). 비면 기본값."""
    out: List[int] = []
    if isinstance(values, list):
        for v in values:
            try:
                m = int(v)
            except (TypeError, ValueError):
                continue
            if 1 <= m <= 1440 and m not in out:
                out.append(m)
    out.sort()
    return out[:MAX_DURATION_PRESETS] or list(DEFAULT_DURATION_PRESETS)


@dataclass
class Settings:
    profiles: List[Profile] = field(default_factory=default_profiles)
    active_profile: str = "공부용"
    poll_interval_ms: int = 300  # 포그라운드 창 확인 주기
    unlock_code_length: int = 32  # 해제용 랜덤 문자열 길이
    default_duration_minutes: int = 50  # 마지막으로 고른 집중 시간. 0이면 "끝낼 때까지"
    duration_presets: List[int] = field(default_factory=lambda: list(DEFAULT_DURATION_PRESETS))
    custom_duration_minutes: int = 45  # "직접 입력" 칸에 마지막으로 넣은 값
    window_geometry: str = ""  # 메인 창 위치·크기 (Qt saveGeometry의 base64)
    check_updates_on_start: bool = True  # 실행할 때 새 버전이 있는지 확인
    github_token: str = ""  # 비공개 저장소에서 업데이트를 받을 때만 필요 (읽기 권한 토큰)
    favorite_apps: List[str] = field(default_factory=list)  # 앱 고르기 창 맨 위에 보일 즐겨찾기 (실행 파일 이름)
    hidden_apps: List[str] = field(default_factory=list)  # 앱 고르기 창 맨 아래 '숨긴 앱'으로 보낸 앱
    require_unlock_for_quit: bool = True
    require_unlock_for_profile_switch: bool = True
    emergency_delay_minutes: int = 10  # 비상 해제가 실제로 적용되기까지의 지연
    show_block_notifications: bool = True
    # 화면 표시용 앱 정보: 실행 파일 이름 -> {"name": 표시 이름, "path": 전체 경로}
    app_info: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # ------------------------------------------------------------- 조회
    def profile_names(self) -> List[str]:
        return [p.name for p in self.profiles]

    def get_profile(self, name: str) -> Optional[Profile]:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def current_profile(self) -> Profile:
        p = self.get_profile(self.active_profile)
        if p is None:
            if not self.profiles:
                self.profiles = default_profiles()
            p = self.profiles[0]
            self.active_profile = p.name
        return p

    def add_profile(self, name: str) -> Profile:
        name = name.strip()
        if not name:
            raise ValueError("프로필 이름이 비어 있습니다.")
        if self.get_profile(name) is not None:
            raise ValueError(f"이미 존재하는 프로필입니다: {name}")
        p = Profile(name)
        self.profiles.append(p)
        return p

    def remove_profile(self, name: str) -> None:
        if len(self.profiles) <= 1:
            raise ValueError("프로필은 최소 하나 이상 있어야 합니다.")
        self.profiles = [p for p in self.profiles if p.name != name]
        if self.active_profile == name:
            self.active_profile = self.profiles[0].name

    def reorder_profiles(self, names: List[str]) -> None:
        """모드 순서를 이 이름 순서대로 바꿉니다 (목록에 없는 모드는 뒤에 그대로)."""
        order = {name: i for i, name in enumerate(names)}
        self.profiles.sort(key=lambda p: order.get(p.name, len(order)))

    def rename_profile(self, old: str, new: str) -> None:
        new = new.strip()
        if not new:
            raise ValueError("프로필 이름이 비어 있습니다.")
        if old != new and self.get_profile(new) is not None:
            raise ValueError(f"이미 존재하는 프로필입니다: {new}")
        p = self.get_profile(old)
        if p is None:
            raise ValueError(f"프로필을 찾을 수 없습니다: {old}")
        p.name = new
        if self.active_profile == old:
            self.active_profile = new

    def remember_app(self, exe_name: str, name: str = "", path: str = "") -> None:
        exe = normalize_exe(exe_name)
        if not exe:
            return
        info = self.app_info.setdefault(exe, {})
        if name.strip():
            info["name"] = name.strip()
        if path.strip():
            info["path"] = path.strip()

    def app_display_name(self, exe_name: str) -> str:
        exe = normalize_exe(exe_name)
        name = self.app_info.get(exe, {}).get("name", "")
        return name or friendly_name(exe)

    def app_path(self, exe_name: str) -> str:
        return self.app_info.get(normalize_exe(exe_name), {}).get("path", "")

    # --------------------------------------------------------- 영속화
    @classmethod
    def path(cls) -> Path:
        return data_dir() / "settings.json"

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        path = path or cls.path()
        if not path.exists():
            return cls()
        try:
            raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "Settings":
        settings = cls()
        profiles_raw = raw.get("profiles")
        if isinstance(profiles_raw, list):
            profiles: List[Profile] = []
            for item in profiles_raw:
                if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                    continue
                apps = item.get("allowed_apps") or []
                profiles.append(
                    Profile(
                        name=str(item["name"]),
                        allowed_apps=[str(a) for a in apps if str(a).strip()],
                        block_everything=bool(item.get("block_everything", True)),
                    )
                )
            if profiles:
                settings.profiles = profiles
        info_raw = raw.get("app_info")
        if isinstance(info_raw, dict):
            for exe, info in info_raw.items():
                if isinstance(info, dict):
                    settings.remember_app(str(exe), str(info.get("name", "")), str(info.get("path", "")))
        for f in fields(cls):
            if f.name in ("profiles", "app_info", "duration_presets", "favorite_apps", "hidden_apps") or f.name not in raw:
                continue
            value = raw[f.name]
            current = getattr(settings, f.name)
            if isinstance(current, bool):
                value = bool(value)
            elif isinstance(current, int):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            elif isinstance(current, str):
                value = str(value)
            setattr(settings, f.name, value)
        settings.poll_interval_ms = max(100, min(5000, settings.poll_interval_ms))
        settings.unlock_code_length = max(8, min(128, settings.unlock_code_length))
        settings.emergency_delay_minutes = max(1, min(240, settings.emergency_delay_minutes))
        settings.default_duration_minutes = max(0, min(1440, settings.default_duration_minutes))
        settings.custom_duration_minutes = max(1, min(1440, settings.custom_duration_minutes))
        settings.duration_presets = clean_presets(raw.get("duration_presets", DEFAULT_DURATION_PRESETS))
        for key in ("favorite_apps", "hidden_apps"):
            values = raw.get(key)
            if isinstance(values, list):
                cleaned = list(dict.fromkeys(normalize_exe(str(v)) for v in values if normalize_exe(str(v))))
                setattr(settings, key, cleaned)
        # 즐겨찾기와 숨김은 동시에 될 수 없음 (즐겨찾기 우선)
        settings.hidden_apps = [h for h in settings.hidden_apps if h not in settings.favorite_apps]
        if settings.get_profile(settings.active_profile) is None:
            settings.active_profile = settings.profiles[0].name
        return settings

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def save(self, path: Optional[Path] = None) -> None:
        path = path or self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

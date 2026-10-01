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


@dataclass
class Settings:
    profiles: List[Profile] = field(default_factory=default_profiles)
    active_profile: str = "공부용"
    poll_interval_ms: int = 300  # 포그라운드 창 확인 주기
    unlock_code_length: int = 32  # 해제용 랜덤 문자열 길이
    default_duration_minutes: int = 50
    require_unlock_for_quit: bool = True
    require_unlock_for_profile_switch: bool = True
    emergency_delay_minutes: int = 10  # 비상 해제가 실제로 적용되기까지의 지연
    show_block_notifications: bool = True

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
        for f in fields(cls):
            if f.name == "profiles" or f.name not in raw:
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
        settings.default_duration_minutes = max(1, min(1440, settings.default_duration_minutes))
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

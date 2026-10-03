"""설정과 프로필을 JSON 파일로 저장/불러오기.

Qt에 의존하지 않으므로 단위 테스트가 가능합니다.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from focus_app.unlock import EDIT_LENGTH as UNLOCK_EDIT_LENGTH
from focus_app.unlock import MAX_LENGTH as UNLOCK_MAX_LENGTH
from focus_app.unlock import MIN_LENGTH as UNLOCK_MIN_LENGTH
from focus_app.unlock import clean_complexity
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


# ---------------------------------------------------------------- 브라우저에 설치한 웹 앱
# Chrome·Edge 등에서 '앱으로 설치'한 사이트(Google Keep 등)는 창이 브라우저 실행 파일(chrome.exe)로 떠서
# 실행 파일 이름으로는 브라우저와 구분되지 않습니다. 그래서 "브라우저 실행 파일|앱 ID"를 앱 이름처럼 쓰고,
# 창의 작업 표시줄 ID(AppUserModelID, 예: "Chrome._crx_<앱 ID>")로 그 앱의 창인지 가립니다.
WEB_APP_BROWSERS: Dict[str, str] = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "brave.exe": "Brave",
    "whale.exe": "웨일",
}
WEB_APP_SEP = "|"
_APP_ID_RE = re.compile(r"^[a-p]{32}$")  # 크롬 확장·웹 앱 ID 모양


def web_app_key(browser_exe: str, app_id: str) -> str:
    return f"{normalize_exe(browser_exe)}{WEB_APP_SEP}{app_id.lower()}"


def split_web_app(key: str) -> Optional[tuple]:
    """웹 앱 키면 (브라우저 실행 파일, 앱 ID), 아니면 None."""
    exe, sep, app_id = (key or "").partition(WEB_APP_SEP)
    if not sep or exe not in WEB_APP_BROWSERS or not _APP_ID_RE.match(app_id):
        return None
    return exe, app_id


def app_id_matches(aumid: str, app_id: str) -> bool:
    """창의 작업 표시줄 ID가 이 웹 앱의 것인지.

    브라우저는 ID가 길면 가운데를 잘라 씁니다 (예: 앱 ID eilembjdkfgodjkcjnpgpaenohkicgjd →
    "Chrome._crx_eilembjdkfjnpgpaenohkicgjd"). 그래서 앞뒤가 맞는지로 비교합니다.
    """
    for part in (aumid or "").lower().split("."):
        if not part.startswith("_crx_"):
            continue
        crx = part[5:]
        if crx == app_id:
            return True
        return 16 <= len(crx) < len(app_id) and app_id.startswith(crx[:6]) and app_id.endswith(crx[-10:])
    return False


def app_kind_label(key: str) -> str:
    """앱 목록에서 이름 옆에 보여 줄 짧은 설명: 실행 파일 이름, 웹 앱이면 'Chrome 앱' 등."""
    parts = split_web_app(key)
    return f"{WEB_APP_BROWSERS[parts[0]]} 앱" if parts else normalize_exe(key)


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
    if split_web_app(exe):
        return app_kind_label(exe)  # 이름을 모르는 웹 앱 (보통은 설정에 저장된 이름을 씀)
    stem = exe[:-4] if exe.endswith(".exe") else exe
    return stem[:1].upper() + stem[1:] if stem else exe


# 사이트 주소의 호스트 부분에 쓸 수 있는 글자 (국제화 도메인은 브라우저처럼 punycode로 바꿔 저장)
_HOST_RE = re.compile(r"^\.?[a-z0-9-]+(\.[a-z0-9-]+)*(:\d{1,5})?$")


def normalize_site(text: str) -> str:
    """사용자가 넣은 사이트 주소를 저장·비교용으로 정리합니다. 쓸 수 없는 주소면 빈 문자열.

    * ``https://www.Notion.so/`` -> ``notion.so`` (스킴, 끝의 /, 맨 앞 www. 제거, 소문자)
    * ``docs.google.com/document`` -> 그대로 (경로까지 지정 가능)
    * ``.notion.so`` -> 그대로 (앞의 점 = 하위 도메인 없이 그 주소만)
    * ``*.notion.so`` -> ``notion.so`` (점 없이 적으면 원래 하위 도메인까지 포함)
    """
    text = (text or "").strip()
    text = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", text)
    if not text or any(c.isspace() for c in text):
        return ""
    text = text.split("#", 1)[0].split("?", 1)[0]
    host, sep, path = text.partition("/")
    host = host.lower().rstrip(".")
    if "@" in host:
        return ""
    exact = host.startswith(".")
    host = host.lstrip(".")
    if host.startswith("*."):
        host = host[2:]
    if host.startswith("www.") and host.count(".") >= 2:
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii") if not host.isascii() else host
    except UnicodeError:
        return ""
    if "." not in host.split(":")[0] and host.split(":")[0] != "localhost":
        return ""
    host = ("." if exact else "") + host
    if not _HOST_RE.match(host):
        return ""
    path = path.rstrip("/")
    return host + ("/" + path if sep and path else "")


def site_url(site: str) -> str:
    """사이트 항목을 브라우저에서 열 주소로 (예: "notion.so" -> "https://notion.so")."""
    return "https://" + site.lstrip(".")


@dataclass
class Profile:
    name: str
    allowed_apps: List[str] = field(default_factory=list)  # 실행 파일 이름 (예: "code.exe")
    block_everything: bool = True  # False면 이 프로필에서는 차단하지 않음 (자유 시간)
    # True면 브라우저(Chrome·Edge 등)에서 allowed_sites만 열 수 있음 (focus_app.browser_policy)
    restrict_sites: bool = False
    allowed_sites: List[str] = field(default_factory=list)  # normalize_site로 정리한 주소 (예: "notion.so")

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

    def allows_window(self, exe_name: str, aumid: str = "") -> bool:
        """이 창을 허용하는지. 브라우저를 허용하지 않았어도 허용한 웹 앱의 창이면 허용합니다."""
        if self.allows(exe_name):
            return True
        exe = normalize_exe(exe_name)
        if exe in WEB_APP_BROWSERS and self.browses_sites():
            return True  # 브라우저는 허용 앱이 아니어도 허용 사이트용으로 씀 (다른 사이트는 정책으로 막힘)
        if not aumid:
            return False
        for key in self.normalized_apps():
            parts = split_web_app(key)
            if parts and parts[0] == exe and app_id_matches(aumid, parts[1]):
                return True
        return False

    def web_apps(self) -> List[tuple]:
        """허용한 웹 앱들의 (브라우저 실행 파일, 앱 ID)."""
        return [parts for parts in map(split_web_app, self.normalized_apps()) if parts]

    def add_app(self, exe_name: str) -> bool:
        n = normalize_exe(exe_name)
        if not n or n in self.normalized_apps():
            return False
        self.allowed_apps.append(n)
        return True

    def remove_app(self, exe_name: str) -> None:
        n = normalize_exe(exe_name)
        self.allowed_apps = [a for a in self.allowed_apps if normalize_exe(a) != n]

    def normalized_sites(self) -> List[str]:
        return list(dict.fromkeys(s for s in (normalize_site(x) for x in self.allowed_sites) if s))

    def limits_sites(self) -> bool:
        """집중 중 브라우저에서 고른 사이트만 열게 하는 모드인지."""
        return self.block_everything and self.restrict_sites

    def browses_sites(self) -> bool:
        """허용 사이트가 있어, 브라우저(Chrome·Edge·웨일·Brave)를 허용 앱에 넣지 않았어도 그 사이트용으로 쓰는지.

        이때 브라우저 창은 허용하고, 허용 사이트 밖으로 가는 것은 브라우저 정책(browser_policy)이 막습니다.
        """
        return self.limits_sites() and bool(self.normalized_sites())

    def add_site(self, text: str) -> str:
        """사이트를 추가하고 정리된 주소를 돌려줍니다. 쓸 수 없는 주소면 ValueError."""
        site = normalize_site(text)
        if not site:
            raise ValueError(f"사이트 주소로 쓸 수 없습니다: {text.strip()}")
        if site not in self.normalized_sites():
            self.allowed_sites.append(site)
        return site

    def remove_site(self, site: str) -> None:
        self.allowed_sites = [s for s in self.allowed_sites if normalize_site(s) != site]


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
    unlock_code_length: int = 32  # 해제용 랜덤 문자열 길이 (32~256)
    edit_code_length: int = 16  # 집중 중 허용 앱 추가·모드 변경용 문자열 길이 (16~256)
    unlock_code_complexity: str = "basic"  # basic / symbols / max (focus_app.unlock.COMPLEXITY)
    default_duration_minutes: int = 50  # 마지막으로 고른 집중 시간. 0이면 "끝낼 때까지"
    duration_presets: List[int] = field(default_factory=lambda: list(DEFAULT_DURATION_PRESETS))
    custom_duration_minutes: int = 45  # "직접 입력" 칸에 마지막으로 넣은 값
    window_geometry: str = ""  # 메인 창 위치·크기 (Qt saveGeometry의 base64)
    # 대화상자별 마지막 위치·크기: 창 종류 이름(클래스 이름) -> saveGeometry의 base64
    window_geometries: Dict[str, str] = field(default_factory=dict)
    ui_zoom: int = 100  # 화면 크기 (%). Ctrl +/−/0, Ctrl+마우스 휠로 바꿈
    check_updates_on_start: bool = True  # 실행할 때 새 버전이 있는지 확인
    github_token: str = ""  # 비공개 저장소에서 업데이트를 받을 때만 필요 (읽기 권한 토큰)
    favorite_apps: List[str] = field(default_factory=list)  # 앱 고르기 창 맨 위에 보일 즐겨찾기 (실행 파일 이름)
    hidden_apps: List[str] = field(default_factory=list)  # 앱 고르기 창 맨 아래 '숨긴 앱'으로 보낸 앱
    require_unlock_for_quit: bool = True
    block_task_manager: bool = False  # 엄격 모드: 집중 중 작업 관리자 끄기 (관리자 권한 도우미가 있어야 동작)
    require_unlock_for_profile_switch: bool = True
    emergency_delay_minutes: int = 10  # 비상 해제가 실제로 적용되기까지의 지연
    show_block_notifications: bool = True
    # 화면 표시용 앱 정보: 실행 파일 이름 -> {"name": 표시 이름, "path": 전체 경로}
    app_info: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # 한 번 추가한 사이트 (모든 모드가 같이 씀). 모드에서는 이 중 쓸 사이트만 체크해 allowed_sites에 둠
    saved_sites: List[str] = field(default_factory=list)

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

    def remember_web_app_site(self, key: str, site: str) -> bool:
        """웹 앱의 시작 주소를 기억합니다 (사이트 목록에는 안 보이고 브라우저 정책에서만 허용). 바뀌었으면 True."""
        site = normalize_site(site)
        if not split_web_app(key) or not site or self.app_info.get(key, {}).get("site") == site:
            return False
        self.app_info.setdefault(key, {})["site"] = site
        return True

    def web_app_sites(self, profile: Optional[Profile]) -> List[str]:
        """이 모드가 허용한 웹 앱들의 주소 (사이트 제한 때 뒤에서 같이 허용)."""
        if profile is None:
            return []
        keys = [k for k in profile.normalized_apps() if split_web_app(k)]
        return list(dict.fromkeys(s for s in (self.app_info.get(k, {}).get("site", "") for k in keys) if s))

    def remember_sites(self, sites: List[str]) -> None:
        """사이트들을 저장한 사이트 목록에 넣습니다 (이미 있으면 그대로)."""
        cleaned = (normalize_site(str(x)) for x in sites)
        self.saved_sites = list(dict.fromkeys([*self.saved_sites, *(x for x in cleaned if x)]))

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
                        restrict_sites=bool(item.get("restrict_sites", False)),
                        allowed_sites=[
                            normalize_site(str(x)) for x in (item.get("allowed_sites") or [])
                            if normalize_site(str(x))
                        ],
                    )
                )
            if profiles:
                settings.profiles = profiles
        info_raw = raw.get("app_info")
        if isinstance(info_raw, dict):
            for exe, info in info_raw.items():
                if isinstance(info, dict):
                    settings.remember_app(str(exe), str(info.get("name", "")), str(info.get("path", "")))
                    settings.remember_web_app_site(str(exe), str(info.get("site", "")))
        for f in fields(cls):
            if f.name in ("profiles", "app_info", "duration_presets", "favorite_apps", "hidden_apps",
                          "window_geometries", "saved_sites") or f.name not in raw:
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
        settings.unlock_code_length = max(UNLOCK_MIN_LENGTH, min(UNLOCK_MAX_LENGTH, settings.unlock_code_length))
        settings.edit_code_length = max(UNLOCK_EDIT_LENGTH, min(UNLOCK_MAX_LENGTH, settings.edit_code_length))
        settings.unlock_code_complexity = clean_complexity(settings.unlock_code_complexity)
        settings.emergency_delay_minutes = max(1, min(240, settings.emergency_delay_minutes))
        settings.default_duration_minutes = max(0, min(1440, settings.default_duration_minutes))
        settings.custom_duration_minutes = max(1, min(1440, settings.custom_duration_minutes))
        settings.ui_zoom = max(80, min(200, settings.ui_zoom))
        geometries = raw.get("window_geometries")
        if isinstance(geometries, dict):
            settings.window_geometries = {str(k): str(v) for k, v in geometries.items() if isinstance(v, str) and v}
        settings.duration_presets = clean_presets(raw.get("duration_presets", DEFAULT_DURATION_PRESETS))
        for key in ("favorite_apps", "hidden_apps"):
            values = raw.get(key)
            if isinstance(values, list):
                cleaned = list(dict.fromkeys(normalize_exe(str(v)) for v in values if normalize_exe(str(v))))
                setattr(settings, key, cleaned)
        saved = raw.get("saved_sites")
        settings.remember_sites([str(x) for x in saved] if isinstance(saved, list) else [])
        # 예전 설정이나 다른 경로로 모드에만 들어간 사이트도 저장한 사이트 목록에 둠
        for profile in settings.profiles:
            settings.remember_sites(profile.normalized_sites())
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

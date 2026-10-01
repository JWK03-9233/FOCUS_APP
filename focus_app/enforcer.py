"""허용 목록 정책: 어떤 창을 허용하고 어떤 창을 최소화할지 결정합니다.

Qt/Windows API에 의존하지 않는 순수 로직이므로 단위 테스트가 가능합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional

from focus_app.config import Profile, normalize_exe

# 항상 예외인 시스템 프로세스. PC를 못 쓰게 되는 상황을 막기 위한 안전장치입니다.
SYSTEM_EXES: FrozenSet[str] = frozenset(
    {
        "explorer.exe",  # 작업 표시줄, 시작 메뉴, 알림 영역, Alt+Tab, 바탕 화면
        "taskmgr.exe",  # 작업 관리자
        "startmenuexperiencehost.exe",
        "shellexperiencehost.exe",
        "searchhost.exe",
        "searchapp.exe",
        "searchui.exe",
        "textinputhost.exe",  # 터치 키보드, 이모지 패널
        "lockapp.exe",
        "logonui.exe",
        "winlogon.exe",
        "csrss.exe",
        "dwm.exe",
        "ctfmon.exe",
        "sihost.exe",
        "systemsettings.exe",  # 설정 앱 (네트워크/디스플레이 복구용)
        "consent.exe",  # UAC 프롬프트
        "openwith.exe",
        "securityhealthsystray.exe",
        "rundll32.exe",
        "shellhost.exe",
        "msiexec.exe",
        "wininit.exe",
    }
)

# 항상 예외인 창 클래스 (프로세스와 무관하게 통과).
# 주의: "#32770"(표준 대화상자)이나 "#32768"(팝업 메뉴)처럼 모든 앱이 쓰는 클래스는
# 넣지 않습니다. 차단 대상 앱의 대화상자가 통과되어 버리기 때문입니다.
SYSTEM_CLASSES: FrozenSet[str] = frozenset(
    {
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "Progman",
        "WorkerW",
        "Windows.UI.Core.CoreWindow",
        "XamlExplorerHostIslandWindow",
        "MultitaskingViewFrame",
        "TaskSwitcherWnd",
        "ForegroundStaging",
        "NotifyIconOverflowWindow",
        "TopLevelWindowForOverflowXamlIsland",
        "tooltips_class32",
        "Windows.UI.Input.InputSite.WindowClass",
    }
)


class Decision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    IGNORE = "ignore"  # 바탕 화면 등, 아무것도 하지 않음


@dataclass(frozen=True)
class ForegroundWindow:
    """감시 루프가 enforcer에 넘기는 최소한의 창 정보."""

    hwnd: int
    pid: int
    exe_name: str
    class_name: str = ""
    title: str = ""


def is_system_window(exe_name: str, class_name: str = "") -> bool:
    exe = normalize_exe(exe_name)
    if exe in SYSTEM_EXES:
        return True
    if class_name in SYSTEM_CLASSES:
        return True
    return False


def decide(window: Optional[ForegroundWindow], profile: Profile, own_pid: int) -> Decision:
    """포그라운드 창에 대한 조치를 결정합니다."""
    if window is None or not window.hwnd:
        return Decision.IGNORE
    if window.pid == own_pid:
        return Decision.ALLOW  # 이 앱 자신 (해제 대화상자 등)
    if not window.exe_name:
        # 프로세스 정보를 얻지 못한 창 (권한 부족 등). 잘못 막는 것보다 통과가 안전.
        return Decision.IGNORE
    if is_system_window(window.exe_name, window.class_name):
        return Decision.ALLOW
    if profile.allows(window.exe_name):
        return Decision.ALLOW
    return Decision.BLOCK


def is_user_app(window: ForegroundWindow, own_pid: int) -> bool:
    """'마지막으로 쓰던 허용 앱'으로 기억할 만한 일반 앱 창인지 여부.

    시스템 창이나 이 앱 자신의 창은 복귀 대상으로 기억하지 않습니다.
    """
    if window.pid == own_pid or not window.exe_name:
        return False
    return not is_system_window(window.exe_name, window.class_name)

"""가짜 OS 백엔드로 감시 루프를 검증합니다."""

from dataclasses import dataclass, field
from typing import Dict, List

from focus_app.config import Profile
from focus_app.enforcer import Decision
from focus_app.monitor import AllowlistMonitor, _Backend
from focus_app.winapi import WindowInfo

OWN = 999


@dataclass
class FakeOS:
    windows: Dict[int, WindowInfo] = field(default_factory=dict)
    foreground_hwnd: int = 0
    minimized: List[int] = field(default_factory=list)
    fronted: List[int] = field(default_factory=list)
    owners: Dict[int, int] = field(default_factory=dict)
    hosted: Dict[int, WindowInfo] = field(default_factory=dict)
    fallbacks: int = 0

    def add(self, hwnd, exe, pid=None, cls="", title=""):
        self.windows[hwnd] = WindowInfo(hwnd, pid or hwnd * 10, exe, f"C:\\{exe}", cls, title)

    def backend(self) -> _Backend:
        return _Backend(
            foreground=lambda: self.foreground_hwnd,
            describe=lambda h: self.windows.get(h),
            hosted_child=lambda h: self.hosted.get(h),
            root_owner=lambda h: self.owners.get(h, h),
            minimize=self._minimize,
            bring_to_front=self._front,
            is_window=lambda h: h in self.windows,
            is_minimized=lambda h: h in self.minimized,
            focus_fallback=self._fallback,
        )

    def _fallback(self):
        self.fallbacks += 1
        return True

    def _minimize(self, h):
        self.minimized.append(h)
        return True

    def _front(self, h):
        self.fronted.append(h)
        self.foreground_hwnd = h
        return True


def make(profile_apps=("code.exe",), **kw):
    os_ = FakeOS()
    blocked = []
    mon = AllowlistMonitor(
        Profile("p", list(profile_apps)), own_pid=OWN, backend=os_.backend(), on_block=blocked.append, **kw
    )
    return os_, mon, blocked


def test_allowed_window_is_remembered():
    os_, mon, blocked = make()
    os_.add(1, "code.exe")
    os_.foreground_hwnd = 1
    assert mon.poll() is Decision.ALLOW
    assert mon.last_allowed_hwnd == 1
    assert not os_.minimized and not blocked


def test_blocked_window_minimized_and_focus_restored():
    os_, mon, blocked = make()
    os_.add(1, "code.exe")
    os_.add(2, "chrome.exe", title="YouTube")
    os_.foreground_hwnd = 1
    mon.poll()
    os_.foreground_hwnd = 2
    assert mon.poll() is Decision.BLOCK
    assert os_.minimized == [2]
    assert os_.fronted == [1]
    assert os_.foreground_hwnd == 1
    assert mon.block_count == 1
    assert [b.exe_name for b in blocked] == ["chrome.exe"]


def test_block_without_previous_app_just_minimizes():
    os_, mon, blocked = make()
    os_.add(2, "chrome.exe")
    os_.foreground_hwnd = 2
    mon.poll()
    assert os_.minimized == [2]
    assert os_.fronted == []


def test_dialog_minimizes_root_owner_too():
    os_, mon, _ = make()
    os_.add(2, "chrome.exe")
    os_.add(3, "chrome.exe", cls="#32770")
    os_.owners[3] = 2
    os_.foreground_hwnd = 3
    mon.poll()
    assert os_.minimized == [2, 3]


def test_system_windows_not_blocked_and_not_remembered():
    os_, mon, _ = make()
    os_.add(1, "code.exe")
    os_.add(5, "explorer.exe", cls="Shell_TrayWnd")
    os_.foreground_hwnd = 1
    mon.poll()
    os_.foreground_hwnd = 5
    assert mon.poll() is Decision.ALLOW
    assert mon.last_allowed_hwnd == 1
    assert not os_.minimized


def test_uwp_host_resolved_to_hosted_app():
    os_, mon, blocked = make(profile_apps=("calculator.exe",))
    os_.add(7, "applicationframehost.exe", title="계산기")
    os_.hosted[7] = WindowInfo(70, 700, "calculator.exe", "", "", "")
    os_.foreground_hwnd = 7
    assert mon.poll() is Decision.ALLOW
    os_.hosted[7] = WindowInfo(71, 701, "whatsapp.exe", "", "", "")
    assert mon.poll() is Decision.BLOCK
    assert blocked[0].exe_name == "whatsapp.exe"


def test_stale_last_window_dropped():
    os_, mon, _ = make()
    os_.add(1, "code.exe")
    os_.add(2, "chrome.exe")
    os_.foreground_hwnd = 1
    mon.poll()
    del os_.windows[1]  # 허용 앱이 닫힘
    os_.foreground_hwnd = 2
    mon.poll()
    assert os_.fronted == []
    assert mon.last_allowed_hwnd == 0


def test_notification_cooldown_per_window():
    os_, mon, blocked = make()
    os_.add(2, "chrome.exe")
    os_.foreground_hwnd = 2
    for _ in range(5):
        mon.poll()
    assert mon.block_count == 1  # 이미 최소화된 창은 다시 세지 않음
    assert len(blocked) == 1
    os_.minimized.clear()  # 사용자가 다시 띄움
    mon.poll()
    assert mon.block_count == 2
    assert len(blocked) == 1  # 쿨다운 중이라 알림은 한 번


def test_profile_switch_applies_immediately():
    os_, mon, _ = make()
    os_.add(2, "chrome.exe")
    os_.foreground_hwnd = 2
    assert mon.poll() is Decision.BLOCK
    mon.set_profile(Profile("free", block_everything=False))
    assert mon.poll() is Decision.ALLOW


def test_backend_errors_do_not_crash():
    def boom():
        raise OSError("fail")

    mon = AllowlistMonitor(Profile("p", ["code.exe"]), own_pid=OWN, backend=_Backend(foreground=boom))
    assert mon.poll() is Decision.IGNORE


def test_block_without_allowed_window_moves_focus_to_taskbar():
    os_, mon, blocked = make()
    os_.add(2, "chrome.exe")
    os_.foreground_hwnd = 2
    assert mon.poll() is Decision.BLOCK
    assert os_.minimized == [2]
    assert os_.fallbacks == 1


def test_already_minimized_foreground_is_not_counted_again():
    os_, mon, blocked = make()
    os_.add(2, "chrome.exe")
    os_.foreground_hwnd = 2
    mon.poll()
    # 포커스 이동이 실패해 최소화된 창이 계속 포그라운드인 상황
    mon.poll()
    mon.poll()
    assert os_.minimized == [2]
    assert mon.block_count == 1
    assert len(blocked) == 1
    assert os_.fallbacks == 3

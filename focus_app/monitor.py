"""허용 목록 감시 루프.

짧은 주기로 포그라운드 창을 확인해 허용되지 않은 앱이면 최소화하고,
마지막으로 쓰던 허용 앱으로 되돌립니다. 이 모듈은 Qt에 의존하지 않으며,
UI 쪽에서 QTimer로 ``poll()``을 주기적으로 호출합니다.

실제 Windows 호출은 ``focus_app.winapi``를 거치며, 테스트에서는 그 자리에
가짜 백엔드를 끼울 수 있도록 함수 참조를 생성자에서 받습니다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from focus_app import winapi
from focus_app.config import Profile
from focus_app.enforcer import Decision, ForegroundWindow, decide, is_user_app

log = logging.getLogger(__name__)

BlockCallback = Callable[[ForegroundWindow], None]


@dataclass
class _Backend:
    """감시 루프가 쓰는 OS 기능 묶음 (테스트에서 교체 가능)."""

    foreground: Callable[[], int] = winapi.get_foreground_window
    describe: Callable[[int], Optional[winapi.WindowInfo]] = winapi.describe_window
    hosted_child: Callable[[int], Optional[winapi.WindowInfo]] = winapi.hosted_child_window
    root_owner: Callable[[int], int] = winapi.root_owner
    minimize: Callable[[int], bool] = winapi.minimize_window
    bring_to_front: Callable[[int], bool] = winapi.bring_to_front
    is_window: Callable[[int], bool] = winapi.is_window
    is_minimized: Callable[[int], bool] = winapi.is_minimized
    focus_fallback: Callable[[], bool] = winapi.focus_taskbar


class AllowlistMonitor:
    """프로필 하나에 대해 포그라운드 창을 감시합니다."""

    # 같은 창을 연속으로 막을 때 알림이 쏟아지지 않도록 하는 최소 간격(초)
    NOTIFY_COOLDOWN = 3.0

    def __init__(
        self,
        profile: Profile,
        own_pid: Optional[int] = None,
        backend: Optional[_Backend] = None,
        on_block: Optional[BlockCallback] = None,
        handles: Optional[Callable[[ForegroundWindow], bool]] = None,
        on_block_failed: Optional[BlockCallback] = None,
        gate: Optional[Callable[[ForegroundWindow], bool]] = None,
    ) -> None:
        self.profile = profile
        self.own_pid = winapi.current_pid() if own_pid is None else own_pid
        self.backend = backend or _Backend()
        self.on_block = on_block
        # 막아야 할 창 중 이 감시가 맡을 창만 고르는 조건 (관리자 권한 도우미와 일을 나눌 때 사용)
        self.handles = handles
        # 최소화를 시도했지만 실제로 안 된 경우 (관리자 권한 창 등) 알림
        self.on_block_failed = on_block_failed
        # 허용 앱이어도 지금은 막아야 하는지 한 번 더 확인 (False면 막음).
        # 사이트 제한을 아직 모르는 브라우저(정책을 쓰기 전부터 실행 중)를 막을 때 사용
        self.gate = gate
        self._last_failed: tuple[int, float] = (0, 0.0)
        self.last_allowed_hwnd: int = 0
        self.last_allowed_pid: int = 0
        self.block_count: int = 0
        self._last_notified: tuple[int, float] = (0, 0.0)

    # ------------------------------------------------------------- 조회
    def _foreground(self) -> Optional[ForegroundWindow]:
        hwnd = self.backend.foreground()
        if not hwnd:
            return None
        info = self.backend.describe(hwnd)
        if info is None:
            return None
        pid, exe = info.pid, info.exe_name
        if exe == "applicationframehost.exe":
            hosted = self.backend.hosted_child(hwnd)
            if hosted is not None and hosted.exe_name:
                pid, exe = hosted.pid, hosted.exe_name
        return ForegroundWindow(
            hwnd=hwnd, pid=pid, exe_name=exe, class_name=info.class_name, title=info.title,
            app_id=getattr(info, "app_id", ""),
        )

    # ------------------------------------------------------------- 동작
    def set_profile(self, profile: Profile) -> None:
        self.profile = profile

    def poll(self) -> Decision:
        """한 번 확인하고 필요한 조치를 수행합니다. 내린 결정을 돌려줍니다."""
        try:
            window = self._foreground()
        except Exception:  # noqa: BLE001 - OS 호출 실패는 다음 주기에 다시 시도
            log.exception("포그라운드 창 조회 실패")
            return Decision.IGNORE

        decision = decide(window, self.profile, self.own_pid)
        if window is None:
            return decision
        if decision is Decision.ALLOW and self.gate is not None and not self._gate_allows(window):
            decision = Decision.BLOCK

        if decision is Decision.ALLOW:
            if is_user_app(window, self.own_pid):
                self.last_allowed_hwnd = window.hwnd
                self.last_allowed_pid = window.pid
            return decision

        if decision is Decision.BLOCK:
            if self.handles is not None and not self.handles(window):
                return Decision.IGNORE  # 다른 쪽(도우미 등)이 맡는 창
            self._block(window)
        return decision

    def _gate_allows(self, window: ForegroundWindow) -> bool:
        try:
            return bool(self.gate(window))
        except Exception:  # noqa: BLE001 - 확인이 고장 나도 허용 앱까지 못 쓰게 되지는 않게
            log.exception("허용 앱 추가 확인 실패")
            return True

    def _block(self, window: ForegroundWindow) -> None:
        target = self.backend.root_owner(window.hwnd) or window.hwnd
        if self.last_allowed_pid == window.pid:
            # 조금 전까지 허용하던 앱을 이제 막는 경우 (사이트 제한 등): 그 창으로 되돌리면 다시 막혀 깜빡임
            self.last_allowed_hwnd = self.last_allowed_pid = 0
        # 이미 최소화된 창이 포그라운드로 남아 있는 경우(복귀할 창이 없을 때 생김)는
        # 새 차단으로 세지 않고 포커스만 다시 옮깁니다.
        if not self.backend.is_minimized(target):
            log.info("차단: %s (%s) hwnd=%s", window.exe_name, window.title, target)
            try:
                self.backend.minimize(target)
                if target != window.hwnd:
                    self.backend.minimize(window.hwnd)
            except Exception:  # noqa: BLE001
                log.exception("창 최소화 실패")
            if not self.backend.is_minimized(target):
                # 관리자 권한으로 실행된 창은 일반 권한으로 최소화할 수 없음 (UIPI) -> 센 것으로 치지 않음
                self._report_failed(window)
            else:
                self.block_count += 1
                self._notify(window)
        if not self._restore_last_allowed():
            try:
                self.backend.focus_fallback()
            except Exception:  # noqa: BLE001
                log.exception("작업 표시줄로 포커스 이동 실패")

    def _restore_last_allowed(self) -> bool:
        hwnd = self.last_allowed_hwnd
        if not hwnd:
            return False
        if not self.backend.is_window(hwnd):
            self.last_allowed_hwnd = 0
            return False
        try:
            return bool(self.backend.bring_to_front(hwnd))
        except Exception:  # noqa: BLE001
            log.exception("허용 앱 복귀 실패")
            return False

    def _report_failed(self, window: ForegroundWindow) -> None:
        now = time.monotonic()
        last_hwnd, last_time = self._last_failed
        if last_hwnd == window.hwnd and now - last_time < 30.0:
            return
        self._last_failed = (window.hwnd, now)
        log.warning("최소화 실패 (관리자 권한 창일 수 있음): %s", window.exe_name)
        if self.on_block_failed is not None:
            try:
                self.on_block_failed(window)
            except Exception:  # noqa: BLE001
                log.exception("최소화 실패 알림 콜백 실패")

    def _notify(self, window: ForegroundWindow) -> None:
        if self.on_block is None:
            return
        now = time.monotonic()
        last_hwnd, last_time = self._last_notified
        if last_hwnd == window.hwnd and now - last_time < self.NOTIFY_COOLDOWN:
            return
        self._last_notified = (window.hwnd, now)
        try:
            self.on_block(window)
        except Exception:  # noqa: BLE001
            log.exception("차단 알림 콜백 실패")

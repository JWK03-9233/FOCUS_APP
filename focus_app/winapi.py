"""Windows API 얇은 래퍼 (ctypes).

Windows가 아닌 환경에서도 import 가능하도록 모든 호출을 보호합니다.
Windows가 아닌 경우 조회 함수는 None/빈 값을, 조작 함수는 False를 돌려줍니다.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional

IS_WINDOWS = sys.platform.startswith("win")

SW_MINIMIZE = 6
SW_RESTORE = 9
GA_ROOTOWNER = 3
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4
WS_EX_TOOLWINDOW = 0x00000080


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    exe_name: str  # 소문자 실행 파일 이름, 예: "chrome.exe"
    exe_path: str
    class_name: str
    title: str


if IS_WINDOWS:  # pragma: no cover - Windows 전용
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_void_p]

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.GetCurrentProcessId.restype = wintypes.DWORD


def current_pid() -> int:
    if IS_WINDOWS:  # pragma: no cover
        return int(kernel32.GetCurrentProcessId())
    import os

    return os.getpid()


def get_foreground_window() -> int:
    if not IS_WINDOWS:
        return 0
    return int(user32.GetForegroundWindow() or 0)  # pragma: no cover


def window_pid(hwnd: int) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    pid = wintypes.DWORD(0)  # pragma: no cover
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))  # pragma: no cover
    return int(pid.value)  # pragma: no cover


def window_thread_id(hwnd: int) -> int:
    if not IS_WINDOWS or not hwnd:
        return 0
    pid = wintypes.DWORD(0)  # pragma: no cover
    return int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)))  # pragma: no cover


def process_image_path(pid: int) -> str:
    if not IS_WINDOWS or not pid:
        return ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)  # pragma: no cover
    if not handle:  # pragma: no cover
        return ""
    try:  # pragma: no cover
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:  # pragma: no cover
        kernel32.CloseHandle(handle)


def window_class(hwnd: int) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)  # pragma: no cover
    user32.GetClassNameW(hwnd, buf, 256)  # pragma: no cover
    return buf.value  # pragma: no cover


def window_title(hwnd: int) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)  # pragma: no cover
    if length <= 0:  # pragma: no cover
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)  # pragma: no cover
    user32.GetWindowTextW(hwnd, buf, length + 1)  # pragma: no cover
    return buf.value  # pragma: no cover


def is_window(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    return bool(user32.IsWindow(hwnd))  # pragma: no cover


def is_window_visible(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    return bool(user32.IsWindowVisible(hwnd))  # pragma: no cover


def is_minimized(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    return bool(user32.IsIconic(hwnd))  # pragma: no cover


def root_owner(hwnd: int) -> int:
    if not IS_WINDOWS or not hwnd:
        return hwnd
    return int(user32.GetAncestor(hwnd, GA_ROOTOWNER) or hwnd)  # pragma: no cover


def describe_window(hwnd: int) -> Optional[WindowInfo]:
    """창 핸들로부터 프로세스/클래스/제목 정보를 모읍니다."""
    if not hwnd:
        return None
    pid = window_pid(hwnd)
    path = process_image_path(pid)
    exe = path.replace("/", "\\").rsplit("\\", 1)[-1].lower() if path else ""
    return WindowInfo(
        hwnd=hwnd,
        pid=pid,
        exe_name=exe,
        exe_path=path,
        class_name=window_class(hwnd),
        title=window_title(hwnd),
    )


def hosted_child_window(hwnd: int) -> Optional[WindowInfo]:
    """ApplicationFrameHost 같은 호스트 창 안에 있는 실제 앱의 자식 창을 찾습니다.

    UWP 앱은 포그라운드 창의 소유 프로세스가 ApplicationFrameHost.exe로 보이므로,
    pid가 다른 자식 창을 찾아 실제 앱을 식별합니다.
    """
    if not IS_WINDOWS or not hwnd:
        return None
    host_pid = window_pid(hwnd)  # pragma: no cover
    found: List[int] = []  # pragma: no cover

    def _cb(child, _lparam):  # pragma: no cover
        if window_pid(child) != host_pid:
            found.append(int(child))
            return False
        return True

    user32.EnumChildWindows(hwnd, WNDENUMPROC(_cb), 0)  # pragma: no cover
    return describe_window(found[0]) if found else None  # pragma: no cover


def minimize_window(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    return bool(user32.ShowWindow(hwnd, SW_MINIMIZE))  # pragma: no cover


def bring_to_front(hwnd: int) -> bool:
    """창을 복원하고 앞으로 가져옵니다. 포그라운드 잠금을 우회하기 위해
    AttachThreadInput과 ALT 키 트릭을 순서대로 시도합니다."""
    if not IS_WINDOWS or not hwnd or not is_window(hwnd):
        return False
    if is_minimized(hwnd):  # pragma: no cover
        user32.ShowWindow(hwnd, SW_RESTORE)
    if user32.SetForegroundWindow(hwnd):  # pragma: no cover
        return True
    # 1) 입력 스레드 연결 트릭
    fg = user32.GetForegroundWindow()  # pragma: no cover
    fg_tid = window_thread_id(fg) if fg else 0  # pragma: no cover
    my_tid = kernel32.GetCurrentThreadId()  # pragma: no cover
    attached = False  # pragma: no cover
    if fg_tid and fg_tid != my_tid:  # pragma: no cover
        attached = bool(user32.AttachThreadInput(my_tid, fg_tid, True))
    try:  # pragma: no cover
        user32.BringWindowToTop(hwnd)
        if user32.SetForegroundWindow(hwnd):
            return True
    finally:  # pragma: no cover
        if attached:
            user32.AttachThreadInput(my_tid, fg_tid, False)
    # 2) ALT 키를 눌렀다 떼어 포그라운드 변경 권한을 얻는 트릭
    VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002  # pragma: no cover
    user32.keybd_event(VK_MENU, 0, 0, None)  # pragma: no cover
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, None)  # pragma: no cover
    return bool(user32.SetForegroundWindow(hwnd))  # pragma: no cover


def list_visible_windows() -> List[WindowInfo]:
    """제목이 있는, 보이는 최상위 창 목록 (설정 화면의 "실행 중인 앱" 선택용)."""
    if not IS_WINDOWS:
        return []
    result: List[WindowInfo] = []  # pragma: no cover

    def _cb(hwnd, _lparam):  # pragma: no cover
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, -20) & WS_EX_TOOLWINDOW:  # GWL_EXSTYLE
            return True
        info = describe_window(int(hwnd))
        if info and info.title and info.exe_name:
            if info.exe_name == "applicationframehost.exe":
                hosted = hosted_child_window(int(hwnd))
                if hosted:
                    info = WindowInfo(
                        hwnd=info.hwnd,
                        pid=hosted.pid,
                        exe_name=hosted.exe_name,
                        exe_path=hosted.exe_path,
                        class_name=info.class_name,
                        title=info.title,
                    )
            result.append(info)
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)  # pragma: no cover
    return result  # pragma: no cover

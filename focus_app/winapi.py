"""Windows API 얇은 래퍼 (ctypes).

Windows가 아닌 환경에서도 import 가능하도록 모든 호출을 보호합니다.
Windows가 아닌 경우 조회 함수는 None/빈 값을, 조작 함수는 False를 돌려줍니다.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, List, Optional

from focus_app.config import WEB_APP_BROWSERS

IS_WINDOWS = sys.platform.startswith("win")

SW_MINIMIZE = 6
SW_RESTORE = 9
GA_ROOTOWNER = 3
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
GW_OWNER = 4
WS_EX_TOOLWINDOW = 0x00000080
TOKEN_QUERY = 0x0008
TOKEN_INTEGRITY_LEVEL = 25  # TOKEN_INFORMATION_CLASS.TokenIntegrityLevel
SECURITY_MANDATORY_HIGH_RID = 0x3000
STILL_ACTIVE = 259
ERROR_ALREADY_EXISTS = 183
DWMWA_CLOAKED = 14


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    exe_name: str  # 소문자 실행 파일 이름, 예: "chrome.exe"
    exe_path: str
    class_name: str
    title: str
    app_id: str = ""  # 작업 표시줄 ID (브라우저 창만 읽음. 웹 앱 창이면 "Chrome._crx_<앱 ID>" 등)


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
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
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
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    advapi32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    advapi32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    advapi32.GetSidSubAuthority.restype = ctypes.POINTER(wintypes.DWORD)


def current_pid() -> int:
    if IS_WINDOWS:  # pragma: no cover
        return int(kernel32.GetCurrentProcessId())
    import os

    return os.getpid()


def process_elevated(pid: int) -> Optional[bool]:
    """프로세스가 관리자 권한(높은 무결성 수준 이상)으로 실행 중인지.

    일반 권한 프로세스는 관리자 권한 프로세스의 토큰을 읽을 수 없으므로, 프로세스는 열리는데
    토큰이 안 열리면 관리자 권한(또는 시스템)으로 봅니다. 프로세스조차 못 열면 None.
    """
    if not IS_WINDOWS or not pid:
        return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)  # pragma: no cover
    if not handle:  # pragma: no cover
        return None
    try:  # pragma: no cover
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return True
        try:
            size = wintypes.DWORD(0)
            advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value or 64)
            if not advapi32.GetTokenInformation(token, TOKEN_INTEGRITY_LEVEL, buf, len(buf), ctypes.byref(size)):
                return None
            psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_MANDATORY_LABEL.Label.Sid
            count = advapi32.GetSidSubAuthorityCount(psid)[0]
            rid = advapi32.GetSidSubAuthority(psid, count - 1)[0]
            return rid >= SECURITY_MANDATORY_HIGH_RID
        finally:
            kernel32.CloseHandle(token)
    finally:  # pragma: no cover
        kernel32.CloseHandle(handle)


def current_process_elevated() -> bool:
    return bool(process_elevated(current_pid()))


def process_alive(pid: int) -> bool:
    if not pid:
        return False
    if not IS_WINDOWS:
        import os

        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)  # pragma: no cover
    if not handle:  # pragma: no cover
        return False
    try:  # pragma: no cover
        code = wintypes.DWORD(0)
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:  # pragma: no cover
        kernel32.CloseHandle(handle)


def acquire_single_instance(name: str):
    """이름 있는 뮤텍스로 한 번만 실행되게 합니다. 이미 있으면 None, 아니면 (닫지 말고 들고 있을) 핸들."""
    if not IS_WINDOWS:
        return object()
    handle = kernel32.CreateMutexW(None, False, name)  # pragma: no cover
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:  # pragma: no cover
        if handle:
            kernel32.CloseHandle(handle)
        return None
    return handle  # pragma: no cover


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
        app_id=app_user_model_id(hwnd) if exe in WEB_APP_BROWSERS else "",
    )


if IS_WINDOWS:  # pragma: no cover - Windows 전용

    class _GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                    ("d4", ctypes.c_ubyte * 8)]

    class _PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]

    class _PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]

    def _guid(text: str) -> "_GUID":
        import uuid

        u = uuid.UUID(text)
        g = _GUID(u.fields[0], u.fields[1], u.fields[2])
        g.d4[:] = u.bytes[8:]
        return g

    _IID_IPropertyStore = _guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99")
    _PKEY_AppUserModel_ID = _PROPERTYKEY(_guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5)
    _VT_LPWSTR = 31
    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    _GetValue = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
                                   ctypes.POINTER(_PROPVARIANT))
    _Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)


def app_user_model_id(hwnd: int) -> str:
    """창의 작업 표시줄 ID (AppUserModelID). 따로 정하지 않은 창이면 빈 문자열.

    브라우저에 설치한 웹 앱 창은 브라우저가 "Chrome._crx_<앱 ID>"처럼 앱마다 다른 ID를 붙입니다.
    """
    if not IS_WINDOWS or not hwnd:
        return ""
    store = ctypes.c_void_p()  # pragma: no cover
    if shell32.SHGetPropertyStoreForWindow(hwnd, ctypes.byref(_IID_IPropertyStore), ctypes.byref(store)) < 0:
        return ""  # pragma: no cover  (HRESULT: 음수면 실패)
    if not store:  # pragma: no cover
        return ""
    # IPropertyStore vtable: QueryInterface, AddRef, Release, GetCount, GetAt, GetValue, ...
    vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    value = _PROPVARIANT()  # pragma: no cover
    try:  # pragma: no cover
        if _GetValue(vtbl[5])(store, ctypes.byref(_PKEY_AppUserModel_ID), ctypes.byref(value)) < 0:  # S_FALSE(1)도 성공
            return ""
        return ctypes.wstring_at(value.p) if value.vt == _VT_LPWSTR and value.p else ""
    except OSError:  # pragma: no cover
        return ""
    finally:  # pragma: no cover
        ole32.PropVariantClear(ctypes.byref(value))
        _Release(vtbl[2])(store)


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


def focus_taskbar() -> bool:
    """작업 표시줄로 포커스를 옮깁니다.

    복귀할 허용 앱이 없을 때, 최소화된 차단 앱이 계속 포그라운드(키보드 입력 대상)로
    남지 않게 하기 위해 사용합니다.
    """
    if not IS_WINDOWS:
        return False
    hwnd = int(user32.FindWindowW("Shell_TrayWnd", None) or 0)  # pragma: no cover
    return bring_to_front(hwnd) if hwnd else False  # pragma: no cover


TH32CS_SNAPPROCESS = 0x00000002


class _ProcessEntry(ctypes.Structure):  # PROCESSENTRY32W
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def _process_entries() -> List[tuple]:
    """지금 실행 중인 프로세스의 (pid, 소문자 실행 파일 이름) 목록. 관리자 권한 프로세스도 포함됩니다."""
    if not IS_WINDOWS:
        return []
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)  # pragma: no cover
    if not snap or snap == wintypes.HANDLE(-1).value:  # pragma: no cover
        return []
    out = []  # pragma: no cover
    try:  # pragma: no cover
        entry = _ProcessEntry()
        entry.dwSize = ctypes.sizeof(_ProcessEntry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append((int(entry.th32ProcessID), entry.szExeFile.lower()))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:  # pragma: no cover
        kernel32.CloseHandle(snap)
    return out


def running_exe_names() -> set:
    """지금 실행 중인 프로세스의 실행 파일 이름들 (소문자). 관리자 권한 프로세스도 포함됩니다."""
    return {name for _pid, name in _process_entries()}


def process_ids(exe_name: str) -> List[int]:
    """이 실행 파일(소문자 이름)로 실행 중인 프로세스들의 pid."""
    exe = exe_name.lower()
    return [pid for pid, name in _process_entries() if name == exe]


# FILETIME(1601-01-01부터 100ns 단위)과 유닉스 시각(1970-01-01부터 초)의 차이
_FILETIME_EPOCH_DIFF = 11644473600


def process_start_time(pid: int) -> Optional[float]:
    """프로세스가 시작된 시각 (time.time()과 같은 기준의 초). 알 수 없으면 None."""
    if not IS_WINDOWS or not pid:
        return None
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)  # pragma: no cover
    if not handle:  # pragma: no cover
        return None
    try:  # pragma: no cover
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return ticks / 10_000_000 - _FILETIME_EPOCH_DIFF
    finally:  # pragma: no cover
        kernel32.CloseHandle(handle)


def terminate_process(pid: int) -> bool:
    """프로세스를 강제로 끝냅니다 (관리자 권한 프로세스는 일반 권한으로 끝낼 수 없음)."""
    if not IS_WINDOWS or not pid:
        return False
    handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)  # pragma: no cover
    if not handle:  # pragma: no cover
        return False
    try:  # pragma: no cover
        return bool(kernel32.TerminateProcess(handle, 1))
    finally:  # pragma: no cover
        kernel32.CloseHandle(handle)


def _is_cloaked(hwnd: int) -> bool:  # pragma: no cover - Windows 전용
    """보이는 것으로 표시되지만 실제로는 화면에 없는 창 (닫힌 뒤 남은 Store 앱 창 등)."""
    try:
        cloaked = wintypes.DWORD(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        return bool(cloaked.value)
    except (AttributeError, OSError):
        return False


def find_app_window(exe_name: str, app_id_match: Optional[Callable[[str], bool]] = None) -> int:
    """이 실행 파일의 앱 창 중 가장 최근에 쓴 것 (최소화된 창 포함, 트레이로 숨긴 창은 제외). 없으면 0.

    ``app_id_match``를 주면 작업 표시줄 ID가 그 조건에 맞는 창만 (브라우저에 설치한 웹 앱 구분용).
    """
    if not IS_WINDOWS or not exe_name:
        return 0
    exe_name = exe_name.lower()  # pragma: no cover
    found: List[int] = []  # pragma: no cover

    def _cb(hwnd, _lparam):  # pragma: no cover
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, -20) & WS_EX_TOOLWINDOW:  # GWL_EXSTYLE
            return True
        if not window_title(int(hwnd)) or _is_cloaked(int(hwnd)):
            return True
        info = describe_window(int(hwnd))
        exe = info.exe_name if info else ""
        if exe == "applicationframehost.exe":  # Store 앱은 호스트 창 안의 실제 앱으로 판단
            hosted = hosted_child_window(int(hwnd))
            exe = hosted.exe_name if hosted else ""
        if exe == exe_name and (app_id_match is None or app_id_match(info.app_id)):
            found.append(int(hwnd))
            return False  # EnumWindows는 앞에 있는 창부터 돌려주므로 처음 것이 가장 최근 창
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)  # pragma: no cover
    return found[0] if found else 0  # pragma: no cover


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

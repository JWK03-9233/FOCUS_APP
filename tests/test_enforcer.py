from focus_app.config import Profile
from focus_app.enforcer import Decision, ForegroundWindow, decide, is_system_window, is_user_app

OWN = 4242
STUDY = Profile("study", allowed_apps=["code.exe", "notepad.exe"])


def fw(exe, pid=100, cls="", hwnd=1):
    return ForegroundWindow(hwnd=hwnd, pid=pid, exe_name=exe, class_name=cls)


def test_allowed_app_passes():
    assert decide(fw("Code.exe"), STUDY, OWN) is Decision.ALLOW


def test_unlisted_app_blocked():
    assert decide(fw("chrome.exe"), STUDY, OWN) is Decision.BLOCK


def test_system_elements_always_allowed():
    assert decide(fw("explorer.exe"), STUDY, OWN) is Decision.ALLOW
    assert decide(fw("Taskmgr.exe"), STUDY, OWN) is Decision.ALLOW
    assert decide(fw("StartMenuExperienceHost.exe"), STUDY, OWN) is Decision.ALLOW
    assert decide(fw("weird.exe", cls="Shell_TrayWnd"), STUDY, OWN) is Decision.ALLOW
    assert is_system_window("EXPLORER.EXE")
    assert not is_system_window("chrome.exe")


def test_own_process_allowed():
    assert decide(fw("python.exe", pid=OWN), STUDY, OWN) is Decision.ALLOW


def test_unknown_or_missing_window_ignored():
    assert decide(None, STUDY, OWN) is Decision.IGNORE
    assert decide(fw("", pid=7), STUDY, OWN) is Decision.IGNORE
    assert decide(ForegroundWindow(hwnd=0, pid=1, exe_name="x.exe"), STUDY, OWN) is Decision.IGNORE


def test_free_profile_never_blocks():
    free = Profile("free", block_everything=False)
    assert decide(fw("chrome.exe"), free, OWN) is Decision.ALLOW


def test_is_user_app_excludes_system_and_self():
    assert is_user_app(fw("code.exe"), OWN)
    assert not is_user_app(fw("explorer.exe"), OWN)
    assert not is_user_app(fw("code.exe", pid=OWN), OWN)
    assert not is_user_app(fw(""), OWN)

"""사이트 제한: 주소 정리, 설정 저장, 감시 루프의 브라우저 막기, 도우미 연동, 화면."""

import os
import threading
import time

import pytest

from focus_app import browser_policy, helper
from focus_app.config import Profile, Settings, normalize_site, site_url
from focus_app.enforcer import Decision
from focus_app.session import FocusSession
from tests.test_main_window import _close
from tests.test_monitor import make


# ---------------------------------------------------------------- 주소 정리
@pytest.mark.parametrize(
    "text, expected",
    [
        ("https://www.Notion.so/", "notion.so"),
        ("notion.so", "notion.so"),
        (".notion.so", ".notion.so"),
        ("*.notion.so", "notion.so"),
        ("docs.google.com/document/", "docs.google.com/document"),
        ("https://ko.wikipedia.org/wiki/A?x=1#y", "ko.wikipedia.org/wiki/A"),
        ("http://localhost:8080/x", "localhost:8080/x"),
        ("한국.kr", "xn--3e0b707e.kr"),
        ("youtube", ""),
        ("a b.com", ""),
        ("user@evil.com", ""),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalize_site(text, expected):
    assert normalize_site(text) == expected


def test_site_url_opens_https():
    assert site_url("notion.so") == "https://notion.so"
    assert site_url(".notion.so") == "https://notion.so"
    assert site_url("docs.google.com/document") == "https://docs.google.com/document"


def test_profile_sites_add_remove_and_dedupe():
    p = Profile("p")
    assert p.add_site("https://www.notion.so") == "notion.so"
    p.add_site("notion.so")
    assert p.normalized_sites() == ["notion.so"]
    with pytest.raises(ValueError):
        p.add_site("not a site")
    p.remove_site("notion.so")
    assert p.normalized_sites() == []


def test_limits_sites_needs_blocking_mode():
    p = Profile("p", restrict_sites=True)
    assert p.limits_sites()
    p.block_everything = False
    assert not p.limits_sites()


def test_sites_roundtrip_and_old_settings(tmp_path):
    s = Settings()
    p = s.current_profile()
    p.restrict_sites = True
    p.allowed_sites = ["notion.so", ".example.com"]
    s.save(tmp_path / "s.json")
    loaded = Settings.load(tmp_path / "s.json").current_profile()
    assert loaded.restrict_sites and loaded.normalized_sites() == ["notion.so", ".example.com"]
    # 예전 설정 파일(사이트 항목 없음)은 사이트 제한 없이 읽힘, 잘못된 주소는 버림
    old = Settings.from_dict({"profiles": [{"name": "a", "allowed_apps": ["chrome.exe"],
                                            "allowed_sites": ["bad site", "https://www.x.com/"]}]})
    assert not old.profiles[0].restrict_sites
    assert old.profiles[0].allowed_sites == ["x.com"]


# ---------------------------------------------------------------- 감시 루프
def test_gate_blocks_allowed_app_and_does_not_bounce_back():
    gate_open = {"value": True}
    os_, mon, blocked = make(("code.exe", "chrome.exe"), gate=lambda w: gate_open["value"] or w.exe_name != "chrome.exe")
    os_.add(1, "chrome.exe", pid=10)
    os_.add(2, "code.exe", pid=20)
    os_.foreground_hwnd = 2
    assert mon.poll() is Decision.ALLOW
    os_.foreground_hwnd = 1
    assert mon.poll() is Decision.ALLOW  # 마지막으로 쓰던 앱 = chrome
    gate_open["value"] = False  # 이제 사이트 제한을 모르는 브라우저라 막아야 함
    assert mon.poll() is Decision.BLOCK
    assert 1 in os_.minimized and blocked
    assert 1 not in os_.fronted  # 막은 브라우저 창으로 되돌아가 깜빡이지 않음


def test_gate_error_does_not_block():
    def broken(_w):
        raise RuntimeError("고장")

    os_, mon, _ = make(("chrome.exe",), gate=broken)
    os_.add(1, "chrome.exe")
    os_.foreground_hwnd = 1
    assert mon.poll() is Decision.ALLOW


# ---------------------------------------------------------------- 도우미
def _site_settings(base):
    s = Settings()
    p = s.current_profile()
    p.allowed_apps = ["chrome.exe"]
    p.restrict_sites = True
    p.allowed_sites = ["notion.so"]
    s.save(base / "settings.json")
    return p.name


def test_helper_engages_site_policy_during_session_and_releases_after(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "IDLE_EXIT_SECONDS", 0.3)
    monkeypatch.setattr(helper, "MUTEX_NAME", f"Local\\FocusAppHelperSites{os.getpid()}")
    import focus_app.monitor as monitor_mod

    monkeypatch.setattr(monitor_mod.AllowlistMonitor, "poll", lambda self: None)
    calls = []
    monkeypatch.setattr(browser_policy, "engage", lambda base, sites: calls.append(("engage", list(sites))) or True)
    monkeypatch.setattr(browser_policy, "release", lambda base: calls.append(("release",)) or True)
    name = _site_settings(tmp_path)
    FocusSession.start(name, None).save(tmp_path / "session.json")
    t = threading.Thread(target=helper.run_helper, args=(tmp_path,))
    t.start()
    time.sleep(1.5)
    assert ("engage", ["notion.so"]) in calls
    FocusSession.clear(tmp_path / "session.json")
    t.join(timeout=5)
    assert not t.is_alive()
    assert calls[-1] == ("release",)  # 집중이 끝나면 되돌림


def test_helper_releases_site_policy_when_no_session(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "IDLE_EXIT_SECONDS", 0.3)
    monkeypatch.setattr(helper, "MUTEX_NAME", f"Local\\FocusAppHelperSites2{os.getpid()}")
    released = []
    monkeypatch.setattr(browser_policy, "release", lambda base: released.append(base) or True)
    helper.run_helper(tmp_path)
    assert released  # 지난번에 비정상 종료돼 남은 사이트 제한을 되돌림


# ---------------------------------------------------------------- 화면
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_site_editor_add_remove_and_warnings(qapp, monkeypatch):
    from focus_app.ui import site_list

    warned = []
    monkeypatch.setattr(site_list.QMessageBox, "warning", lambda *a: warned.append(a))
    ed = site_list.SiteEditor()
    changes = []
    ed.changed.connect(lambda: changes.append(1))
    ed.set_values(False, [])
    assert not ed.add_btn.isEnabled()
    ed.check.setChecked(True)
    assert ed.restrict and ed.add_btn.isEnabled()
    bad = ed.add_sites("https://www.notion.so, docs.google.com/document  잘못된주소")
    assert ed.sites == ["notion.so", "docs.google.com/document"]
    assert bad == ["잘못된주소"] and warned
    ed.remove_site("notion.so")
    assert ed.sites == ["docs.google.com/document"] and changes

    ed.set_context(["code.exe"], True)
    assert ed.warning.isHidden()  # 브라우저를 허용 앱에 넣지 않아도 허용 사이트는 열 수 있음
    assert "넣지 않아도" in ed.empty.text()
    ed.set_context(["chrome.exe", "firefox.exe"], False)
    assert "Firefox" in ed.warning.text() and "도우미" in ed.warning.text()
    ed.set_context(["chrome.exe"], True)
    assert ed.warning.isHidden()


def test_main_window_edits_sites_and_shows_them_while_running(qapp):
    from PySide6.QtCore import Qt

    from focus_app.ui.main_window import SITE_ROLE, MainWindow

    s = Settings()
    w = MainWindow(s)
    try:
        p = w.current_mode()
        p.allowed_apps = ["chrome.exe"]
        w._show_mode()
        w.site_editor.check.setChecked(True)
        w.site_editor.add_sites("notion.so")
        assert p.restrict_sites and p.normalized_sites() == ["notion.so"]
        assert "사이트 1개" in w.start_summary.text()

        w.show_running(FocusSession.start(p.name, 30), p)
        assert not w.run_sites.isHidden()
        item = w.run_sites.item(0)
        assert item.text() == "notion.so" and item.data(SITE_ROLE) == "notion.so"
        asked = []
        w.open_site_requested.connect(asked.append)
        w.run_sites.itemClicked.emit(item)
        assert asked == ["notion.so"]
        assert w.edit_apps_btn.text().startswith("허용 앱·사이트")

        w.set_site_status("Chrome은 다시 시작해야", True)
        assert not w.site_banner.isHidden() and not w.restart_browsers_btn.isHidden()
        w.set_site_status("", False)
        assert w.site_banner.isHidden()

        p.restrict_sites = False
        w.show_running(FocusSession.start(p.name, 30), p)
        assert w.run_sites.isHidden()
        assert Qt  # noqa
    finally:
        w.allow_close = True
        w.close()


def test_notice_action_button(qapp):
    from focus_app.ui.main_window import MainWindow

    w = MainWindow(Settings())
    try:
        clicked = []
        w.show_notice("끝", "브라우저 다시 시작", lambda: clicked.append(1))
        assert not w.notice_btn.isHidden()
        w.notice_btn.click()
        assert clicked and w.notice.isHidden()
        w.show_notice("그냥 알림")
        assert w.notice_btn.isHidden()
    finally:
        w.allow_close = True
        w.close()


def test_allowed_apps_dialog_saves_sites(qapp):
    from focus_app.ui.allowed_apps_dialog import AllowedAppsDialog

    s = Settings()
    p = s.current_profile()
    dlg = AllowedAppsDialog(s, p)
    dlg.sites.check.setChecked(True)
    dlg.sites.add_sites("notion.so")
    assert not p.restrict_sites  # 저장 전까지 원본은 그대로
    dlg.apply_to(s)
    assert p.restrict_sites and p.normalized_sites() == ["notion.so"]
    dlg.deleteLater()


def test_controller_gate_and_open_site(qapp, monkeypatch, tmp_path):
    from focus_app import app as app_mod
    from focus_app.enforcer import ForegroundWindow

    ctl = app_mod.FocusApp(qapp, show_window=False)
    try:
        p = ctl.settings.current_profile()
        p.allowed_apps = ["chrome.exe", "code.exe"]
        p.restrict_sites = True
        p.allowed_sites = ["notion.so"]
        ctl.start_focus(p.name, 30)
        chrome = ForegroundWindow(hwnd=1, pid=4242, exe_name="chrome.exe")
        code = ForegroundWindow(hwnd=2, pid=4343, exe_name="code.exe")
        assert ctl._browser_gate(code)
        assert not ctl._browser_gate(chrome)  # 아직 정책이 적용되지 않음 -> 막음

        ctl._policy_state = (["notion.so"], 1000.0)
        monkeypatch.setattr(app_mod.winapi, "process_start_time", lambda pid: 900.0)
        monkeypatch.setattr(browser_policy.time, "time", lambda: 1010.0)
        assert not ctl._browser_gate(chrome)  # 정책 전부터 실행 중 -> 다시 시작 전까지 막음
        monkeypatch.setattr(app_mod.winapi, "process_start_time", lambda pid: 1005.0)
        assert ctl._browser_gate(chrome)

        opened = []
        monkeypatch.setattr(ctl, "_pick_browser", lambda: ("chrome.exe", "C:\\chrome.exe"))
        monkeypatch.setattr(browser_policy, "stale_browsers", lambda exes, applied_at, now=None: [])
        monkeypatch.setattr(browser_policy, "open_url", lambda path, url, restore_session=False: opened.append(url) or True)
        ctl.open_site("notion.so")
        ctl.open_site("youtube.com")  # 허용하지 않은 사이트는 열지 않음
        assert opened == ["https://notion.so"]
    finally:
        ctl._end_session("manual")
        _close(ctl)


def test_end_notice_offers_restart_even_for_background_browser(qapp, monkeypatch):
    from focus_app import app as app_mod

    ctl = app_mod.FocusApp(qapp, show_window=False)
    try:
        p = ctl.settings.current_profile()
        p.allowed_apps = ["chrome.exe"]
        p.restrict_sites = True
        p.allowed_sites = ["notion.so"]
        ctl.start_focus(p.name, 30)
        # 창은 못 찾았지만 Chrome 프로세스는 돌고 있음 -> 그래도 알림 띠에 다시 시작 버튼
        monkeypatch.setattr(browser_policy, "has_window", lambda exe: False)
        monkeypatch.setattr(browser_policy, "running_pids", lambda exe: [77] if exe == "chrome.exe" else [])
        ctl._end_session("manual")
        assert not ctl.window.notice.isHidden()
        assert not ctl.window.notice_btn.isHidden()
        assert "Chrome" in ctl.window.notice_label.text()

        closed = []
        monkeypatch.setattr(browser_policy, "engaged", lambda d: False)
        monkeypatch.setattr(browser_policy, "close_browser", lambda exe, timeout=8.0: closed.append(exe) or True)
        monkeypatch.setattr(app_mod, "run_in_thread", lambda fn, name: fn())
        ctl.window.notice_btn.click()  # 창이 없으니 묻지 않고 뒤에서 돌던 프로세스만 끝냄
        assert closed == ["chrome.exe"]
    finally:
        _close(ctl)

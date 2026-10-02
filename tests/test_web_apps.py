"""브라우저에 설치한 웹 앱 (Google Keep 등): 키, 창 구분, 바로가기·저장소 읽기, 사이트 자동 추가."""

import pytest

from focus_app import web_apps
from focus_app.config import (
    Profile,
    app_id_matches,
    app_kind_label,
    friendly_name,
    split_web_app,
    web_app_key,
)
from focus_app.enforcer import Decision, ForegroundWindow, decide

KEEP = "eilembjdkfgodjkcjnpgpaenohkicgjd"
DRIVE = "aghbiahbpaijignceidepookljebhfak"
KEEP_AUMID = "Chrome._crx_eilembjdkfjnpgpaenohkicgjd"  # 이 PC에서 실제로 읽은 값 (가운데가 잘림)


def test_web_app_key_round_trip_and_labels():
    key = web_app_key("Chrome.exe", KEEP)
    assert key == f"chrome.exe|{KEEP}"
    assert split_web_app(key) == ("chrome.exe", KEEP)
    assert split_web_app("chrome.exe") is None and split_web_app("notepad.exe|x") is None
    assert app_kind_label(key) == "Chrome 앱" and app_kind_label("code.exe") == "code.exe"
    assert friendly_name(key) == "Chrome 앱"


def test_taskbar_id_matches_shortened_app_id():
    assert app_id_matches(KEEP_AUMID, KEEP)
    assert app_id_matches(f"Chrome._crx_{KEEP}", KEEP)  # 자르지 않은 경우
    assert app_id_matches(f"Chrome._crx_{KEEP}.UserData.Profile1", KEEP)  # 다른 프로필
    assert not app_id_matches(KEEP_AUMID, DRIVE)
    assert not app_id_matches("Chrome", KEEP) and not app_id_matches("", KEEP)


def test_allowed_web_app_window_passes_but_rest_of_chrome_is_blocked():
    p = Profile("p", ["code.exe", web_app_key("chrome.exe", KEEP)])
    keep = ForegroundWindow(hwnd=1, pid=2, exe_name="chrome.exe", app_id=KEEP_AUMID)
    chrome = ForegroundWindow(hwnd=3, pid=2, exe_name="chrome.exe")
    drive = ForegroundWindow(hwnd=4, pid=2, exe_name="chrome.exe", app_id=f"Chrome._crx_{DRIVE}")
    edge_keep = ForegroundWindow(hwnd=5, pid=9, exe_name="msedge.exe", app_id=KEEP_AUMID)
    assert decide(keep, p, own_pid=0) is Decision.ALLOW
    assert decide(chrome, p, own_pid=0) is Decision.BLOCK
    assert decide(drive, p, own_pid=0) is Decision.BLOCK
    assert decide(edge_keep, p, own_pid=0) is Decision.BLOCK  # 다른 브라우저의 창은 아님
    assert p.web_apps() == [("chrome.exe", KEEP)]


def test_read_shortcut_finds_app_id_at_odd_offset(tmp_path):
    lnk = tmp_path / "Google Keep.lnk"
    args = f"--profile-directory=Default --app-id={KEEP}".encode("utf-16-le")
    lnk.write_bytes(b"L\0\0\0\x01" + args + b"\0\0")  # 인수 문자열이 홀수 위치에서 시작
    proxy = r"C:\Program Files\Google\Chrome\Application\chrome_proxy.exe"
    assert web_apps.read_shortcut(lnk, proxy) == ("chrome.exe", KEEP)
    assert web_apps.read_shortcut(lnk, r"C:\apps\notepad.exe") is None  # 웹 앱 바로가기가 아님


def test_find_start_host_after_app_record():
    data = (b"junk https://other.com/ web_apps-dt-" + KEEP.encode()
            + b"\x12\x05Keep\x1a,https://keep.google.com/?usp=installed_webapp\x22https://ssl.gstatic.com/x.png")
    assert web_apps.find_start_host(data, KEEP) == "keep.google.com"
    assert web_apps.find_start_host(data, DRIVE) is None


def test_snappy_decompress_literal_and_copy():
    # "abcabcabc" = 리터럴 "abc" + 3바이트 앞에서 6바이트 복사
    assert web_apps.snappy_decompress(bytes([9, 0x08]) + b"abc" + bytes([0x09, 0x03])) == b"abcabcabc"


def test_table_records_rejects_non_table_files():
    assert web_apps.table_records(b"not a leveldb table" * 10) == b""


def test_sites_for_new_apps_skips_covered_and_non_web_apps(monkeypatch):
    hosts = {KEEP: "keep.google.com", DRIVE: "drive.google.com"}
    monkeypatch.setattr(web_apps, "start_host", lambda browser, app_id: hosts.get(app_id))
    keep, drive = web_app_key("chrome.exe", KEEP), web_app_key("chrome.exe", DRIVE)
    assert web_apps.sites_for_new_apps([keep, drive, "code.exe"], ["notion.so"]) == [
        "keep.google.com", "drive.google.com"]
    assert web_apps.sites_for_new_apps([keep], ["google.com"]) == []  # 하위 도메인까지 이미 허용
    assert web_apps.sites_for_new_apps([keep], [".google.com"]) == ["keep.google.com"]  # 그 주소만 허용
    assert web_apps.sites_for_new_apps([keep], ["keep.google.com/u/0"]) == ["keep.google.com"]  # 경로만 허용


@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_adding_web_app_in_main_window_adds_its_site(qapp, monkeypatch):
    from focus_app.config import Settings
    from focus_app.ui import app_catalog
    from focus_app.ui.main_window import MainWindow

    monkeypatch.setattr(web_apps, "start_host", lambda browser, app_id: "keep.google.com")
    s = Settings()
    w = MainWindow(s)
    p = w.current_mode()
    key = web_app_key("chrome.exe", KEEP)
    w.add_entries(p, [app_catalog.AppEntry(exe=key, name="Google Keep")])
    assert key in p.normalized_apps() and "keep.google.com" in p.normalized_sites()
    assert s.app_display_name(key) == "Google Keep"

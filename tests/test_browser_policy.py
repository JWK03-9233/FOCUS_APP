"""사이트 제한: 브라우저 정책 쓰기/되돌리기 (레지스트리는 가짜로 바꿔 검증)."""

import json

import pytest

from focus_app import browser_policy as bp
from focus_app.config import Profile

CHROME = r"Software\Policies\Google\Chrome"
WHALE = r"Software\Policies\Naver\Naver Whale"


class FakeRegistry:
    """키 경로 -> {값 이름: (데이터, 형식)}. HKLM 키는 앞에 ``HKLM\\``를 붙여 같은 사전에 둡니다.

    처음부터 있는 키는 (HKCU, HKLM 모두) ``Software``, ``Software\\Policies``.
    """

    def __init__(self):
        self.keys = {"Software": {}, r"Software\Policies": {}, r"HKLM\Software": {}, r"HKLM\Software\Policies": {}}
        self.fail_on = None  # 이 경로에 쓰면 OSError

    @staticmethod
    def _key(path, machine):
        return "HKLM\\" + path if machine else path

    def _subkeys(self, key):
        prefix = key + "\\"
        return [k for k in self.keys if k.startswith(prefix)]

    def exists(self, path, machine=False):
        return self._key(path, machine) in self.keys

    def values(self, path, machine=False):
        v = self.keys.get(self._key(path, machine))
        return None if v is None else dict(v)

    def is_empty(self, path, machine=False):
        key = self._key(path, machine)
        return key in self.keys and not self.keys[key] and not self._subkeys(key)

    def replace_values(self, path, values, machine=False):
        if self.fail_on and path.startswith(self.fail_on):
            raise OSError("권한 없음")
        key = self._key(path, machine)
        parts = key.split("\\")
        for i in range(1, len(parts) + 1):
            self.keys.setdefault("\\".join(parts[:i]), {})
        self.keys[key] = dict(values)

    def delete_key(self, path, machine=False):
        key = self._key(path, machine)
        if self._subkeys(key):
            raise OSError("하위 키가 있음")
        self.keys.pop(key, None)

    def simple(self, path, machine=False):
        v = self.keys.get(self._key(path, machine))
        return None if v is None else {k: d for k, (d, _t) in v.items()}


@pytest.fixture
def reg(monkeypatch):
    fake = FakeRegistry()
    monkeypatch.setattr(bp, "_reg", fake)
    return fake


def test_engage_blocks_everything_but_chosen_sites_in_every_browser(tmp_path, reg):
    assert bp.engage(tmp_path, ["notion.so", ".example.com"])
    for b in bp.BROWSERS:
        assert reg.simple(b.key + r"\URLBlocklist") == {"1": "*"}
        allow = reg.simple(b.key + r"\URLAllowlist")
        assert list(allow.values())[:2] == ["notion.so", ".example.com"]
        assert "file://*" in allow.values()  # 내 PC의 파일(PDF 등)은 열 수 있음
    sites, applied_at = bp.applied(tmp_path)
    assert sites == ["notion.so", ".example.com"] and applied_at > 0


def test_release_removes_everything_we_created(tmp_path, reg):
    before = set(reg.keys)
    bp.engage(tmp_path, ["notion.so"])
    assert bp.engaged(tmp_path)
    assert bp.release(tmp_path)
    assert set(reg.keys) == before  # 만든 키(브라우저 키와 그 부모)까지 모두 지움
    assert not bp.engaged(tmp_path) and bp.applied(tmp_path) is None


def test_release_restores_existing_policies_exactly(tmp_path, reg):
    # 원래 다른 프로그램(또는 사용자)이 둔 정책
    reg.replace_values(CHROME, {"HomepageLocation": ("https://a.com", 1)})
    reg.replace_values(CHROME + r"\URLAllowlist", {"1": ("intranet.local", 1)})
    bp.engage(tmp_path, ["notion.so"])
    assert reg.simple(CHROME + r"\URLAllowlist")["1"] == "notion.so"
    bp.release(tmp_path)
    assert reg.simple(CHROME) == {"HomepageLocation": "https://a.com"}  # 다른 정책 값은 건드리지 않음
    assert reg.simple(CHROME + r"\URLAllowlist") == {"1": "intranet.local"}
    assert reg.simple(CHROME + r"\URLBlocklist") is None  # 원래 없던 목록은 지움


def test_release_keeps_keys_someone_else_filled_meanwhile(tmp_path, reg):
    bp.engage(tmp_path, ["notion.so"])
    reg.replace_values(WHALE, {"Other": ("x", 1)})  # 집중하는 사이 다른 프로그램이 같은 키에 정책을 넣음
    bp.release(tmp_path)
    assert reg.simple(WHALE) == {"Other": "x"}


def test_engage_again_keeps_original_snapshot_and_updates_sites(tmp_path, reg):
    reg.replace_values(CHROME + r"\URLAllowlist", {"1": ("intranet.local", 1)})
    bp.engage(tmp_path, ["notion.so"])
    first = bp.applied(tmp_path)[1]
    bp.engage(tmp_path, ["notion.so"])  # 같은 목록이면 아무것도 하지 않음
    assert bp.applied(tmp_path)[1] == first
    bp.engage(tmp_path, ["notion.so", "docs.google.com"])  # 집중 중에 사이트를 고침
    sites, second = bp.applied(tmp_path)
    assert sites == ["notion.so", "docs.google.com"] and second >= first
    bp.release(tmp_path)
    assert reg.simple(CHROME + r"\URLAllowlist") == {"1": "intranet.local"}  # 맨 처음 값으로 되돌림


def test_engage_rewrites_policy_someone_removed(tmp_path, reg, monkeypatch):
    bp.engage(tmp_path, ["notion.so"])
    reg.delete_key(CHROME + r"\URLBlocklist")
    monkeypatch.setattr(bp.time, "time", lambda: 10**10)
    bp.engage(tmp_path, ["notion.so"])
    assert reg.simple(CHROME + r"\URLBlocklist") == {"1": "*"}
    assert bp.applied(tmp_path)[1] == 10**10  # 다시 썼으니 브라우저도 다시 읽어야 함


def test_failed_engage_leaves_nothing_behind(tmp_path, reg):
    before = set(reg.keys)
    reg.fail_on = WHALE
    assert not bp.engage(tmp_path, ["notion.so"])
    assert set(reg.keys) == before and not bp.engaged(tmp_path)


def test_release_with_broken_marker_removes_only_our_lists(tmp_path, reg):
    reg.replace_values(CHROME + r"\URLBlocklist", {"1": ("*", 1)})
    reg.replace_values(CHROME + r"\URLAllowlist", {"1": ("notion.so", 1)})
    edge = r"Software\Policies\Microsoft\Edge"
    reg.replace_values(edge + r"\URLBlocklist", {"1": ("bad.com", 1)})  # 우리가 쓴 모양이 아님
    bp.marker_path(tmp_path).write_text("{깨짐", encoding="utf-8")
    assert bp.release(tmp_path)
    assert reg.simple(CHROME + r"\URLBlocklist") is None and reg.simple(CHROME + r"\URLAllowlist") is None
    assert reg.simple(edge + r"\URLBlocklist") == {"1": "bad.com"}
    assert not bp.engaged(tmp_path)


def test_machine_wide_list_gets_our_entries_and_is_restored(tmp_path, reg):
    """PC 전체(HKLM) 정책에 URLAllowlist가 있으면 HKCU 허용 목록은 무시되므로 그쪽에도 덧붙임."""
    # 이 PC에서 실제로 본 모양: 다른 프로그램이 번호가 아닌 이름(-2)으로 넣어 둔 값
    original = {"-2": ("fastdown://*", 1)}
    reg.replace_values(CHROME + r"\URLAllowlist", original, machine=True)
    assert bp.engage(tmp_path, ["naver.com", "kr.tradingview.com"])
    machine = reg.simple(CHROME + r"\URLAllowlist", machine=True)
    assert machine["-2"] == "fastdown://*"  # 원래 값은 그대로
    assert [machine["1"], machine["2"]] == ["naver.com", "kr.tradingview.com"]  # 브라우저가 읽는 1, 2, ...
    assert "file://*" in machine.values()
    assert reg.simple(CHROME + r"\URLBlocklist", machine=True) is None  # HKLM에 없던 목록은 만들지 않음
    assert reg.simple(CHROME + r"\URLBlocklist") == {"1": "*"}
    edge = r"Software\Policies\Microsoft\Edge"
    assert reg.simple(edge + r"\URLAllowlist", machine=True) is None  # HKLM에 목록이 없는 브라우저는 그대로
    bp.release(tmp_path)
    assert reg.values(CHROME + r"\URLAllowlist", machine=True) == original


def test_machine_list_merge_continues_numbering_and_skips_duplicates(tmp_path, reg):
    reg.replace_values(CHROME + r"\URLAllowlist", {"1": ("intranet.local", 1), "2": ("naver.com", 1)}, machine=True)
    reg.replace_values(CHROME + r"\URLBlocklist", {"1": ("bad.com", 1)}, machine=True)
    bp.engage(tmp_path, ["naver.com", "notion.so"])
    allow = reg.simple(CHROME + r"\URLAllowlist", machine=True)
    assert allow["1"] == "intranet.local" and allow["2"] == "naver.com" and allow["3"] == "notion.so"
    assert list(allow.values()).count("naver.com") == 1
    assert reg.simple(CHROME + r"\URLBlocklist", machine=True) == {"1": "bad.com", "2": "*"}
    first = bp.applied(tmp_path)[1]
    bp.engage(tmp_path, ["naver.com", "notion.so"])  # 이미 원하는 값이면 다시 쓰지 않음
    assert bp.applied(tmp_path)[1] == first
    bp.engage(tmp_path, ["docs.google.com"])  # 집중 중 사이트를 바꾸면 원래 값 기준으로 다시 합침
    allow = reg.simple(CHROME + r"\URLAllowlist", machine=True)
    assert "notion.so" not in allow.values() and allow["3"] == "docs.google.com"
    bp.release(tmp_path)
    assert reg.simple(CHROME + r"\URLAllowlist", machine=True) == {"1": "intranet.local", "2": "naver.com"}
    assert reg.simple(CHROME + r"\URLBlocklist", machine=True) == {"1": "bad.com"}


def test_release_without_engage_does_nothing(tmp_path, reg):
    before = dict(reg.keys)
    assert bp.release(tmp_path)
    assert reg.keys == before


def test_marker_is_written_before_registry(tmp_path, reg, monkeypatch):
    seen = []
    original = reg.replace_values

    def spy(path, values, machine=False):
        seen.append(bp.engaged(tmp_path))
        original(path, values, machine)

    monkeypatch.setattr(reg, "replace_values", spy)
    bp.engage(tmp_path, ["notion.so"])
    assert seen and all(seen)  # 도중에 꺼져도 되돌릴 수 있게 원래 값을 먼저 남김
    assert json.loads(bp.marker_path(tmp_path).read_text(encoding="utf-8"))["previous"]


def test_sync_engages_or_releases(tmp_path, reg):
    bp.sync(tmp_path, ["notion.so"])
    assert bp.engaged(tmp_path)
    bp.sync(tmp_path, None)
    assert not bp.engaged(tmp_path)


def test_desired_sites_when_browser_sites_or_web_apps_are_allowed():
    p = Profile("p", ["code.exe"], restrict_sites=True)
    assert bp.desired_sites(p) is None  # 브라우저도 사이트도 없음: 브라우저 자체가 막히므로 정책이 필요 없음
    p.allowed_sites = ["notion.so"]
    assert bp.desired_sites(p) == ["notion.so"]  # 브라우저를 허용하지 않아도 허용 사이트용으로 씀
    p.allowed_sites = []
    p.add_app("chrome.exe|eilembjdkfgodjkcjnpgpaenohkicgjd")
    assert bp.desired_sites(p) == []  # 웹 앱만 허용: 웹 앱 창도 다른 사이트로 못 나가게
    p.allowed_apps = ["code.exe", "chrome.exe"]
    p.allowed_sites = ["notion.so"]
    assert bp.desired_sites(p) == ["notion.so"]
    p.restrict_sites = False
    assert bp.desired_sites(p) is None
    p.restrict_sites, p.block_everything = True, False
    assert bp.desired_sites(p) is None  # 아무것도 막지 않는 모드
    assert bp.desired_sites(None) is None


def test_desired_sites_can_be_empty():
    p = Profile("p", ["msedge.exe"], restrict_sites=True)
    assert bp.desired_sites(p) == []  # 사이트 없이 켜면 모든 사이트를 막음 (파일만 열림)


def test_unsupported_browsers_are_reported():
    p = Profile("p", ["chrome.exe", "firefox.exe"], restrict_sites=True)
    assert bp.unsupported_browsers(p) == ["Firefox"]


def test_needs_restart():
    applied = 1000.0
    assert bp.needs_restart(started=900, applied_at=applied, now=1010)  # 정책 쓰기 전부터 실행 중
    assert not bp.needs_restart(started=1005, applied_at=applied, now=1010)  # 그 뒤에 실행
    assert bp.needs_restart(started=None, applied_at=applied, now=1010)  # 모르면 안전하게
    # 15분(+여유)이 지나면 브라우저가 스스로 다시 읽음
    assert not bp.needs_restart(started=900, applied_at=applied, now=applied + bp.RELOAD_INTERVAL)


def test_browser_windows_allowed_for_sites_without_allowing_the_browser():
    from focus_app.enforcer import Decision, ForegroundWindow, decide

    p = Profile("p", ["code.exe"], restrict_sites=True, allowed_sites=["notion.so"])
    chrome = ForegroundWindow(hwnd=1, pid=2, exe_name="chrome.exe")
    firefox = ForegroundWindow(hwnd=3, pid=4, exe_name="firefox.exe")
    assert decide(chrome, p, own_pid=0) is Decision.ALLOW  # 다른 사이트는 브라우저 정책이 막음
    assert decide(firefox, p, own_pid=0) is Decision.BLOCK  # 정책을 따르지 않는 브라우저는 그대로 막음
    p.allowed_sites = []
    assert decide(chrome, p, own_pid=0) is Decision.BLOCK  # 허용 사이트가 없으면 브라우저도 막음
    p.allowed_sites, p.restrict_sites = ["notion.so"], False
    assert decide(chrome, p, own_pid=0) is Decision.BLOCK  # 사이트 제한을 끄면 사이트 목록은 쓰지 않음


def test_windowless_background_browser_is_not_restarted(monkeypatch):
    """Edge '시작 부스트'처럼 창 없이 도는 프로세스는 다시 시작 대상이 아님 (켠 적 없는 Edge 창이 열리던 문제)."""
    monkeypatch.setattr(bp, "running_pids", lambda exe: [10] if exe == "msedge.exe" else [])
    monkeypatch.setattr(bp.winapi, "process_start_time", lambda pid: 100.0)
    windows = set()
    monkeypatch.setattr(bp.winapi, "find_app_window", lambda exe, match=None: 1 if exe in windows else 0)
    assert bp.stale_browsers(["msedge.exe"], applied_at=200.0, now=210.0) == []
    assert bp.stale_background("msedge.exe", applied_at=200.0, now=210.0)  # 새 창을 열면 옛 정책 -> 먼저 끝냄
    windows.add("msedge.exe")  # 그 프로세스로 창을 열면 그때는 다시 시작 대상
    assert bp.stale_browsers(["msedge.exe"], applied_at=200.0, now=210.0) == ["msedge.exe"]
    assert not bp.stale_background("msedge.exe", applied_at=200.0, now=210.0)

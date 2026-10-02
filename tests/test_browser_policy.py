"""사이트 제한: 브라우저 정책 쓰기/되돌리기 (레지스트리는 가짜로 바꿔 검증)."""

import json

import pytest

from focus_app import browser_policy as bp
from focus_app.config import Profile

CHROME = r"Software\Policies\Google\Chrome"
WHALE = r"Software\Policies\Naver\Naver Whale"


class FakeRegistry:
    """키 경로 -> {값 이름: (데이터, 형식)}. 처음부터 있는 키는 ``Software``, ``Software\\Policies``."""

    def __init__(self):
        self.keys = {"Software": {}, r"Software\Policies": {}}
        self.fail_on = None  # 이 경로에 쓰면 OSError

    def _subkeys(self, path):
        prefix = path + "\\"
        return [k for k in self.keys if k.startswith(prefix)]

    def exists(self, path):
        return path in self.keys

    def values(self, path, machine=False):
        if machine:
            return None
        v = self.keys.get(path)
        return None if v is None else dict(v)

    def is_empty(self, path):
        return path in self.keys and not self.keys[path] and not self._subkeys(path)

    def replace_values(self, path, values):
        if self.fail_on and path.startswith(self.fail_on):
            raise OSError("권한 없음")
        parts = path.split("\\")
        for i in range(1, len(parts) + 1):
            self.keys.setdefault("\\".join(parts[:i]), {})
        self.keys[path] = dict(values)

    def delete_key(self, path):
        if self._subkeys(path):
            raise OSError("하위 키가 있음")
        self.keys.pop(path, None)

    def simple(self, path):
        v = self.keys.get(path)
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


def test_release_without_engage_does_nothing(tmp_path, reg):
    before = dict(reg.keys)
    assert bp.release(tmp_path)
    assert reg.keys == before


def test_marker_is_written_before_registry(tmp_path, reg, monkeypatch):
    seen = []
    original = reg.replace_values

    def spy(path, values):
        seen.append(bp.engaged(tmp_path))
        original(path, values)

    monkeypatch.setattr(reg, "replace_values", spy)
    bp.engage(tmp_path, ["notion.so"])
    assert seen and all(seen)  # 도중에 꺼져도 되돌릴 수 있게 원래 값을 먼저 남김
    assert json.loads(bp.marker_path(tmp_path).read_text(encoding="utf-8"))["previous"]


def test_sync_engages_or_releases(tmp_path, reg):
    bp.sync(tmp_path, ["notion.so"])
    assert bp.engaged(tmp_path)
    bp.sync(tmp_path, None)
    assert not bp.engaged(tmp_path)


def test_desired_sites_only_when_a_supported_browser_is_allowed():
    p = Profile("p", ["code.exe"], restrict_sites=True, allowed_sites=["notion.so"])
    assert bp.desired_sites(p) is None  # 브라우저 자체가 막히므로 정책이 필요 없음
    p.add_app("chrome.exe")
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

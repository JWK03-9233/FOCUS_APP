"""사이트 제한: 집중 중에 브라우저에서 고른 사이트만 열 수 있게 합니다.

Chromium 계열 브라우저(Chrome, Edge, 웨일, Brave)의 관리 정책 ``URLBlocklist``와 ``URLAllowlist``를
``HKCU\\Software\\Policies\\<브라우저>`` 아래에 씁니다. 모든 주소를 막고(``*``) 고른 사이트만 허용합니다.
같은 목록이 PC 전체 정책(HKLM)에도 있으면 그쪽에도 합쳐 씁니다 (아래 '조심할 점').
``notion.so``처럼 적으면 하위 도메인까지, ``.notion.so``처럼 점을 붙이면 그 주소만 허용합니다.
HKCU의 Policies 키는 일반 권한으로 쓸 수 없어서 관리자 권한 도우미만 켜고 끕니다 (작업 관리자 끄기와 같음).

조심할 점
    * 원래 정책을 지우지 않음: 쓰기 전에 두 목록의 원래 값과, 새로 만들게 될 키를 ``browser_policy.json``에
      먼저 적어 둡니다. 되돌릴 때는 그대로 복원하고, 우리가 만든 빈 키만 지웁니다. 다른 정책 값은 건드리지 않습니다.
    * PC 전체 정책: 목록 정책은 한 곳에서만 읽히고 HKLM이 HKCU보다 우선합니다 (목록끼리 합쳐지지 않음).
      다른 프로그램이 HKLM에 ``URLAllowlist``를 두었으면 HKCU에 쓴 허용 사이트는 통째로 무시되어
      모든 사이트가 막힙니다. 그래서 HKLM에 같은 목록 키가 있으면 원래 값은 그대로 두고 그 뒤 번호에
      우리 값을 덧붙이고, 되돌릴 때는 원래 값으로 정확히 복원합니다 (표시 파일의 ``machine``).
    * 비정상 종료: 표시 파일이 남아 있으면 도우미가 다음에 실행될 때(집중 시작, 로그온) 되돌립니다.
    * 적용 시점: 브라우저는 정책을 실행할 때와 15분마다만 다시 읽습니다 (그룹 정책 알림은 도메인 PC에서만 옴).
      그래서 정책을 쓰기 전부터 실행 중이던 브라우저는 다시 시작하기 전까지(최대 15분) 사이트를 막지 못합니다.
      본 앱은 그런 브라우저 창을 최소화하고 '브라우저 다시 시작'을 권합니다 (``needs_restart``).
    * Firefox 등 이 정책을 읽지 않는 브라우저는 앱 허용 목록으로만 막을 수 있습니다 (``OTHER_BROWSERS``).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from focus_app import winapi
from focus_app.config import Profile, normalize_exe

log = logging.getLogger(__name__)

MARKER_FILE = "browser_policy.json"
LISTS = ("URLBlocklist", "URLAllowlist")
# 브라우저는 정책을 15분마다 다시 읽음 (Chromium AsyncPolicyLoader). 여유를 1분 둠
RELOAD_INTERVAL = 16 * 60
# 사이트와 상관없이 늘 허용: 내 PC의 파일(PDF 등)과 확장 프로그램 화면(브라우저 PDF 뷰어 포함)
ALWAYS_ALLOWED = ("file://*", "chrome-extension://*", "extension://*")


@dataclass(frozen=True)
class Browser:
    name: str
    exe: str
    key: str  # HKCU 아래 정책 키


BROWSERS: Tuple[Browser, ...] = (
    Browser("Chrome", "chrome.exe", r"Software\Policies\Google\Chrome"),
    Browser("Edge", "msedge.exe", r"Software\Policies\Microsoft\Edge"),
    Browser("웨일", "whale.exe", r"Software\Policies\Naver\Naver Whale"),
    Browser("Brave", "brave.exe", r"Software\Policies\BraveSoftware\Brave"),
)
SUPPORTED_EXES = frozenset(b.exe for b in BROWSERS)
# 사이트 제한이 적용되지 않는 브라우저 (허용하면 모든 사이트가 열림)
OTHER_BROWSERS: Dict[str, str] = {
    "firefox.exe": "Firefox",
    "opera.exe": "Opera",
    "vivaldi.exe": "Vivaldi",
    "iexplore.exe": "Internet Explorer",
    "waterfox.exe": "Waterfox",
    "librewolf.exe": "LibreWolf",
    "floorp.exe": "Floorp",
    "zen.exe": "Zen",
    "arc.exe": "Arc",
    "thorium.exe": "Thorium",
    "yandex.exe": "Yandex",
}


def browser_name(exe: str) -> str:
    exe = normalize_exe(exe)
    for b in BROWSERS:
        if b.exe == exe:
            return b.name
    return OTHER_BROWSERS.get(exe, exe)


# ---------------------------------------------------------------- 무엇을 막을지
def desired_sites(profile: Optional[Profile]) -> Optional[List[str]]:
    """이 모드로 집중할 때 적용할 허용 사이트 목록. 사이트 제한이 필요 없으면 None.

    정책을 쓰는 경우: 허용 앱에 지원 브라우저가 있거나, 허용 사이트가 있거나(브라우저를 허용 앱에 넣지 않아도
    그 사이트용으로 열림), 브라우저에 설치한 웹 앱을 허용했을 때(웹 앱 창이 다른 사이트로 못 나가게).
    셋 다 아니면 브라우저 자체가 막히므로 정책을 쓰지 않습니다.
    """
    if profile is None or not profile.limits_sites():
        return None
    browser_allowed = any(exe in SUPPORTED_EXES for exe in profile.normalized_apps())
    if not (browser_allowed or profile.browses_sites() or profile.web_apps()):
        return None
    return profile.normalized_sites()


def unsupported_browsers(profile: Profile) -> List[str]:
    """허용 앱 중 사이트 제한이 적용되지 않는 브라우저의 이름."""
    return [OTHER_BROWSERS[exe] for exe in profile.normalized_apps() if exe in OTHER_BROWSERS]


def policy_values(sites: Sequence[str]) -> Dict[str, Dict[str, str]]:
    """정책 키 아래에 쓸 값: {목록 이름: {"1": 값, ...}}."""
    allow = list(dict.fromkeys([*sites, *ALWAYS_ALLOWED]))
    return {
        "URLBlocklist": {"1": "*"},
        "URLAllowlist": {str(i): v for i, v in enumerate(allow, 1)},
    }


# ---------------------------------------------------------------- 레지스트리 (테스트에서 교체)
RegValues = Dict[str, Tuple[object, int]]  # 값 이름 -> (데이터, 형식)


class _WinRegistry:
    """정책 키를 다루는 최소 기능. 기본은 HKEY_CURRENT_USER, machine=True면 HKEY_LOCAL_MACHINE."""

    @staticmethod
    def _winreg():
        if not sys.platform.startswith("win"):
            raise OSError("Windows에서만 쓸 수 있습니다.")
        import winreg

        return winreg

    def _root(self, machine: bool):
        winreg = self._winreg()
        return winreg.HKEY_LOCAL_MACHINE if machine else winreg.HKEY_CURRENT_USER

    def exists(self, path: str, machine: bool = False) -> bool:
        winreg = self._winreg()
        try:
            winreg.CloseKey(winreg.OpenKey(self._root(machine), path))
            return True
        except FileNotFoundError:
            return False

    def values(self, path: str, machine: bool = False) -> Optional[RegValues]:
        """키의 값들. 키가 없으면 None."""
        winreg = self._winreg()
        try:
            key = winreg.OpenKey(self._root(machine), path)
        except FileNotFoundError:
            return None
        out: RegValues = {}
        with key:
            i = 0
            while True:
                try:
                    name, data, kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                out[name] = (data, kind)
                i += 1
        return out

    def is_empty(self, path: str, machine: bool = False) -> bool:
        winreg = self._winreg()
        try:
            key = winreg.OpenKey(self._root(machine), path)
        except FileNotFoundError:
            return False
        with key:
            subkeys, values, _ = winreg.QueryInfoKey(key)
        return subkeys == 0 and values == 0

    def replace_values(self, path: str, values: RegValues, machine: bool = False) -> None:
        """키를 (없으면 만들고) 값을 모두 지운 뒤 주어진 값으로 채웁니다."""
        winreg = self._winreg()
        with winreg.CreateKeyEx(self._root(machine), path, 0,
                                winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            for name in list(self.values(path, machine) or {}):
                winreg.DeleteValue(key, name)
            for name, (data, kind) in values.items():
                winreg.SetValueEx(key, name, 0, kind, data)

    def delete_key(self, path: str, machine: bool = False) -> None:
        """하위 키가 없는 키를 지웁니다 (없으면 그냥 넘어감)."""
        winreg = self._winreg()
        try:
            winreg.DeleteKey(self._root(machine), path)
        except FileNotFoundError:
            pass


_reg = _WinRegistry()
REG_SZ = 1


def _parents(path: str) -> List[str]:
    """``Software\\Policies`` 아래의 조상 키부터 자신까지 (예: ...\\Naver, ...\\Naver\\Naver Whale)."""
    parts = path.split("\\")
    return ["\\".join(parts[:i]) for i in range(3, len(parts) + 1)]


def _encode(values: Optional[RegValues]) -> Optional[list]:
    if values is None:
        return None
    out = []
    for name, (data, kind) in values.items():
        if isinstance(data, bytes):
            out.append([name, {"hex": data.hex()}, kind])
        else:
            out.append([name, data, kind])
    return out


def _decode(raw: Optional[list]) -> Optional[RegValues]:
    if raw is None:
        return None
    out: RegValues = {}
    for name, data, kind in raw:
        if isinstance(data, dict) and "hex" in data:
            data = bytes.fromhex(data["hex"])
        out[str(name)] = (data, int(kind))
    return out


# ---------------------------------------------------------------- 표시 파일
def marker_path(base: Path) -> Path:
    return base / MARKER_FILE


def engaged(base: Path) -> bool:
    """FocusApp이 브라우저 정책을 써 둔 상태인지 (되돌릴 일이 남았는지)."""
    return marker_path(base).exists()


def _read_marker(base: Path) -> Optional[dict]:
    try:
        raw = json.loads(marker_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) and isinstance(raw.get("previous"), dict) else None


def _write_marker(base: Path, data: dict) -> None:
    tmp = marker_path(base).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, marker_path(base))


def applied(base: Path) -> Optional[Tuple[List[str], float]]:
    """지금 적용해 둔 (허용 사이트, 적용 시각). 적용 전이면 None. 본 앱이 읽기만 합니다."""
    marker = _read_marker(base)
    if marker is None or marker.get("sites") is None:
        return None
    try:
        return [str(s) for s in marker["sites"]], float(marker.get("applied_at") or 0)
    except (TypeError, ValueError):
        return None


def _machine_lists(key: str) -> Dict[str, list]:
    """HKLM에 이미 있는 목록 키의 원래 값 (그 목록은 HKLM에도 합쳐 써야 함). 읽을 수 없으면 없는 것으로 봄."""
    out = {}
    for name in LISTS:
        try:
            values = _reg.values(f"{key}\\{name}", machine=True)
        except OSError:
            continue
        if values is not None:
            out[name] = _encode(values)
    return out


def _snapshot() -> dict:
    previous = {}
    for b in BROWSERS:
        previous[b.key] = {
            "created": [p for p in _parents(b.key) if not _reg.exists(p)],
            "lists": {name: _encode(_reg.values(f"{b.key}\\{name}")) for name in LISTS},
            "machine": _machine_lists(b.key),
        }
        for name in previous[b.key]["machine"]:
            log.info("%s: PC 전체 정책에 %s가 있어 그쪽에도 합쳐 씁니다.", b.name, name)
    return previous


def merge_list(original: RegValues, entries: Sequence[str]) -> RegValues:
    """원래 목록 값은 그대로 두고, 우리 항목을 그 뒤 번호에 덧붙인 값.

    브라우저는 목록을 ``1``, ``2``, ``3``… 순서로 빈 번호가 나올 때까지 읽으므로, 1부터 이어지는 번호 다음에
    붙입니다 (예: 원래 값이 ``-2`` 하나뿐이면 브라우저에는 빈 목록이라, 우리 값은 ``1``부터). 이미 읽히는 값은 다시 넣지 않음.
    """
    merged = dict(original)
    n = 1
    while str(n) in merged:
        n += 1
    present = {str(merged[str(i)][0]) for i in range(1, n)}
    for entry in entries:
        if entry in present:
            continue
        merged[str(n)] = (entry, REG_SZ)
        present.add(entry)
        n += 1
    return merged


# ---------------------------------------------------------------- 켜기 / 끄기
def engage(base: Path, sites: Sequence[str]) -> bool:
    """사이트 제한을 켜거나 허용 사이트를 바꿉니다. 레지스트리가 이미 원하는 값이면 아무것도 하지 않음.

    누가 값을 바꾸거나 지웠으면 다시 씁니다 (그때도 적용 시각이 새로 찍힘). 성공하면 True.
    """
    sites = list(sites)
    marker = _read_marker(base)
    try:
        if marker is None:
            # 값을 바꾸기 전에 원래 값을 먼저 남겨, 도중에 꺼져도 되돌릴 수 있게 함
            marker = {"previous": _snapshot(), "sites": None, "applied_at": 0}
            _write_marker(base, marker)
        ours = policy_values(sites)
        wanted = {name: {k: (v, REG_SZ) for k, v in vals.items()} for name, vals in ours.items()}
        changed = False
        for b in BROWSERS:
            machine = (marker["previous"].get(b.key) or {}).get("machine") or {}
            for name, values in wanted.items():
                path = f"{b.key}\\{name}"
                if _reg.values(path) != values:
                    _reg.replace_values(path, values)
                    changed = True
                if name in machine:
                    # PC 전체 정책이 우선하므로 거기에도 (원래 값 + 우리 값)으로 씀
                    merged = merge_list(_decode(machine[name]) or {}, list(ours[name].values()))
                    if _reg.values(path, machine=True) != merged:
                        _reg.replace_values(path, merged, machine=True)
                        changed = True
        if changed or marker.get("sites") != sites:
            marker["sites"] = sites
            marker["applied_at"] = time.time()
            _write_marker(base, marker)
            log.info("사이트 제한: 허용 사이트 %s", sites)
    except OSError:
        log.exception("사이트 제한을 켜지 못함")
        release(base)
        return False
    return True


def release(base: Path) -> bool:
    """써 두었던 정책을 원래대로 돌립니다. 되돌린 게 없거나 성공하면 True."""
    path = marker_path(base)
    if not path.exists():
        return True
    marker = _read_marker(base)
    ok = True
    if marker is None:
        ok = _release_without_marker()
    else:
        for key, prev in marker["previous"].items():
            try:
                lists = prev.get("lists") or {}
                for name in LISTS:
                    old = _decode(lists.get(name))
                    if old is None:
                        _reg.delete_key(f"{key}\\{name}")
                    else:
                        _reg.replace_values(f"{key}\\{name}", old)
                for name, raw in (prev.get("machine") or {}).items():
                    _reg.replace_values(f"{key}\\{name}", _decode(raw) or {}, machine=True)
                # 우리가 만든 키는 비어 있을 때만 지움 (그사이 다른 프로그램이 정책을 넣었으면 남겨 둠)
                for created in reversed(prev.get("created") or []):
                    if _reg.is_empty(created):
                        _reg.delete_key(created)
            except (OSError, ValueError, TypeError, AttributeError):
                log.exception("%s 정책을 되돌리지 못함", key)
                ok = False
    if not ok:
        return False
    try:
        path.unlink()
    except OSError:
        pass
    log.info("사이트 제한: 브라우저 정책을 원래대로 돌렸습니다")
    return True


def _release_without_marker() -> bool:
    """표시 파일이 깨져 원래 값을 모를 때: 우리가 쓴 모양(모든 주소 차단 '*' 하나)인 목록만 지움.

    PC 전체 정책에 덧붙인 값은 원래 값을 모르면 가려낼 수 없어 그대로 둡니다 (기록만 남김).
    """
    log.warning("사이트 제한 표시 파일을 읽지 못해 FocusApp이 쓴 값만 지웁니다 (PC 전체 정책은 그대로)")
    ok = True
    for b in BROWSERS:
        try:
            block = _reg.values(f"{b.key}\\URLBlocklist")
            if block is not None and {k: v for k, (v, _t) in block.items()} == {"1": "*"}:
                for name in LISTS:
                    _reg.delete_key(f"{b.key}\\{name}")
        except OSError:
            log.exception("%s 정책을 지우지 못함", b.name)
            ok = False
    return ok


def sync(base: Path, sites: Optional[Sequence[str]]) -> bool:
    return release(base) if sites is None else engage(base, sites)


# ---------------------------------------------------------------- 실행 중인 브라우저
def needs_restart(started: Optional[float], applied_at: float, now: Optional[float] = None) -> bool:
    """정책을 쓰기 전부터 실행 중이라 아직 사이트 제한을 모르는 브라우저인지.

    시작 시각을 모르면 안전하게 다시 시작이 필요한 것으로 봅니다. 정책을 쓴 지 15분이 넘으면
    브라우저가 스스로 다시 읽었으므로 필요 없음.
    """
    now = time.time() if now is None else now
    if now - applied_at >= RELOAD_INTERVAL:
        return False
    return started is None or started <= applied_at


def running_pids(exe: str) -> List[int]:
    return winapi.process_ids(normalize_exe(exe))


def has_window(exe: str) -> bool:
    """이 브라우저의 창이 떠 있는지 (최소화 포함).

    Edge의 '시작 부스트'나 Chrome의 '백그라운드 앱 계속 실행'은 창 없이 프로세스만 남겨 두므로,
    프로세스가 있다고 사용 중인 브라우저로 보면 안 됩니다 (켠 적 없는 Edge를 다시 시작해 창이 열림).
    """
    return bool(winapi.find_app_window(normalize_exe(exe)))


def stale_browsers(exes: Iterable[str], applied_at: float, now: Optional[float] = None) -> List[str]:
    """이 브라우저들 중 다시 시작해야 사이트 제한이 적용되는 것 (실행 파일 이름). 창이 있는 브라우저만.

    창 없이 뒤에서만 도는 프로세스는 건드리지 않습니다. 나중에 그 프로세스로 창을 열면, 감시 루프가 창마다
    프로세스 시작 시각을 확인해 그때 막고 다시 시작을 권합니다 (app의 브라우저 확인).
    """
    out = []
    for exe in exes:
        if exe not in SUPPORTED_EXES or not has_window(exe):
            continue
        if any(needs_restart(winapi.process_start_time(pid), applied_at, now) for pid in running_pids(exe)):
            out.append(exe)
    return out


def stale_background(exe: str, applied_at: float, now: Optional[float] = None) -> bool:
    """창은 없고, 정책을 쓰기 전부터 뒤에서 돌던 프로세스만 있는지 (새 창을 열면 그 프로세스가 옛 정책으로 띄움)."""
    if exe not in SUPPORTED_EXES or has_window(exe):
        return False
    return any(needs_restart(winapi.process_start_time(pid), applied_at, now) for pid in running_pids(exe))


def _no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def open_url(browser_path: str, url: str, restore_session: bool = False) -> bool:
    """이 브라우저로 주소를 엽니다 (이미 실행 중이면 새 탭으로)."""
    if not browser_path:
        return False
    args = [browser_path, *(["--restore-last-session"] if restore_session else []), *([url] if url else [])]
    try:
        subprocess.Popen(args, cwd=str(Path(browser_path).parent), close_fds=True)
    except OSError:
        log.exception("브라우저를 열지 못함: %s", browser_path)
        return False
    return True


def close_browser(exe: str, timeout: float = 8.0) -> bool:
    """브라우저 프로세스를 모두 끝냅니다 (다시 열지 않음). 시간이 걸리니 스레드에서 호출."""
    for pid in running_pids(exe):
        winapi.terminate_process(pid)
    deadline = time.monotonic() + timeout
    while running_pids(exe):
        if time.monotonic() >= deadline:
            log.warning("%s을(를) 끝내지 못했습니다 (관리자 권한으로 실행됐을 수 있음)", exe)
            return False
        time.sleep(0.2)
    return True


def restart_browser(exe: str, fallback_path: str = "", url: str = "", timeout: float = 8.0,
                    restore: Optional[bool] = None) -> bool:
    """브라우저를 끝내고 열려 있던 탭 그대로 다시 엽니다 (새 정책을 읽게 함). 시간이 걸리니 스레드에서 호출.

    창을 하나씩 닫으면 마지막 창만 복원되므로 모든 프로세스를 한 번에 끝내고 ``--restore-last-session``으로
    다시 엽니다. Edge의 '시작 부스트'나 Chrome의 '백그라운드 앱 계속 실행'으로 창이 없이 남은 프로세스도 같이 끝냅니다.
    """
    pids = running_pids(exe)
    path = next((p for p in (winapi.process_image_path(pid) for pid in pids) if p), "") or fallback_path
    for pid in pids:
        winapi.terminate_process(pid)
    deadline = time.monotonic() + timeout
    while running_pids(exe):
        if time.monotonic() >= deadline:
            log.warning("%s을(를) 끝내지 못했습니다 (관리자 권한으로 실행됐을 수 있음)", exe)
            return False
        time.sleep(0.2)
    log.info("사이트 제한을 적용하려고 %s을(를) 다시 시작합니다", exe)
    # restore가 None이면 끝낸 프로세스가 있었을 때만 열려 있던 탭을 다시 엶 (창 없던 프로세스면 False로 부름)
    return open_url(path, url, restore_session=bool(pids) if restore is None else restore)

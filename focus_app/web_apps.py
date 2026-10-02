"""브라우저에 '앱으로 설치'한 사이트(웹 앱, 예: Google Keep)를 찾습니다.

* 시작 메뉴의 웹 앱 바로가기는 ``chrome_proxy.exe --profile-directory=Default --app-id=<앱 ID>``를 가리킵니다.
  바로가기 파일에서 앱 ID를 읽어 "chrome.exe|<앱 ID>" 키로 씁니다 (``config.web_app_key``).
* 아이콘은 브라우저 사용자 폴더의 ``Web Applications\\_crx_<앱 ID>\\*.ico``.
* 시작 주소는 브라우저 내부 저장소(``Sync Data\\LevelDB``)에서 찾아봅니다. 사이트 제한을 켜면 웹 앱 창도
  브라우저 정책을 따르므로, 그 주소를 허용 사이트에 함께 넣는 데 씁니다. 형식이 공개된 파일이 아니라
  못 찾을 수도 있으며, 그때는 사용자가 사이트를 직접 넣어야 합니다.
"""

from __future__ import annotations

import functools
import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from focus_app.config import normalize_exe, normalize_site, split_web_app, web_app_key

log = logging.getLogger(__name__)

# 웹 앱 바로가기가 가리키는 공용 실행 파일 -> 실제 창이 뜨는 브라우저 실행 파일
PROXIES = {
    "chrome_proxy.exe": "chrome.exe",
    "msedge_proxy.exe": "msedge.exe",
    "brave_proxy.exe": "brave.exe",
    "whale_proxy.exe": "whale.exe",
}

# 브라우저 사용자 폴더 (%LOCALAPPDATA% 아래)
_USER_DATA = {
    "chrome.exe": ("Google", "Chrome", "User Data"),
    "msedge.exe": ("Microsoft", "Edge", "User Data"),
    "brave.exe": ("BraveSoftware", "Brave-Browser", "User Data"),
    "whale.exe": ("Naver", "Naver Whale", "User Data"),
}

_APP_ID_ARG = re.compile(r"--app-id=([a-p]{32})")
_URL = re.compile(rb"https?://[\x21-\x7e]{3,200}")
_SCAN_WINDOW = 4000  # 앱 기록 키 뒤에서 시작 주소를 찾을 범위 (바이트)
_MAX_FILE = 64 * 1024 * 1024  # 이보다 큰 저장소 파일은 읽지 않음


def read_shortcut(lnk: Path, target: str) -> Optional[Tuple[str, str]]:
    """웹 앱 바로가기면 (브라우저 실행 파일, 앱 ID). ``target``은 바로가기가 가리키는 실행 파일 경로."""
    browser = PROXIES.get(normalize_exe(target))
    if browser is None:
        return None
    try:
        raw = lnk.read_bytes()
    except OSError:
        return None
    # 바로가기의 인수 문자열은 UTF-16으로 들어 있고, 홀수 위치에서 시작할 수도 있음
    for text in (raw.decode("utf-16-le", errors="ignore"), raw[1:].decode("utf-16-le", errors="ignore"),
                 raw.decode("latin-1")):
        m = _APP_ID_ARG.search(text)
        if m:
            return browser, m.group(1)
    return None


def user_data_dir(browser_exe: str) -> Optional[Path]:
    parts = _USER_DATA.get(normalize_exe(browser_exe))
    base = os.environ.get("LOCALAPPDATA")
    if not parts or not base:
        return None
    path = Path(base).joinpath(*parts)
    return path if path.is_dir() else None


def _profile_dirs(browser_exe: str) -> List[Path]:
    root = user_data_dir(browser_exe)
    if root is None:
        return []
    try:
        return [d for d in root.iterdir() if d.is_dir() and (d.name == "Default" or d.name.startswith("Profile"))]
    except OSError:
        return []


def icon_path(browser_exe: str, app_id: str) -> str:
    """웹 앱 아이콘 파일 (.ico). 못 찾으면 빈 문자열."""
    for profile in _profile_dirs(browser_exe):
        folder = profile / "Web Applications" / f"_crx_{app_id}"
        try:
            icons = sorted(folder.glob("*.ico"))
        except OSError:
            continue
        if icons:
            return str(icons[0])
    return ""


def find_start_host(data: bytes, app_id: str) -> Optional[str]:
    """저장소 파일 내용에서 이 웹 앱 기록 뒤의 첫 주소의 호스트 (예: keep.google.com)."""
    marker = f"web_apps-dt-{app_id}".encode("ascii")
    start = data.find(marker)
    while start >= 0:
        for m in _URL.finditer(data, start + len(marker), start + len(marker) + _SCAN_WINDOW):
            host = urlsplit(m.group(0).decode("ascii", errors="ignore")).hostname
            if host:
                return host
        start = data.find(marker, start + 1)
    return None


# ---------------------------------------------------------------- LevelDB 표 파일(.ldb) 읽기
# 오래된 기록은 .ldb 파일에 블록 단위로 Snappy 압축되어 있고, 키도 앞 키와 겹치는 부분을 빼고 저장됩니다.
# 그래서 블록을 풀고 항목을 하나씩 꺼내 "키 + 값"을 이어 붙인 뒤 find_start_host로 찾습니다.
def _varint(data: bytes, pos: int) -> Tuple[int, int]:
    result = shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, pos
        shift += 7


def snappy_decompress(data: bytes) -> bytes:
    """Snappy 블록 형식 풀기 (LevelDB가 쓰는 형식만)."""
    size, pos = _varint(data, 0)
    out = bytearray()
    while pos < len(data):
        tag = data[pos]
        pos += 1
        kind = tag & 3
        if kind == 0:  # 리터럴
            length = tag >> 2
            if length >= 60:
                extra = length - 59
                length = int.from_bytes(data[pos:pos + extra], "little")
                pos += extra
            length += 1
            out += data[pos:pos + length]
            pos += length
            continue
        if kind == 1:
            length = ((tag >> 2) & 7) + 4
            offset = ((tag >> 5) << 8) | data[pos]
            pos += 1
        elif kind == 2:
            length = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            length = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        if offset <= 0 or offset > len(out):
            raise ValueError("잘못된 Snappy 데이터")
        for _ in range(length):  # 겹치는 복사가 있어 한 바이트씩
            out.append(out[-offset])
    if len(out) != size:
        raise ValueError("Snappy 길이가 맞지 않음")
    return bytes(out)


def _block(data: bytes, offset: int, size: int) -> bytes:
    raw = data[offset:offset + size]
    kind = data[offset + size] if offset + size < len(data) else 0  # 블록 뒤 5바이트: 압축 형식 + CRC
    return snappy_decompress(raw) if kind == 1 else raw


def _entries(block: bytes):
    """블록의 (키, 값)들."""
    if len(block) < 4:
        return
    restarts = int.from_bytes(block[-4:], "little")
    end = len(block) - 4 - 4 * restarts
    pos, key = 0, b""
    while 0 <= pos < end:
        shared, pos = _varint(block, pos)
        unshared, pos = _varint(block, pos)
        vlen, pos = _varint(block, pos)
        key = key[:shared] + block[pos:pos + unshared]
        pos += unshared
        yield key, block[pos:pos + vlen]
        pos += vlen


def table_records(data: bytes) -> bytes:
    """.ldb 파일의 모든 항목을 "키 + 값"으로 이어 붙인 내용. 읽을 수 없는 파일이면 빈 바이트."""
    if len(data) < 48 or data[-8:] != bytes.fromhex("57fb808b247547db"):  # LevelDB 표 파일 표식
        return b""
    try:
        pos = len(data) - 48
        _meta_off, pos = _varint(data, pos)
        _meta_size, pos = _varint(data, pos)
        index_off, pos = _varint(data, pos)
        index_size, pos = _varint(data, pos)
        out = bytearray()
        for _key, handle in _entries(_block(data, index_off, index_size)):
            off, p = _varint(handle, 0)
            size, _p = _varint(handle, p)
            for key, value in _entries(_block(data, off, size)):
                out += key + value
        return bytes(out)
    except (IndexError, ValueError):
        return b""


@functools.lru_cache(maxsize=64)
def start_host(browser_exe: str, app_id: str) -> Optional[str]:
    """웹 앱의 시작 주소 호스트. 못 찾으면 None (결과는 실행하는 동안 기억)."""
    for profile in _profile_dirs(browser_exe):
        folder = profile / "Sync Data" / "LevelDB"
        try:
            # 최근 기록(.log)부터: 압축되지 않음. 그다음 표 파일(.ldb)은 풀어서 찾음
            files = sorted(folder.glob("*.log")) + sorted(folder.glob("*.ldb"), reverse=True)
        except OSError:
            continue
        for f in files:
            try:
                if f.stat().st_size > _MAX_FILE:
                    continue
                data = f.read_bytes()
            except OSError:
                continue
            host = find_start_host(data if f.suffix == ".log" else table_records(data), app_id)
            if host:
                return host
    log.info("웹 앱 %s의 시작 주소를 찾지 못했습니다 (%s)", app_id, browser_exe)
    return None


def start_hosts(apps: List[Tuple[str, str]]) -> List[str]:
    """여러 웹 앱의 시작 주소 호스트 (찾은 것만, 중복 없이)."""
    out: List[str] = []
    for browser, app_id in apps:
        host = start_host(browser, app_id)
        if host and host not in out:
            out.append(host)
    return out


def learn_sites(settings, keys: Iterable[str]) -> bool:
    """웹 앱들의 시작 주소를 찾아 설정에 기억합니다 (이미 아는 앱은 건너뜀). 새로 기억한 것이 있으면 True.

    본 앱(사용자 계정)에서 불러 둡니다: 도우미는 이 기억된 값으로 정책을 씀.
    """
    changed = False
    for key in keys:
        parts = split_web_app(key)
        if not parts or settings.app_info.get(key, {}).get("site"):
            continue
        host = start_host(*parts)
        if host:
            changed = settings.remember_web_app_site(key, host) or changed
    return changed


def key_for_shortcut(lnk: Path, target: str) -> Optional[str]:
    found = read_shortcut(lnk, target)
    return web_app_key(*found) if found else None


def _covered(host: str, sites: Iterable[str]) -> bool:
    """이 호스트가 이미 허용 사이트에 들어 있는지 (점 없이 적은 주소는 하위 도메인까지 포함)."""
    for site in sites:
        domain, _sep, path = site.partition("/")
        if path:
            continue  # 경로까지 정한 주소는 그 사이트 전체를 허용하지 않음
        if domain.startswith("."):
            if host == domain[1:]:
                return True
        elif host == domain or host.endswith("." + domain):
            return True
    return False


def sites_for_new_apps(keys: Iterable[str], sites: Iterable[str]) -> List[str]:
    """새로 허용한 웹 앱들을 쓰려면 더 넣어야 하는 사이트 (이미 허용된 주소는 빼고).

    사이트 제한을 켜면 웹 앱 창도 브라우저 정책을 따르므로, 앱을 추가할 때 그 시작 주소를 허용 사이트에 넣습니다.
    """
    current = list(sites)
    out: List[str] = []
    for key in keys:
        parts = split_web_app(key)
        host = start_host(*parts) if parts else None
        site = normalize_site(host or "")
        if site and not _covered(site, current + out):
            out.append(site)
    return out

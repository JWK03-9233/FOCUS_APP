"""엄격 모드: 집중 중에 작업 관리자를 못 열게 합니다.

``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System``의 ``DisableTaskMgr`` 값을 씁니다.
Windows 11에서는 이 키에 일반 권한으로 쓸 수 없어서 관리자 권한 도우미만 켜고 끕니다.

켜기 전에 원래 값을 ``taskmgr_lock.json``에 먼저 적어 둡니다. 앱이 비정상 종료되더라도
도우미가 다음에 실행될 때(집중 시작, 로그온) 이 파일을 보고 원래 값으로 되돌립니다.
관리자가 원래 정책으로 작업 관리자를 꺼 두었다면 그 값은 건드리지 않습니다.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

MARKER_FILE = "taskmgr_lock.json"
KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
VALUE_NAME = "DisableTaskMgr"


# ---------------------------------------------------------------- 레지스트리 (테스트에서 교체)
def _read_value() -> Optional[int]:
    if not sys.platform.startswith("win"):
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return int(value)
    except (OSError, ValueError, TypeError):
        return None


def _write_value(value: int) -> None:
    if not sys.platform.startswith("win"):
        raise OSError("Windows에서만 쓸 수 있습니다.")
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_DWORD, int(value))


def _delete_value() -> None:
    if not sys.platform.startswith("win"):
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- 표시 파일
def marker_path(base: Path) -> Path:
    return base / MARKER_FILE


def engaged(base: Path) -> bool:
    """FocusApp이 작업 관리자를 꺼 둔 상태인지 (되돌릴 일이 남았는지)."""
    return marker_path(base).exists()


def engage(base: Path) -> bool:
    """작업 관리자를 끕니다. 이미 꺼 두었으면 아무것도 하지 않음. 성공하면 True."""
    if engaged(base):
        return True
    previous = _read_value()
    tmp = marker_path(base).with_suffix(".tmp")
    try:
        # 값을 바꾸기 전에 원래 값을 먼저 남겨, 도중에 꺼져도 되돌릴 수 있게 함
        tmp.write_text(json.dumps({"previous": previous}), encoding="utf-8")
        os.replace(tmp, marker_path(base))
        if previous != 1:
            _write_value(1)
    except OSError:
        log.exception("작업 관리자를 끄지 못함")
        release(base)
        return False
    log.info("엄격 모드: 작업 관리자를 껐습니다 (원래 값 %s)", previous)
    return True


def release(base: Path) -> bool:
    """꺼 두었던 작업 관리자를 원래대로 돌립니다. 되돌린 게 없거나 성공하면 True."""
    path = marker_path(base)
    if not path.exists():
        return True
    try:
        previous = json.loads(path.read_text(encoding="utf-8")).get("previous")
    except (OSError, ValueError, AttributeError):
        previous = None
    try:
        if previous is None:
            _delete_value()
        else:
            _write_value(int(previous))
    except (OSError, ValueError, TypeError):
        log.exception("작업 관리자 설정을 되돌리지 못함")
        return False
    try:
        path.unlink()
    except OSError:
        pass
    log.info("엄격 모드: 작업 관리자를 원래대로 돌렸습니다 (값 %s)", previous)
    return True


def sync(base: Path, want: bool) -> bool:
    return engage(base) if want else release(base)

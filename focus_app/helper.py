"""관리자 권한 도우미: 일반 권한의 FocusApp이 못 막는 창까지 최소화합니다.

배경
    Windows는 일반 권한 프로세스가 관리자 권한(높은 무결성 수준)으로 실행된 창을 조작하지 못하게
    막습니다(UIPI). 그래서 사용자가 "관리자 권한으로 실행"한 앱은 FocusApp이 최소화할 수 없습니다.

구성
    * 도우미 = 같은 실행 파일을 ``--helper`` 인자로 관리자 권한으로 실행한 것. 창(Qt) 없이 감시만 합니다.
    * 작업 스케줄러에 "가장 높은 권한으로 실행" 작업(``FocusApp\\Helper``)을 한 번 등록해 두면
      (이때만 UAC 확인), 이후에는 확인 창 없이 ``schtasks /run``으로 관리자 권한 도우미를 띄울 수 있습니다.
      로그온할 때도 자동으로 실행되어, 재부팅 뒤 이어지는 집중도 바로 지킵니다.

역할 나누기
    * 본 앱이 실행 중이면: 도우미는 관리자 권한 창만 맡고, 본 앱은 나머지를 맡습니다.
    * 본 앱이 꺼져 있으면 (작업 관리자로 끈 경우 등): 도우미가 모든 창을 맡고,
      일반 권한 작업(``FocusApp\\Main``)으로 본 앱을 다시 띄웁니다. 본 앱도 도우미가 꺼지면 다시 띄웁니다.
      관리자 계정이면 작업 관리자가 관리자 권한으로 뜨므로 둘 다 끌 수는 있지만, 하나씩 끄면 서로 되살립니다.
    * 엄격 모드면 집중 중에 작업 관리자를 끕니다 (``taskmgr_lock``, 관리자 권한이 필요해 도우미가 맡음).
    * 사이트 제한 모드면 집중 중에 브라우저 정책을 씁니다 (``browser_policy``, 역시 관리자 권한이 필요).
    * 집중 중에 해제 문자열을 넣고 정식으로 종료하면 (``quit.json``) 본 앱을 다시 띄우지 않습니다.
    * 집중 세션이 없거나 끝나면 도우미는 스스로 종료합니다 (업데이트 중 파일이 잠기지 않도록).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

from focus_app import browser_policy, taskmgr_lock, winapi
from focus_app.config import Settings, data_dir
from focus_app.enforcer import ForegroundWindow
from focus_app.session import FocusSession
from focus_app.version import APP_ID, __version__

log = logging.getLogger(__name__)

TASK_NAME = "FocusApp\\Helper"
MAIN_TASK_NAME = "FocusApp\\Main"  # 본 앱을 일반 권한으로 다시 띄우는 작업 (도우미가 등록)
MUTEX_NAME = "Local\\FocusAppHelper"
HEARTBEAT_FILE = "helper.json"
HEARTBEAT_STALE = 6.0  # 초. 이보다 오래 갱신이 없으면 도우미가 없는 것으로 봄
LOCK_FILE = "focus_app.lock"  # 본 앱(QLockFile)이 쓰는 잠금 파일. 첫 줄이 pid
QUIT_FILE = "quit.json"  # 집중 중에 정식으로 종료했다는 표시 (본 앱을 다시 띄우지 않음)
IDLE_EXIT_SECONDS = 5.0  # 세션이 없으면 이만큼 기다렸다가 종료
RELAUNCH_GRACE = 2.0  # 초. 본 앱이 이만큼 꺼져 있으면 다시 띄움 (업데이트·재시작 중 겹치지 않게)
RELAUNCH_INTERVAL = 10.0  # 초. 다시 띄우기를 시도하는 최소 간격


# ---------------------------------------------------------------------- 상태 파일
def heartbeat_path(base: Optional[Path] = None) -> Path:
    return (base or data_dir()) / HEARTBEAT_FILE


def write_heartbeat(base: Path, state: str) -> None:
    data = {"pid": os.getpid(), "time": time.time(), "state": state, "version": __version__,
            "elevated": winapi.current_process_elevated()}
    tmp = heartbeat_path(base).with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, heartbeat_path(base))
    except OSError:
        pass


def read_heartbeat(base: Optional[Path] = None) -> Optional[dict]:
    try:
        return json.loads(heartbeat_path(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def helper_alive(base: Optional[Path] = None, now: Optional[float] = None) -> bool:
    """관리자 권한 도우미가 지금 실행 중이고 정상적으로 감시하고 있는지."""
    hb = read_heartbeat(base)
    if not hb:
        return False
    now = time.time() if now is None else now
    if now - float(hb.get("time", 0)) > HEARTBEAT_STALE:
        return False
    return bool(hb.get("elevated")) and winapi.process_alive(int(hb.get("pid", 0)))


def main_app_pid(base: Path) -> int:
    """본 앱의 pid (실행 중이 아니면 0). QLockFile 내용의 첫 줄이 pid입니다."""
    try:
        first = (base / LOCK_FILE).read_text(encoding="utf-8", errors="replace").splitlines()[0]
        pid = int(first.strip())
    except (OSError, ValueError, IndexError):
        return 0
    return pid if winapi.process_alive(pid) else 0


def mark_quit(session: FocusSession, base: Optional[Path] = None) -> None:
    """집중 중에 정식으로 종료함: 이 세션 동안은 도우미가 본 앱을 다시 띄우지 않음."""
    try:
        ((base or data_dir()) / QUIT_FILE).write_text(json.dumps({"started_at": session.started_at}), encoding="utf-8")
    except OSError:
        log.exception("종료 표시를 남기지 못함")


def clear_quit(base: Optional[Path] = None) -> None:
    try:
        ((base or data_dir()) / QUIT_FILE).unlink()
    except OSError:
        pass


def quit_marked(session: FocusSession, base: Path) -> bool:
    try:
        raw = json.loads((base / QUIT_FILE).read_text(encoding="utf-8"))
        return float(raw.get("started_at")) == session.started_at
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def should_relaunch(main_pid: int, dead_since: Optional[float], last_try: float, now: float, quit: bool) -> bool:
    """본 앱을 다시 띄울 때인지: 정식 종료가 아니고, 잠깐 이상 꺼져 있었고, 최근에 시도하지 않았을 때."""
    if main_pid or quit or dead_since is None:
        return False
    return now - dead_since >= RELAUNCH_GRACE and now - last_try >= RELAUNCH_INTERVAL


# ---------------------------------------------------------------------- 도우미 본체
def helper_handles(window: ForegroundWindow, main_pid: int, is_elevated=winapi.process_elevated) -> bool:
    """도우미가 맡을 창인지: FocusApp 자신의 창은 절대 건드리지 않고,
    본 앱이 살아 있으면 관리자 권한 창만, 꺼져 있으면 모든 창."""
    if window.exe_name.lower() == "focusapp.exe" or (main_pid and window.pid == main_pid):
        return False
    if not main_pid:
        return True
    return bool(is_elevated(window.pid))


def run_helper(base: Optional[Path] = None) -> int:
    """도우미 감시 루프. 세션이 없거나 끝나면 종료합니다."""
    from focus_app.monitor import AllowlistMonitor

    base = base or data_dir()
    mutex = winapi.acquire_single_instance(MUTEX_NAME)
    if mutex is None:
        log.info("도우미가 이미 실행 중입니다.")
        return 0
    log.info("도우미 시작 (관리자 권한: %s, pid %s)", winapi.current_process_elevated(), os.getpid())

    monitor: Optional[AllowlistMonitor] = None
    profile_key: Tuple = ()
    settings_mtime = 0.0
    settings = Settings.load(base / "settings.json")
    idle_since: Optional[float] = None
    main_pid = 0
    main_dead_since: Optional[float] = None
    last_relaunch = 0.0
    last_beat = 0.0
    last_main_check = 0.0
    main_task_ready = False
    taskmgr_failed = False
    policy_retry_at = 0.0  # 사이트 제한을 켜지 못했으면 이 시각 전에는 다시 시도하지 않음

    while True:
        now = time.time()
        session = FocusSession.load(base / "session.json")
        active = session is not None and not session.is_expired(now)
        if now - last_beat >= 1.0:
            write_heartbeat(base, "active" if active else "idle")
            last_beat = now
        if not active:
            monitor = None
            taskmgr_lock.release(base)  # 집중이 끝났거나 지난번에 비정상 종료됨 -> 작업 관리자 되돌림
            browser_policy.release(base)  # 브라우저 사이트 제한도 같은 이유로 되돌림
            idle_since = idle_since or now
            if now - idle_since >= IDLE_EXIT_SECONDS:
                log.info("집중 세션이 없어 도우미를 종료합니다.")
                break
            time.sleep(0.5)
            continue
        idle_since = None

        try:
            mtime = (base / "settings.json").stat().st_mtime
        except OSError:
            mtime = 0.0
        if mtime != settings_mtime:
            settings_mtime = mtime
            settings = Settings.load(base / "settings.json")
        profile = settings.get_profile(session.profile) or settings.current_profile()
        key = (profile.name, profile.block_everything, tuple(profile.normalized_apps()))
        if monitor is None or key != profile_key:
            monitor = AllowlistMonitor(profile, handles=lambda w: helper_handles(w, main_pid))
            profile_key = key
        if now - last_main_check >= 1.0:
            last_main_check = now
            if not settings.block_task_manager:
                taskmgr_lock.release(base)
            elif not taskmgr_failed:
                taskmgr_failed = not taskmgr_lock.engage(base)  # 실패하면 이번 실행에서는 다시 시도하지 않음
            # 매초 레지스트리를 확인해 다르면 다시 씀 (모드의 사이트를 고쳤거나 누가 값을 지운 경우)
            sites = browser_policy.desired_sites(profile, settings.web_app_sites(profile))
            if sites is None:
                browser_policy.release(base)
            elif now >= policy_retry_at and not browser_policy.engage(base, sites):
                policy_retry_at = now + 30.0  # 실패하면 본 앱이 브라우저를 막고 있으니 가끔만 다시 시도
            main_pid = main_app_pid(base)
            main_dead_since = None if main_pid else (main_dead_since or now)
            if should_relaunch(main_pid, main_dead_since, last_relaunch, now, quit_marked(session, base)):
                last_relaunch = now
                if not main_task_ready:
                    main_task_ready = ensure_main_task(base)
                if main_task_ready and relaunch_main():
                    log.info("꺼진 본 앱을 다시 띄웁니다.")
        if settings.block_task_manager:
            _minimize_task_manager()
        monitor.poll()
        time.sleep(max(0.1, settings.poll_interval_ms / 1000))

    taskmgr_lock.release(base)
    browser_policy.release(base)
    try:
        heartbeat_path(base).unlink()
    except OSError:
        pass
    return 0


def _minimize_task_manager() -> None:
    """엄격 모드: 집중 전에 미리 열어 둔 작업 관리자 창을 최소화 (새로 여는 것은 정책이 막음)."""
    hwnd = winapi.get_foreground_window()
    info = winapi.describe_window(hwnd) if hwnd else None
    if info is not None and info.exe_name == "taskmgr.exe":
        winapi.minimize_window(winapi.root_owner(hwnd) or hwnd)


# ---------------------------------------------------------------------- 작업 스케줄러
def _command(args: List[str]) -> Tuple[str, List[str], str]:
    """(실행 파일, 인자, 작업 폴더). exe 배포본이면 FocusApp.exe, 소스 실행이면 pythonw -m focus_app."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return str(exe), args, str(exe.parent)
    pyw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = str(pyw if pyw.exists() else Path(sys.executable))
    project = str(Path(__file__).resolve().parent.parent)
    return interpreter, ["-m", "focus_app", *args], project


def helper_command(base: Optional[Path] = None) -> Tuple[str, List[str], str]:
    return _command(["--helper", "--data-dir", str(base or data_dir())])


def main_command(base: Optional[Path] = None) -> Tuple[str, List[str], str]:
    return _command(["--data-dir", str(base or data_dir())])


def _quote(arg: str) -> str:
    return f'"{arg}"' if (" " in arg or not arg) else arg


def _current_user() -> str:
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")


def task_xml(user: Optional[str] = None, base: Optional[Path] = None) -> str:
    """로그온 시 + 요청 시 관리자 권한으로 도우미를 실행하는 작업 정의."""
    return _task_xml(
        "관리자 권한으로 실행된 앱까지 집중 모드 중에 최소화합니다. 집중 중이 아니면 바로 종료됩니다.",
        helper_command(base), user, run_level="HighestAvailable", logon=True, instances="IgnoreNew", priority=7,
    )


def main_task_xml(user: Optional[str] = None, base: Optional[Path] = None) -> str:
    """집중 중에 꺼진 본 앱을 도우미가 일반 권한으로 다시 띄울 때 쓰는 작업 정의 (요청 시에만 실행)."""
    # 본 앱은 스스로 한 번만 실행되므로(잠금 파일) 작업 쪽에서 막지 않음
    return _task_xml(
        "집중 중에 강제로 꺼진 FocusApp을 다시 띄웁니다.",
        main_command(base), user, run_level="LeastPrivilege", logon=False, instances="Parallel", priority=4,
    )


def _task_xml(description: str, command: Tuple[str, List[str], str], user: Optional[str], run_level: str,
              logon: bool, instances: str, priority: int) -> str:
    from xml.sax.saxutils import escape

    exe, args, workdir = command
    user = user or _current_user()
    arguments = " ".join(_quote(a) for a in args)
    triggers = f"""
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user)}</UserId>
    </LogonTrigger>
  </Triggers>""" if logon else ""
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{APP_ID}: {escape(description)}</Description>
  </RegistrationInfo>{triggers}
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>{run_level}</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>{instances}</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>{priority}</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(exe)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def _schtasks(*args: str, timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, errors="replace",
                          timeout=timeout, creationflags=_no_window())


def is_registered() -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        return _schtasks("/Query", "/TN", TASK_NAME).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _run_elevated(exe: str, arguments: str, timeout: float = 120) -> int:
    """UAC 확인을 거쳐 관리자 권한으로 실행하고 끝날 때까지 기다립니다. 취소하면 -1."""
    ps = (
        "try { $p = Start-Process -FilePath '" + exe.replace("'", "''") + "' -ArgumentList '"
        + arguments.replace("'", "''") + "' -Verb RunAs -WindowStyle Hidden -PassThru -Wait; exit $p.ExitCode }"
        " catch { exit -1 }"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                       timeout=timeout, creationflags=_no_window())
    return r.returncode if r.returncode < 2**31 else r.returncode - 2**32


def register() -> Tuple[bool, str]:
    """작업을 등록합니다 (UAC 확인 1번). (성공 여부, 메시지)."""
    xml_path = Path(tempfile.mkdtemp(prefix="focusapp-task-")) / "helper_task.xml"
    xml_path.write_text(task_xml(), encoding="utf-16")
    try:
        code = _run_elevated("schtasks.exe", f'/Create /TN "{TASK_NAME}" /XML "{xml_path}" /F')
    finally:
        try:
            xml_path.unlink()
            xml_path.parent.rmdir()
        except OSError:
            pass
    if code == -1:
        return False, "관리자 권한 확인을 취소했습니다."
    if code != 0 or not is_registered():
        return False, f"작업을 등록하지 못했습니다 (코드 {code})."
    return True, "관리자 권한 도우미를 설치했습니다."


def _release_locks_first(base: Optional[Path] = None, timeout: float = 8.0) -> None:
    """도우미가 바꿔 둔 설정(작업 관리자 끄기, 사이트 제한)이 남아 있으면 도우미를 띄워 되돌리게 합니다.

    도우미 작업을 지우면 되돌릴 방법이 없어지므로 지우기 전에 부릅니다 (집중 중이 아닐 때만 제거할 수 있음).
    """
    base = base or data_dir()
    if not (taskmgr_lock.engaged(base) or browser_policy.engaged(base)):
        return
    if not start():
        return
    deadline = time.monotonic() + timeout
    while (taskmgr_lock.engaged(base) or browser_policy.engaged(base)) and time.monotonic() < deadline:
        time.sleep(0.2)


def unregister() -> Tuple[bool, str]:
    _release_locks_first()
    # 본 앱 다시 띄우기 작업도 함께 지움 (없으면 그 부분만 실패하고 넘어감, 종료 코드는 도우미 작업 기준)
    code = _run_elevated(
        "cmd.exe", f'/c schtasks /Delete /TN "{MAIN_TASK_NAME}" /F & schtasks /Delete /TN "{TASK_NAME}" /F'
    )
    if code == -1:
        return False, "관리자 권한 확인을 취소했습니다."
    if is_registered():
        return False, f"작업을 지우지 못했습니다 (코드 {code})."
    return True, "관리자 권한 도우미를 제거했습니다."


def start(check_registered: bool = True) -> bool:
    """등록된 작업을 실행합니다 (UAC 확인 없이 관리자 권한으로 뜸). 이미 실행 중이면 아무 일도 없음."""
    if check_registered and not is_registered():
        return False
    try:
        return _schtasks("/Run", "/TN", TASK_NAME).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_main_task(base: Optional[Path] = None) -> bool:
    """본 앱 다시 띄우기 작업을 지금 실행 파일 기준으로 등록합니다 (도우미가 관리자 권한으로 호출).

    도우미를 예전 버전에서 설치했어도 따로 다시 설치할 필요가 없게 도우미가 직접 등록합니다.
    """
    return _create_task(MAIN_TASK_NAME, main_task_xml(base=base))


def register_here() -> int:
    """``--register-helper``: 이미 관리자 권한일 때 도우미 작업을 바로 등록합니다 (확인 창 없음).

    설치 프로그램이 '관리자 권한 도우미 설치'를 고른 경우 UAC를 거쳐 이 명령으로 실행합니다. 성공하면 0.
    """
    if not winapi.current_process_elevated():
        log.warning("관리자 권한이 아니어서 도우미 작업을 등록할 수 없습니다.")
        return 1
    return 0 if _create_task(TASK_NAME, task_xml()) else 1


def _create_task(name: str, xml: str) -> bool:
    """작업 정의(XML)로 작업을 등록합니다 (같은 이름이 있으면 덮어씀). 관리자 권한으로 호출해야 함."""
    folder = Path(tempfile.mkdtemp(prefix="focusapp-task-"))
    xml_path = folder / "task.xml"
    try:
        xml_path.write_text(xml, encoding="utf-16")
        r = _schtasks("/Create", "/TN", name, "/XML", str(xml_path), "/F")
        if r.returncode != 0:
            log.warning("작업 %s을(를) 등록하지 못함: %s", name, (r.stderr or r.stdout).strip())
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        log.exception("작업 %s 등록 실패", name)
        return False
    finally:
        try:
            xml_path.unlink()
            folder.rmdir()
        except OSError:
            pass


def relaunch_main() -> bool:
    """본 앱을 일반 권한으로 다시 띄웁니다 (도우미는 관리자 권한이라 직접 띄우면 본 앱도 관리자 권한이 됨)."""
    try:
        return _schtasks("/Run", "/TN", MAIN_TASK_NAME).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def registered_command() -> str:
    """등록된 작업이 실행하는 파일 경로 (없거나 못 읽으면 빈 문자열)."""
    try:
        r = _schtasks("/Query", "/TN", TASK_NAME, "/XML")
    except (OSError, subprocess.SubprocessError):
        return ""
    import re
    from xml.sax.saxutils import unescape

    m = re.search(r"<Command>(.*?)</Command>", r.stdout or "", re.S)
    return unescape(m.group(1).strip()) if (r.returncode == 0 and m) else ""


def points_here() -> bool:
    """등록된 작업이 지금 실행 중인 FocusApp을 가리키는지 (다른 위치에 설치했다면 다시 설치해야 함)."""
    current = os.path.normcase(os.path.abspath(helper_command()[0]))
    registered = registered_command()
    return bool(registered) and os.path.normcase(os.path.abspath(registered)) == current


def status_text() -> str:
    if not sys.platform.startswith("win"):
        return "Windows에서만 쓸 수 있습니다."
    if not is_registered():
        return "설치 안 됨 — 관리자 권한으로 실행한 앱은 막지 못합니다."
    if not points_here():
        return "다른 위치의 FocusApp으로 설치되어 있습니다 — 제거한 뒤 다시 설치하세요."
    if helper_alive():
        return "설치됨 · 지금 실행 중"
    return "설치됨 · 집중을 시작하면 자동으로 실행됩니다"

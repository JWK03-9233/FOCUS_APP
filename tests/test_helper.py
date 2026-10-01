"""관리자 권한 도우미의 판단 로직 (실제 관리자 권한 없이 검증 가능한 부분)."""

import json
import os
import threading
import time

from focus_app import helper
from focus_app.enforcer import ForegroundWindow
from focus_app.session import FocusSession


def win(exe, pid=100):
    return ForegroundWindow(hwnd=1, pid=pid, exe_name=exe)


def test_helper_never_touches_focusapp_itself():
    assert not helper.helper_handles(win("focusapp.exe"), main_pid=0, is_elevated=lambda p: True)
    assert not helper.helper_handles(win("python.exe", pid=42), main_pid=42, is_elevated=lambda p: True)


def test_helper_takes_only_elevated_windows_while_main_app_runs():
    elevated = {7}
    is_el = lambda pid: pid in elevated  # noqa: E731
    assert helper.helper_handles(win("regedit.exe", pid=7), main_pid=42, is_elevated=is_el)
    assert not helper.helper_handles(win("chrome.exe", pid=8), main_pid=42, is_elevated=is_el)


def test_helper_takes_everything_when_main_app_is_gone():
    assert helper.helper_handles(win("chrome.exe", pid=8), main_pid=0, is_elevated=lambda p: False)


def test_heartbeat_alive_and_stale(tmp_path):
    helper.write_heartbeat(tmp_path, "active")
    hb = helper.read_heartbeat(tmp_path)
    assert hb["pid"] == os.getpid()
    # 테스트 프로세스는 관리자 권한이 아니므로 '살아 있는 도우미'로 보지 않음
    assert helper.helper_alive(tmp_path) is bool(hb["elevated"])
    data = json.loads(helper.heartbeat_path(tmp_path).read_text())
    data.update(elevated=True, time=time.time() - 60)
    helper.heartbeat_path(tmp_path).write_text(json.dumps(data))
    assert not helper.helper_alive(tmp_path)  # 오래된 신호


def test_main_app_pid_from_lock_file(tmp_path):
    (tmp_path / "focus_app.lock").write_text(f"{os.getpid()}\npython\nhost\n")
    assert helper.main_app_pid(tmp_path) == os.getpid()
    (tmp_path / "focus_app.lock").write_text("999999\npython\nhost\n")
    assert helper.main_app_pid(tmp_path) == 0


def test_run_helper_exits_by_itself_when_no_session(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "IDLE_EXIT_SECONDS", 0.3)
    monkeypatch.setattr(helper, "MUTEX_NAME", f"Local\\FocusAppHelperTest{os.getpid()}")
    started = time.time()
    assert helper.run_helper(tmp_path) == 0
    assert time.time() - started < 5
    assert not helper.heartbeat_path(tmp_path).exists()


def test_run_helper_keeps_running_during_session_then_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, "IDLE_EXIT_SECONDS", 0.3)
    monkeypatch.setattr(helper, "MUTEX_NAME", f"Local\\FocusAppHelperTest2{os.getpid()}")
    polls = []
    import focus_app.monitor as monitor_mod

    monkeypatch.setattr(monitor_mod.AllowlistMonitor, "poll", lambda self: polls.append(1))
    FocusSession.start("공부용", None).save(tmp_path / "session.json")
    t = threading.Thread(target=helper.run_helper, args=(tmp_path,))
    t.start()
    time.sleep(1.5)
    assert t.is_alive() and polls  # 세션 중에는 감시를 계속함
    assert helper.read_heartbeat(tmp_path)["state"] == "active"
    FocusSession.clear(tmp_path / "session.json")  # 집중이 끝나면
    t.join(timeout=5)
    assert not t.is_alive()  # 스스로 종료


def test_relaunch_main_only_after_grace_and_not_too_often():
    rl = helper.should_relaunch
    assert not rl(main_pid=42, dead_since=None, last_try=0, now=100, quit=False)  # 살아 있음
    assert not rl(main_pid=0, dead_since=99.5, last_try=0, now=100, quit=False)  # 막 꺼짐 (재시작 중일 수 있음)
    assert rl(main_pid=0, dead_since=95, last_try=0, now=100, quit=False)
    assert not rl(main_pid=0, dead_since=95, last_try=95, now=100, quit=False)  # 방금 시도함
    assert not rl(main_pid=0, dead_since=95, last_try=0, now=100, quit=True)  # 정식으로 종료함


def test_quit_marker_applies_only_to_that_session(tmp_path):
    session = FocusSession.start("공부용", 50)
    assert not helper.quit_marked(session, tmp_path)
    helper.mark_quit(session, tmp_path)
    assert helper.quit_marked(session, tmp_path)
    later = FocusSession.start("공부용", 50, now=session.started_at + 3600)
    assert not helper.quit_marked(later, tmp_path)  # 다음 집중에서는 다시 띄움
    helper.clear_quit(tmp_path)
    assert not helper.quit_marked(session, tmp_path)


def test_run_helper_restores_task_manager_when_no_session(tmp_path, monkeypatch):
    from focus_app import taskmgr_lock

    monkeypatch.setattr(helper, "IDLE_EXIT_SECONDS", 0.3)
    monkeypatch.setattr(helper, "MUTEX_NAME", f"Local\\FocusAppHelperTest3{os.getpid()}")
    released = []
    monkeypatch.setattr(taskmgr_lock, "release", lambda base: released.append(base) or True)
    helper.run_helper(tmp_path)
    assert released  # 지난번에 꺼 둔 작업 관리자가 있으면 되돌림


def test_register_here_needs_elevation(monkeypatch):
    created = []
    monkeypatch.setattr(helper, "_create_task", lambda name, xml: created.append(name) or True)
    monkeypatch.setattr(helper.winapi, "current_process_elevated", lambda: False)
    assert helper.register_here() == 1 and not created  # 관리자 권한이 아니면 시도하지 않음
    monkeypatch.setattr(helper.winapi, "current_process_elevated", lambda: True)
    assert helper.register_here() == 0 and created == [helper.TASK_NAME]


def test_main_task_xml_runs_app_without_elevation_on_demand():
    xml = helper.main_task_xml(user="PC\\me")
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert "<LogonTrigger>" not in xml  # 로그온 때 띄우는 것은 도우미 몫
    assert "--helper" not in xml and "--data-dir" in xml
    assert "<MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>" in xml


def test_task_xml_runs_helper_with_highest_privileges():
    xml = helper.task_xml(user="PC\\me")
    assert "<RunLevel>HighestAvailable</RunLevel>" in xml
    assert "--helper" in xml and "--data-dir" in xml
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml  # 72시간 제한으로 꺼지지 않게
    assert "<LogonTrigger>" in xml

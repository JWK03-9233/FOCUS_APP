"""오프스크린 Qt로 메인 창, 앱 고르기 창, 컨트롤러 흐름을 검증합니다."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from focus_app.config import Settings  # noqa: E402
from focus_app.session import FocusSession  # noqa: E402
from focus_app.ui import app_catalog  # noqa: E402
from focus_app.ui.app_catalog import AppEntry  # noqa: E402
from focus_app.ui.app_picker import AppPickerDialog  # noqa: E402
from focus_app.ui.main_window import CUSTOM_ID, UNLIMITED_ID, MainWindow, format_clock  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def no_installed_scan():
    # 테스트에서 실제 시작 메뉴를 읽지 않도록 빈 목록으로 채워 둠
    app_catalog.installed_apps.set([AppEntry("hwp.exe", "한글", "")])
    yield


def make_window(qapp):
    s = Settings()
    w = MainWindow(s)
    w._confirm_start = lambda p, m: True
    return s, w


def test_mode_list_shows_all_modes_and_selects_active(qapp):
    s, w = make_window(qapp)
    assert w.mode_list.count() == len(s.profiles)
    assert w.current_mode().name == s.active_profile
    assert w.mode_title.text() == s.active_profile


def test_selecting_mode_updates_active_and_saves(qapp):
    s, w = make_window(qapp)
    saved = []
    w.settings_changed.connect(lambda: saved.append(1))
    w.mode_list.setCurrentRow(1)
    assert s.active_profile == s.profiles[1].name
    assert saved


def test_add_and_remove_apps(qapp):
    s, w = make_window(qapp)
    p = w.current_mode()
    before = len(p.normalized_apps())
    w.add_entries(p, [AppEntry("obsidian.exe", "Obsidian 노트", "C:\\x\\Obsidian.exe")])
    assert "obsidian.exe" in p.normalized_apps()
    assert s.app_display_name("obsidian.exe") == "Obsidian 노트"
    assert w.app_list.count() == before + 1
    w._remove_app("obsidian.exe")
    assert "obsidian.exe" not in p.normalized_apps()
    assert w.app_list.count() == before


def test_free_mode_hides_app_list(qapp):
    s, w = make_window(qapp)
    w.free_radio.setChecked(True)
    assert w.current_mode().block_everything is False
    assert w.apps_stack.currentWidget() is w.apps_empty
    assert not w.add_app_btn.isEnabled()
    w.block_radio.setChecked(True)
    assert w.current_mode().block_everything is True


def test_duration_choices(qapp):
    s, w = make_window(qapp)
    w.duration_group.button(90).setChecked(True)
    assert w.selected_minutes() == 90
    w.duration_group.button(UNLIMITED_ID).setChecked(True)
    assert w.selected_minutes() is None
    w.duration_group.button(CUSTOM_ID).setChecked(True)
    w.custom_spin.setValue(37)
    assert w.selected_minutes() == 37


def test_start_emits_request_and_remembers_duration(qapp):
    s, w = make_window(qapp)
    got = []
    w.start_requested.connect(lambda name, minutes: got.append((name, minutes)))
    w.duration_group.button(25).setChecked(True)
    w.start_btn.click()
    assert got == [(s.active_profile, 25)]
    assert s.default_duration_minutes == 25


def test_start_cancelled_does_nothing(qapp):
    s, w = make_window(qapp)
    w._confirm_start = lambda p, m: False
    got = []
    w.start_requested.connect(lambda *a: got.append(a))
    w.start_btn.click()
    assert got == []


def test_running_page_shows_timer_and_emergency(qapp):
    s, w = make_window(qapp)
    p = s.current_profile()
    sess = FocusSession.start(p.name, 50, now=time.time() - 600)
    w.show_running(sess, p)
    w.update_running(sess, 3)
    assert w.stack.currentWidget() is w.running_page
    assert w.timer_label.text() in ("40:00", "39:59")
    assert "3번" in w.run_info.text()
    assert w.run_apps.count() == len(p.normalized_apps())
    assert w.emergency_banner.isHidden()
    sess.request_emergency(10)
    w.update_running(sess, 3)
    assert not w.emergency_banner.isHidden()
    assert w.emergency_btn.isHidden()


def test_format_clock():
    assert format_clock(65) == "01:05"
    assert format_clock(3725) == "1:02:05"


def test_picker_marks_existing_and_returns_new(qapp):
    running = [AppEntry("notepad.exe", "메모장", "", True), AppEntry("chrome.exe", "Chrome", "", True)]
    dlg = AppPickerDialog("공부용", ["notepad.exe"], running=running)
    items = {dlg.list.item(i).data(Qt.ItemDataRole.UserRole): dlg.list.item(i) for i in range(dlg.list.count())}
    assert "hwp.exe" in items  # 설치된 앱도 표시
    assert not (items["notepad.exe"].flags() & Qt.ItemFlag.ItemIsEnabled)  # 이미 추가됨
    assert not dlg.ok_btn.isEnabled()
    items["chrome.exe"].setCheckState(Qt.CheckState.Checked)
    assert dlg.ok_btn.isEnabled()
    assert [e.exe for e in dlg.selected_entries()] == ["chrome.exe"]
    dlg.search.setText("한글")
    assert items["chrome.exe"].isHidden() and not items["hwp.exe"].isHidden()


def test_controller_start_and_end_flow(qapp):
    from focus_app.app import FocusApp

    ctl = FocusApp(qapp, show_window=False)
    try:
        name = ctl.settings.active_profile
        ctl.start_focus(name, 30)
        assert ctl.active
        assert FocusSession.load() is not None
        assert ctl.window.stack.currentWidget() is ctl.window.running_page
        ctl._end_session("expired")
        assert not ctl.active
        assert FocusSession.load() is None
        assert ctl.window.stack.currentWidget() is ctl.window.setup_page
        assert not ctl.window.notice.isHidden()
    finally:
        ctl.tray.hide()
        ctl.window.allow_close = True
        ctl.window.close()


def test_preset_chips_follow_settings_and_edit(qapp):
    s, w = make_window(qapp)
    assert [b.text() for b in w._preset_buttons] == ["25분", "50분", "1시간 30분", "2시간", "3시간"]
    s.duration_presets = [10, 45]
    w._rebuild_chips()
    assert [b.text() for b in w._preset_buttons] == ["10분", "45분"]
    w.duration_group.button(45).setChecked(True)
    assert w.selected_minutes() == 45


def test_preset_dialog_add_remove_limits(qapp):
    from focus_app.ui.preset_dialog import PresetDialog

    dlg = PresetDialog([25, 50])
    assert dlg.add_minutes(40)
    assert not dlg.add_minutes(40)  # 중복
    assert not dlg.add_minutes(0)
    assert dlg.presets() == [25, 40, 50]
    dlg.list.selectAll()
    dlg._remove()  # 전부 지우려 하면 거부
    assert dlg.presets() == [25, 40, 50]
    for m in (1, 2, 3, 4, 5):
        dlg.add_minutes(m)
    assert len(dlg.presets()) == 8 and not dlg.add_btn.isEnabled()


def test_last_choices_are_remembered_across_restart(qapp):
    s, w = make_window(qapp)
    w.mode_list.setCurrentRow(1)
    w.duration_group.button(UNLIMITED_ID).setChecked(True)
    s.save()
    s2 = Settings.load()
    w2 = MainWindow(s2)
    assert w2.current_mode().name == s.profiles[1].name
    assert w2.duration_group.checkedId() == UNLIMITED_ID
    assert w2.selected_minutes() is None

    w2.duration_group.button(CUSTOM_ID).setChecked(True)
    w2.custom_spin.setValue(73)
    s2.save()
    w3 = MainWindow(Settings.load())
    assert w3.duration_group.checkedId() == CUSTOM_ID
    assert w3.selected_minutes() == 73


def test_window_geometry_is_saved_and_restored(qapp):
    s, w = make_window(qapp)
    w.resize(760, 600)
    w.save_geometry()
    assert s.window_geometry
    w2 = MainWindow(s)
    assert (w2.width(), w2.height()) == (760, 600)


def _controller(qapp):
    from focus_app.app import FocusApp

    return FocusApp(qapp, show_window=False)


def _close(ctl):
    ctl.tray.hide()
    ctl.window.allow_close = True
    ctl.window.close()


def test_dialogs_are_released_after_use(qapp):
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QDialog

    s, w = make_window(qapp)
    orig = AppPickerDialog.exec
    AppPickerDialog.exec = lambda self: (QTimer.singleShot(0, self.reject), orig(self))[1]
    try:
        for _ in range(5):
            w._add_apps()
    finally:
        AppPickerDialog.exec = orig
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert w.findChildren(QDialog) == []


def test_session_expiring_during_unlock_prompt_ends_once(qapp, monkeypatch):
    ctl = _controller(qapp)
    try:
        ctl.start_focus(ctl.settings.active_profile, 30)
        ended = []
        orig_end = ctl._end_session
        monkeypatch.setattr(ctl, "_end_session", lambda reason: (ended.append(reason), orig_end(reason)))

        def confirm(purpose):  # 문자열을 입력하는 사이 시간이 다 됨
            ctl.session.ends_at = time.time() - 1
            ctl._refresh_status()
            return True

        monkeypatch.setattr(ctl, "_confirm", confirm)
        ctl.stop_focus()
        assert ended == ["expired"]
        assert not ctl.active
    finally:
        _close(ctl)


def test_session_save_failure_does_not_break_blocking(qapp, monkeypatch):
    ctl = _controller(qapp)
    try:
        def boom(self, path=None):
            raise PermissionError("locked by sync")

        monkeypatch.setattr(FocusSession, "save", boom)
        ctl.start_focus(ctl.settings.active_profile, 30)
        assert ctl.active and ctl.monitor is not None
        assert ctl.poll_timer.isActive()
        ctl.cancel_emergency()  # 저장 실패해도 예외가 새지 않음
    finally:
        ctl._end_session("manual")
        _close(ctl)


def test_unhandled_exceptions_are_logged(caplog):
    import logging
    import sys
    import threading

    from focus_app.main import _install_exception_hooks

    old_sys, old_thread = sys.excepthook, threading.excepthook
    try:
        _install_exception_hooks()
        with caplog.at_level(logging.CRITICAL, logger="focus_app.crash"):
            try:
                raise ValueError("슬롯 오류")
            except ValueError:
                sys.excepthook(*sys.exc_info())
            t = threading.Thread(target=lambda: 1 / 0, name="worker")
            t.start()
            t.join()
        text = caplog.text
        assert "슬롯 오류" in text and "worker" in text and "ZeroDivisionError" in text
    finally:
        sys.excepthook, threading.excepthook = old_sys, old_thread

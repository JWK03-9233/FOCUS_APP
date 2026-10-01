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


def test_edit_apps_during_focus_requires_code_and_keeps_session(qapp, monkeypatch):
    from focus_app.ui import allowed_apps_dialog

    ctl = _controller(qapp)
    try:
        name = ctl.settings.active_profile
        ctl.start_focus(name, 30)
        session = ctl.session

        monkeypatch.setattr(ctl, "_confirm", lambda purpose: False)  # 문자열을 틀리거나 취소
        ctl.edit_apps_during_focus()
        assert "obsidian.exe" not in ctl.settings.get_profile(name).normalized_apps()

        def fake_exec(self):
            self.add_entries([AppEntry("obsidian.exe", "Obsidian", "")])
            self.remove_app("notepad.exe")
            return 1  # Accepted

        monkeypatch.setattr(ctl, "_confirm", lambda purpose: True)
        monkeypatch.setattr(allowed_apps_dialog.AllowedAppsDialog, "exec", fake_exec)
        ctl.edit_apps_during_focus()

        apps = ctl.settings.get_profile(name).normalized_apps()
        assert "obsidian.exe" in apps and "notepad.exe" not in apps
        assert ctl.monitor.profile.allows("obsidian.exe")  # 감시에 즉시 반영
        assert not ctl.monitor.profile.allows("notepad.exe")
        assert ctl.session is session and ctl.active  # 집중은 그대로
        assert "obsidian.exe" in Settings.load().get_profile(name).normalized_apps()  # 저장됨
    finally:
        ctl._end_session("manual")
        _close(ctl)


def test_allowed_apps_dialog_cancel_changes_nothing(qapp):
    from focus_app.ui.allowed_apps_dialog import AllowedAppsDialog

    s = Settings()
    p = s.current_profile()
    before = p.normalized_apps()
    dlg = AllowedAppsDialog(s, p)
    dlg.remove_app(before[0])
    dlg.add_entries([AppEntry("x.exe", "X", "")])
    dlg.reject()
    assert p.normalized_apps() == before  # 저장 전까지 원본은 그대로


def test_update_dialog_states(qapp):
    from focus_app.updater import ReleaseInfo
    from focus_app.ui.update_dialog import UpdateDialog

    newer = ReleaseInfo("99.0.0", "v99.0.0", "- 좋아짐", "https://x", "a-win64.zip", "u", 1, "")
    dlg = UpdateDialog(info=newer)
    assert "99.0.0" in dlg.title.text() and not dlg.notes.isHidden()
    assert dlg.install_btn.isHidden()  # 테스트는 소스 실행이라 자동 설치 버튼 대신 안내
    assert "소스 코드" in dlg.status.text()

    same = ReleaseInfo("0.0.1", "v0.0.1", "", "https://x")
    dlg2 = UpdateDialog(info=same)
    assert "최신" in dlg2.title.text()


def test_update_dialog_background_check_reports_errors(qapp):
    from focus_app.updater import UpdateError
    from focus_app.ui.update_dialog import UpdateDialog

    def fail(token):
        raise UpdateError("연결 안 됨")

    dlg = UpdateDialog(fetch=fail)
    deadline = time.time() + 5
    while "연결 안 됨" not in dlg.status.text() and time.time() < deadline:
        qapp.processEvents()
    assert "연결 안 됨" in dlg.status.text()
    assert not dlg.retry_btn.isHidden()


def test_update_button_highlights_new_version(qapp):
    s, w = make_window(qapp)
    w.set_update_available("9.9.9")
    assert "9.9.9" in w.update_btn.text()
    w.set_update_available(None)
    assert w.update_btn.text() == "업데이트 확인"


def test_picker_checkbox_square_and_row_both_toggle_once(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    dlg = AppPickerDialog("공부용", [], running=[AppEntry("chrome.exe", "Chrome", "", True)])
    dlg.show()
    lst = dlg.list
    item = next(lst.item(i) for i in range(lst.count()) if lst.item(i).data(Qt.ItemDataRole.UserRole) == "chrome.exe")
    rect = lst.visualItemRect(item)
    opt = QStyleOptionViewItem()
    opt.initFrom(lst)
    opt.rect = rect
    opt.features |= QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    box = lst.style().subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, opt, lst)

    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=box.center())  # 체크박스 칸
    assert item.checkState() == Qt.CheckState.Checked
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.center().x() + 80, rect.center().y()))
    assert item.checkState() == Qt.CheckState.Unchecked  # 이름 부분
    assert lst.focusPolicy() == Qt.FocusPolicy.NoFocus  # 포커스 테두리로 목록이 출렁이지 않게


def test_installed_app_filters(tmp_path):
    import sys as _sys

    from focus_app.ui import app_catalog as cat

    # 실행 파일이 없거나, 설치·제거 도구거나, 설치 캐시 폴더에 있는 것은 제외
    assert cat._usable_exe(str(tmp_path / "missing.exe")) is None
    for name in ("unins000.exe", "Setup.exe", "fooUpdater.exe"):
        (tmp_path / name).write_bytes(b"MZ")
        assert cat._usable_exe(str(tmp_path / name)) is None
    cache = tmp_path / "Package Cache"
    cache.mkdir()
    (cache / "app.exe").write_bytes(b"MZ")
    assert cat._usable_exe(str(cache / "app.exe")) is None
    (tmp_path / "Real.exe").write_bytes(b"MZ")
    assert cat._usable_exe(f'"{tmp_path / "Real.exe"}",0') == str(tmp_path / "Real.exe")  # DisplayIcon 형식
    if _sys.platform.startswith("win"):
        assert cat.is_gui_exe(r"C:\Windows\notepad.exe")
        assert not cat.is_gui_exe(r"C:\Windows\System32\cmd.exe")  # 명령줄 도구
    assert not cat.is_gui_exe(str(tmp_path / "Real.exe"))  # PE가 아님


def _rows(dlg):
    out = []
    for i in range(dlg.list.count()):
        it = dlg.list.item(i)
        out.append((it.data(Qt.ItemDataRole.UserRole + 1) or it.data(Qt.ItemDataRole.UserRole), it.isHidden()))
    return out


def _item(dlg, exe):
    return next(dlg.list.item(i) for i in range(dlg.list.count()) if dlg.list.item(i).data(Qt.ItemDataRole.UserRole) == exe)


def test_hide_apps_moves_them_to_bottom_and_remembers(qapp):
    saved = []
    running = [AppEntry("chrome.exe", "Chrome", "", True), AppEntry("code.exe", "VS Code", "", True)]
    dlg = AppPickerDialog("공부용", [], running=running, on_hidden_changed=saved.append)
    _item(dlg, "chrome.exe").setCheckState(Qt.CheckState.Checked)
    _item(dlg, "hwp.exe").setCheckState(Qt.CheckState.Checked)  # 설치된 앱도 숨길 수 있음
    assert dlg.hide_btn.isEnabled()
    dlg.hide_checked()

    assert saved[-1] == ["chrome.exe", "hwp.exe"]  # 바로 저장
    rows = _rows(dlg)
    keys = [k for k, _ in rows]
    assert keys[-3:] == ["hidden", "chrome.exe", "hwp.exe"]  # 맨 아래 '숨긴 앱' 구역
    assert dict(rows)["chrome.exe"] is True  # 기본은 접혀 있어 안 보임
    assert _item(dlg, "chrome.exe").checkState() == Qt.CheckState.Unchecked  # 숨기면서 체크 해제
    assert dlg.selected_exes() == []

    # 다음에 열어도 숨김 유지
    dlg2 = AppPickerDialog("공부용", [], running=running, hidden=saved[-1])
    assert [k for k, _ in _rows(dlg2)][-3:] == ["hidden", "chrome.exe", "hwp.exe"]
    assert "숨긴 앱 (2)" in _item_header(dlg2).text()


def _item_header(dlg):
    return next(dlg.list.item(i) for i in range(dlg.list.count()) if dlg.list.item(i).data(Qt.ItemDataRole.UserRole + 1) == "hidden")


def test_hidden_section_expand_search_and_unhide(qapp):
    saved = []
    running = [AppEntry("chrome.exe", "Chrome", "", True)]
    dlg = AppPickerDialog("공부용", [], running=running, hidden=["chrome.exe"], on_hidden_changed=saved.append)
    assert _item(dlg, "chrome.exe").isHidden()
    dlg._on_item_clicked(_item_header(dlg))  # 머리글을 눌러 펼침
    assert not _item(dlg, "chrome.exe").isHidden()
    dlg._on_item_clicked(_item_header(dlg))  # 다시 접음
    assert _item(dlg, "chrome.exe").isHidden()

    dlg.search.setText("chrome")  # 검색하면 숨긴 앱에서도 찾아 줌
    assert not _item(dlg, "chrome.exe").isHidden()
    dlg.search.setText("")

    _item(dlg, "chrome.exe").setCheckState(Qt.CheckState.Checked)
    assert not dlg.unhide_btn.isHidden()
    assert dlg.selected_exes() == ["chrome.exe"]  # 숨긴 앱도 체크하면 추가할 수 있음
    dlg.unhide_checked()
    assert saved[-1] == []
    keys = [k for k, _ in _rows(dlg)]
    assert "hidden" not in keys and keys.index("chrome.exe") < keys.index("installed")  # 원래 자리로


def test_hidden_apps_saved_in_settings(qapp):
    s = Settings()
    s.hidden_apps = ["Chrome.EXE", "chrome.exe", "", "C:/x/Game.exe"]
    s.save()
    assert Settings.load().hidden_apps == ["chrome.exe", "game.exe"]
    assert Settings.from_dict({"hidden_apps": "junk"}).hidden_apps == []

    s2, w = make_window(qapp)
    w._save_hidden_apps(["zoom.exe"])
    assert s2.hidden_apps == ["zoom.exe"]

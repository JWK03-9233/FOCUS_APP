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
    assert not hasattr(w, "emergency_btn")  # 비상 해제를 새로 요청하는 버튼은 없음


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
        _close(ctl)


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
    # 타이머를 멈춰 두지 않으면 테스트가 끝난 뒤에도 남은 컨트롤러가 계속 돌며 다음 테스트를 방해함
    ctl.poll_timer.stop()
    ctl.status_timer.stop()
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

        lengths = []
        monkeypatch.setattr(ctl, "_confirm", lambda purpose, length=None: lengths.append(length) or False)  # 틀리거나 취소
        ctl.edit_apps_during_focus()
        assert lengths == [16]  # 편집용은 짧은 문자열
        assert "obsidian.exe" not in ctl.settings.get_profile(name).normalized_apps()

        def fake_exec(self):
            self.add_entries([AppEntry("obsidian.exe", "Obsidian", "")])
            self.remove_app("notepad.exe")
            return 1  # Accepted

        monkeypatch.setattr(ctl, "_confirm", lambda purpose, length=None: True)
        monkeypatch.setattr(allowed_apps_dialog.AllowedAppsDialog, "exec", fake_exec)
        ctl.edit_apps_during_focus()

        apps = ctl.settings.get_profile(name).normalized_apps()
        assert "obsidian.exe" in apps and "notepad.exe" not in apps
        assert ctl.monitor.profile.allows("obsidian.exe")  # 감시에 즉시 반영
        assert not ctl.monitor.profile.allows("notepad.exe")
        assert ctl.session is session and ctl.active  # 집중은 그대로
        assert "obsidian.exe" in Settings.load().get_profile(name).normalized_apps()  # 저장됨
        ctl._end_session("manual")
        assert "obsidian.exe" in ctl.settings.get_profile(name).normalized_apps()  # 집중이 끝나도 모드에 남음
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


def _keys(dlg):
    out = []
    for i in range(dlg.list.count()):
        it = dlg.list.item(i)
        out.append(it.data(Qt.ItemDataRole.UserRole + 1) or it.data(Qt.ItemDataRole.UserRole))
    return out


def _item(dlg, exe):
    return next(dlg.list.item(i) for i in range(dlg.list.count()) if dlg.list.item(i).data(Qt.ItemDataRole.UserRole) == exe)


def _click_star(dlg, exe):
    from PySide6.QtTest import QTest

    from focus_app.ui.app_picker import star_rect

    item = _item(dlg, exe)
    dlg.list.scrollToItem(item)
    pos = star_rect(dlg.list.visualItemRect(item)).center()
    QTest.mouseClick(dlg.list.viewport(), Qt.MouseButton.LeftButton, pos=pos)


def test_star_click_moves_app_to_favorites_and_keeps_check(qapp):
    saved = []
    running = [AppEntry("chrome.exe", "Chrome", "", True), AppEntry("code.exe", "VS Code", "", True)]
    dlg = AppPickerDialog("공부용", [], running=running, on_favorites_changed=saved.append)
    dlg.show()
    _item(dlg, "code.exe").setCheckState(Qt.CheckState.Checked)
    _click_star(dlg, "hwp.exe")  # 설치된 앱의 별
    _click_star(dlg, "code.exe")  # 실행 중인 앱의 별

    assert saved[-1] == ["hwp.exe", "code.exe"]  # 바로 저장
    keys = _keys(dlg)
    assert keys[0] == "favorites" and set(keys[1:3]) == {"hwp.exe", "code.exe"}
    assert keys.count("code.exe") == 1  # 원래 구역에서는 빠짐
    assert _item(dlg, "code.exe").checkState() == Qt.CheckState.Checked  # 별을 눌러도 체크는 그대로
    assert _item(dlg, "hwp.exe").checkState() == Qt.CheckState.Unchecked
    assert dlg.selected_exes() == ["code.exe"]

    # 다음에 열어도 맨 위
    dlg2 = AppPickerDialog("공부용", [], running=running, favorites=saved[-1])
    assert _keys(dlg2)[0] == "favorites" and set(_keys(dlg2)[1:3]) == {"code.exe", "hwp.exe"}
    assert "즐겨찾기 (2)" in dlg2.list.item(0).text()


def test_star_works_on_already_added_and_unknown_apps(qapp):
    saved = []
    running = [AppEntry("chrome.exe", "Chrome", "", True)]
    dlg = AppPickerDialog("공부용", ["chrome.exe"], running=running, favorites=["portable.exe"],
                          on_favorites_changed=saved.append, app_names=lambda exe: "내 휴대용 앱")
    dlg.show()
    # 실행 중도 설치 목록에도 없는 즐겨찾기도 이름과 함께 보이고, 바로 체크해 추가할 수 있음
    assert "내 휴대용 앱" in _item(dlg, "portable.exe").text()
    _item(dlg, "portable.exe").setCheckState(Qt.CheckState.Checked)
    assert dlg.selected_exes() == ["portable.exe"]
    # 이미 추가된(비활성) 앱도 별로 즐겨찾기 가능
    _click_star(dlg, "chrome.exe")
    assert saved[-1] == ["portable.exe", "chrome.exe"]
    assert _item(dlg, "chrome.exe").checkState() == Qt.CheckState.Checked
    # 다시 누르면 해제
    _click_star(dlg, "portable.exe")
    assert saved[-1] == ["chrome.exe"]
    assert "portable.exe" not in _keys(dlg)  # 어디에도 없는 앱은 즐겨찾기에서 빼면 목록에서 사라짐
    dlg.search.setText("chrome")
    assert not _item(dlg, "chrome.exe").isHidden()


def test_favorite_apps_saved_in_settings(qapp):
    s = Settings()
    s.favorite_apps = ["Chrome.EXE", "chrome.exe", "", "C:/x/Game.exe"]
    s.save()
    assert Settings.load().favorite_apps == ["chrome.exe", "game.exe"]
    assert Settings.from_dict({"favorite_apps": "junk"}).favorite_apps == []

    s2, w = make_window(qapp)
    w._save_favorite_apps(["zoom.exe"])
    assert s2.favorite_apps == ["zoom.exe"]


def _click_hide(dlg, exe):
    from PySide6.QtTest import QTest

    from focus_app.ui.app_picker import hide_rect

    item = _item(dlg, exe)
    dlg.list.scrollToItem(item)
    QTest.mouseClick(dlg.list.viewport(), Qt.MouseButton.LeftButton, pos=hide_rect(dlg.list.visualItemRect(item)).center())


def _header(dlg, key):
    return next(dlg.list.item(i) for i in range(dlg.list.count()) if dlg.list.item(i).data(Qt.ItemDataRole.UserRole + 1) == key)


def test_hide_and_favorite_together(qapp):
    favs, hid = [], []
    running = [AppEntry("chrome.exe", "Chrome", "", True), AppEntry("code.exe", "VS Code", "", True)]
    dlg = AppPickerDialog("공부용", [], running=running, on_favorites_changed=favs.append, on_hidden_changed=hid.append)
    dlg.show()
    _item(dlg, "chrome.exe").setCheckState(Qt.CheckState.Checked)
    _click_hide(dlg, "chrome.exe")  # 숨기기
    assert hid[-1] == ["chrome.exe"]
    keys = _keys(dlg)
    assert keys[-2:] == ["hidden", "chrome.exe"]  # 맨 아래 숨긴 앱 구역
    assert _item(dlg, "chrome.exe").isHidden()  # 기본은 접힘
    assert _item(dlg, "chrome.exe").checkState() == Qt.CheckState.Checked  # 숨겨도 체크는 그대로
    dlg._on_item_clicked(_header(dlg, "hidden"))  # 펼침
    assert not _item(dlg, "chrome.exe").isHidden()

    _click_star(dlg, "code.exe")  # 즐겨찾기
    assert _keys(dlg)[:2] == ["favorites", "code.exe"]
    _click_hide(dlg, "code.exe")  # 즐겨찾기를 숨기면 즐겨찾기에서 빠짐
    assert favs[-1] == [] and hid[-1] == ["chrome.exe", "code.exe"]
    _click_star(dlg, "chrome.exe")  # 숨긴 앱을 즐겨찾기하면 숨김에서 나옴
    assert favs[-1] == ["chrome.exe"] and hid[-1] == ["code.exe"]
    _click_hide(dlg, "code.exe")  # 숨김 해제
    assert hid[-1] == [] and "hidden" not in _keys(dlg)

    dlg2 = AppPickerDialog("공부용", [], running=running, favorites=["chrome.exe"], hidden=["code.exe"])
    keys = _keys(dlg2)
    assert keys[:2] == ["favorites", "chrome.exe"] and keys[-2:] == ["hidden", "code.exe"]  # 다음에 열어도 유지


def test_unusable_installed_entries_are_listed_but_not_selectable(qapp):
    from focus_app.ui.app_catalog import unusable_key

    hid = []
    key = unusable_key("Python 3.13.7 (64-bit)")
    app_catalog.installed_apps.set([AppEntry("hwp.exe", "한글", ""), AppEntry(key, "Python 3.13.7 (64-bit)", usable=False)])
    dlg = AppPickerDialog("공부용", [], running=[], on_hidden_changed=hid.append)
    dlg.show()
    item = _item(dlg, key)
    assert "실행 파일 없음" in item.text()
    assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)
    dlg._on_item_clicked(item)
    assert dlg.selected_exes() == []
    _click_star(dlg, key)  # 별은 없음 (실행 파일이 없으니 즐겨찾기 의미 없음)
    assert "favorites" not in _keys(dlg)
    _click_hide(dlg, key)  # 숨기기는 가능
    assert hid[-1] == [key]


def test_hidden_and_favorites_saved_in_settings(qapp):
    s = Settings()
    s.favorite_apps = ["a.exe"]
    s.hidden_apps = ["B.EXE", "a.exe", "?python 3"]
    s.save()
    loaded = Settings.load()
    assert loaded.favorite_apps == ["a.exe"]
    assert loaded.hidden_apps == ["b.exe", "?python 3"]  # 즐겨찾기와 겹치면 즐겨찾기 우선
    s2, w = make_window(qapp)
    w._save_hidden_apps(["zoom.exe"])
    assert s2.hidden_apps == ["zoom.exe"]


def test_best_exe_in_install_folder_and_store_logo(tmp_path):
    from pathlib import Path
    import shutil
    import sys as _sys

    from focus_app.ui import app_catalog as cat

    if not _sys.platform.startswith("win"):
        return
    gui = r"C:\Windows\notepad.exe"
    app = tmp_path / "Millie"
    (app / "bin").mkdir(parents=True)
    shutil.copy(gui, app / "bin" / "millie-desktop.exe")  # 한 단계 아래 폴더
    shutil.copy(gui, app / "bin" / "other.exe")
    shutil.copy(gui, app / "bin" / "unins000.exe")  # 제거 프로그램은 후보에서 제외
    assert Path(cat._best_exe_in(str(app), "Millie Desktop")).name == "millie-desktop.exe"

    assets = tmp_path / "pkg" / "Assets"
    assets.mkdir(parents=True)
    for n in ("Logo.scale-100.png", "Logo.targetsize-48.png", "Logo.targetsize-48_contrast-black.png"):
        (assets / n).write_bytes(b"png")
    assert Path(cat._store_logo(str(tmp_path / "pkg"), r"Assets\Logo.png")).name == "Logo.targetsize-48.png"


def test_end_popup_on_expiry_brings_only_focusapp_to_front(qapp, monkeypatch):
    from focus_app import winapi
    from focus_app.ui.end_dialog import FocusEndDialog

    from focus_app.monitor import AllowlistMonitor

    fronted = []
    monkeypatch.setattr(winapi, "bring_to_front", lambda hwnd: fronted.append(hwnd) or True)
    # 기다리는 동안 실제 감시가 돌면 지금 앞에 있는 진짜 창(편집기 등)을 막아 횟수가 바뀌고 그 창이 최소화됨
    monkeypatch.setattr(AllowlistMonitor, "poll", lambda self: None)
    ctl = _controller(qapp)
    try:
        ctl.start_focus(ctl.settings.active_profile, 30)
        ctl.monitor.block_count = 3
        ctl.session.started_at -= 30 * 60  # 30분 지난 것으로
        ctl.session.ends_at = time.time() - 1
        QTest_wait(qapp, 300)  # 앞선 테스트가 예약해 둔 동작이 끝나기를 기다린 뒤 기록 시작
        fronted.clear()
        ctl._refresh_status()  # 타이머가 끝난 것을 감지

        popup = ctl._end_popup
        assert isinstance(popup, FocusEndDialog) and popup.isVisible()
        assert "끝났어요" in popup.title.text()
        assert "30분" in popup.summary.text() and "3번" in popup.summary.text()
        assert popup.windowFlags() & Qt.WindowType.WindowStaysOnTopHint  # 닫을 때까지 위에 떠 있음
        assert ctl.window.isVisible()
        qapp.processEvents()
        QTest_wait(qapp, 250)
        # 앞으로 가져오는 것은 FocusApp 창과 알림 창뿐 (최소화된 다른 앱은 건드리지 않음)
        assert set(fronted) <= {int(ctl.window.winId()), int(popup.winId())} and fronted
        popup.ok_btn.click()  # 닫으면 스스로 정리됨
        from PySide6.QtCore import QCoreApplication, QEvent

        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()
        assert ctl._end_popup is None
        ctl._bring_end_popup_to_front()  # 닫힌 뒤에 불려도 오류 없음
    finally:
        _close(ctl)


def test_no_end_popup_when_user_ends_focus(qapp, monkeypatch):
    ctl = _controller(qapp)
    try:
        ctl.start_focus(ctl.settings.active_profile, 30)
        monkeypatch.setattr(ctl, "_confirm", lambda purpose: True)
        ctl.stop_focus()
        assert ctl._end_popup is None
    finally:
        _close(ctl)


def test_end_popup_emergency_text(qapp):
    from focus_app.ui.end_dialog import FocusEndDialog

    dlg = FocusEndDialog("emergency", "공부용", 600, 0)
    assert "비상 해제" in dlg.title.text()
    assert "10분" in dlg.summary.text() and "새지 않았어요" in dlg.summary.text()
    assert dlg.restart_btn is None  # 열린 브라우저가 없으면 다시 시작 버튼 없음


def test_end_popup_restart_browsers_button(qapp):
    from focus_app.ui.end_dialog import FocusEndDialog

    dlg = FocusEndDialog("expired", "공부용", 600, 0, ["Chrome"])
    fired = []
    dlg.restart_browsers_requested.connect(lambda: fired.append(True))
    assert dlg.restart_btn is not None
    dlg.restart_btn.click()
    assert fired == [True]
    assert dlg.result() == dlg.DialogCode.Accepted  # 확인 창을 가리지 않게 먼저 닫힘


def QTest_wait(qapp, ms):
    from PySide6.QtTest import QTest

    QTest.qWait(ms)


def test_launch_target_prefers_shortcut_or_store_id(tmp_path, monkeypatch):
    exe = tmp_path / "Sumatra.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(app_catalog, "running_apps", lambda: [])
    app_catalog.installed_apps.set(
        [
            AppEntry("claude.exe", "Claude", "logo.png", launch=r"shell:AppsFolder\Claude_x!App"),
            AppEntry("sumatra.exe", "SumatraPDF", str(exe)),
        ]
    )
    assert app_catalog.launch_target("Claude.exe") == r"shell:AppsFolder\Claude_x!App"
    assert app_catalog.launch_target("sumatra.exe") == str(exe)  # 바로가기가 없으면 실행 파일
    assert app_catalog.launch_target("other.exe", str(exe)) == str(exe)  # 목록에 없으면 알고 있는 경로
    assert app_catalog.launch_target("other.exe") == ""


def test_clicking_allowed_app_on_running_page_requests_launch(qapp):
    s, w = make_window(qapp)
    p = s.current_profile()
    p.block_everything = True
    p.allowed_apps = ["hwp.exe", "notepad.exe"]
    w.show_running(FocusSession.start(p.name, 30), p)
    asked = []
    w.launch_app_requested.connect(asked.append)
    w.run_apps.itemClicked.emit(w.run_apps.item(1))
    assert asked == ["notepad.exe"]


def test_escape_hides_main_window_to_tray(qapp):
    from PySide6.QtTest import QTest

    s, w = make_window(qapp)
    hidden = []
    w.on_hidden_to_tray = lambda: hidden.append(1)
    w.show()
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert not w.isVisible() and hidden


def test_tray_menu_lists_allowed_apps_and_launches(qapp, monkeypatch):
    launched = []
    monkeypatch.setattr(app_catalog, "launch_app", lambda exe, path="": launched.append(exe) or True)
    ctl = _controller(qapp)
    try:
        p = ctl.settings.current_profile()
        p.block_everything = True
        p.allowed_apps = ["hwp.exe", "notepad.exe"]
        ctl._refresh_app_actions()
        assert ctl._app_actions == []  # 대기 중에는 앱 목록 없음
        ctl.start_focus(p.name, 30)
        ctl._refresh_app_actions()
        labels = [a.text().strip() for a in ctl._app_actions]
        assert labels[0] == "지금 쓸 수 있는 앱" and "한글" in labels and len(labels) == 3
        assert all(a in ctl.menu.actions() for a in ctl._app_actions)
        ctl._app_actions[2].trigger()
        assert launched == ["notepad.exe"]
        ctl.launch_app("chrome.exe")  # 허용되지 않은 앱은 열지 않음
        assert launched == ["notepad.exe"]
        ctl._refresh_app_actions()  # 다시 채워도 중복되지 않음
        assert len(ctl._app_actions) == 3
        assert not hasattr(ctl, "emergency_action")
    finally:
        ctl._end_session("manual")
        _close(ctl)


def test_hand_cursor_only_over_allowed_app_items(qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    s, w = make_window(qapp)
    p = s.current_profile()
    p.block_everything = True
    p.allowed_apps = ["hwp.exe"]
    w.resize(900, 700)
    w.show()
    w.show_running(FocusSession.start(p.name, 30), p)
    qapp.processEvents()
    vp = w.run_apps.viewport()
    rect = w.run_apps.visualItemRect(w.run_apps.item(0))
    QTest.mouseMove(vp, rect.center())
    assert vp.cursor().shape() == Qt.CursorShape.PointingHandCursor
    QTest.mouseMove(vp, QPoint(vp.width() - 5, vp.height() - 5))  # 앱이 없는 빈 곳
    assert vp.cursor().shape() == Qt.CursorShape.ArrowCursor
    w.hide()


def test_tray_notifications_only_when_an_app_is_blocked(qapp, monkeypatch):
    from focus_app.enforcer import ForegroundWindow

    ctl = _controller(qapp)
    shown = []
    monkeypatch.setattr(ctl.tray, "showMessage", lambda *a, **k: shown.append(a[1]))
    try:
        ctl.window.show()
        ctl.window.close()  # 트레이로 숨김 -> 안내 없음
        ctl.start_focus(ctl.settings.active_profile, 30)  # 시작 안내 없음
        assert shown == []
        ctl._on_block(ForegroundWindow(hwnd=1, pid=1, exe_name="chrome.exe"))
        assert len(shown) == 1 and "최소화" in shown[0]
        ctl.session.ends_at = time.time() - 1
        ctl._refresh_status()  # 타이머 끝 -> 종료 창은 뜨지만 트레이 알림은 없음
        assert len(shown) == 1
    finally:
        if ctl._end_popup is not None:
            ctl._end_popup.close()
        _close(ctl)


def test_modes_can_be_reordered_by_drag(qapp):
    from PySide6.QtCore import QModelIndex

    s, w = make_window(qapp)
    saved = []
    w.settings_changed.connect(lambda: saved.append(1))
    names = [p.name for p in s.profiles]
    selected = w.current_mode().name
    assert w.mode_list.dragDropMode() == w.mode_list.DragDropMode.InternalMove
    # 마지막 모드를 맨 위로 끌어 놓은 것과 같은 이동
    assert w.mode_list.model().moveRow(QModelIndex(), len(names) - 1, QModelIndex(), 0)
    qapp.processEvents()
    expected = [names[-1]] + names[:-1]
    assert [p.name for p in s.profiles] == expected and saved
    assert [w.mode_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.mode_list.count())] == expected
    assert all(w.mode_list.itemWidget(w.mode_list.item(i)) is not None for i in range(w.mode_list.count()))
    assert w.current_mode().name == selected  # 고른 모드는 그대로
    # 다시 불러와도 순서 유지
    from focus_app.config import Settings as S

    s2 = S()
    s2.profiles = list(s.profiles)
    s2.reorder_profiles(names)
    assert [p.name for p in s2.profiles] == names


def test_unlimited_session_hides_timer(qapp):
    s, w = make_window(qapp)
    p = s.current_profile()
    w.show_running(FocusSession.start(p.name, None), p)
    assert w.timer_label.isHidden() and w.timer_caption.isHidden() and w.progress.isHidden()
    assert "직접 끝낼 때까지" in w.run_info.text()
    w.show_running(FocusSession.start(p.name, 30), p)  # 시간을 정한 집중이면 다시 보임
    assert not w.timer_label.isHidden() and not w.progress.isHidden()


def test_launch_app_brings_existing_window_instead_of_opening_new(monkeypatch):
    from focus_app import winapi

    fronted, started = [], []
    monkeypatch.setattr(winapi, "bring_to_front", lambda hwnd: fronted.append(hwnd) or True)
    monkeypatch.setattr(app_catalog, "launch_target", lambda exe, path="": "C:\apps\notepad.exe")
    monkeypatch.setattr(app_catalog.os, "startfile", lambda *a, **k: started.append(a[0]), raising=False)
    monkeypatch.setattr(app_catalog.sys, "platform", "win32")

    # 창이 있으면 (뒤에 있거나 최소화) 그 창을 앞으로, 새로 열지 않음
    monkeypatch.setattr(winapi, "find_app_window", lambda exe, match=None: 77 if exe == "notepad.exe" else 0)
    assert app_catalog.launch_app("Notepad.exe")
    assert fronted == [77] and started == []

    # 창이 없으면 (꺼져 있거나 트레이에만 있음) 실행
    monkeypatch.setattr(winapi, "find_app_window", lambda exe, match=None: 0)
    assert app_catalog.launch_app("notepad.exe")
    assert fronted == [77] and started == ["C:\apps\notepad.exe"]


def test_open_apps_get_a_dot_and_tooltip(qapp):
    from focus_app.ui.main_window import OPEN_ROLE

    s, w = make_window(qapp)
    p = s.current_profile()
    p.block_everything = True
    p.allowed_apps = ["hwp.exe", "notepad.exe"]
    w.show_running(FocusSession.start(p.name, 30), p)
    items = {w.run_apps.item(i).data(Qt.ItemDataRole.UserRole): w.run_apps.item(i) for i in range(2)}
    assert not any(it.data(OPEN_ROLE) for it in items.values())

    w.set_open_apps({"notepad.exe", "explorer.exe"})
    assert items["notepad.exe"].data(OPEN_ROLE) and not items["hwp.exe"].data(OPEN_ROLE)
    assert "실행 중" in items["notepad.exe"].toolTip() and "열기" in items["hwp.exe"].toolTip()

    w.set_open_apps(set())  # 앱을 닫으면 점이 사라짐
    assert not items["notepad.exe"].data(OPEN_ROLE)

    # 모드를 다시 그려도 (허용 앱 편집 등) 실행 중 표시는 유지
    w.set_open_apps({"hwp.exe"})
    w.show_running(FocusSession.start(p.name, 30), p)
    hwp = next(w.run_apps.item(i) for i in range(2) if w.run_apps.item(i).data(Qt.ItemDataRole.UserRole) == "hwp.exe")
    assert hwp.data(OPEN_ROLE)
    w.grab()  # 점 그리기에서 오류가 나지 않는지


def test_running_page_shows_every_allowed_app_without_scrolling(qapp):
    s, w = make_window(qapp)
    p = s.current_profile()
    p.block_everything = True
    p.allowed_apps = [f"app{i}.exe" for i in range(14)]
    w.resize(700, 900)
    w.show()
    w.show_running(FocusSession.start(p.name, 30), p)
    qapp.processEvents()
    vp = w.run_apps.viewport()
    rects = [w.run_apps.visualItemRect(w.run_apps.item(i)) for i in range(w.run_apps.count())]
    assert len({r.top() for r in rects}) > 1  # 여러 줄로 감김
    assert all(vp.rect().contains(r) for r in rects)  # 잘리거나 스크롤해야 보이는 앱 없음
    w.hide()


def test_setup_warns_when_site_mode_has_no_helper(qapp):
    s, w = make_window(qapp)
    p = w.current_mode()
    p.block_everything = True
    p.allowed_apps = ["chrome.exe"]
    p.restrict_sites = True
    p.allowed_sites = ["notion.so"]
    w._show_mode()
    assert w.helper_banner.isHidden()  # 설치 여부를 아직 모르면 띄우지 않음
    w.set_helper_installed(False)
    assert not w.helper_banner.isHidden()
    p.restrict_sites = False
    w._update_start_summary()
    assert w.helper_banner.isHidden()  # 사이트 제한을 안 쓰는 모드면 필요 없음
    p.restrict_sites = True
    w.set_helper_installed(True)
    assert w.helper_banner.isHidden()


def test_short_window_scrolls_instead_of_overlapping(qapp):
    """창이 내용보다 낮으면 목록을 겹치게 줄이지 않고 창 전체를 스크롤."""
    s, w = make_window(qapp)
    p = s.current_profile()
    p.block_everything = True
    p.allowed_apps = [f"app{i}.exe" for i in range(30)]
    p.allowed_sites = ["notion.so"]
    p.restrict_sites = True
    w.show()
    w.show_running(FocusSession.start(p.name, 30), p)
    w.setMinimumSize(0, 0)
    w.resize(700, 300)
    qapp.processEvents()
    apps_bottom = w.run_apps.mapTo(w.running_page, w.run_apps.rect().bottomLeft()).y()
    sites_top = w.run_sites_title.mapTo(w.running_page, w.run_sites_title.rect().topLeft()).y()
    assert sites_top > apps_bottom  # 사이트 제목이 앱 목록 위에 겹치지 않음
    assert w.centralWidget().verticalScrollBar().maximum() > 0  # 대신 창이 스크롤됨
    w.hide()


def test_windows_never_scroll_sideways_and_wrap_text(qapp):
    """창 전체는 가로로 스크롤하지 않고, 긴 글자는 줄을 바꿔 맞춤."""
    from PySide6.QtWidgets import QLabel

    s, w = make_window(qapp)
    w.show()
    w.setMinimumSize(300, 300)  # 코드에서 정한 최소 크기가 내용보다 작아도
    w.resize(300, 400)
    qapp.processEvents()
    w.resize(300, 400)
    qapp.processEvents()
    scroll = w.centralWidget()
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.widget().width() <= scroll.viewport().width()  # 내용이 창 밖으로 잘리지 않음
    assert all(label.wordWrap() for label in scroll.widget().findChildren(QLabel))
    w.hide()


def test_app_list_is_fully_expanded_and_rows_not_clipped(qapp):
    """모드의 앱 목록은 안쪽 스크롤 없이 모두 펼치고, 줄 높이는 줄 위젯이 필요한 만큼 (글자 아래가 잘리지 않음)."""
    s, w = make_window(qapp)
    p = w.current_mode()
    p.block_everything = True
    p.allowed_apps = [f"app{i}.exe" for i in range(20)]
    w._show_mode()
    w.show()
    qapp.processEvents()
    lst = w.app_list
    assert lst.count() == 20
    assert lst.verticalScrollBar().maximum() == 0  # 안쪽 스크롤 없음
    last = lst.visualItemRect(lst.item(lst.count() - 1))
    assert lst.viewport().rect().contains(last)  # 마지막 줄까지 보임
    for i in range(lst.count()):
        row = lst.itemWidget(lst.item(i))
        assert lst.item(i).sizeHint().height() >= row.sizeHint().height()
    w.hide()


def test_app_row_labels_get_their_full_height(qapp):
    """줄 위젯이 칸 여백 때문에 눌려 글자 아래(g 꼬리 등)가 잘리지 않음."""
    from PySide6.QtWidgets import QLabel

    from focus_app.ui import theme

    qapp.setStyleSheet(theme.STYLESHEET)
    try:
        s, w = make_window(qapp)
        p = w.current_mode()
        p.block_everything = True
        p.allowed_apps = ["gemini.exe", "typora.exe"]
        w._show_mode()
        w.show()
        qapp.processEvents()
        row = w.app_list.itemWidget(w.app_list.item(0))
        for label in row.findChildren(QLabel)[1:]:  # 이름, 실행 파일 이름
            assert label.height() >= label.sizeHint().height()
        w.hide()
    finally:
        qapp.setStyleSheet("")


def test_running_page_height_follows_its_own_content(qapp):
    """설정 화면의 긴 앱 목록 때문에 진행 화면 밑에 빈칸·스크롤이 생기지 않음."""
    s, w = make_window(qapp)
    p = s.current_profile()
    p.block_everything = True
    p.allowed_apps = [f"app{i}.exe" for i in range(30)]  # 설정 화면은 아주 길어짐
    w._show_mode()
    w.show()
    w.resize(1000, 800)
    w.show_running(FocusSession.start(p.name, 30), p)
    qapp.processEvents()
    scroll = w.centralWidget()
    assert scroll.verticalScrollBar().maximum() == 0  # 진행 화면은 창에 다 들어감
    # 사이트 목록·안내 바로 밑에 끝내기 버튼 (카드가 창 높이만큼 늘어나지 않음)
    hint_bottom = w.stop_btn.mapTo(w.running_page, w.stop_btn.rect().bottomLeft()).y()
    assert hint_bottom < w.running_page.height() - 50
    w.show_setup()
    qapp.processEvents()
    assert scroll.verticalScrollBar().maximum() > 0  # 설정 화면은 길어서 창 전체 스크롤
    w.hide()


def test_session_extend():
    s = FocusSession.start("A", 30, now=1000.0)
    assert s.extend(10, now=1500.0) and s.ends_at == 1000.0 + 40 * 60
    assert s.extend(5, now=99999.0) and s.ends_at == 99999.0 + 300  # 이미 지났으면 지금부터
    assert not FocusSession.start("A", None).extend(10)


def test_add_time_during_focus_needs_no_code(qapp, monkeypatch):
    ctl = _controller(qapp)
    try:
        ctl.start_focus(ctl.settings.active_profile, 30)
        before = ctl.session.ends_at
        monkeypatch.setattr(ctl, "_confirm", lambda *a, **k: pytest.fail("시간 추가에는 해제 문자열이 필요 없음"))
        monkeypatch.setattr(ctl, "_ask_minutes", lambda title: 20)
        ctl.add_time_during_focus()
        assert ctl.session.ends_at == pytest.approx(before + 20 * 60)
        assert FocusSession.load().ends_at == pytest.approx(ctl.session.ends_at)  # 저장됨
    finally:
        ctl._end_session("manual")
        _close(ctl)


def test_change_mode_during_focus_code_only_when_moving_down(qapp, monkeypatch):
    """목록 아래쪽 모드(보통 더 많이 허용)로 바꿀 때만 해제 문자열을 요구하고, 위쪽으로는 바로 바꿈."""
    ctl = _controller(qapp)
    try:
        first, second = ctl.settings.profile_names()[:2]
        ctl.start_focus(first, 30)
        session, before = ctl.session, ctl.session.ends_at

        # 위 -> 아래: 문자열을 틀리면(취소하면) 바뀌지 않음
        lengths = []
        monkeypatch.setattr(ctl, "_ask_mode", lambda names: second)
        monkeypatch.setattr(ctl, "_confirm", lambda purpose, length=None: lengths.append(length) or False)
        ctl.change_mode_during_focus()
        assert lengths == [16] and ctl.session.profile == first

        # 위 -> 아래: 문자열을 맞히면 바뀌고 시간도 늘릴 수 있음
        monkeypatch.setattr(ctl, "_confirm", lambda purpose, length=None: True)
        asked = []
        monkeypatch.setattr(ctl, "_ask_yes", lambda title, text: asked.append(text) or True)
        monkeypatch.setattr(ctl, "_ask_minutes", lambda title: 15)
        ctl.change_mode_during_focus()
        assert asked and ctl.session is session and ctl.session.profile == second
        assert ctl.session.ends_at == pytest.approx(before + 15 * 60)
        assert ctl.monitor.profile.name == second
        assert FocusSession.load().profile == second  # 도우미도 새 모드를 따름

        # 아래 -> 위: 해제 문자열 없이 바로 바뀜
        monkeypatch.setattr(ctl, "_confirm", lambda *a, **k: pytest.fail("위쪽 모드로는 해제 문자열이 필요 없음"))
        monkeypatch.setattr(ctl, "_ask_mode", lambda names: first)
        monkeypatch.setattr(ctl, "_ask_yes", lambda title, text: False)  # 시간은 그대로
        monkeypatch.setattr(ctl, "_ask_minutes", lambda title: pytest.fail("묻지 않아야 함"))
        ends = ctl.session.ends_at
        ctl.change_mode_during_focus()
        assert ctl.session.profile == first and ctl.session.ends_at == ends
        assert FocusSession.load().profile == first
    finally:
        ctl._end_session("manual")
        _close(ctl)

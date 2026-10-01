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

    fronted = []
    monkeypatch.setattr(winapi, "bring_to_front", lambda hwnd: fronted.append(hwnd) or True)
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

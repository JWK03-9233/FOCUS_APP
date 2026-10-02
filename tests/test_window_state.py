"""모든 창 공통: 확대·축소와 창 위치·크기 기억."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QVBoxLayout

from focus_app.config import Settings
from focus_app.ui import theme
from focus_app.ui.window_state import WindowStateManager, next_zoom, tracked


class SampleDialog(QDialog):
    def __init__(self):
        super().__init__()
        QVBoxLayout(self).addWidget(QLabel("내용"))


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
    app.setStyleSheet(theme.STYLESHEET)  # 다른 테스트에 확대 상태가 남지 않게
    theme.set_zoom(100)


@pytest.fixture
def manager(qapp):
    settings = Settings()
    saves = []
    m = WindowStateManager(qapp, settings, lambda: saves.append(1))
    m.saves = saves
    yield m
    qapp.removeEventFilter(m)


def test_zoom_steps_and_limits():
    assert next_zoom(100, 1) == 110 and next_zoom(100, -1) == 90
    assert next_zoom(200, 1) == 200 and next_zoom(80, -1) == 80
    assert next_zoom(117, 1) == 125 and next_zoom(117, -1) == 110  # 단계 사이 값


def test_stylesheet_scales_text_and_spacing_but_not_hairlines():
    big = theme.build_stylesheet(150)
    assert theme.build_stylesheet(100) == theme.STYLESHEET
    assert "QWidget { font-size: 12.8pt; }" in big  # 기본 8.5pt
    assert "padding: 15px 39px" in big  # 시작 버튼 여백 (기본 10px 26px)
    assert "border: 1px solid" in big  # 1px 선은 그대로
    assert theme.ACCENT in big and "stop:1 #8b5cf6" in big  # 색·그라데이션은 건드리지 않음
    assert "font-size: 6.8pt" in theme.build_stylesheet(80)


def test_ctrl_keys_and_wheel_change_zoom_everywhere(qapp, manager):
    dlg = SampleDialog()
    dlg.show()
    QTest.keyClick(dlg, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    assert manager.settings.ui_zoom == 110
    assert "font-size: 9.4pt" in qapp.styleSheet()
    QTest.keyClick(dlg, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(dlg, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    assert manager.settings.ui_zoom == 90
    QTest.keyClick(dlg, Qt.Key.Key_0, Qt.KeyboardModifier.ControlModifier)
    assert manager.settings.ui_zoom == 100 and manager.saves
    QTest.keyClick(dlg, Qt.Key.Key_0)  # Ctrl 없이 누른 0은 그대로 통과
    assert manager.settings.ui_zoom == 100
    dlg.close()


def test_saved_zoom_is_applied_on_start(qapp):
    settings = Settings()
    settings.ui_zoom = 125
    m = WindowStateManager(qapp, settings, lambda: None)
    try:
        assert qapp.styleSheet() == theme.build_stylesheet(125)
    finally:
        qapp.removeEventFilter(m)


def test_dialog_reopens_with_last_size_and_position(qapp, manager):
    dlg = SampleDialog()
    dlg.show()
    dlg.setGeometry(150, 160, 480, 330)
    qapp.processEvents()
    dlg.close()  # 닫을 때 기억
    stored = manager.settings.window_geometries["SampleDialog"]
    assert stored

    again = SampleDialog()
    again.show()
    qapp.processEvents()
    assert (again.width(), again.height()) == (480, 330)
    assert (again.x(), again.y()) == (dlg.x(), dlg.y())
    again.close()


def test_moving_or_resizing_is_saved_soon_without_closing(qapp, manager):
    dlg = SampleDialog()
    dlg.show()
    qapp.processEvents()
    manager.saves.clear()
    dlg.resize(500, 340)
    qapp.processEvents()
    manager.flush()  # 타이머(0.5초)를 기다리는 대신 바로
    assert "SampleDialog" in manager.settings.window_geometries and manager.saves
    dlg.close()


def test_zoom_grows_open_windows_and_list_rows(qapp, manager):
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    dlg = SampleDialog()
    dlg.setMinimumSize(300, 200)
    lst = QListWidget(dlg)
    item = QListWidgetItem("행")
    item.setSizeHint(QSize(0, theme.px(40)))
    lst.addItem(item)
    dlg.show()
    dlg.resize(400, 300)
    qapp.processEvents()

    manager.apply_zoom(150)  # 글자만 커지면 내용이 잘리므로 창·최소 크기·목록 행도 같은 비율로
    assert (dlg.width(), dlg.height()) == (600, 450)
    assert (dlg.minimumWidth(), dlg.minimumHeight()) == (450, 300)
    assert item.sizeHint().height() == 60
    later = QListWidgetItem("확대 뒤에 만든 행")
    later.setSizeHint(QSize(0, theme.px(40)))
    lst.addItem(later)
    assert later.sizeHint().height() == 60

    manager.apply_zoom(100)  # 되돌리면 원래 크기로 (반올림 오차가 쌓이지 않음)
    assert (dlg.width(), dlg.height()) == (400, 300)
    assert item.sizeHint().height() == 40 and later.sizeHint().height() == 40
    dlg.close()


def test_new_window_opens_scaled_when_zoomed(qapp, manager):
    manager.apply_zoom(125, announce=False)
    dlg = SampleDialog()
    dlg.setMinimumSize(320, 160)
    dlg.resize(400, 240)
    dlg.show()
    qapp.processEvents()
    assert (dlg.minimumWidth(), dlg.width(), dlg.height()) == (400, 500, 300)
    dlg.close()


def test_message_boxes_are_not_tracked(qapp):
    assert not tracked(QMessageBox())
    assert tracked(SampleDialog())


def test_settings_keep_zoom_and_geometries(tmp_path):
    s = Settings()
    s.ui_zoom = 150
    s.window_geometries = {"PreferencesDialog": "AAAA"}
    s.save(tmp_path / "settings.json")
    loaded = Settings.load(tmp_path / "settings.json")
    assert loaded.ui_zoom == 150 and loaded.window_geometries == {"PreferencesDialog": "AAAA"}
    assert Settings.from_dict({"ui_zoom": 999}).ui_zoom == 200
    assert Settings.from_dict({"window_geometries": ["잘못된 값"]}).window_geometries == {}

import os
import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """모든 테스트가 실제 AppData 대신 임시 폴더를 쓰도록 합니다."""
    monkeypatch.setenv("FOCUSAPP_DATA_DIR", str(tmp_path / "data"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    controllers = _track_controllers(monkeypatch)
    yield tmp_path
    _dispose_controllers(controllers)
    _close_leftover_windows()


def _track_controllers(monkeypatch) -> list:
    """테스트에서 만든 FocusApp 컨트롤러를 모아 둡니다 (끝나면 _dispose_controllers로 정리)."""
    if "PySide6.QtWidgets" not in sys.modules:
        return []
    from focus_app import app as app_module

    created: list = []
    orig_init = app_module.FocusApp.__init__

    def init(self, *args, **kwargs):
        created.append(self)
        orig_init(self, *args, **kwargs)

    monkeypatch.setattr(app_module.FocusApp, "__init__", init)
    return created


def _dispose_controllers(controllers: list) -> None:
    """남은 컨트롤러를 확실히 멈추고 트레이·메뉴까지 지웁니다.

    실제 앱에서는 컨트롤러가 프로세스와 수명이 같지만, 테스트에서는 컨트롤러가 순환 참조로 남아 있다가
    아무 때나 GC로 정리됩니다. 그때 아래 _close_leftover_windows가 이미 지운 창·트레이 메뉴와 엇갈려
    가끔 접근 위반(access violation)으로 죽었으므로, 창을 지우기 전에 여기서 순서대로 정리합니다.
    """
    import gc

    import shiboken6

    for ctl in controllers:
        for name in ("poll_timer", "status_timer"):
            timer = getattr(ctl, name, None)
            if timer is not None and shiboken6.isValid(timer):
                timer.stop()
        tray = getattr(ctl, "tray", None)
        if tray is not None and shiboken6.isValid(tray):
            tray.hide()
            tray.setContextMenu(None)
            shiboken6.delete(tray)
        menu = getattr(ctl, "menu", None)
        if menu is not None and shiboken6.isValid(menu):
            shiboken6.delete(menu)
        window = getattr(ctl, "window", None)
        if window is not None and shiboken6.isValid(window):
            window.allow_close = True
    controllers.clear()
    gc.collect()


def _close_leftover_windows() -> None:
    """테스트가 만들고 정리하지 않은 창을 닫고 지웁니다.

    * 남은 창이 다음 테스트의 창 위에 겹쳐 마우스 이벤트를 가로채거나, 이벤트 처리 중에
      파이썬 쪽에서 정리되어 접근 위반(access violation)으로 죽는 일을 막습니다.
    * 숨긴 창도 지웁니다. 쌓여 있으면 화면 크기를 바꿀 때(스타일 다시 적용) 테스트가 몹시 느려집니다.
    """
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if widget.isVisible():
            widget.close()
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

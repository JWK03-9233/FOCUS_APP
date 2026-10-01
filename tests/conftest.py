import os
import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """모든 테스트가 실제 AppData 대신 임시 폴더를 쓰도록 합니다."""
    monkeypatch.setenv("FOCUSAPP_DATA_DIR", str(tmp_path / "data"))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield tmp_path
    _close_leftover_windows()


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

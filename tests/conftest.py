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
    """테스트가 show()만 하고 닫지 않은 창을 닫습니다.

    남은 창이 다음 테스트의 창 위에 겹쳐 마우스 이벤트를 가로채거나, 이벤트 처리 중에
    파이썬 쪽에서 정리되어 접근 위반(access violation)으로 죽는 일을 막습니다.
    """
    if "PySide6.QtWidgets" not in sys.modules:
        return
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        if widget.isVisible():
            widget.close()
    app.processEvents()

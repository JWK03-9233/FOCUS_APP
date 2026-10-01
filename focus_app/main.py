"""진입점: QApplication을 만들고 트레이 컨트롤러를 띄웁니다."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from focus_app.config import data_dir
from focus_app.version import APP_ID, APP_NAME


def _setup_logging() -> None:
    log_path = data_dir() / "focus_app.log"
    handler = RotatingFileHandler(log_path, maxBytes=512 * 1024, backupCount=2, encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        root.addHandler(console)


def main() -> int:
    _setup_logging()
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    from focus_app.app import FocusApp

    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # 창이 모두 닫혀도 트레이에 남음

    lock = QLockFile(str(data_dir() / "focus_app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, APP_NAME, f"{APP_NAME}이(가) 이미 실행 중입니다. 트레이 아이콘을 확인하세요.")
        return 1

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "시스템 트레이를 사용할 수 없어 실행할 수 없습니다.")
        return 1

    if not sys.platform.startswith("win"):
        logging.getLogger(__name__).warning("Windows가 아닌 환경입니다. 창 감시/최소화는 동작하지 않습니다.")

    controller = FocusApp(app)
    app.aboutToQuit.connect(lambda: lock.unlock())
    _keep = controller  # noqa: F841 - GC 방지
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

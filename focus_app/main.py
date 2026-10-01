"""진입점: QApplication을 만들고 트레이 컨트롤러를 띄웁니다."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

if not __package__:
    # `python focus_app/main.py`처럼 스크립트로 직접 실행된 경우 패키지 상위 폴더를 경로에 추가
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from focus_app.config import data_dir
from focus_app.version import APP_ID, APP_NAME


def _setup_logging(filename: str = "focus_app.log") -> None:
    log_path = data_dir() / filename
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


def _install_exception_hooks() -> None:
    """처리되지 않은 예외를 로그 파일에 남깁니다.

    pythonw/exe로 실행하면 콘솔이 없어 예외가 아무 데도 기록되지 않으므로,
    Qt 슬롯과 백그라운드 스레드에서 난 예외까지 모두 focus_app.log에 기록합니다.
    """
    import threading

    log = logging.getLogger("focus_app.crash")

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("처리되지 않은 예외", exc_info=(exc_type, exc, tb))

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        log.critical(
            "스레드 %s에서 처리되지 않은 예외",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = hook
    threading.excepthook = thread_hook


def _set_windows_app_id() -> None:
    # python.exe로 실행해도 작업 표시줄에 파이썬 대신 FocusApp 아이콘이 보이게 함
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.{APP_ID}")
        except (AttributeError, OSError):
            pass


def _helper_main(argv: list) -> int:
    """``--helper [--data-dir <폴더>]``: 창 없이 관리자 권한 도우미 감시만 실행 (Qt를 띄우지 않음)."""
    if "--data-dir" in argv:
        i = argv.index("--data-dir")
        if i + 1 < len(argv):
            # 관리자 권한이 다른 계정으로 뜨더라도 본 앱과 같은 설정·세션 폴더를 보도록
            os.environ["FOCUSAPP_DATA_DIR"] = argv[i + 1]
    _setup_logging("helper.log")
    _install_exception_hooks()
    from focus_app.helper import run_helper

    return run_helper()


def main() -> int:
    if "--helper" in sys.argv[1:]:
        return _helper_main(sys.argv[1:])
    _setup_logging()
    _install_exception_hooks()
    _set_windows_app_id()
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    from focus_app.app import FocusApp
    from focus_app.ui import icons

    app = QApplication(sys.argv)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # 창이 모두 닫혀도 트레이에 남음
    app.setWindowIcon(icons.app_icon())  # 모든 창·대화상자의 기본 아이콘

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

    controller = FocusApp(app, check_updates=True)
    app.aboutToQuit.connect(lambda: lock.unlock())
    _keep = controller  # noqa: F841 - GC 방지
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

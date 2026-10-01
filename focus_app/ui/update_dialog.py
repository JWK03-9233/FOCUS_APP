"""업데이트 확인·설치 대화상자. 네트워크 작업은 백그라운드 스레드에서 하고 결과만 시그널로 받습니다."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from focus_app import updater
from focus_app.updater import ReleaseInfo, UpdateError
from focus_app.version import __version__


class _Bridge(QObject):
    """작업 스레드 -> UI 스레드 전달용. 시그널은 받는 쪽 스레드에서 실행됩니다."""

    checked = Signal(object)  # ReleaseInfo
    failed = Signal(str)
    progress = Signal(int, int)
    ready = Signal(object, object)  # 설치 준비된 파일(설치 프로그램 또는 압축 푼 폴더), 작업 폴더


def _safe_emit(signal, *args) -> None:
    try:
        signal.emit(*args)
    except RuntimeError:  # 대화상자가 이미 닫혀 정리된 경우
        pass


def run_in_thread(target: Callable[[], None], name: str) -> threading.Thread:
    t = threading.Thread(target=target, name=name, daemon=True)
    t.start()
    return t


class UpdateDialog(QDialog):
    """설치할 준비가 끝나면 install_requested(종류, 준비된 파일, 작업 폴더)를 보냅니다."""

    install_requested = Signal(str, object, object)

    def __init__(
        self,
        token: str = "",
        info: Optional[ReleaseInfo] = None,
        parent: QWidget | None = None,
        fetch: Callable[[str], ReleaseInfo] = lambda token: updater.fetch_latest(token),
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("업데이트")
        self.setMinimumSize(520, 420)
        self.token = token
        self.info: Optional[ReleaseInfo] = None
        self._fetch = fetch
        self._cancel = threading.Event()
        self._busy = False

        self.bridge = _Bridge(self)
        self.bridge.checked.connect(self._on_checked)
        self.bridge.failed.connect(self._on_failed)
        self.bridge.progress.connect(self._on_progress)
        self.bridge.ready.connect(self._on_ready)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.title = QLabel("업데이트 확인 중…")
        self.title.setObjectName("sectionTitle")
        layout.addWidget(self.title)
        self.subtitle = QLabel(f"현재 버전 v{__version__}")
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.hide()
        layout.addWidget(self.notes, 1)
        layout.addStretch(0)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)  # 얇은 막대라 글자가 잘림 -> 퍼센트는 아래 상태 줄에 표시
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.page_btn = QPushButton("릴리스 페이지 열기")
        self.page_btn.setObjectName("linkButton")
        self.page_btn.clicked.connect(self._open_page)
        buttons.addWidget(self.page_btn)
        buttons.addStretch(1)
        self.install_btn = QPushButton("지금 업데이트")
        self.install_btn.setObjectName("primary")
        self.install_btn.clicked.connect(self._start_install)
        self.install_btn.hide()
        buttons.addWidget(self.install_btn)
        self.retry_btn = QPushButton("다시 확인")
        self.retry_btn.clicked.connect(self.check)
        self.retry_btn.hide()
        buttons.addWidget(self.retry_btn)
        self.close_btn = QPushButton("닫기")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        if info is not None:
            self._on_checked(info)
        else:
            self.check()

    # ------------------------------------------------------------- 확인
    def check(self) -> None:
        self.title.setText("업데이트 확인 중…")
        self.status.setText("")
        self.retry_btn.hide()
        self.progress.setRange(0, 0)
        self.progress.show()
        token, fetch, bridge = self.token, self._fetch, self.bridge

        def work() -> None:
            try:
                _safe_emit(bridge.checked, fetch(token))
            except UpdateError as exc:
                _safe_emit(bridge.failed, str(exc))
            except Exception as exc:  # noqa: BLE001 - 예상 못 한 오류도 화면에 표시
                _safe_emit(bridge.failed, f"확인하지 못했습니다: {exc}")

        run_in_thread(work, "update-check")

    def _on_checked(self, info: ReleaseInfo) -> None:
        self.info = info
        self.progress.hide()
        if not info.newer:
            self.title.setText("최신 버전을 쓰고 있습니다 ✓")
            self.subtitle.setText(f"현재 버전 v{__version__} · 최근 릴리스 v{info.version}")
            self.notes.hide()
            return
        self.title.setText(
            f"{'중요 업데이트' if info.urgency == 'critical' else '새 버전'} v{info.version}이(가) 있습니다"
        )
        self.subtitle.setText(f"현재 버전 v{__version__}  →  v{info.version}")
        self.notes.setMarkdown(info.notes or "(변경 내용 설명 없음)")
        self.notes.show()
        if not info.installable:
            self.status.setText("이 릴리스에는 설치 파일이 없습니다. 릴리스 페이지에서 확인하세요.")
        elif not updater.is_frozen():
            self.status.setText(
                "지금은 소스 코드(python)로 실행 중이라 자동 설치는 할 수 없습니다. "
                "git pull로 받거나, 릴리스 페이지에서 exe 배포본을 내려받으세요."
            )
        else:
            self.status.setText("업데이트하면 FocusApp이 잠시 꺼졌다가 새 버전으로 다시 켜집니다. 설정은 그대로 유지됩니다.")
            self.install_btn.show()

    def _on_failed(self, message: str) -> None:
        self._busy = False
        self.progress.hide()
        self.title.setText("업데이트하지 못했습니다")
        self.status.setText(message)
        self.retry_btn.show()
        self.install_btn.setEnabled(True)
        self.close_btn.setText("닫기")

    # ------------------------------------------------------------- 설치
    def _start_install(self) -> None:
        info = self.info
        if info is None or self._busy:
            return
        self._busy = True
        self._cancel.clear()
        self.install_btn.setEnabled(False)
        self.retry_btn.hide()
        self.close_btn.setText("취소")
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.show()
        self.status.setText("내려받는 중…")
        token, bridge, cancel = self.token, self.bridge, self._cancel

        def work() -> None:
            work_dir = updater.make_work_dir()
            try:
                zip_path = updater.download(
                    info,
                    work_dir,
                    token,
                    progress=lambda done, total: _safe_emit(bridge.progress, done, total),
                    cancelled=cancel.is_set,
                )
                prepared = updater.prepare(info, work_dir, zip_path)
                _safe_emit(bridge.ready, prepared, work_dir)
            except UpdateError as exc:
                _safe_emit(bridge.failed, str(exc))
            except Exception as exc:  # noqa: BLE001
                _safe_emit(bridge.failed, f"설치 파일을 준비하지 못했습니다: {exc}")

        run_in_thread(work, "update-download")

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setValue(int(1000 * done / total))
            self.status.setText(f"내려받는 중… {100 * done // total}%  ·  {done / 2**20:.1f} / {total / 2**20:.1f} MB")
        else:
            self.status.setText(f"내려받는 중… {done / 2**20:.1f} MB")

    def _on_ready(self, prepared: Path, work_dir: Path) -> None:
        self._busy = False
        self.status.setText("설치를 시작합니다. 잠시 뒤 새 버전이 열립니다…")
        self.install_requested.emit(self.info.kind if self.info else "zip", prepared, work_dir)

    # ------------------------------------------------------------- 기타
    def _open_page(self) -> None:
        url = self.info.page_url if self.info else updater.RELEASES_PAGE
        QDesktopServices.openUrl(QUrl(url))

    def reject(self) -> None:
        self._cancel.set()  # 내려받는 중이면 멈춤
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._cancel.set()
        super().closeEvent(event)

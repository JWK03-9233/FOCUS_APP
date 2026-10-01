"""랜덤 문자열을 직접 입력해야 닫히는 해제 대화상자.

* 붙여넣기(Ctrl+V, Shift+Insert, 컨텍스트 메뉴, 드래그 앤 드롭, 마우스 가운데 버튼)를 막습니다.
* 한 번에 2글자 이상 들어오는 입력(IME 일괄 입력 등)은 되돌립니다.
* 표시된 문자열은 선택/복사할 수 없습니다.
* 틀리면 새 문자열이 발급됩니다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from focus_app.unlock import UnlockChallenge


class NoPasteLineEdit(QLineEdit):
    """붙여넣기와 일괄 입력을 막는 입력창."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._previous = ""
        self.textChanged.connect(self._guard)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.StandardKey.Paste) or (
            event.key() == Qt.Key.Key_Insert and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            event.ignore()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:  # X11/일부 환경의 선택 붙여넣기
            event.ignore()
            return
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        event.ignore()

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        return  # 모든 MIME 입력(붙여넣기/드롭) 차단

    def _guard(self, text: str) -> None:
        # 한 번의 변경으로 2글자 이상 늘어나면 붙여넣기/일괄 입력으로 보고 되돌림
        if len(text) - len(self._previous) > 1:
            self.blockSignals(True)
            self.setText(self._previous)
            self.blockSignals(False)
            return
        self._previous = text


class UnlockDialog(QDialog):
    def __init__(self, length: int, purpose: str = "집중 모드 해제", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.challenge = UnlockChallenge(length=length)
        self.setWindowTitle(f"{purpose} - 확인 문자열 입력")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"<b>{purpose}</b> — 정말 하려면 아래 문자열을 <u>직접 손으로</u> 입력하세요.<br>"
            "붙여넣기는 되지 않고, 틀리면 새 문자열이 나옵니다. 띄어쓰기는 입력하지 않아도 됩니다."
        )
        intro.setWordWrap(False)  # 줄은 <br>로 나눔. 자동 줄바꿈은 창 높이를 쓸데없이 키움
        layout.addWidget(intro)

        self.code_label = QLabel()
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setWordWrap(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(16)
        self.code_label.setFont(font)
        self.code_label.setStyleSheet(
            "QLabel { background: rgba(127, 127, 127, 0.14); border: 1px solid rgba(127, 127, 127, 0.32);"
            " padding: 16px; border-radius: 14px; letter-spacing: 1px; }"
        )
        layout.addWidget(self.code_label)

        self.input = NoPasteLineEdit()
        self.input.setFont(font)
        self.input.setPlaceholderText("여기에 입력")
        self.input.returnPressed.connect(self._check)
        self.input.textChanged.connect(self._update_counter)
        layout.addWidget(self.input)

        self.counter = QLabel("")
        self.counter.setObjectName("hint")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.counter)

        self.status = QLabel("")
        self.status.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("확인")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh()
        self.adjustSize()  # 줄바꿈 문장 때문에 생기는 빈 공간 없이 내용에 맞춤

    def _update_counter(self, *_args) -> None:
        typed = len("".join(self.input.text().split()))
        self.counter.setText(f"{typed} / {len(self.challenge.code)} 글자")

    def _refresh(self) -> None:
        self.code_label.setText(self.challenge.display)
        self.input.clear()
        self.input._previous = ""
        self.input.setFocus()
        self._update_counter()

    def _check(self) -> None:
        if self.challenge.verify(self.input.text()):
            self.accept()
            return
        self.status.setText(f"틀렸습니다. 새 문자열이 발급되었습니다. (시도 {self.challenge.attempts}회)")
        self._refresh()


def confirm_with_code(length: int, purpose: str, parent: QWidget | None = None) -> bool:
    """대화상자를 띄우고 사용자가 올바르게 입력했을 때만 True."""
    dlg = UnlockDialog(length=length, purpose=purpose, parent=parent)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    try:
        return dlg.exec() == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()

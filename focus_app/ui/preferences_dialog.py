"""고급 설정 대화상자. 항목마다 무슨 뜻인지 짧은 설명을 붙입니다."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focus_app.config import Settings


def _field_label(text: str) -> QLabel:
    """설정 항목 이름. 구역이 달라도 입력칸이 같은 위치에서 시작하도록 너비를 맞춤."""
    label = QLabel(text)
    label.setMinimumWidth(140)
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


class PreferencesDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("설정")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        title = QLabel("끄기 어렵게 만드는 장치")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.setVerticalSpacing(4)

        self.code_len = QSpinBox()
        self.code_len.setRange(8, 128)
        self.code_len.setSuffix(" 글자")
        self.code_len.setValue(settings.unlock_code_length)
        form.addRow(_field_label("해제 문자열 길이"), self.code_len)
        form.addRow(_field_label(""), _hint("집중을 중간에 끝내려면 이 길이의 랜덤 문자열을 손으로 입력해야 합니다. 길수록 끄기 어렵습니다."))

        self.quit_check = QCheckBox("집중 중에 FocusApp을 종료할 때도 문자열 입력 요구")
        self.quit_check.setChecked(settings.require_unlock_for_quit)
        layout.addLayout(form)
        layout.addWidget(self.quit_check)

        title2 = QLabel("알림과 감시")
        title2.setObjectName("sectionTitle")
        layout.addWidget(title2)
        self.notify_check = QCheckBox("앱을 최소화할 때 알림 표시")
        self.notify_check.setChecked(settings.show_block_notifications)
        layout.addWidget(self.notify_check)
        form2 = QFormLayout()
        form2.setVerticalSpacing(4)

        self.poll = QSpinBox()
        self.poll.setRange(100, 5000)
        self.poll.setSingleStep(50)
        self.poll.setSuffix(" ms")
        self.poll.setValue(settings.poll_interval_ms)
        form2.addRow(_field_label("확인 주기"), self.poll)
        form2.addRow(_field_label(""), _hint("앞에 나온 창을 얼마나 자주 확인할지 정합니다. 보통은 바꿀 필요가 없습니다."))
        layout.addLayout(form2)

        title_h = QLabel("관리자 권한 앱 차단")
        title_h.setObjectName("sectionTitle")
        layout.addWidget(title_h)
        layout.addWidget(_hint(
            "'관리자 권한으로 실행'한 앱은 Windows 보안 때문에 FocusApp이 최소화할 수 없습니다. "
            "도우미를 설치하면(관리자 확인 1번) 그런 앱도 막습니다. 집중 중에 FocusApp이나 도우미 중 하나를 "
            "강제로 끄면 다른 쪽이 다시 띄웁니다."
        ))
        helper_row = QHBoxLayout()
        self.helper_status = QLabel("")
        self.helper_status.setWordWrap(True)
        helper_row.addWidget(self.helper_status, 1)
        self.helper_btn = QPushButton("")
        self.helper_btn.clicked.connect(self._toggle_helper)
        helper_row.addWidget(self.helper_btn)
        layout.addLayout(helper_row)
        self.strict_check = QCheckBox("엄격 모드: 집중 중에는 작업 관리자를 열 수 없게 하기")
        self.strict_check.setChecked(settings.block_task_manager)
        layout.addWidget(self.strict_check)
        self.strict_hint = _hint("")
        layout.addWidget(self.strict_hint)
        self._refresh_helper()

        title3 = QLabel("업데이트")
        title3.setObjectName("sectionTitle")
        layout.addWidget(title3)
        self.update_check = QCheckBox("실행할 때 새 버전이 있는지 확인")
        self.update_check.setChecked(settings.check_updates_on_start)
        layout.addWidget(self.update_check)
        form3 = QFormLayout()
        form3.setVerticalSpacing(4)
        self.token_edit = QLineEdit(settings.github_token)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("비워 두면 사용하지 않음")
        form3.addRow(_field_label("GitHub 토큰"), self.token_edit)
        form3.addRow(_field_label(""), _hint("저장소가 비공개일 때만 필요합니다. 'Contents: 읽기' 권한만 있는 토큰을 쓰세요."))
        layout.addLayout(form3)
        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("저장")
        save.setDefault(True)
        save.clicked.connect(self._save)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _refresh_helper(self) -> None:
        from focus_app import helper

        installed = helper.is_registered()
        self.helper_status.setText("도우미: " + helper.status_text())
        self.helper_btn.setText("도우미 제거…" if installed else "도우미 설치…")
        self.helper_btn.setObjectName("" if installed else "secondary")
        self.helper_btn.style().unpolish(self.helper_btn)
        self.helper_btn.style().polish(self.helper_btn)
        # 작업 관리자 끄기는 관리자 권한이 필요해 도우미가 맡음
        self.strict_check.setEnabled(installed)
        self.strict_hint.setText(
            "집중이 끝나면 작업 관리자는 저절로 다시 열립니다. 집중 전에 열어 둔 작업 관리자 창도 최소화합니다."
            if installed else "도우미를 설치해야 쓸 수 있습니다."
        )

    def _toggle_helper(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox

        from focus_app import helper

        installed = helper.is_registered()
        if not installed:
            answer = QMessageBox.question(
                self,
                "관리자 권한 도우미",
                "Windows 작업 스케줄러에 'FocusApp\\Helper' 작업을 등록합니다.\n\n"
                "• 집중 중에만 관리자 권한으로 잠깐 실행되고, 집중이 끝나면 스스로 꺼집니다.\n"
                "• 이어서 나오는 Windows 관리자 확인(UAC)에서 '예'를 눌러 주세요.\n\n설치할까요?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            ok, message = helper.unregister() if installed else helper.register()
        finally:
            QApplication.restoreOverrideCursor()
        (QMessageBox.information if ok else QMessageBox.warning)(self, "관리자 권한 도우미", message)
        self._refresh_helper()

    def _save(self) -> None:
        s = self.settings
        s.unlock_code_length = int(self.code_len.value())
        s.require_unlock_for_quit = self.quit_check.isChecked()
        s.block_task_manager = self.strict_check.isChecked()
        s.show_block_notifications = self.notify_check.isChecked()
        s.poll_interval_ms = int(self.poll.value())
        s.check_updates_on_start = self.update_check.isChecked()
        s.github_token = self.token_edit.text().strip()
        self.accept()

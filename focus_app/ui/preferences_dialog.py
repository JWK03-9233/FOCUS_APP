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
        form.addRow("해제 문자열 길이", self.code_len)
        form.addRow("", _hint("집중을 중간에 끝내려면 이 길이의 랜덤 문자열을 손으로 입력해야 합니다. 길수록 끄기 어렵습니다."))

        self.emergency = QSpinBox()
        self.emergency.setRange(1, 240)
        self.emergency.setSuffix(" 분")
        self.emergency.setValue(settings.emergency_delay_minutes)
        form.addRow("비상 해제 대기 시간", self.emergency)
        form.addRow("", _hint("문자열 입력 없이 끝내는 비상 수단입니다. 요청한 뒤 이 시간이 지나야 차단이 풀립니다."))

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
        form2.addRow("확인 주기", self.poll)
        form2.addRow("", _hint("앞에 나온 창을 얼마나 자주 확인할지 정합니다. 보통은 바꿀 필요가 없습니다."))
        layout.addLayout(form2)

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
        form3.addRow("GitHub 토큰", self.token_edit)
        form3.addRow("", _hint("저장소가 비공개일 때만 필요합니다. 'Contents: 읽기' 권한만 있는 토큰을 쓰세요."))
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

    def _save(self) -> None:
        s = self.settings
        s.unlock_code_length = int(self.code_len.value())
        s.emergency_delay_minutes = int(self.emergency.value())
        s.require_unlock_for_quit = self.quit_check.isChecked()
        s.show_block_notifications = self.notify_check.isChecked()
        s.poll_interval_ms = int(self.poll.value())
        s.check_updates_on_start = self.update_check.isChecked()
        s.github_token = self.token_edit.text().strip()
        self.accept()

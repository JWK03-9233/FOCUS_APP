"""집중 모드 시작 대화상자: 프로필과 시간 선택."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focus_app.config import Settings

PRESETS = [25, 50, 90, 120, 180]


class StartDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("집중 모드 시작")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.profile_box = QComboBox()
        self.profile_box.addItems(settings.profile_names())
        idx = self.profile_box.findText(settings.active_profile)
        if idx >= 0:
            self.profile_box.setCurrentIndex(idx)
        self.profile_box.currentTextChanged.connect(self._update_summary)
        form.addRow("프로필", self.profile_box)

        self.duration = QSpinBox()
        self.duration.setRange(1, 1440)
        self.duration.setSuffix(" 분")
        self.duration.setValue(settings.default_duration_minutes)
        form.addRow("시간", self.duration)

        presets = QHBoxLayout()
        for minutes in PRESETS:
            btn = QPushButton(f"{minutes}분")
            btn.clicked.connect(lambda _=False, m=minutes: self.duration.setValue(m))
            presets.addWidget(btn)
        form.addRow("", presets)

        self.unlimited = QCheckBox("시간 제한 없이 수동 해제할 때까지")
        self.unlimited.toggled.connect(lambda on: self.duration.setDisabled(on))
        form.addRow("", self.unlimited)
        layout.addLayout(form)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #555;")
        layout.addWidget(self.summary)

        warn = QLabel(
            "시작하면 허용 목록 편집이 잠기고, 해제·종료·프로필 전환에는 랜덤 문자열 입력이 필요합니다."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #a0522d;")
        layout.addWidget(warn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("시작")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_summary()

    def _update_summary(self) -> None:
        p = self.settings.get_profile(self.profile_box.currentText())
        if p is None:
            self.summary.setText("")
            return
        if not p.block_everything:
            self.summary.setText("이 프로필은 차단하지 않습니다 (자유 시간).")
            return
        apps: List[str] = p.normalized_apps()
        shown = ", ".join(apps[:8]) + (" …" if len(apps) > 8 else "")
        self.summary.setText(f"허용 앱 {len(apps)}개: {shown or '(없음 - 시스템 창 외 전부 차단)'}")

    def result_values(self) -> Tuple[str, Optional[int]]:
        minutes = None if self.unlimited.isChecked() else int(self.duration.value())
        return self.profile_box.currentText(), minutes

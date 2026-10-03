"""새 모드 만들기 대화상자: 이름을 정하고, 원하면 기존 모드의 앱·사이트를 그대로 이어받습니다."""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from focus_app.config import Profile
from focus_app.ui.scroll import scroll_layout


def _summary(p: Profile) -> str:
    if not p.block_everything:
        return f"{p.name}  (차단 안 함)"
    parts = [f"앱 {len(p.normalized_apps())}개"]
    if p.limits_sites():
        parts.append(f"사이트 {len(p.normalized_sites())}개")
    return f"{p.name}  ({' · '.join(parts)})"


class NewModeDialog(QDialog):
    def __init__(self, profiles: List[Profile], base: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("새 모드")
        self.setMinimumWidth(380)

        layout = scroll_layout(self)  # 내용이 많으면 창 전체를 스크롤
        layout.setSpacing(10)

        title = QLabel("모드 이름")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 시험 공부, 글쓰기")
        self.name_edit.textChanged.connect(self._update_buttons)
        layout.addWidget(self.name_edit)

        base_title = QLabel("기존 모드 이어받기")
        base_title.setObjectName("sectionTitle")
        layout.addWidget(base_title)
        self.base_combo = QComboBox()
        self.base_combo.addItem("이어받지 않음 (빈 모드로 시작)", "")
        for p in profiles:
            self.base_combo.addItem(_summary(p), p.name)
        self.base_combo.setCurrentIndex(max(0, self.base_combo.findData(base)))
        layout.addWidget(self.base_combo)
        hint = QLabel("이어받으면 그 모드의 앱·웹 앱·사이트가 모두 담긴 채로 만들어집니다.\n만든 뒤 빼거나 더해서 고치면 됩니다.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_btn = QPushButton("만들기")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.ok_btn)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self._update_buttons()
        self.name_edit.setFocus()

    def _update_buttons(self) -> None:
        self.ok_btn.setEnabled(bool(self.name()))

    def name(self) -> str:
        return self.name_edit.text().strip()

    def base(self) -> str:
        """이어받을 모드 이름. 이어받지 않으면 빈 문자열."""
        return self.base_combo.currentData() or ""

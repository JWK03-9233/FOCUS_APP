"""집중 시간 버튼 목록(25분, 50분 …)을 사용자가 고치는 대화상자."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from focus_app.config import DEFAULT_DURATION_PRESETS, MAX_DURATION_PRESETS, clean_presets
from focus_app.session import format_minutes


class PresetDialog(QDialog):
    def __init__(self, presets: List[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("시간 버튼 편집")
        self.setMinimumWidth(380)
        self._presets = clean_presets(list(presets))

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel("자주 쓰는 집중 시간을 버튼으로 만들어 두세요.")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel(f"최대 {MAX_DURATION_PRESETS}개까지, 짧은 시간부터 순서대로 표시됩니다.")
        hint.setObjectName("hint")
        layout.addWidget(hint)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.list, 1)

        add_row = QHBoxLayout()
        self.hours = QSpinBox()
        self.hours.setRange(0, 24)
        self.hours.setSuffix(" 시간")
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 59)
        self.minutes.setSingleStep(5)
        self.minutes.setSuffix(" 분")
        self.minutes.setValue(30)
        self.add_btn = QPushButton("+  추가")
        self.add_btn.setObjectName("secondary")
        self.add_btn.clicked.connect(self._add)
        add_row.addWidget(self.hours)
        add_row.addWidget(self.minutes)
        add_row.addWidget(self.add_btn)
        add_row.addStretch(1)
        layout.addLayout(add_row)

        edit_row = QHBoxLayout()
        self.remove_btn = QPushButton("선택한 시간 삭제")
        self.remove_btn.clicked.connect(self._remove)
        reset = QPushButton("기본값으로")
        reset.setObjectName("linkButton")
        reset.clicked.connect(self._reset)
        edit_row.addWidget(self.remove_btn)
        edit_row.addStretch(1)
        edit_row.addWidget(reset)
        layout.addLayout(edit_row)

        self.status = QLabel("")
        self.status.setObjectName("hint")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("저장")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self._reload()

    def _reload(self) -> None:
        self.list.clear()
        for m in self._presets:
            item = QListWidgetItem(format_minutes(m))
            item.setData(Qt.ItemDataRole.UserRole, m)
            self.list.addItem(item)
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.remove_btn.setEnabled(bool(self.list.selectedItems()) and len(self._presets) > 1)
        full = len(self._presets) >= MAX_DURATION_PRESETS
        self.add_btn.setEnabled(not full)
        self.status.setText(f"버튼이 {MAX_DURATION_PRESETS}개로 가득 찼습니다." if full else "")

    def add_minutes(self, minutes: int) -> bool:
        if not 1 <= minutes <= 1440:
            self.status.setText("1분에서 24시간 사이로 정해 주세요.")
            return False
        if minutes in self._presets:
            self.status.setText(f"{format_minutes(minutes)}은(는) 이미 있습니다.")
            return False
        if len(self._presets) >= MAX_DURATION_PRESETS:
            return False
        self._presets = clean_presets(self._presets + [minutes])
        self._reload()
        return True

    def _add(self) -> None:
        self.add_minutes(self.hours.value() * 60 + self.minutes.value())

    def _remove(self) -> None:
        chosen = {item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()}
        remaining = [m for m in self._presets if m not in chosen]
        if not remaining:
            self.status.setText("버튼은 하나 이상 있어야 합니다.")
            return
        self._presets = remaining
        self._reload()

    def _reset(self) -> None:
        self._presets = list(DEFAULT_DURATION_PRESETS)
        self._reload()

    def presets(self) -> List[int]:
        return list(self._presets)

"""집중 중에 지금 모드의 허용 앱 목록만 고치는 대화상자 (해제 문자열을 입력한 뒤에만 열림).

타이머와 차단은 그대로 계속되며, 저장하면 바뀐 목록이 즉시 적용됩니다.
"""

from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from focus_app.config import Profile, Settings, normalize_exe
from focus_app.ui import app_catalog
from focus_app.ui.app_catalog import AppEntry
from focus_app.ui.app_picker import AppPickerDialog
from focus_app.ui.main_window import AppRow


class AllowedAppsDialog(QDialog):
    def __init__(self, settings: Settings, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.profile_name = profile.name
        self._apps: List[str] = profile.normalized_apps()  # 저장 전까지는 복사본만 고침
        self._new_entries: Dict[str, AppEntry] = {}
        self.setWindowTitle("허용 앱 편집")
        self.setMinimumSize(460, 480)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel(f"<b>{profile.name}</b> 모드의 허용 앱")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel("집중은 그대로 계속됩니다. 저장하면 바뀐 목록이 바로 적용됩니다.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        head = QHBoxLayout()
        self.count = QLabel("")
        self.count.setObjectName("sectionTitle")
        head.addWidget(self.count, 1)
        add = QPushButton("+  앱 추가")
        add.setObjectName("secondary")
        add.clicked.connect(self._add)
        head.addWidget(add)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setObjectName("appList")
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.list, 1)

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

    def _name(self, exe: str) -> str:
        entry = self._new_entries.get(exe)
        return entry.name if entry else self.settings.app_display_name(exe)

    def _path(self, exe: str) -> str:
        entry = self._new_entries.get(exe)
        return (entry.path if entry else self.settings.app_path(exe)) or app_catalog.find_installed_path(exe)

    def _reload(self) -> None:
        self.list.clear()
        self.count.setText(f"쓸 수 있는 앱 ({len(self._apps)}개)")
        for exe in self._apps:
            row = AppRow(self._name(exe), exe, self._path(exe), self.remove_app)
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 46))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)

    def _add(self) -> None:
        dlg = AppPickerDialog(self.profile_name, self._apps, parent=self)
        try:
            if dlg.exec() != AppPickerDialog.DialogCode.Accepted:
                return
            entries = dlg.selected_entries()
        finally:
            dlg.deleteLater()
        self.add_entries(entries)

    def add_entries(self, entries: List[AppEntry]) -> None:
        for e in entries:
            exe = normalize_exe(e.exe)
            if exe and exe not in self._apps:
                self._apps.append(exe)
                self._new_entries[exe] = e
        self._reload()

    def remove_app(self, exe: str) -> None:
        exe = normalize_exe(exe)
        self._apps = [a for a in self._apps if a != exe]
        self._reload()

    def apply_to(self, settings: Settings) -> Profile:
        """편집 결과를 설정의 해당 모드에 반영하고 그 모드를 돌려줍니다."""
        profile = settings.get_profile(self.profile_name)
        if profile is None:
            raise ValueError(f"모드를 찾을 수 없습니다: {self.profile_name}")
        profile.allowed_apps = list(self._apps)
        for exe, e in self._new_entries.items():
            if exe in self._apps:
                settings.remember_app(exe, e.name, e.path)
        return profile

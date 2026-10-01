"""허용할 앱을 체크해서 고르는 대화상자 (실행 중인 앱 + 설치된 앱 + 파일 찾기)."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from focus_app.config import friendly_name, normalize_exe
from focus_app.enforcer import SYSTEM_EXES
from focus_app.ui import app_catalog
from focus_app.ui.app_catalog import AppEntry

_ROLE_EXE = Qt.ItemDataRole.UserRole
_ROLE_HEADER = Qt.ItemDataRole.UserRole + 1


class AppPickerDialog(QDialog):
    def __init__(
        self,
        mode_name: str,
        already_allowed: Iterable[str],
        running: Optional[List[AppEntry]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("허용할 앱 고르기")
        self.resize(520, 600)
        self._already = {normalize_exe(a) for a in already_allowed}
        self._entries: Dict[str, AppEntry] = {}
        self._running = app_catalog.running_apps() if running is None else running
        self._installed_shown = False

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        title = QLabel(f"<b>{mode_name}</b> 모드에서 쓸 앱을 체크하세요.")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        sub = QLabel("체크한 앱만 집중 중에 쓸 수 있고, 나머지 앱은 앞으로 나오면 자동으로 최소화됩니다.")
        sub.setObjectName("muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  앱 이름으로 찾기")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setObjectName("pickList")
        self.list.setIconSize(QSize(24, 24))
        self.list.setSpacing(1)
        # 목록이 포커스를 가져가면 Windows 11 스타일이 테두리를 강조색으로 다시 그려 목록이 순간
        # 커지는 것처럼 보임 -> 포커스는 검색 칸에 두고, 선택 표시도 쓰지 않음
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.itemChanged.connect(self._update_count)
        self.list.itemClicked.connect(self._toggle_on_click)
        layout.addWidget(self.list, 1)

        browse_row = QHBoxLayout()
        browse_row.addWidget(QLabel("목록에 없나요?"))
        browse = QPushButton("실행 파일(.exe) 직접 찾기…")
        browse.setObjectName("linkButton")
        browse.clicked.connect(self._browse)
        browse_row.addWidget(browse)
        browse_row.addStretch(1)
        layout.addLayout(browse_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_btn = QPushButton("추가")
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.ok_btn)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self._populate()
        if not self._installed_shown:
            # 설치된 앱 목록을 아직 읽는 중이면 준비될 때까지 기다렸다가 채움
            app_catalog.installed_apps.preload()
            self._wait_timer = QTimer(self)
            self._wait_timer.timeout.connect(self._check_installed)
            self._wait_timer.start(300)
        self._update_count()
        self.search.setFocus()

    # ------------------------------------------------------------- 목록
    def _add_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(_ROLE_HEADER, True)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        self.list.addItem(item)

    def _add_entry(self, entry: AppEntry, checked: bool = False) -> QListWidgetItem:
        self._entries[entry.exe] = entry
        allowed = entry.exe in self._already
        label = f"{entry.name}    ({entry.exe})" if entry.name.lower() != entry.exe else entry.name
        if allowed:
            label += "  · 이미 추가됨"
        item = QListWidgetItem(app_catalog.app_icon(entry.path, entry.name), label)
        item.setData(_ROLE_EXE, entry.exe)
        item.setSizeHint(QSize(0, 34))
        # ItemIsUserCheckable은 일부러 주지 않음: Qt가 체크박스 칸 클릭을 따로 토글하면
        # 줄 클릭 처리(_toggle_on_click)와 겹쳐 두 번 바뀌어(=그대로) 버림. 토글은 한 곳에서만 함.
        if allowed:
            item.setFlags(Qt.ItemFlag.NoItemFlags)  # 비활성 + 체크 표시
            item.setCheckState(Qt.CheckState.Checked)
        else:
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.addItem(item)
        return item

    def _populate(self) -> None:
        checked = set(self.selected_exes())
        self.list.blockSignals(True)
        self.list.clear()
        self._entries.clear()
        shown = set()
        if self._running:
            self._add_header("지금 실행 중인 앱")
            for e in sorted(self._running, key=lambda e: e.name.lower()):
                self._add_entry(e, e.exe in checked)
                shown.add(e.exe)
        installed = app_catalog.installed_apps.get()
        self._add_header("설치된 앱")
        if installed is None:
            loading = QListWidgetItem("   설치된 앱 목록을 불러오는 중…")
            loading.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(loading)
        else:
            self._installed_shown = True
            for e in installed:
                if e.exe not in shown:
                    self._add_entry(e, e.exe in checked)
                    shown.add(e.exe)
        self.list.blockSignals(False)
        self._apply_filter(self.search.text() if hasattr(self, "search") else "")

    def _check_installed(self) -> None:
        if app_catalog.installed_apps.get() is not None:
            self._wait_timer.stop()
            self._populate()
            self._update_count()

    def _apply_filter(self, text: str) -> None:
        q = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(_ROLE_HEADER) or item.data(_ROLE_EXE) is None:
                item.setHidden(bool(q))
                continue
            entry = self._entries.get(item.data(_ROLE_EXE))
            hay = f"{entry.name} {entry.exe}".lower() if entry else item.text().lower()
            item.setHidden(bool(q) and q not in hay)

    def _toggle_on_click(self, item: QListWidgetItem) -> None:
        # 체크박스 칸이든 이름이든 줄 아무 곳을 눌러도 한 번만 바뀜
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled) or item.data(_ROLE_EXE) is None:
            return
        new = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
        item.setCheckState(new)

    def _update_count(self, *_args) -> None:
        n = len(self.selected_exes())
        self.ok_btn.setText(f"{n}개 추가" if n else "추가")
        self.ok_btn.setEnabled(n > 0)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "실행 파일 선택", "C:\\Program Files", "실행 파일 (*.exe)")
        if not path:
            return
        exe = normalize_exe(path)
        if exe in SYSTEM_EXES:
            QMessageBox.information(self, "허용 앱", f"{exe}은(는) 시스템 요소라 항상 쓸 수 있습니다. 추가하지 않아도 됩니다.")
            return
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(_ROLE_EXE) == exe:
                if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                    item.setCheckState(Qt.CheckState.Checked)
                self.list.scrollToItem(item)
                return
        entry = AppEntry(exe=exe, name=friendly_name(exe), path=str(Path(path)))
        item = self._add_entry(entry, checked=True)
        self.list.scrollToItem(item)
        self._update_count()

    # ------------------------------------------------------------- 결과
    def selected_exes(self) -> List[str]:
        if not hasattr(self, "list"):
            return []
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            exe = item.data(_ROLE_EXE)
            if exe and exe not in self._already and item.checkState() == Qt.CheckState.Checked:
                out.append(exe)
        return out

    def selected_entries(self) -> List[AppEntry]:
        return [self._entries[e] for e in self.selected_exes() if e in self._entries]

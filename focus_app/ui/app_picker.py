"""허용할 앱을 체크해서 고르는 대화상자 (실행 중인 앱 + 설치된 앱 + 파일 찾기 + 숨긴 앱)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

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
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from focus_app.config import friendly_name, normalize_exe
from focus_app.enforcer import SYSTEM_EXES
from focus_app.ui import app_catalog
from focus_app.ui.app_catalog import AppEntry

_ROLE_EXE = Qt.ItemDataRole.UserRole
_ROLE_HEADER = Qt.ItemDataRole.UserRole + 1  # 값: 구역 이름 ("running", "installed", "hidden" …)
_ROLE_HIDDEN = Qt.ItemDataRole.UserRole + 2  # 숨긴 앱 구역의 항목인지


class _NoAutoToggleDelegate(QStyledItemDelegate):
    """체크박스는 보통 모양 그대로 그리되, Qt가 체크박스 칸 클릭으로 스스로 토글하지는 않게 함.

    토글은 줄 클릭(_on_item_clicked) 한 곳에서만 해야 체크박스 칸을 눌렀을 때 두 번 바뀌지(=그대로) 않음.
    """

    def editorEvent(self, event, model, option, index):  # noqa: N802
        return False


class AppPickerDialog(QDialog):
    def __init__(
        self,
        mode_name: str,
        already_allowed: Iterable[str],
        running: Optional[List[AppEntry]] = None,
        parent: QWidget | None = None,
        hidden: Iterable[str] = (),
        on_hidden_changed: Optional[Callable[[List[str]], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("허용할 앱 고르기")
        self.resize(520, 640)
        self._already = {normalize_exe(a) for a in already_allowed}
        self._entries: Dict[str, AppEntry] = {}
        self._running = app_catalog.running_apps() if running is None else running
        self._extra: List[AppEntry] = []  # '직접 찾기'로 고른 앱
        self._hidden: List[str] = [normalize_exe(h) for h in hidden if normalize_exe(h)]
        self._on_hidden_changed = on_hidden_changed
        self._hidden_open = False  # 숨긴 앱 구역 펼침 여부
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
        self.list.setItemDelegate(_NoAutoToggleDelegate(self.list))
        self.list.itemChanged.connect(self._update_count)
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

        tools = QHBoxLayout()
        self.hide_btn = QPushButton("체크한 앱 숨기기")
        self.hide_btn.setToolTip("자주 안 쓰는 앱을 목록 맨 아래 '숨긴 앱'으로 보냅니다. 다음에 열어도 숨겨져 있습니다.")
        self.hide_btn.clicked.connect(self.hide_checked)
        tools.addWidget(self.hide_btn)
        self.unhide_btn = QPushButton("숨김 해제")
        self.unhide_btn.clicked.connect(self.unhide_checked)
        tools.addWidget(self.unhide_btn)
        tools.addStretch(1)
        browse = QPushButton("실행 파일(.exe) 직접 찾기…")
        browse.setObjectName("linkButton")
        browse.clicked.connect(self._browse)
        tools.addWidget(browse)
        layout.addLayout(tools)

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
    def _add_header(self, text: str, key: str, clickable: bool = False) -> QListWidgetItem:
        item = QListWidgetItem(text)
        # 숨긴 앱 머리글만 눌러서 펼치거나 접을 수 있음
        item.setFlags(Qt.ItemFlag.ItemIsEnabled if clickable else Qt.ItemFlag.NoItemFlags)
        item.setData(_ROLE_HEADER, key)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        if clickable:
            item.setToolTip("눌러서 펼치기/접기")
        self.list.addItem(item)
        return item

    def _add_entry(self, entry: AppEntry, checked: bool = False, hidden: bool = False) -> QListWidgetItem:
        self._entries[entry.exe] = entry
        allowed = entry.exe in self._already
        label = f"{entry.name}    ({entry.exe})" if entry.name.lower() != entry.exe else entry.name
        if allowed:
            label += "  · 이미 추가됨"
        item = QListWidgetItem(app_catalog.app_icon(entry.path, entry.name), label)
        item.setData(_ROLE_EXE, entry.exe)
        item.setData(_ROLE_HIDDEN, hidden)
        item.setSizeHint(QSize(0, 34))
        # 체크박스 모양을 위해 ItemIsUserCheckable은 주지만, 실제 토글은 _NoAutoToggleDelegate가 막고
        # 줄 클릭 처리(_on_item_clicked) 한 곳에서만 함
        if allowed and not hidden:
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable)  # 비활성 + 체크 표시
            item.setCheckState(Qt.CheckState.Checked)
        else:
            # 숨긴 앱은 이미 추가된 앱이어도 '숨김 해제'를 위해 체크할 수 있어야 함
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.addItem(item)
        return item

    def _checked_exes(self) -> set:
        out = set()
        for i in range(self.list.count()) if hasattr(self, "list") else ():
            item = self.list.item(i)
            exe = item.data(_ROLE_EXE)
            if exe and item.flags() & Qt.ItemFlag.ItemIsEnabled and item.checkState() == Qt.CheckState.Checked:
                out.add(exe)
        return out

    def _populate(self) -> None:
        checked = self._checked_exes()
        self.list.blockSignals(True)
        self.list.clear()
        self._entries.clear()
        hidden = set(self._hidden)
        shown = set()
        hidden_entries: Dict[str, AppEntry] = {}

        def place(entries: Iterable[AppEntry]) -> None:
            for e in entries:
                if e.exe in shown or e.exe in hidden_entries:
                    continue
                if e.exe in hidden:
                    hidden_entries[e.exe] = e
                    continue
                self._add_entry(e, e.exe in checked)
                shown.add(e.exe)

        if self._extra:
            self._add_header("직접 찾은 앱", "extra")
            place(self._extra)
        visible_running = [e for e in self._running if e.exe not in hidden]
        if visible_running:
            self._add_header("지금 실행 중인 앱", "running")
        place(sorted(self._running, key=lambda e: e.name.lower()))
        installed = app_catalog.installed_apps.get()
        self._add_header("설치된 앱", "installed")
        if installed is None:
            loading = QListWidgetItem("   설치된 앱 목록을 불러오는 중…")
            loading.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(loading)
        else:
            self._installed_shown = True
            place(installed)

        if hidden_entries:
            arrow = "▾" if self._hidden_open else "▸"
            self._add_header(f"{arrow}  숨긴 앱 ({len(hidden_entries)})", "hidden", clickable=True)
            for e in sorted(hidden_entries.values(), key=lambda e: e.name.lower()):
                self._add_entry(e, e.exe in checked, hidden=True)
        self.list.blockSignals(False)
        self._apply_filter(self.search.text() if hasattr(self, "search") else "")
        self._update_count()

    def _check_installed(self) -> None:
        if app_catalog.installed_apps.get() is not None:
            self._wait_timer.stop()
            self._populate()

    def _apply_filter(self, text: str) -> None:
        q = text.strip().lower()
        for i in range(self.list.count()):
            item = self.list.item(i)
            header = item.data(_ROLE_HEADER)
            if header or item.data(_ROLE_EXE) is None:
                item.setHidden(bool(q))
                continue
            entry = self._entries.get(item.data(_ROLE_EXE))
            hay = f"{entry.name} {entry.exe}".lower() if entry else item.text().lower()
            if q:
                item.setHidden(q not in hay)  # 검색할 때는 숨긴 앱에서도 찾아 줌
            else:
                item.setHidden(bool(item.data(_ROLE_HIDDEN)) and not self._hidden_open)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if item.data(_ROLE_HEADER) == "hidden":
            self._hidden_open = not self._hidden_open
            self._populate()
            return
        # 체크박스 칸이든 이름이든 줄 아무 곳을 눌러도 한 번만 바뀜
        if not (item.flags() & Qt.ItemFlag.ItemIsEnabled) or item.data(_ROLE_EXE) is None:
            return
        new = Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked
        item.setCheckState(new)

    def _checked_in(self, hidden: bool) -> List[str]:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            exe = item.data(_ROLE_EXE)
            if (
                exe
                and bool(item.data(_ROLE_HIDDEN)) == hidden
                and item.flags() & Qt.ItemFlag.ItemIsEnabled
                and item.checkState() == Qt.CheckState.Checked
            ):
                out.append(exe)
        return out

    def _update_count(self, *_args) -> None:
        if not hasattr(self, "ok_btn"):
            return
        n = len(self.selected_exes())
        self.ok_btn.setText(f"{n}개 추가" if n else "추가")
        self.ok_btn.setEnabled(n > 0)
        to_hide, to_unhide = len(self._checked_in(False)), len(self._checked_in(True))
        self.hide_btn.setText(f"체크한 앱 숨기기 ({to_hide})" if to_hide else "체크한 앱 숨기기")
        self.hide_btn.setEnabled(to_hide > 0)
        self.unhide_btn.setText(f"숨김 해제 ({to_unhide})" if to_unhide else "숨김 해제")
        self.unhide_btn.setVisible(to_unhide > 0)

    # ------------------------------------------------------------- 숨기기
    def hidden_apps(self) -> List[str]:
        return list(self._hidden)

    def _set_hidden(self, hidden: List[str], uncheck: Iterable[str]) -> None:
        self._hidden = hidden
        for i in range(self.list.count()):  # 옮긴 앱은 체크를 풀어 둠 (실수로 추가되지 않게)
            item = self.list.item(i)
            if item.data(_ROLE_EXE) in set(uncheck):
                item.setCheckState(Qt.CheckState.Unchecked)
        if self._on_hidden_changed is not None:
            self._on_hidden_changed(list(self._hidden))  # 바로 저장해 다음에도 숨김 유지
        self._populate()

    def hide_checked(self) -> None:
        exes = self._checked_in(False)
        if exes:
            self._set_hidden(self._hidden + [e for e in exes if e not in self._hidden], exes)

    def unhide_checked(self) -> None:
        exes = self._checked_in(True)
        if exes:
            self._set_hidden([h for h in self._hidden if h not in exes], exes)

    # ------------------------------------------------------------- 직접 찾기
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "실행 파일 선택", "C:\\Program Files", "실행 파일 (*.exe)")
        if path:
            self.add_custom(path)

    def add_custom(self, path: str) -> None:
        exe = normalize_exe(path)
        if exe in SYSTEM_EXES:
            QMessageBox.information(self, "허용 앱", f"{exe}은(는) 시스템 요소라 항상 쓸 수 있습니다. 추가하지 않아도 됩니다.")
            return
        if exe in self._hidden:  # 직접 고른 앱은 숨김에서 꺼냄
            self._set_hidden([h for h in self._hidden if h != exe], [])
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(_ROLE_EXE) == exe:
                if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                    item.setCheckState(Qt.CheckState.Checked)
                self.list.scrollToItem(item)
                return
        self._extra.append(AppEntry(exe=exe, name=friendly_name(exe), path=str(Path(path))))
        self._populate()
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(_ROLE_EXE) == exe:
                item.setCheckState(Qt.CheckState.Checked)
                self.list.scrollToItem(item)

    # ------------------------------------------------------------- 결과
    def selected_exes(self) -> List[str]:
        """추가할 앱 (이미 허용된 앱 제외). 숨긴 앱이라도 체크했으면 포함."""
        if not hasattr(self, "list"):
            return []
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            exe = item.data(_ROLE_EXE)
            if exe and exe not in self._already and item.checkState() == Qt.CheckState.Checked and exe not in out:
                out.append(exe)
        return out

    def selected_entries(self) -> List[AppEntry]:
        return [self._entries[e] for e in self.selected_exes() if e in self._entries]

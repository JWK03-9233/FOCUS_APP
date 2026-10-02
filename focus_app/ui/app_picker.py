"""허용할 앱을 체크해서 고르는 대화상자.

구역 순서: ★ 즐겨찾기 → 직접 찾은 앱 → 지금 실행 중인 앱 → 설치된 앱 → 숨긴 앱(맨 아래, 접힘)

* 줄 오른쪽 ☆를 누르면 즐겨찾기(맨 위), 줄에 마우스를 올리면 나오는 '숨기기'로 맨 아래로 보냄.
  둘 다 설정에 바로 저장되어 다음에 열어도 유지됩니다. 즐겨찾기와 숨김은 동시에 될 수 없습니다.
* 체크박스는 '이 모드에 추가할지'만 뜻합니다. 별·숨기기를 눌러도 체크는 바뀌지 않습니다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from focus_app.config import app_kind_label, friendly_name, normalize_exe
from focus_app.enforcer import SYSTEM_EXES
from focus_app.ui import app_catalog, theme
from focus_app.ui.app_catalog import AppEntry
from focus_app.ui.scroll import scroll_layout

_ROLE_EXE = Qt.ItemDataRole.UserRole
_ROLE_HEADER = Qt.ItemDataRole.UserRole + 1  # 값: 구역 이름 ("favorites", "running", "installed", "hidden" …)
_ROLE_FAVORITE = Qt.ItemDataRole.UserRole + 2  # 즐겨찾기 구역의 항목인지
_ROLE_HIDDEN = Qt.ItemDataRole.UserRole + 3  # 숨긴 앱 구역의 항목인지
_ROLE_USABLE = Qt.ItemDataRole.UserRole + 4  # 실행 파일이 있어 고를 수 있는지

STAR_WIDTH = 34  # 줄 오른쪽 끝의 즐겨찾기 별 영역
HIDE_WIDTH = 72  # 별 왼쪽의 '숨기기'/'숨김 해제' 영역
STAR_ON = QColor("#fbbf24")
STAR_OFF = QColor("#7b8296")
HIDE_TEXT = QColor("#7b8296")


def star_rect(row: QRect) -> QRect:
    return QRect(row.right() - STAR_WIDTH, row.top(), STAR_WIDTH, row.height())


def hide_rect(row: QRect) -> QRect:
    return QRect(row.right() - STAR_WIDTH - HIDE_WIDTH, row.top(), HIDE_WIDTH, row.height())


class _PickerDelegate(QStyledItemDelegate):
    """체크박스는 보통 모양 그대로 그리고, 줄 오른쪽에 '숨기기'(마우스를 올렸을 때)와 별(☆/★)을 그림.

    Qt가 체크박스 칸 클릭으로 스스로 토글하지는 않게 함: 토글은 줄 클릭(_on_item_clicked) 한 곳에서만 해야
    체크박스 칸을 눌렀을 때 두 번 바뀌지(=그대로) 않음.
    """

    def editorEvent(self, event, model, option, index):  # noqa: N802
        return False

    def paint(self, painter, option, index):
        if not index.data(_ROLE_EXE):  # 구역 머리글 등은 그대로
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        text = opt.text
        # 배경·체크박스·아이콘은 스타일이 그리고, 이름은 오른쪽 '숨기기'·별 영역 앞에서 '…'로 잘라 직접 그림
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        opt.text = text
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        text_rect.setLeft(text_rect.left() + 6)  # 아이콘과 이름 사이 간격
        text_rect.setRight(min(text_rect.right(), hide_rect(option.rect).left() - 8))
        enabled = bool(opt.state & QStyle.StateFlag.State_Enabled)
        group = QPalette.ColorGroup.Normal if enabled else QPalette.ColorGroup.Disabled
        painter.save()
        painter.setFont(opt.font)
        painter.setPen(opt.palette.color(group, QPalette.ColorRole.Text))
        elided = opt.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, max(0, text_rect.width()))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)
        painter.restore()

        hidden = bool(index.data(_ROLE_HIDDEN))
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        if hover or hidden:
            small = QFont(option.font)
            small.setPointSizeF(small.pointSizeF() * 0.9)
            painter.setFont(small)
            painter.setPen(HIDE_TEXT)
            painter.drawText(hide_rect(option.rect), Qt.AlignmentFlag.AlignCenter, "숨김 해제" if hidden else "숨기기")
        if index.data(_ROLE_USABLE):
            fav = bool(index.data(_ROLE_FAVORITE))
            big = QFont(option.font)
            big.setPointSizeF(big.pointSizeF() * 1.35)
            painter.setFont(big)
            painter.setPen(STAR_ON if fav else STAR_OFF)
            painter.drawText(star_rect(option.rect), Qt.AlignmentFlag.AlignCenter, "★" if fav else "☆")
        painter.restore()


class _RowButtonsFilter(QObject):
    """줄 오른쪽의 별·숨기기 영역 클릭을 처리 (체크 상태는 바꾸지 않음). 고를 수 없는 줄에서도 동작."""

    def __init__(self, dialog: "AppPickerDialog") -> None:
        super().__init__(dialog)
        self.dialog = dialog

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        ):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        lst = self.dialog.list
        pos = event.position().toPoint()
        item = lst.itemAt(pos)
        if item is None or not item.data(_ROLE_EXE):
            return False
        row = lst.visualItemRect(item)
        release = event.type() == QEvent.Type.MouseButtonRelease
        exe = item.data(_ROLE_EXE)
        if item.data(_ROLE_USABLE) and star_rect(row).contains(pos):
            if release:
                self.dialog.toggle_favorite(exe)
            return True  # 별·숨기기 클릭은 체크 토글로 이어지지 않게 삼킴
        if hide_rect(row).contains(pos):
            if release:
                self.dialog.toggle_hidden(exe)
            return True
        return False


class AppPickerDialog(QDialog):
    def __init__(
        self,
        mode_name: str,
        already_allowed: Iterable[str],
        running: Optional[List[AppEntry]] = None,
        parent: QWidget | None = None,
        favorites: Iterable[str] = (),
        on_favorites_changed: Optional[Callable[[List[str]], None]] = None,
        hidden: Iterable[str] = (),
        on_hidden_changed: Optional[Callable[[List[str]], None]] = None,
        app_names: Optional[Callable[[str], str]] = None,
        app_paths: Optional[Callable[[str], str]] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("허용할 앱 고르기")
        self.resize(560, 660)
        self._already = {normalize_exe(a) for a in already_allowed}
        self._entries: Dict[str, AppEntry] = {}
        self._running = app_catalog.running_apps() if running is None else running
        self._extra: List[AppEntry] = []  # '직접 찾기'로 고른 앱
        self._favorites: List[str] = list(dict.fromkeys(normalize_exe(f) for f in favorites if normalize_exe(f)))
        self._hidden: List[str] = list(dict.fromkeys(normalize_exe(h) for h in hidden if normalize_exe(h)))
        self._hidden = [h for h in self._hidden if h not in self._favorites]
        self._on_favorites_changed = on_favorites_changed
        self._on_hidden_changed = on_hidden_changed
        self._hidden_open = False  # 숨긴 앱 구역 펼침 여부
        # 지금 실행 중도 아니고 설치 목록에도 없는 즐겨찾기(예: 휴대용 앱)를 보여 줄 때 쓸 이름·경로
        self._app_names = app_names or friendly_name
        self._app_paths = app_paths or (lambda exe: "")
        self._installed_shown = False

        layout = scroll_layout(self)  # 내용이 많으면 창 전체를 스크롤
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
        self.list.setMouseTracking(True)  # 마우스를 올린 줄에만 '숨기기'를 보여 주기 위해
        self.list.setItemDelegate(_PickerDelegate(self.list))
        self.list.viewport().installEventFilter(_RowButtonsFilter(self))
        self.list.itemChanged.connect(self._update_count)
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

        tools = QHBoxLayout()
        hint = QLabel("☆ 즐겨찾기는 맨 위로 · 줄에 마우스를 올려 '숨기기'를 누르면 맨 아래로")
        hint.setObjectName("hint")
        tools.addWidget(hint, 1)
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

    def _add_entry(
        self, entry: AppEntry, checked: bool = False, favorite: bool = False, hidden: bool = False
    ) -> QListWidgetItem:
        self._entries[entry.exe] = entry
        allowed = entry.exe in self._already
        if not entry.usable:
            label = f"{entry.name}    · 실행 파일 없음"
        else:
            kind = app_kind_label(entry.exe)  # 실행 파일 이름, 웹 앱이면 'Chrome 앱'
            label = f"{entry.name}    ({kind})" if entry.name.lower() != entry.exe else entry.name
            if allowed:
                label += "  · 이미 추가됨"
        item = QListWidgetItem(app_catalog.app_icon(entry.path, entry.name), label)
        item.setData(_ROLE_EXE, entry.exe)
        item.setData(_ROLE_FAVORITE, favorite)
        item.setData(_ROLE_HIDDEN, hidden)
        item.setData(_ROLE_USABLE, entry.usable)
        item.setSizeHint(QSize(0, theme.px(30)))
        if not entry.usable:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setToolTip("실행 파일을 찾지 못해 고를 수 없습니다. 아래 '실행 파일(.exe) 직접 찾기'로 추가하세요.")
        elif allowed:
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable)  # 비활성 + 체크 표시 (별·숨기기는 따로 누를 수 있음)
            item.setCheckState(Qt.CheckState.Checked)
        else:
            # 체크박스 모양을 위해 ItemIsUserCheckable은 주지만, 실제 토글은 _PickerDelegate가 막고
            # 줄 클릭 처리(_on_item_clicked) 한 곳에서만 함
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.addItem(item)
        return item

    def _checked_exes(self) -> set:
        out = set()
        for i in range(self.list.count()):
            item = self.list.item(i)
            exe = item.data(_ROLE_EXE)
            if exe and item.flags() & Qt.ItemFlag.ItemIsEnabled and item.checkState() == Qt.CheckState.Checked:
                out.add(exe)
        return out

    def _known_entries(self) -> Dict[str, AppEntry]:
        """지금 알고 있는 모든 앱 (직접 찾은 앱 > 실행 중 > 설치된 앱 순으로 우선)."""
        known: Dict[str, AppEntry] = {}
        for e in list(self._extra) + list(self._running) + list(app_catalog.installed_apps.get() or []):
            known.setdefault(e.exe, e)
        return known

    def _entry_for(self, exe: str, known: Dict[str, AppEntry]) -> AppEntry:
        if exe in known:
            return known[exe]
        if exe.startswith("?"):  # 실행 파일 없는 항목인데 지금 목록에는 없음
            return AppEntry(exe=exe, name=exe[1:], usable=False)
        return AppEntry(exe=exe, name=self._app_names(exe), path=self._app_paths(exe))

    def _populate(self) -> None:
        checked = self._checked_exes() if hasattr(self, "list") else set()
        self.list.blockSignals(True)
        self.list.clear()
        self._entries.clear()
        known = self._known_entries()
        favorites, hidden = set(self._favorites), set(self._hidden)
        shown = set()

        if self._favorites:
            self._add_header(f"★  즐겨찾기 ({len(self._favorites)})", "favorites")
            fav_entries = [self._entry_for(exe, known) for exe in self._favorites]
            for e in sorted(fav_entries, key=lambda e: e.name.lower()):
                self._add_entry(e, e.exe in checked, favorite=True)
                shown.add(e.exe)

        def section(title: str, key: str, entries: Iterable[AppEntry]) -> None:
            rows = [e for e in entries if e.exe not in shown and e.exe not in favorites and e.exe not in hidden]
            if not rows:
                return
            self._add_header(title, key)
            for e in rows:
                if e.exe in shown:
                    continue
                self._add_entry(e, e.exe in checked)
                shown.add(e.exe)

        section("직접 찾은 앱", "extra", self._extra)
        section("지금 실행 중인 앱", "running", sorted(self._running, key=lambda e: e.name.lower()))
        installed = app_catalog.installed_apps.get()
        if installed is None:
            self._add_header("설치된 앱", "installed")
            loading = QListWidgetItem("   설치된 앱 목록을 불러오는 중…")
            loading.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(loading)
        else:
            self._installed_shown = True
            # 고를 수 있는 앱을 먼저, 실행 파일을 못 찾은 항목은 뒤에 (설치 목록이 이미 그 순서)
            section("설치된 앱", "installed", installed)

        if self._hidden:
            arrow = "▾" if self._hidden_open else "▸"
            self._add_header(f"{arrow}  숨긴 앱 ({len(self._hidden)})", "hidden", clickable=True)
            hidden_entries = [self._entry_for(exe, known) for exe in self._hidden]
            for e in sorted(hidden_entries, key=lambda e: e.name.lower()):
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
            if item.data(_ROLE_HEADER) or item.data(_ROLE_EXE) is None:
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

    def _update_count(self, *_args) -> None:
        if not hasattr(self, "ok_btn"):
            return
        n = len(self.selected_exes())
        self.ok_btn.setText(f"{n}개 추가" if n else "추가")
        self.ok_btn.setEnabled(n > 0)

    # ------------------------------------------------------------- 즐겨찾기·숨기기
    def favorite_apps(self) -> List[str]:
        return list(self._favorites)

    def hidden_apps(self) -> List[str]:
        return list(self._hidden)

    def _save(self, favorites_changed: bool, hidden_changed: bool) -> None:
        # 바로 저장해 다음에 열어도 그대로 보이게
        if favorites_changed and self._on_favorites_changed is not None:
            self._on_favorites_changed(list(self._favorites))
        if hidden_changed and self._on_hidden_changed is not None:
            self._on_hidden_changed(list(self._hidden))
        self._populate()

    def toggle_favorite(self, exe: str) -> None:
        """즐겨찾기를 켜고 끕니다. 숨겨 둔 앱을 즐겨찾기하면 숨김에서 꺼냅니다. 체크는 그대로."""
        exe = normalize_exe(exe)
        unhid = exe in self._hidden
        if exe in self._favorites:
            self._favorites = [f for f in self._favorites if f != exe]
        else:
            self._favorites = self._favorites + [exe]
            self._hidden = [h for h in self._hidden if h != exe]
        self._save(True, unhid)

    def toggle_hidden(self, exe: str) -> None:
        """숨기기/숨김 해제. 즐겨찾기를 숨기면 즐겨찾기에서 뺍니다. 체크는 그대로."""
        exe = normalize_exe(exe)
        unfav = exe in self._favorites
        if exe in self._hidden:
            self._hidden = [h for h in self._hidden if h != exe]
        else:
            self._hidden = self._hidden + [exe]
            self._favorites = [f for f in self._favorites if f != exe]
        self._save(unfav, True)

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
            self._hidden = [h for h in self._hidden if h != exe]
            self._save(False, True)
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
        """추가할 앱 (이미 허용된 앱, 실행 파일 없는 항목 제외)."""
        if not hasattr(self, "list"):
            return []
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            exe = item.data(_ROLE_EXE)
            if (
                exe
                and item.data(_ROLE_USABLE)
                and exe not in self._already
                and item.checkState() == Qt.CheckState.Checked
                and exe not in out
            ):
                out.append(exe)
        return out

    def selected_entries(self) -> List[AppEntry]:
        return [self._entries[e] for e in self.selected_exes() if e in self._entries]

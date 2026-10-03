"""메인 창: 모드(허용 앱 묶음) 편집 → 시간 고르기 → 집중 시작 → 진행 화면.

이 창은 화면만 담당하고, 실제 세션 시작/해제는 시그널로 컨트롤러(app.py)에 맡깁니다.
"""

from __future__ import annotations

import time
from typing import List, Optional

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from focus_app import web_apps
from focus_app.config import Profile, Settings, app_kind_label
from focus_app.session import FocusSession, format_duration, format_minutes
from focus_app.ui import app_catalog, icons, theme
from focus_app.ui.app_picker import AppPickerDialog
from focus_app.ui.preset_dialog import PresetDialog
from focus_app.ui.scroll import ExpandedList, WindowScroll
from focus_app.ui.site_list import SiteEditor
from focus_app.ui.theme import SUCCESS
from focus_app.version import APP_NAME, __version__

CUSTOM_ID = 100000  # 분 값(최대 1440)과 겹치지 않는 id. -1은 Qt가 "자동 지정"으로 해석해 쓰면 안 됨
UNLIMITED_ID = 0
OPEN_ROLE = Qt.ItemDataRole.UserRole + 1  # 진행 화면의 허용 앱이 지금 실행 중인지
SITE_ROLE = Qt.ItemDataRole.UserRole + 2  # 진행 화면의 허용 사이트 주소


def _label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def format_clock(seconds: int) -> str:
    """큰 타이머 표시용: 42:13 또는 1:42:13."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def format_end_time(ts: float) -> str:
    t = time.localtime(ts)
    ampm = "오전" if t.tm_hour < 12 else "오후"
    hour = t.tm_hour % 12 or 12
    return f"{ampm} {hour}:{t.tm_min:02d}"


def mode_summary(profile: Profile) -> str:
    if not profile.block_everything:
        return "차단 없음"
    n = len(profile.normalized_apps())
    text = f"앱 {n}개 허용" if n else "허용한 앱 없음"
    if profile.limits_sites():
        text += f" · 사이트 {len(profile.normalized_sites())}개"
    return text


class AppRow(QWidget):
    """허용 앱 목록의 한 줄: 아이콘, 이름, 실행 파일 이름, 빼기 버튼."""

    def __init__(self, name: str, exe: str, path: str, on_remove, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 4, 4)
        row.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(app_catalog.app_icon(path, name).pixmap(24, 24))
        row.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(0)
        title = QLabel(name)
        title.setStyleSheet("font-weight: 600;")
        text.addWidget(title)
        text.addWidget(_label(app_kind_label(exe), "hint"))  # 실행 파일 이름, 웹 앱이면 'Chrome 앱'
        row.addLayout(text, 1)
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("iconButton")
        self.remove_btn.setToolTip("이 앱을 목록에서 빼기")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: on_remove(exe))
        row.addWidget(self.remove_btn)


class ModeRow(QWidget):
    """모드 목록의 한 줄: 모드 이름과 요약 (예: "앱 5개 허용")."""

    def __init__(self, profile: Profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 8, 8, 8)
        col.setSpacing(2)
        title = QLabel(profile.name)
        title.setObjectName("modeRowTitle")
        col.addWidget(title)
        summary = _label(mode_summary(profile), "hint")
        summary.setStyleSheet("background: transparent;")
        col.addWidget(summary)


class _LaunchCursorFilter(QObject):
    """'지금 쓸 수 있는 앱' 목록에서 앱 위에 있을 때만 손가락 모양 커서, 빈 곳에서는 보통 화살표."""

    def __init__(self, view: QListWidget) -> None:
        super().__init__(view)
        self.view = view
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)

    def over_app(self, pos) -> bool:
        item = self.view.itemAt(pos)
        return item is not None and bool(item.data(Qt.ItemDataRole.UserRole) or item.data(SITE_ROLE))

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.MouseMove:
            if self.over_app(event.position().toPoint()):
                obj.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                obj.unsetCursor()
        elif event.type() == QEvent.Type.Leave:
            obj.unsetCursor()
        return False


class _PageStack(QStackedWidget):
    """보이는 화면의 크기만 따르는 화면 묶음.

    QStackedWidget은 가장 큰 화면에 크기를 맞추므로, 앱 목록을 다 펼친 설정 화면 때문에 진행 화면 밑에 큰 빈칸과
    쓸데없는 스크롤이 생겼습니다. 창 전체 스크롤(WindowScroll)이 묻는 크기를 지금 화면 기준으로 답합니다.
    """

    def _current(self) -> Optional[QWidget]:
        return self.currentWidget()

    def sizeHint(self) -> QSize:  # noqa: N802
        page = self._current()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        page = self._current()
        return page.minimumSizeHint() if page is not None else super().minimumSizeHint()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        page = self._current()
        return page.hasHeightForWidth() if page is not None else False

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        page = self._current()
        return page.heightForWidth(width) if page is not None else -1


class _RunAppDelegate(QStyledItemDelegate):
    """'지금 쓸 수 있는 앱' 항목: 앱이 실행 중이면 이름 오른쪽에 작은 점 (Dock처럼)."""

    DOT = 6
    GAP = 14  # 점이 들어갈 자리. 점이 생기고 없어질 때 목록이 출렁이지 않게 항상 비워 둠

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        size = super().sizeHint(option, index)
        if index.data(Qt.ItemDataRole.UserRole):
            size.setWidth(size.width() + self.GAP)
        return size

    def paint(self, painter: QPainter, option, index) -> None:
        super().paint(painter, option, index)
        if not index.data(OPEN_ROLE):
            return
        # 이름 바로 뒤에 붙여야 옆 앱의 점으로 보이지 않음
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        text_end = text_rect.left() + min(text_rect.width(), opt.fontMetrics.horizontalAdvance(opt.text))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(SUCCESS))  # 실행 중 = 에메랄드 점
        x = text_end + 6
        y = option.rect.center().y() - self.DOT / 2 + 1
        painter.drawEllipse(int(x), int(y), self.DOT, self.DOT)
        painter.restore()


class MainWindow(QMainWindow):
    start_requested = Signal(str, object)  # 모드 이름, 분(None이면 제한 없음)
    stop_requested = Signal()
    cancel_emergency_requested = Signal()  # 예전 버전에서 요청해 둔 비상 해제가 남아 있을 때만 쓰임
    launch_app_requested = Signal(str)  # 진행 화면에서 허용 앱을 눌렀을 때 (실행 파일 이름)
    settings_changed = Signal()
    preferences_requested = Signal()
    quit_requested = Signal()
    update_requested = Signal()
    edit_apps_requested = Signal()  # 집중 중 허용 앱 편집 (해제 문자열 필요)
    remove_apps_requested = Signal()  # 집중 중 허용 앱·사이트 빼기만 (해제 문자열 없이)
    add_time_requested = Signal()  # 집중 중 시간 추가 (해제 문자열 없이)
    change_mode_requested = Signal()  # 집중 중 모드 변경 (짧은 해제 문자열 필요)
    open_site_requested = Signal(str)  # 진행 화면에서 허용 사이트를 눌렀을 때 (사이트 주소)
    restart_browsers_requested = Signal()  # 사이트 제한을 적용하려고 브라우저 다시 시작

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._open_apps: set = set()  # 지금 실행 중인 앱 (진행 화면의 점 표시용)
        self.helper_installed: Optional[bool] = None  # 관리자 권한 도우미 설치 여부 (컨트롤러가 알려 줌)
        self._notice_action = None
        self._restoring = True  # 화면을 채우는 동안에는 선택 변경을 저장하지 않음
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.resize(860, 640)
        self.setMinimumSize(720, 560)
        self.allow_close = False  # True면 창을 닫을 때 숨기지 않고 실제로 닫음 (종료 시)
        self.on_hidden_to_tray = None  # 창을 닫아 트레이로 숨길 때 호출할 콜백

        self.stack = _PageStack()
        self.setCentralWidget(WindowScroll(self.stack))  # 내용이 화면보다 크면 창 전체를 스크롤
        self.setup_page = self._build_setup_page()
        self.running_page = self._build_running_page()
        self.stack.addWidget(self.setup_page)
        self.stack.addWidget(self.running_page)
        self._show_page(self.setup_page)

        self.reload_modes(select=settings.active_profile)
        self._rebuild_chips()
        self._restoring = False
        self._restore_geometry()

    # ================================================================ 준비 화면
    def _build_setup_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        # --- 머리글: 설정·업데이트는 왼쪽, 종료는 오른쪽 (앱 이름·설명은 창 제목과 트레이에 있으니 생략)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.prefs_btn = QPushButton("⚙  설정")
        self.prefs_btn.clicked.connect(self.preferences_requested.emit)
        header.addWidget(self.prefs_btn)
        self.update_btn = QPushButton("업데이트 확인")
        self.update_btn.setToolTip(f"현재 버전 v{__version__}")
        self.update_btn.clicked.connect(self.update_requested.emit)
        header.addWidget(self.update_btn)
        header.addStretch(1)
        quit_btn = QPushButton("종료")  # 끄는 버튼은 실수로 누르지 않게 오른쪽 끝에 따로
        quit_btn.setToolTip("FocusApp을 완전히 끕니다 (창을 닫으면 트레이에서 계속 실행됩니다)")
        quit_btn.clicked.connect(self.quit_requested.emit)
        header.addWidget(quit_btn)
        root.addLayout(header)

        # --- 알림 띠 (집중이 끝났을 때 등)
        self.notice = QFrame()
        self.notice.setObjectName("notice")
        nl = QHBoxLayout(self.notice)
        nl.setContentsMargins(12, 8, 6, 8)
        self.notice_label = _label(wrap=True)
        nl.addWidget(self.notice_label, 1)
        self.notice_btn = QPushButton("")
        self.notice_btn.setObjectName("secondary")
        self.notice_btn.clicked.connect(self._on_notice_action)
        self.notice_btn.hide()
        nl.addWidget(self.notice_btn)
        close_notice = QPushButton("✕")
        close_notice.setObjectName("iconButton")
        close_notice.clicked.connect(self.notice.hide)
        nl.addWidget(close_notice)
        self.notice.hide()
        root.addWidget(self.notice)

        # --- 도우미 경고 띠: 고른 모드가 사이트 제한을 쓰는데 관리자 권한 도우미가 없을 때 (시작 전에 미리 알림)
        self.helper_banner = QFrame()
        self.helper_banner.setObjectName("banner")
        hl = QHBoxLayout(self.helper_banner)
        hl.setContentsMargins(12, 8, 8, 8)
        hl.addWidget(_label(
            "⚠ 관리자 권한 도우미가 설치되어 있지 않아 이 모드의 사이트 제한을 쓸 수 없습니다. "
            "이대로 시작하면 브라우저가 모두 최소화됩니다.", wrap=True,
        ), 1)
        install = QPushButton("⚙  설정에서 설치")
        install.setCursor(Qt.CursorShape.PointingHandCursor)
        install.clicked.connect(self.preferences_requested.emit)
        hl.addWidget(install)
        self.helper_banner.hide()
        root.addWidget(self.helper_banner)

        # --- 본문: 왼쪽 모드 목록 / 오른쪽 모드 편집
        body = QHBoxLayout()
        body.setSpacing(12)

        left = _card()
        left.setProperty("leftPanel", True)  # 너비는 theme에서 (화면 크기에 따라 같이 커짐)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(10, 12, 10, 10)
        ll.addWidget(_label("① 모드 고르기", "sectionTitle"))
        self.mode_list = QListWidget()
        self.mode_list.setObjectName("modeList")
        self.mode_list.currentItemChanged.connect(self._on_mode_selected)
        # 드래그해서 모드 순서 바꾸기. 옮긴 뒤 목록을 다시 그려 각 줄의 위젯이 제자리에 오게 함
        self.mode_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.mode_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.mode_list.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._on_modes_reordered))
        ll.addWidget(self.mode_list, 1)
        self.add_mode_btn = QPushButton("+  새 모드 만들기")
        self.add_mode_btn.setObjectName("secondary")
        self.add_mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_mode_btn.clicked.connect(self._add_mode)
        ll.addWidget(self.add_mode_btn)
        body.addWidget(left)

        right = _card()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 12, 16, 12)
        rl.setSpacing(8)
        title_row = QHBoxLayout()
        self.mode_title = _label("", "modeTitle")
        title_row.addWidget(self.mode_title, 1)
        self.rename_btn = QPushButton("이름 바꾸기")
        self.rename_btn.setObjectName("linkButton")
        self.rename_btn.clicked.connect(self._rename_mode)
        title_row.addWidget(self.rename_btn)
        self.delete_btn = QPushButton("모드 삭제")
        self.delete_btn.setObjectName("linkButton")
        self.delete_btn.clicked.connect(self._delete_mode)
        title_row.addWidget(self.delete_btn)
        rl.addLayout(title_row)

        self.block_radio = QRadioButton("고른 앱만 쓰기  —  목록에 없는 앱은 자동으로 최소화")
        self.free_radio = QRadioButton("아무것도 막지 않기  —  시간만 잽니다")
        group = QButtonGroup(self)
        group.addButton(self.block_radio)
        group.addButton(self.free_radio)
        self.block_radio.toggled.connect(self._on_block_toggled)
        rl.addWidget(self.block_radio)
        rl.addWidget(self.free_radio)

        # ② 쓸 앱 / 쓸 사이트: 탭처럼 하나씩 보여 줌 (한 화면에 같이 두면 목록이 너무 좁아짐)
        apps_header = QHBoxLayout()
        apps_header.setSpacing(6)
        self.apps_title = QPushButton("② 쓸 앱")
        self.sites_title = QPushButton("쓸 사이트")
        self.list_tabs = QButtonGroup(self)
        for i, btn in enumerate((self.apps_title, self.sites_title)):
            btn.setObjectName("chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.list_tabs.addButton(btn, i)
            apps_header.addWidget(btn)
        self.apps_title.setChecked(True)
        self.list_tabs.idClicked.connect(self._show_list_tab)
        apps_header.addStretch(1)
        self.add_app_btn = QPushButton("+  앱 추가")
        self.add_app_btn.setObjectName("secondary")
        self.add_app_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_app_btn.clicked.connect(self._add_apps)
        apps_header.addWidget(self.add_app_btn)
        rl.addSpacing(6)
        rl.addLayout(apps_header)

        self.list_pages = QStackedWidget()
        apps_page = QWidget()
        al = QVBoxLayout(apps_page)
        al.setContentsMargins(0, 0, 0, 0)
        self.apps_stack = QStackedWidget()
        self.app_list = ExpandedList()  # 안쪽 스크롤 없이 모두 펼침 (넘치면 창 전체 스크롤)
        self.app_list.setObjectName("appList")
        self.app_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.apps_stack.addWidget(self.app_list)
        self.apps_empty = _label("", "muted", wrap=True)
        self.apps_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apps_stack.addWidget(self.apps_empty)
        al.addWidget(self.apps_stack, 1)
        al.addWidget(
            _label("작업 표시줄, 시작 메뉴, 작업 관리자, Windows 설정은 목록과 상관없이 항상 쓸 수 있습니다.", "hint", True)
        )
        self.list_pages.addWidget(apps_page)
        self.site_editor = SiteEditor()
        self.site_editor.changed.connect(self._on_sites_changed)
        self.site_editor.library_changed.connect(self._on_site_library_changed)
        self.list_pages.addWidget(self.site_editor)
        rl.addWidget(self.list_pages, 1)
        body.addWidget(right, 1)
        root.addLayout(body, 1)

        # --- 아래: 시간 고르기 + 시작
        bottom = _card()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.addWidget(_label("③ 집중할 시간", "sectionTitle"))
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chips_layout = chips
        self.duration_group = QButtonGroup(self)
        self.duration_group.setExclusive(True)
        self._preset_buttons: List[QPushButton] = []  # 사용자 시간 버튼 (맨 앞에 끼워 넣음)
        chips.addWidget(self._chip("직접 입력", CUSTOM_ID))
        self.custom_spin = QSpinBox()
        self.custom_spin.setRange(1, 1440)
        self.custom_spin.setSuffix(" 분")
        self.custom_spin.setValue(self.settings.custom_duration_minutes)
        self.custom_spin.valueChanged.connect(self._on_custom_changed)
        chips.addWidget(self.custom_spin)
        chips.addWidget(self._chip("끝낼 때까지", UNLIMITED_ID))
        self.edit_presets_btn = QPushButton("✎ 편집")
        self.edit_presets_btn.setObjectName("linkButton")
        self.edit_presets_btn.setToolTip("시간 버튼 목록을 바꿉니다")
        self.edit_presets_btn.clicked.connect(self._edit_presets)
        chips.addWidget(self.edit_presets_btn)
        chips.addStretch(1)
        self.duration_group.idToggled.connect(self._on_duration_changed)
        bl.addLayout(chips)

        start_row = QHBoxLayout()
        self.start_summary = _label("", "muted", wrap=True)
        start_row.addWidget(self.start_summary, 1)
        self.start_btn = QPushButton("▶   집중 시작")
        self.start_btn.setObjectName("primary")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._request_start)
        start_row.addWidget(self.start_btn)
        bl.addLayout(start_row)
        root.addWidget(bottom)
        return page

    def _chip(self, text: str, minutes: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("chip")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.duration_group.addButton(btn, minutes)
        return btn

    # ------------------------------------------------------------- 모드 목록
    def current_mode(self) -> Optional[Profile]:
        item = self.mode_list.currentItem()
        if item is None:
            return None
        return self.settings.get_profile(item.data(Qt.ItemDataRole.UserRole))

    def reload_modes(self, select: Optional[str] = None) -> None:
        current = self.current_mode()
        select = select or (current.name if current else self.settings.active_profile)
        self.mode_list.blockSignals(True)
        self.mode_list.clear()
        target = None
        for p in self.settings.profiles:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, p.name)
            item.setSizeHint(QSize(0, theme.px(54)))
            self.mode_list.addItem(item)
            self.mode_list.setItemWidget(item, ModeRow(p))
            if p.name == select:
                target = item
        self.mode_list.blockSignals(False)
        self.mode_list.setCurrentItem(target or self.mode_list.item(0))
        self._show_mode()

    def _on_modes_reordered(self) -> None:
        names = [self.mode_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.mode_list.count())]
        if names == [p.name for p in self.settings.profiles]:
            return
        self.settings.reorder_profiles(names)
        self.settings_changed.emit()
        self.reload_modes()

    def _refresh_mode_item(self) -> None:
        item = self.mode_list.currentItem()
        p = self.current_mode()
        if item is not None and p is not None:
            self.mode_list.setItemWidget(item, ModeRow(p))

    def _on_mode_selected(self, *_args) -> None:
        p = self.current_mode()
        if p is not None and p.name != self.settings.active_profile:
            self.settings.active_profile = p.name
            self.settings_changed.emit()
        self._show_mode()

    def _show_mode(self) -> None:
        p = self.current_mode()
        if p is None:
            return
        self.mode_title.setText(p.name)
        self.delete_btn.setEnabled(len(self.settings.profiles) > 1)
        for radio in (self.block_radio, self.free_radio):
            radio.blockSignals(True)
        self.block_radio.setChecked(p.block_everything)
        self.free_radio.setChecked(not p.block_everything)
        for radio in (self.block_radio, self.free_radio):
            radio.blockSignals(False)
        self._reload_apps()
        self._update_start_summary()

    def _reload_sites(self) -> None:
        p = self.current_mode()
        if p is None:
            return
        self.sites_title.setVisible(p.block_everything)
        if not p.block_everything:
            self._show_list_tab(0)
        self._update_sites_title(p)
        self.site_editor.set_values(p.restrict_sites, p.normalized_sites(), self.settings.saved_sites)
        self.site_editor.set_context(p.normalized_apps(), self.helper_installed)

    def _update_sites_title(self, p: Profile) -> None:
        n = len(p.normalized_sites())
        self.sites_title.setText(f"쓸 사이트  ({n}개)" if p.restrict_sites else "쓸 사이트  (제한 없음)")

    def _show_list_tab(self, index: int) -> None:
        """② 쓸 앱(0) / 쓸 사이트(1) 중 하나를 보여 줍니다."""
        self.list_tabs.button(index).setChecked(True)
        self.list_pages.setCurrentIndex(index)
        self.add_app_btn.setVisible(index == 0)

    def set_helper_installed(self, installed: Optional[bool]) -> None:
        """관리자 권한 도우미가 설치돼 있는지 (사이트 제한 경고 문구용)."""
        self.helper_installed = installed
        p = self.current_mode()
        if p is not None:
            self.site_editor.set_context(p.normalized_apps(), installed)
            self._update_start_summary()

    def _on_sites_changed(self) -> None:
        p = self.current_mode()
        if p is None:
            return
        p.restrict_sites = self.site_editor.restrict
        p.allowed_sites = list(self.site_editor.sites)
        self.settings_changed.emit()
        self._update_sites_title(p)
        self._refresh_mode_item()
        self._update_start_summary()

    def _on_site_library_changed(self) -> None:
        library = list(self.site_editor.library)
        gone = [s for s in self.settings.saved_sites if s not in library]
        self.settings.saved_sites = library
        # 저장한 목록에서 지운 사이트는 다른 모드에서도 뺌 (안 그러면 다음에 다시 나타남)
        for profile in self.settings.profiles:
            for site in gone:
                profile.remove_site(site)
        self.settings_changed.emit()

    def _reload_apps(self) -> None:
        p = self.current_mode()
        self.app_list.clear()
        if p is None:
            return
        self._reload_sites()
        apps = p.normalized_apps()
        self.add_app_btn.setEnabled(p.block_everything)
        if not p.block_everything:
            self.apps_title.setText("② 쓸 앱")
            self.apps_empty.setText("이 모드는 아무 앱도 막지 않습니다.\n집중 시간만 재고 싶을 때 쓰세요.")
            self.apps_stack.setCurrentWidget(self.apps_empty)
            return
        self.apps_title.setText(f"② 쓸 앱  ({len(apps)}개)")
        if not apps:
            self.apps_empty.setText(
                "아직 고른 앱이 없습니다.\n\n오른쪽 위 '+ 앱 추가'를 눌러\n집중할 때 쓸 앱을 고르세요."
            )
            self.apps_stack.setCurrentWidget(self.apps_empty)
            return
        for exe in apps:
            row = AppRow(self.settings.app_display_name(exe), exe, self._app_path(exe), self._remove_app)
            self.app_list.add_row(row, 40)
        self.apps_stack.setCurrentWidget(self.app_list)

    def _app_path(self, exe: str) -> str:
        """아이콘용 경로: 저장된 경로가 없으면 설치된 앱 목록에서 찾아 기억해 둡니다."""
        path = self.settings.app_path(exe)
        if not path:
            path = app_catalog.find_installed_path(exe)
            if path:
                self.settings.remember_app(exe, path=path)
        return path

    # ------------------------------------------------------------- 모드 편집
    def _add_mode(self) -> None:
        name, ok = QInputDialog.getText(self, "새 모드", "모드 이름 (예: 시험 공부, 글쓰기):")
        if not ok or not name.strip():
            return
        try:
            self.settings.add_profile(name)
        except ValueError as exc:
            QMessageBox.warning(self, "새 모드", str(exc))
            return
        self.settings_changed.emit()
        self.reload_modes(select=name.strip())
        self._add_apps()  # 만들자마자 쓸 앱을 고르게 함

    def _rename_mode(self) -> None:
        p = self.current_mode()
        if p is None:
            return
        name, ok = QInputDialog.getText(self, "이름 바꾸기", "새 이름:", text=p.name)
        if not ok:
            return
        try:
            self.settings.rename_profile(p.name, name)
        except ValueError as exc:
            QMessageBox.warning(self, "이름 바꾸기", str(exc))
            return
        self.settings_changed.emit()
        self.reload_modes(select=name.strip())

    def _delete_mode(self) -> None:
        p = self.current_mode()
        if p is None:
            return
        answer = QMessageBox.question(self, "모드 삭제", f"'{p.name}' 모드를 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.settings.remove_profile(p.name)
        except ValueError as exc:
            QMessageBox.warning(self, "모드 삭제", str(exc))
            return
        self.settings_changed.emit()
        self.reload_modes(select=self.settings.active_profile)

    def _on_block_toggled(self, on: bool) -> None:
        p = self.current_mode()
        if p is None:
            return
        p.block_everything = on
        self.settings_changed.emit()
        self._refresh_mode_item()
        self._reload_apps()
        self._update_start_summary()

    def _add_apps(self) -> None:
        p = self.current_mode()
        if p is None or not p.block_everything:
            return
        dlg = AppPickerDialog(
            p.name,
            p.normalized_apps(),
            parent=self,
            favorites=self.settings.favorite_apps,
            on_favorites_changed=self._save_favorite_apps,
            hidden=self.settings.hidden_apps,
            on_hidden_changed=self._save_hidden_apps,
            app_names=self.settings.app_display_name,
            app_paths=self._app_path,
        )
        try:
            if dlg.exec() != AppPickerDialog.DialogCode.Accepted:
                return
            entries = dlg.selected_entries()
        finally:
            dlg.deleteLater()  # 부모(메인 창)에 붙은 채 쌓이지 않도록 정리
        self.add_entries(p, entries)

    def _save_favorite_apps(self, favorites: List[str]) -> None:
        self.settings.favorite_apps = list(favorites)
        self.settings_changed.emit()

    def _save_hidden_apps(self, hidden: List[str]) -> None:
        self.settings.hidden_apps = list(hidden)
        self.settings_changed.emit()

    def add_entries(self, profile: Profile, entries: List[app_catalog.AppEntry]) -> None:
        for e in entries:
            profile.add_app(e.exe)
            self.settings.remember_app(e.exe, e.name, e.path)
        # 웹 앱(Google Keep 등)의 주소는 사이트 목록에 넣지 않고 기억만 함 (사이트 제한 때 뒤에서 허용)
        web_apps.learn_sites(self.settings, [e.exe for e in entries])
        self.settings_changed.emit()
        self._refresh_mode_item()
        self._reload_apps()
        self._update_start_summary()

    def _remove_app(self, exe: str) -> None:
        p = self.current_mode()
        if p is None:
            return
        p.remove_app(exe)
        self.settings_changed.emit()
        self._refresh_mode_item()
        self._reload_apps()
        self._update_start_summary()

    # ------------------------------------------------------------- 시간/시작
    def _rebuild_chips(self) -> None:
        """설정의 시간 목록대로 버튼을 다시 만들고, 마지막으로 고른 시간을 선택합니다."""
        for btn in self._preset_buttons:
            self.duration_group.removeButton(btn)
            self.chips_layout.removeWidget(btn)
            btn.deleteLater()
        self._preset_buttons = []
        for i, minutes in enumerate(self.settings.duration_presets):
            btn = self._chip(format_minutes(minutes), minutes)
            self.chips_layout.insertWidget(i, btn)
            self._preset_buttons.append(btn)
        self._select_duration(self.settings.default_duration_minutes)

    def _select_duration(self, minutes: Optional[int]) -> None:
        """minutes가 None 또는 0이면 "끝낼 때까지", 버튼에 없는 값이면 "직접 입력"."""
        restoring, self._restoring = self._restoring, True
        if not minutes:
            self.duration_group.button(UNLIMITED_ID).setChecked(True)
        elif self.duration_group.button(minutes) is not None:
            self.duration_group.button(minutes).setChecked(True)
        else:
            self.custom_spin.setValue(minutes)
            self.duration_group.button(CUSTOM_ID).setChecked(True)
        self._restoring = restoring
        self._on_duration_changed()

    def _on_duration_changed(self, *_args) -> None:
        self.custom_spin.setVisible(self.duration_group.checkedId() == CUSTOM_ID)
        self._update_start_summary()
        self._remember_duration()

    def _on_custom_changed(self, value: int) -> None:
        if not self._restoring:
            self.settings.custom_duration_minutes = int(value)
        self._update_start_summary()
        self._remember_duration()

    def _remember_duration(self) -> None:
        """고른 시간을 바로 저장해 다음에 열 때도 같은 시간이 선택되게 합니다."""
        if self._restoring or self.duration_group.checkedId() == -1:
            return
        minutes = self.selected_minutes()
        value = 0 if minutes is None else minutes
        if value != self.settings.default_duration_minutes:
            self.settings.default_duration_minutes = value
            self.settings_changed.emit()
        elif self.duration_group.checkedId() == CUSTOM_ID:
            self.settings_changed.emit()  # 직접 입력 값만 바뀐 경우

    def _edit_presets(self) -> None:
        dlg = PresetDialog(self.settings.duration_presets, parent=self)
        try:
            if dlg.exec() != PresetDialog.DialogCode.Accepted:
                return
            presets = dlg.presets()
        finally:
            dlg.deleteLater()
        self.settings.duration_presets = presets
        self.settings_changed.emit()
        self._rebuild_chips()

    def selected_minutes(self) -> Optional[int]:
        bid = self.duration_group.checkedId()
        if bid == UNLIMITED_ID:
            return None
        if bid == CUSTOM_ID:
            return int(self.custom_spin.value())
        return bid if bid > 0 else self.settings.duration_presets[0]

    def _update_start_summary(self, *_args) -> None:
        p = self.current_mode()
        if p is None:
            return
        minutes = self.selected_minutes()
        when = "직접 끝낼 때까지" if minutes is None else format_duration(minutes * 60).replace(" 00초", "")
        if not p.block_everything:
            what = "아무 앱도 막지 않습니다"
        else:
            n = len(p.normalized_apps())
            what = f"고른 앱 {n}개만 쓸 수 있습니다" if n else "⚠ 고른 앱이 없어 거의 모든 앱이 최소화됩니다"
            if p.limits_sites():
                k = len(p.normalized_sites())
                what += f" · 브라우저에서는 사이트 {k}개만" if k else " · 브라우저에서 사이트를 열 수 없습니다"
        self.start_summary.setText(f"<b>{p.name}</b> · {when}<br>{what}")
        # 확인 전(None)에는 띄우지 않음
        self.helper_banner.setVisible(self.helper_installed is False and p.limits_sites())

    def _request_start(self) -> None:
        p = self.current_mode()
        if p is None:
            return
        minutes = self.selected_minutes()
        if not self._confirm_start(p, minutes):
            return
        self.start_requested.emit(p.name, minutes)

    def _confirm_start(self, p: Profile, minutes: Optional[int]) -> bool:
        when = "직접 끝낼 때까지" if minutes is None else f"{minutes}분 동안"
        if p.block_everything:
            names = [self.settings.app_display_name(a) for a in p.normalized_apps()]
            apps = ", ".join(names[:6]) + (f" 외 {len(names) - 6}개" if len(names) > 6 else "")
            body = (
                f"<b>{p.name}</b> 모드로 {when} 집중합니다.<br><br>"
                f"쓸 수 있는 앱: {apps or '(없음)'}<br>"
                "그 밖의 앱은 앞에 나오면 바로 최소화됩니다.<br><br>"
                + self._sites_confirm_text(p)
                + f"중간에 끝내려면 <b>{self.settings.unlock_code_length}글자 랜덤 문자열</b>을 직접 입력해야 합니다."
            )
        else:
            body = f"<b>{p.name}</b> 모드로 {when} 집중합니다. 앱은 막지 않습니다."
        box = QMessageBox(QMessageBox.Icon.Question, "집중 시작", body, parent=self)
        box.setTextFormat(Qt.TextFormat.RichText)
        start = box.addButton("시작", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(start)
        try:
            box.exec()
            return box.clickedButton() is start
        finally:
            box.deleteLater()

    def _sites_confirm_text(self, p: Profile) -> str:
        """집중 시작 확인 창의 사이트 제한 안내 (사이트 제한을 안 쓰면 빈 문자열)."""
        if not p.limits_sites():
            return ""
        sites = [s.lstrip(".") for s in p.normalized_sites()]
        text = ", ".join(sites[:6]) + (f" 외 {len(sites) - 6}개" if len(sites) > 6 else "")
        out = f"브라우저에서 열 수 있는 사이트: {text or '(없음)'}<br>"
        if self.helper_installed is False:
            out += "⚠ 관리자 권한 도우미가 없어 사이트 제한을 쓸 수 없어, 브라우저가 모두 최소화됩니다.<br>"
        else:
            out += "열려 있는 브라우저는 다시 시작해야 사이트 제한이 적용됩니다.<br>"
        return out + "<br>"

    def set_update_available(self, version: Optional[str]) -> None:
        """새 버전이 있으면 머리글 버튼을 눈에 띄게 바꿉니다."""
        if version:
            self.update_btn.setText(f"⬆  새 버전 v{version}")
            self.update_btn.setObjectName("secondary")
        else:
            self.update_btn.setText("업데이트 확인")
            self.update_btn.setObjectName("")
        self.update_btn.style().unpolish(self.update_btn)
        self.update_btn.style().polish(self.update_btn)

    def show_notice(self, text: str, action_text: str = "", on_action=None) -> None:
        """알림 띠를 보여 줍니다. action_text를 주면 오른쪽에 그 버튼을 달고, 누르면 on_action을 부름."""
        self.notice_label.setText(text)
        self._notice_action = on_action if action_text else None
        self.notice_btn.setText(action_text)
        self.notice_btn.setVisible(bool(action_text))
        self.notice.show()

    def _on_notice_action(self) -> None:
        action = self._notice_action
        self.notice.hide()
        if action is not None:
            action()

    # ================================================================ 진행 화면
    def _build_running_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(20, 16, 20, 20)

        card = _card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 28, 32, 24)
        cl.setSpacing(6)

        caption = _label("집중하는 중", "muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(caption)
        self.run_mode = _label("", "runningMode")
        self.run_mode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.run_mode)
        self.timer_caption = _label("남은 시간", "muted")
        self.timer_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addSpacing(8)
        cl.addWidget(self.timer_caption)
        self.timer_label = _label("00:00", "timer")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.timer_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        cl.addWidget(self.progress)
        self.run_info = _label("", "muted")
        self.run_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(self.run_info)

        cl.addSpacing(14)
        self.run_apps_title = _label("지금 쓸 수 있는 앱", "sectionTitle")
        cl.addWidget(self.run_apps_title)
        # 허용 앱·사이트는 스크롤 없이 모두 보여 줌 (ExpandedList가 높이를 내용에 맞춤)
        self.run_apps = ExpandedList(wrapping=True)
        self.run_apps.setObjectName("runList")  # 진행 화면용: 아이콘·글자를 크게 (theme)
        self.run_apps.setSpacing(6)
        self.run_apps.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.run_apps.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._run_apps_cursor = _LaunchCursorFilter(self.run_apps)
        self.run_apps.setItemDelegate(_RunAppDelegate(self.run_apps))
        self.run_apps.itemClicked.connect(self._on_run_app_clicked)
        cl.addWidget(self.run_apps)

        self.run_sites_title = _label("지금 열 수 있는 사이트", "sectionTitle")
        cl.addWidget(self.run_sites_title)
        self.run_sites = ExpandedList(wrapping=True)
        self.run_sites.setObjectName("runList")
        self.run_sites.setSpacing(6)
        self.run_sites.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.run_sites.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._run_sites_cursor = _LaunchCursorFilter(self.run_sites)
        self.run_sites.itemClicked.connect(self._on_run_site_clicked)
        cl.addWidget(self.run_sites)
        cl.addSpacing(6)  # 사이트 목록 바로 밑에 안내 한 줄 (남는 공간은 창 맨 아래로)
        cl.addWidget(_label("작업 표시줄, 시작 메뉴, 작업 관리자, Windows 설정은 항상 쓸 수 있습니다.", "hint", True))
        root.addWidget(card)

        # 비상 해제 대기 띠
        self.emergency_banner = QFrame()
        self.emergency_banner.setObjectName("banner")
        eb = QHBoxLayout(self.emergency_banner)
        eb.setContentsMargins(12, 8, 8, 8)
        self.emergency_label = _label(wrap=True)
        eb.addWidget(self.emergency_label, 1)
        cancel = QPushButton("비상 해제 취소")
        cancel.clicked.connect(self.cancel_emergency_requested.emit)
        eb.addWidget(cancel)
        self.emergency_banner.hide()
        root.addSpacing(10)
        root.addWidget(self.emergency_banner)

        # 사이트 제한 상태 띠 (다시 시작해야 하는 브라우저가 있거나 도우미가 없을 때)
        self.site_banner = QFrame()
        self.site_banner.setObjectName("banner")
        sb = QHBoxLayout(self.site_banner)
        sb.setContentsMargins(12, 8, 8, 8)
        self.site_banner_label = _label(wrap=True)
        sb.addWidget(self.site_banner_label, 1)
        self.restart_browsers_btn = QPushButton("브라우저 다시 시작")
        self.restart_browsers_btn.setToolTip("열려 있던 탭은 다시 열립니다. 입력하던 내용은 사라질 수 있어요.")
        self.restart_browsers_btn.clicked.connect(self.restart_browsers_requested.emit)
        sb.addWidget(self.restart_browsers_btn)
        self.site_banner.hide()
        root.addSpacing(6)
        root.addWidget(self.site_banner)

        buttons = QHBoxLayout()
        root.addSpacing(10)
        self.end_hint = _label("", "hint", wrap=True)
        buttons.addWidget(self.end_hint, 1)
        # 집중 중에 고칠 수 있는 것들은 톱니바퀴 메뉴 하나에 모음 (버튼이 늘어서면 지저분해서)
        self.run_menu = QMenu(self)  # 창이 소유하므로 따로 지울 필요 없음
        self.run_menu.setToolTipsVisible(True)

        def item(text: str, tip: str, signal) -> QAction:
            action = self.run_menu.addAction(text)
            action.setToolTip(tip)
            action.triggered.connect(signal.emit)
            return action

        self.add_time_btn = item("시간 추가…", "해제 문자열 없이 집중 시간을 늘립니다", self.add_time_requested)
        self.change_mode_btn = item(
            "모드 변경…", "집중을 끝내지 않고 다른 모드로 바꿉니다 (목록에서 아래쪽 모드로 바꿀 때만 짧은 해제 문자열 필요)", self.change_mode_requested
        )
        self.run_menu.addSeparator()
        self.edit_apps_btn = item(
            "허용 앱 편집…", "짧은 해제 문자열을 입력하면 집중을 끝내지 않고 허용 앱 목록을 고칠 수 있습니다",
            self.edit_apps_requested,
        )
        self.remove_apps_btn = item(
            "앱·사이트 빼기…", "해제 문자열 없이 허용 앱·사이트를 목록에서 뺄 수 있습니다 (추가는 안 됨)",
            self.remove_apps_requested,
        )
        self.run_menu_btn = QPushButton("⚙")
        self.run_menu_btn.setObjectName("runMenuButton")
        self.run_menu_btn.setToolTip("시간 추가 · 모드 변경 · 허용 앱·사이트 편집")
        self.run_menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.run_menu_btn.setMenu(self.run_menu)
        buttons.addWidget(self.run_menu_btn)
        self.stop_btn = QPushButton("집중 끝내기…")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        buttons.addWidget(self.stop_btn)
        root.addLayout(buttons)
        root.addStretch(1)  # 창이 내용보다 크면 빈 공간은 맨 아래에
        return page

    # ------------------------------------------------------------- 상태 전환
    def _show_page(self, page: QWidget) -> None:
        """설정 화면 / 진행 화면 중 하나를 보여 줍니다 (창 크기·스크롤은 보이는 화면만 따름, _PageStack)."""
        self.stack.setCurrentWidget(page)
        self.stack.updateGeometry()

    def show_setup(self) -> None:
        self._show_page(self.setup_page)
        self.reload_modes(select=self.settings.active_profile)

    def show_running(self, session: FocusSession, profile: Profile) -> None:
        self.notice.hide()
        self._show_page(self.running_page)
        self.run_mode.setText(profile.name)
        self.run_apps.clear()
        if profile.block_everything:
            apps = profile.normalized_apps()
            self.run_apps_title.setText(f"지금 쓸 수 있는 앱 ({len(apps)}개)")
            for exe in apps:
                name = self.settings.app_display_name(exe)
                item = QListWidgetItem(app_catalog.app_icon(self._app_path(exe), name), name)
                item.setData(Qt.ItemDataRole.UserRole, exe)
                self.run_apps.addItem(item)
            self.set_open_apps(self._open_apps, force=True)
            if not apps:
                self.run_apps.addItem("(없음 — 시스템 요소만 쓸 수 있습니다)")
        else:
            self.run_apps_title.setText("이 모드는 앱을 막지 않습니다")
        self._show_run_sites(profile)
        self.set_site_status("", False)
        self.edit_apps_btn.setVisible(profile.block_everything)
        self.remove_apps_btn.setVisible(profile.block_everything)
        self.add_time_btn.setVisible(session.ends_at is not None)  # '끝낼 때까지'는 늘릴 시간이 없음
        self.change_mode_btn.setVisible(len(self.settings.profiles) > 1)
        self.run_menu_btn.setVisible(any(a.isVisible() for a in self.run_menu.actions() if not a.isSeparator()))
        self.edit_apps_btn.setText("허용 앱·사이트 편집…" if profile.limits_sites() else "허용 앱 편집…")
        self.end_hint.setText(
            f"끝내려면 {self.settings.unlock_code_length}글자 랜덤 문자열을 직접 입력해야 합니다."
        )
        self.update_running(session, 0)

    def update_running(self, session: FocusSession, block_count: int) -> None:
        now = time.time()
        remaining = session.remaining_seconds(now)
        if remaining is None:
            # '끝낼 때까지'는 시간을 보여 주지 않음
            self.timer_caption.hide()
            self.timer_label.hide()
            self.progress.hide()
            info = "직접 끝낼 때까지 계속됩니다"
        else:
            self.timer_caption.show()
            self.timer_label.show()
            self.timer_caption.setText("남은 시간")
            self.timer_label.setText(format_clock(remaining))
            total = max(1.0, (session.ends_at or now) - session.started_at)
            self.progress.show()
            self.progress.setValue(int(1000 * min(1.0, (now - session.started_at) / total)))
            info = f"{format_end_time(session.ends_at)}에 끝나요"
        if block_count:
            info += f"  ·  다른 앱을 {block_count}번 막았어요"
        self.run_info.setText(info)

        pending = session.emergency_at is not None
        self.emergency_banner.setVisible(pending)
        if pending:
            left = format_duration(session.emergency_remaining_seconds(now))
            self.emergency_label.setText(f"<b>비상 해제 대기 중</b> — {left} 뒤에 차단이 풀립니다.")

    def set_open_apps(self, running: set, force: bool = False) -> None:
        """실행 중인 앱(실행 파일 이름, 소문자)을 받아 진행 화면의 앱 옆 점과 설명을 갱신합니다."""
        if running == self._open_apps and not force:
            return
        self._open_apps = set(running)
        for i in range(self.run_apps.count()):
            item = self.run_apps.item(i)
            exe = item.data(Qt.ItemDataRole.UserRole)
            if not exe:
                continue
            is_open = exe in self._open_apps
            name = item.text()
            if bool(item.data(OPEN_ROLE)) != is_open or force:
                item.setData(OPEN_ROLE, is_open)
                item.setToolTip(f"{name} 실행 중 · 눌러서 앞으로 가져오기" if is_open else f"눌러서 {name} 열기")

    def _show_run_sites(self, profile: Profile) -> None:
        self.run_sites.clear()
        on = profile.limits_sites()
        self.run_sites_title.setVisible(on)
        self.run_sites.setVisible(on)
        if not on:
            return
        sites = profile.normalized_sites()
        self.run_sites_title.setText(f"지금 열 수 있는 사이트 ({len(sites)}개)")
        globe = icons.globe_icon()
        for site in sites:
            item = QListWidgetItem(globe, site.lstrip("."))
            item.setData(SITE_ROLE, site)
            item.setToolTip(f"눌러서 {site.lstrip('.')} 열기")
            self.run_sites.addItem(item)
        if not sites:
            self.run_sites.addItem("(없음 — 허용한 웹 앱과 내 PC의 파일만 열 수 있습니다)" if profile.web_apps()
                                   else "(없음 — 내 PC의 파일만 열 수 있습니다)")

    def set_site_status(self, text: str, can_restart: bool) -> None:
        """사이트 제한 상태 띠. text가 비면 숨김."""
        if self.site_banner_label.text() != text:
            self.site_banner_label.setText(text)
        self.restart_browsers_btn.setVisible(can_restart)
        self.site_banner.setVisible(bool(text))

    def _on_run_site_clicked(self, item: QListWidgetItem) -> None:
        site = item.data(SITE_ROLE)
        if site:
            self.open_site_requested.emit(str(site))

    def _on_run_app_clicked(self, item: QListWidgetItem) -> None:
        exe = item.data(Qt.ItemDataRole.UserRole)
        if exe:
            self.launch_app_requested.emit(str(exe))

    # ------------------------------------------------------------- 창 위치
    def _restore_geometry(self) -> None:
        if self.settings.window_geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(self.settings.window_geometry.encode("ascii")))
            except (ValueError, UnicodeEncodeError):
                pass

    def save_geometry(self) -> None:
        """창 위치·크기를 설정에 기록합니다 (닫거나 종료할 때 호출)."""
        value = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        if value != self.settings.window_geometry:
            self.settings.window_geometry = value
            self.settings_changed.emit()

    # ------------------------------------------------------------- 창 닫기
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        # Esc = 창 닫기 (트레이에는 그대로 남음)
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.save_geometry()
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()
        if self.on_hidden_to_tray is not None:
            self.on_hidden_to_tray()

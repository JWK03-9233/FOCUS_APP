"""창 전체 스크롤: 내용이 화면보다 크면 위젯을 겹치게 줄이지 않고 창 안에서 스크롤합니다.

모든 창(메인 창·대화상자)의 내용은 ``WindowScroll`` 안에 들어갑니다.
* 화면에 다 들어가면 스크롤 막대 없이 예전과 똑같이 보입니다.
* 화면이 낮거나 크게 확대하면, 내용은 제 최소 크기를 지키고 창만 스크롤됩니다.
* 가로로는 스크롤하지 않습니다. 글자는 모두 줄을 바꿔(word wrap) 창 너비에 맞춥니다.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from focus_app.ui import theme

SCREEN_SHARE = 0.9  # 처음 여는 창이 화면(작업 표시줄 제외)을 이 비율까지만 차지


class WindowScroll(QScrollArea):
    """내용 크기를 그대로 원하는 크기로 알려 주되(화면 안으로), 최소 크기는 작게 두는 스크롤 영역."""

    def __init__(self, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("windowScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # 가로 스크롤 없음
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setWidget(content)
        # 창 배경을 그대로 보이게 (스크롤 영역이 따로 칠하지 않음)
        self.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        content.installEventFilter(self)  # 내용의 최소 너비가 바뀌면 창 최소 너비도 맞춤

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self.widget() and event.type() == QEvent.Type.LayoutRequest:
            self._ensure_window_width()
        return False

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._ensure_window_width()

    def _ensure_window_width(self) -> None:
        """창이 내용의 최소 너비보다 좁아지지 않게 (가로 스크롤이 없으니 좁아지면 오른쪽이 잘림).

        코드에서 정한 창 최소 크기(setMinimumSize)는 레이아웃의 최소 크기보다 우선하므로 여기서 직접 올립니다.
        """
        win = self.window()
        if win is None or win is self:
            return
        needed = self.minimumSizeHint().width() + max(0, win.width() - self.width())
        limit = self._screen_limit()
        if limit is not None:
            needed = min(needed, int(limit.width() / SCREEN_SHARE))
        if win.minimumWidth() < needed:
            win.setMinimumWidth(needed)

    def wrap_labels(self) -> None:
        """내용 안의 글자를 모두 줄 바꿈으로 (길면 가로로 늘어나는 대신 다음 줄로)."""
        content = self.widget()
        if content is None:
            return
        changed = False
        for label in content.findChildren(QLabel):
            if not label.wordWrap():
                label.setWordWrap(True)
                changed = True
        if changed:
            content.updateGeometry()
            self.updateGeometry()

    def showEvent(self, event) -> None:  # noqa: N802
        self.wrap_labels()  # 보이기 직전에: 만든 뒤 글자를 넣은 라벨까지 포함
        super().showEvent(event)

    def _screen_limit(self) -> QSize | None:
        screen = self.screen()
        if screen is None:
            return None
        area = screen.availableGeometry()
        return QSize(int(area.width() * SCREEN_SHARE), int(area.height() * SCREEN_SHARE))

    def sizeHint(self) -> QSize:  # noqa: N802
        content = self.widget()
        if content is None:
            return super().sizeHint()
        hint = content.sizeHint().expandedTo(content.minimumSizeHint())
        size = QSize(hint.width() + 2 * self.frameWidth(), hint.height() + 2 * self.frameWidth())
        limit = self._screen_limit()
        if limit is not None and (size.height() > limit.height() or size.width() > limit.width()):
            # 스크롤 막대가 생기므로 그 자리만큼 넓힘
            size = QSize(size.width() + self.verticalScrollBar().sizeHint().width(), size.height())
            size = size.boundedTo(limit)
        return size

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # 창은 얼마든지 줄일 수 있고, 모자라면 스크롤 (너비는 내용 최소 너비까지는 지키되 화면을 넘지 않게)
        content = self.widget()
        width = content.minimumSizeHint().width() if content is not None else 0
        width += self.verticalScrollBar().sizeHint().width()  # 세로 스크롤 막대가 생겨도 내용이 잘리지 않게
        limit = self._screen_limit()
        if limit is not None:
            width = min(width, limit.width())
        return QSize(width, 120)


class ExpandedList(QListWidget):
    """안쪽 스크롤 없이 항목을 모두 펼쳐 보여 주는 목록. 높이를 내용에 맞추고, 넘치면 창 전체가 스크롤됩니다.

    ``wrapping=True``면 항목을 가로로 늘어놓고 줄을 바꿉니다 (진행 화면의 앱·사이트 목록).
    """

    def __init__(self, parent: QWidget | None = None, wrapping: bool = False) -> None:
        super().__init__(parent)
        if wrapping:
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setFlow(QListView.Flow.LeftToRight)
            self.setWrapping(True)
            self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        model = self.model()
        model.rowsInserted.connect(self.fit_height)
        model.rowsRemoved.connect(self.fit_height)
        model.modelReset.connect(self.fit_height)

    def add_row(self, widget: QWidget, min_height: int = 0) -> QListWidgetItem:
        """줄 위젯을 넣습니다. 줄 높이는 위젯이 실제로 필요한 높이 (글자가 아래로 잘리지 않게)."""
        if not self.property("rowWidgets"):
            # 줄 위젯이 칸 전체를 쓰도록 칸 여백을 없앰 (theme의 QListWidget[rowWidgets="true"])
            self.setProperty("rowWidgets", True)
            self.style().unpolish(self)
            self.style().polish(self)
        widget.ensurePolished()  # 공통 스타일(글자 크기)을 반영한 크기를 얻으려고
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, max(theme.px(min_height), widget.sizeHint().height())))
        self.addItem(item)
        self.setItemWidget(item, widget)
        return item

    def fit_height(self, *_args) -> None:
        self.doItemsLayout()
        bottom = 0
        for i in range(self.count()):
            bottom = max(bottom, self.visualItemRect(self.item(i)).bottom() + 1)
        height = bottom + self.verticalOffset() + self.spacing() + 2 * self.frameWidth()
        if height != self.height():
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.fit_height()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.fit_height()


def scroll_layout(window: QWidget, layout: QLayout | None = None) -> QLayout:
    """창의 내용을 스크롤 영역에 넣고, 내용을 채울 레이아웃을 돌려줍니다.

    대화상자에서 ``layout = QVBoxLayout(self)`` 대신 ``layout = scroll_layout(self)``로 씁니다.
    여백은 예전처럼 창 가장자리에 둡니다(스크롤 막대는 창 끝에 붙음).
    """
    outer = QVBoxLayout(window)
    outer.setContentsMargins(0, 0, 0, 0)
    body = QWidget()
    inner = layout if layout is not None else QVBoxLayout()
    body.setLayout(inner)
    outer.addWidget(WindowScroll(body))
    return inner

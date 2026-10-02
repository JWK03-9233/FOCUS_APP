"""모든 창에 공통: 화면 확대·축소와 창 위치·크기 기억.

앱 전체에 이벤트 필터 하나를 걸어, 창마다 따로 코드를 넣지 않아도 되게 합니다.

* 확대·축소: Ctrl + / Ctrl − / Ctrl 0(원래대로), Ctrl + 마우스 휠. 공통 스타일(theme)의 글자 크기와
  여백을 비율대로 바꿔 다시 적용하므로 열려 있는 창이 모두 함께 바뀝니다.
* 위치·크기: 대화상자는 창 종류(클래스 이름)마다 마지막 위치·크기로 다시 엽니다. 옮기거나 크기를 바꾸면
  잠시 뒤 바로 저장하므로, 앱이 강제로 꺼져도 기억이 남습니다. 메인 창은 MainWindow가 직접 복원합니다.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QToolTip,
    QWidget,
)

from focus_app.config import Settings
from focus_app.ui import theme
from focus_app.ui.theme import ZOOM_LEVELS, build_stylesheet, clamp_zoom

log = logging.getLogger(__name__)

MAIN_KEY = "MainWindow"
SAVE_DELAY_MS = 500
# 내용에 맞춰 크기가 정해지는 표준 대화상자는 기억하지 않음
_SKIP = (QMessageBox, QInputDialog, QFileDialog, QProgressDialog)
_RESTORED = "_focusapp_geometry_restored"
_BASE_HEIGHT_ROLE = Qt.ItemDataRole.UserRole + 90  # 목록 항목의 100% 기준 높이
_BASE_MIN = "_focusapp_base_min"  # 창의 100% 기준 최소 크기
_BASE_SIZE = "_focusapp_base_size"  # 창의 100% 기준 크기
_EXPECTED = "_focusapp_expected_size"  # 확대·축소로 요청한 크기 (사용자 변경과 구분)


def window_key(widget: QWidget) -> str:
    return MAIN_KEY if isinstance(widget, QMainWindow) else type(widget).__name__


def tracked(widget: QObject) -> bool:
    """위치·크기를 기억할 창인지."""
    return (
        isinstance(widget, (QDialog, QMainWindow))
        and widget.isWindow()
        and not isinstance(widget, _SKIP)
    )


def next_zoom(current: int, step: int) -> int:
    """한 단계 크게(step=1) 또는 작게(-1). 단계 사이 값이면 가까운 다음 단계로."""
    current = clamp_zoom(current)
    if step > 0:
        return next((z for z in ZOOM_LEVELS if z > current), ZOOM_LEVELS[-1])
    return next((z for z in reversed(ZOOM_LEVELS) if z < current), ZOOM_LEVELS[0])


class WindowStateManager(QObject):
    _active: "WindowStateManager | None" = None  # 앱에 하나만 (새로 만들면 이전 것은 떼어 냄)

    def __init__(self, app: QApplication, settings: Settings, save: Callable[[], None]) -> None:
        super().__init__()
        previous = WindowStateManager._active
        if previous is not None:
            try:
                app.removeEventFilter(previous)
            except RuntimeError:  # 이미 정리됨
                pass
        WindowStateManager._active = self
        self.app = app
        self.settings = settings
        self.save = save
        self._pending: Dict[str, QWidget] = {}
        self._wheel = 0
        self._zooming = False
        self._last_factor = settings.ui_zoom / 100  # 목록 항목 높이를 마지막으로 맞춘 배율
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVE_DELAY_MS)
        self._timer.timeout.connect(self.flush)
        self.apply_zoom(settings.ui_zoom, announce=False)
        app.installEventFilter(self)

    # ------------------------------------------------------------- 확대·축소
    @property
    def factor(self) -> float:
        return self.settings.ui_zoom / 100

    def apply_zoom(self, percent: int, announce: bool = True) -> None:
        percent = clamp_zoom(percent)
        changed = percent != self.settings.ui_zoom
        self.settings.ui_zoom = percent
        theme.set_zoom(percent)
        self.app.setStyleSheet(build_stylesheet(percent))
        if changed:
            self._rescale_lists()
            # 글자만 커지고 창은 그대로면 내용이 잘리므로 열려 있는 창(트레이로 숨긴 창 포함)도 같은 비율로
            for widget in self.app.topLevelWidgets():
                if tracked(widget) and widget.property(_RESTORED):
                    self._zoom_window(widget)
            self.save()
        if announce:
            QToolTip.showText(QCursor.pos(), f"화면 크기 {percent}%")

    def _rescale_lists(self) -> None:
        """높이를 정해 둔 목록 항목(모드·앱 목록 등)도 화면 크기에 맞춤."""
        for view in self.app.allWidgets():
            if not isinstance(view, QListWidget):
                continue
            for i in range(view.count()):
                item = view.item(i)
                hint = item.sizeHint()
                if hint.height() <= 0:
                    continue
                base = item.data(_BASE_HEIGHT_ROLE)
                if base is None:
                    base = hint.height() / self._last_factor
                    item.setData(_BASE_HEIGHT_ROLE, base)
                item.setSizeHint(QSize(hint.width(), round(base * self.factor)))
            view.doItemsLayout()
            if hasattr(view, "fit_height"):
                view.fit_height()  # 펼쳐 보이는 목록(ExpandedList)은 높이도 다시 맞춤
        self._last_factor = self.factor

    # 창마다 100% 기준 크기를 기억해 두고 (사용자가 직접 바꿀 때만 갱신) 거기에 배율을 곱함.
    # 지금 크기에 비율을 곱하면, 크게 확대해 화면 크기로 잘린 뒤 되돌릴 때 창이 쪼그라듦.
    def _zoom_window(self, widget: QWidget) -> None:
        f = self.factor
        self._zooming = True  # 최소 크기를 바꾸면 창이 먼저 늘어나는데, 그것을 사용자가 바꾼 크기로 보지 않게
        try:
            base_min = widget.property(_BASE_MIN)
            if base_min:
                self._set_minimum(widget, base_min[0] * f, base_min[1] * f)
            if widget.isMaximized() or widget.isFullScreen():
                return
            base = widget.property(_BASE_SIZE)
            if base:
                self._fit(widget, round(base[0] * f), round(base[1] * f))
        finally:
            self._zooming = False

    @staticmethod
    def _area(widget: QWidget):
        """창 안쪽(제목 표시줄·테두리 제외)이 쓸 수 있는 최대 크기와 화면 영역. 화면을 모르면 None."""
        screen = widget.screen() or QApplication.primaryScreen()
        if screen is None:
            return None
        area = screen.availableGeometry()
        frame = widget.frameGeometry()
        extra_w, extra_h = max(0, frame.width() - widget.width()), max(0, frame.height() - widget.height())
        return area, area.width() - extra_w, area.height() - extra_h

    def _set_minimum(self, widget: QWidget, width: float, height: float) -> None:
        """최소 크기도 비율대로 바꾸되, 크게 확대해도 화면보다 커지지 않게."""
        fit = self._area(widget)
        if fit is not None:
            width, height = min(width, fit[1]), min(height, fit[2])
        widget.setMinimumSize(round(width), round(height))

    def _fit(self, widget: QWidget, width: int, height: int) -> None:
        """크기를 바꾸되 화면(작업 표시줄 제외)을 넘지 않게, 넘치면 화면 안으로 옮김."""
        fit = self._area(widget)
        if fit is not None:
            width, height = min(width, fit[1]), min(height, fit[2])
        widget.setProperty(_EXPECTED, (width, height))  # 이 크기 변경은 사용자가 한 것이 아님
        widget.resize(width, height)
        if fit is None:
            return
        area, frame = fit[0], widget.frameGeometry()
        x = min(max(frame.x(), area.left()), area.right() - frame.width() + 1)
        y = min(max(frame.y(), area.top()), area.bottom() - frame.height() + 1)
        if (x, y) != (frame.x(), frame.y()):
            widget.move(x, y)

    def _remember_base_size(self, widget: QWidget) -> None:
        f = self.factor
        widget.setProperty(_BASE_SIZE, (widget.width() / f, widget.height() / f))

    def zoom_step(self, step: int) -> None:
        self.apply_zoom(next_zoom(self.settings.ui_zoom, step))

    def _zoom_key(self, event) -> bool:
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        key = event.key()
        if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_step(1)
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.zoom_step(-1)
        elif key == Qt.Key.Key_0:
            self.apply_zoom(100)
        else:
            return False
        return True

    def _zoom_wheel(self, event) -> bool:
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        # 터치패드는 작은 값으로 여러 번 오므로 한 칸(120)만큼 모였을 때 한 단계
        self._wheel += event.angleDelta().y()
        while abs(self._wheel) >= 120:
            step = 1 if self._wheel > 0 else -1
            self._wheel -= 120 * step
            self.zoom_step(step)
        return True

    # ------------------------------------------------------------- 위치·크기
    def _load(self, key: str) -> str:
        if key == MAIN_KEY:
            return self.settings.window_geometry
        return self.settings.window_geometries.get(key, "")

    def _store(self, key: str, value: str) -> bool:
        if self._load(key) == value:
            return False
        if key == MAIN_KEY:
            self.settings.window_geometry = value
        else:
            self.settings.window_geometries[key] = value
        return True

    def restore(self, widget: QWidget) -> None:
        """처음 뜰 때: 화면 크기에 맞춰 최소 크기를 키우고, 마지막 위치·크기로 엽니다."""
        widget.setProperty(_RESTORED, True)
        f = self.factor
        size = widget.size()
        minimum = widget.minimumSize()
        if minimum.width() or minimum.height():
            widget.setProperty(_BASE_MIN, (minimum.width(), minimum.height()))  # 코드에서 정한 100% 기준
            if f != 1:
                self._set_minimum(widget, minimum.width() * f, minimum.height() * f)
        key = window_key(widget)
        value = self._load(key)
        restored = False
        if value and key != MAIN_KEY:  # MainWindow는 만들 때 직접 복원함 (최대화 상태 포함)
            try:
                restored = widget.restoreGeometry(QByteArray.fromBase64(value.encode("ascii")))
            except (ValueError, UnicodeEncodeError):
                restored = False
        if restored:
            self._fit(widget, widget.width(), widget.height())  # 저장된 크기가 지금 화면보다 크면 줄임
        elif not value and f != 1:
            self._fit(widget, round(size.width() * f), round(size.height() * f))  # 처음 여는 창
        self._remember_base_size(widget)

    def remember(self, widget: QWidget) -> None:
        """창 위치·크기를 설정에 기록하고, 바뀌었으면 저장합니다."""
        try:
            value = bytes(widget.saveGeometry().toBase64().data()).decode("ascii")
        except RuntimeError:  # 이미 정리된 창
            return
        if self._store(window_key(widget), value):
            self.save()

    def flush(self) -> None:
        pending, self._pending = self._pending, {}
        for widget in pending.values():
            self.remember(widget)

    def _schedule(self, widget: QWidget) -> None:
        self._pending[window_key(widget)] = widget
        self._timer.start()

    # ------------------------------------------------------------- 이벤트
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        t = event.type()
        if t == QEvent.Type.KeyPress:
            return self._zoom_key(event)
        if t == QEvent.Type.Wheel:
            return self._zoom_wheel(event)
        if t not in (QEvent.Type.Show, QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Hide):
            return False
        if not tracked(obj):
            return False
        if t == QEvent.Type.Show:
            if not obj.property(_RESTORED):
                self.restore(obj)
        elif t == QEvent.Type.Hide:
            self._pending.pop(window_key(obj), None)
            self.remember(obj)
        elif obj.property(_RESTORED):
            if t == QEvent.Type.Resize:
                expected = obj.property(_EXPECTED)
                if expected and tuple(expected) == (obj.width(), obj.height()):
                    obj.setProperty(_EXPECTED, None)  # 확대·축소로 바꾼 크기
                elif not (self._zooming or obj.isMaximized() or obj.isFullScreen()):
                    self._remember_base_size(obj)  # 사용자가 바꾼 크기
            if obj.isVisible():
                self._schedule(obj)
        return False

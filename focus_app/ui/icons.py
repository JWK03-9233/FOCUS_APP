"""앱/트레이 아이콘. focus_app/assets/focus_icon.ico를 쓰고, 트레이에서는 상태 점을 덧그립니다."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

from focus_app.ui import theme

ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "focus_icon.ico"

COLOR_IDLE = QColor("#7b8296")
COLOR_ACTIVE = QColor(theme.ACCENT)
COLOR_EMERGENCY = QColor(theme.WARN)

_base_pixmap: Optional[QPixmap] = None


def _base(size: int = 64) -> QPixmap:
    """앱 아이콘 원본 (파일이 없으면 단색 원으로 대신)."""
    global _base_pixmap
    if _base_pixmap is None:
        pm = QIcon(str(ICON_PATH)).pixmap(128, 128) if ICON_PATH.exists() else QPixmap()
        if pm.isNull():
            pm = QPixmap(128, 128)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(COLOR_IDLE))
            p.drawEllipse(QRectF(8, 8, 112, 112))
            p.end()
        _base_pixmap = pm
    return _base_pixmap.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )


def app_icon() -> QIcon:
    """창·작업 표시줄에 쓰는 앱 아이콘."""
    if ICON_PATH.exists():
        icon = QIcon(str(ICON_PATH))
        if not icon.isNull():
            return icon
    return QIcon(_base())


def _with_dot(color: Optional[QColor], size: int = 64) -> QIcon:
    pm = _base(size)
    if color is not None:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = size * 0.42
        p.setPen(QPen(QColor("white"), size * 0.06))
        p.setBrush(QBrush(color))
        p.drawEllipse(QRectF(size - d - 1, size - d - 1, d, d))
        p.end()
    return QIcon(pm)


def idle_icon() -> QIcon:
    return _with_dot(None)


def active_icon() -> QIcon:
    return _with_dot(COLOR_ACTIVE)


def emergency_icon() -> QIcon:
    return _with_dot(COLOR_EMERGENCY)


def globe_icon(size: int = 40) -> QIcon:
    """허용 사이트 목록에 쓰는 지구본 아이콘 (선 몇 개로 그림)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(COLOR_ACTIVE, size * 0.07)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = size * 0.1
    r = QRectF(m, m, size - 2 * m, size - 2 * m)
    p.drawEllipse(r)
    p.drawEllipse(QRectF(r.center().x() - r.width() * 0.22, r.top(), r.width() * 0.44, r.height()))
    p.drawLine(int(r.left()), int(r.center().y()), int(r.right()), int(r.center().y()))
    p.end()
    return QIcon(pm)

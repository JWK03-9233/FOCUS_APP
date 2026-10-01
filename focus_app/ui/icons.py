"""외부 리소스 없이 QPainter로 트레이 아이콘을 그립니다."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

COLOR_IDLE = QColor("#8a8f98")
COLOR_ACTIVE = QColor("#2e9e5b")
COLOR_EMERGENCY = QColor("#d9822b")


def make_icon(color: QColor, size: int = 64, locked: bool = False) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.08
    p.setPen(QPen(QColor(0, 0, 0, 60), size * 0.04))
    p.setBrush(QBrush(color))
    p.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    # 가운데에 잠금 표시 (활성) 또는 빈 원 (대기)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("white")))
    if locked:
        body = QRectF(size * 0.33, size * 0.46, size * 0.34, size * 0.26)
        p.drawRoundedRect(body, size * 0.04, size * 0.04)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("white"), size * 0.07))
        p.drawArc(QRectF(size * 0.38, size * 0.28, size * 0.24, size * 0.3), 0, 180 * 16)
    else:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("white"), size * 0.07))
        p.drawEllipse(QRectF(size * 0.33, size * 0.33, size * 0.34, size * 0.34))
    p.end()
    return QIcon(pm)


def idle_icon() -> QIcon:
    return make_icon(COLOR_IDLE, locked=False)


def active_icon() -> QIcon:
    return make_icon(COLOR_ACTIVE, locked=True)


def emergency_icon() -> QIcon:
    return make_icon(COLOR_EMERGENCY, locked=True)

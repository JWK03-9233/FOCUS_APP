"""집중이 끝났을 때 띄우는 알림 창. 직접 닫을 때까지 다른 창 위에 떠 있습니다.

정한 시간이 끝났거나 비상 해제가 적용된 경우에만 띄웁니다 (직접 끝낸 경우는 띄우지 않음).
집중 중에 최소화된 앱들은 그대로 둡니다 (한꺼번에 다시 열지 않음).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QWidget

from focus_app.session import format_minutes
from focus_app.ui.scroll import scroll_layout


class FocusEndDialog(QDialog):
    def __init__(
        self,
        reason: str,
        mode_name: str,
        focused_seconds: int,
        blocked: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("집중 끝")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumWidth(380)

        layout = scroll_layout(self)  # 내용이 많으면 창 전체를 스크롤
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(8)

        emergency = reason == "emergency"
        icon = QLabel("⏰" if emergency else "🎉")
        icon.setObjectName("endIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        self.title = QLabel("비상 해제로 집중이 끝났어요" if emergency else "집중 시간이 끝났어요!")
        self.title.setObjectName("modeTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)

        # 분 단위로 반올림해 보여 줌 (1분 미만만 초로)
        if focused_seconds < 60:
            minutes = f"{max(0, int(focused_seconds))}초"
        else:
            minutes = format_minutes(round(focused_seconds / 60))
        lines = [f"<b>{mode_name}</b> 모드로 <b>{minutes}</b> 집중했어요."]
        lines.append(f"다른 앱을 {blocked}번 막았어요." if blocked else "한 번도 다른 앱으로 새지 않았어요.")
        if not emergency:
            lines.append("수고했어요. 잠깐 쉬어 가세요.")
        self.summary = QLabel("<br>".join(lines))
        self.summary.setObjectName("muted")
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.summary)
        layout.addSpacing(10)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_btn = QPushButton("확인")
        self.ok_btn.setDefault(True)
        self.ok_btn.setMinimumWidth(120)
        self.ok_btn.clicked.connect(self.accept)
        buttons.addWidget(self.ok_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

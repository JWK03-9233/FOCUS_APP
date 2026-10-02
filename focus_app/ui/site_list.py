"""모드의 허용 사이트 편집 (메인 창의 모드 편집과 집중 중 '허용 앱 편집' 창에서 같이 씀).

값만 들고 있다가 바뀔 때마다 ``changed``를 보냅니다. 모드에 반영하는 것은 쓰는 쪽이 합니다.
"""

from __future__ import annotations

import re
from typing import List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from focus_app import browser_policy
from focus_app.config import normalize_site
from focus_app.ui import icons, theme

SUPPORTED_NAMES = "·".join(b.name for b in browser_policy.BROWSERS)


def site_scope(site: str) -> str:
    """사이트 항목 옆에 붙는 설명."""
    if "/" in site:
        return "이 주소로 시작하는 페이지만"
    if site.startswith("."):
        return "이 주소만 (하위 도메인 제외)"
    return "하위 도메인 포함"


class SiteRow(QWidget):
    """허용 사이트 목록의 한 줄: 지구본, 주소, 범위 설명, 빼기 버튼."""

    def __init__(self, site: str, on_remove, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 4, 2)
        row.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.globe_icon().pixmap(20, 20))
        row.addWidget(icon)
        title = QLabel(site.lstrip("."))
        title.setStyleSheet("font-weight: 600;")
        row.addWidget(title)
        scope = QLabel(site_scope(site))
        scope.setObjectName("hint")
        row.addWidget(scope, 1)
        self.remove_btn = QPushButton("✕")
        self.remove_btn.setObjectName("iconButton")
        self.remove_btn.setToolTip("이 사이트를 목록에서 빼기")
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.clicked.connect(lambda: on_remove(site))
        row.addWidget(self.remove_btn)


class SiteEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.restrict = False
        self.sites: List[str] = []
        self._apps: List[str] = []
        self._helper_installed: Optional[bool] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        head = QHBoxLayout()
        self.check = QCheckBox("브라우저에서 고른 사이트만 열기")
        self.check.setToolTip(f"{SUPPORTED_NAMES}에 적용됩니다")
        self.check.toggled.connect(self._on_toggled)
        head.addWidget(self.check, 1)
        self.add_btn = QPushButton("+  사이트 추가")
        self.add_btn.setObjectName("secondary")
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.clicked.connect(self._add)
        head.addWidget(self.add_btn)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setObjectName("appList")
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list.setMinimumHeight(theme.px(76))
        layout.addWidget(self.list, 1)
        self.empty = QLabel("")
        self.empty.setObjectName("muted")
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.warning = QLabel("")
        self.warning.setObjectName("warnText")
        self.warning.setWordWrap(True)
        layout.addWidget(self.warning)

    # ------------------------------------------------------------- 값
    def set_values(self, restrict: bool, sites: List[str]) -> None:
        self.restrict = bool(restrict)
        self.sites = list(sites)
        self.check.blockSignals(True)
        self.check.setChecked(self.restrict)
        self.check.blockSignals(False)
        self._reload()

    def set_context(self, apps: List[str], helper_installed: Optional[bool]) -> None:
        """경고 문구에 쓰는 정보: 모드의 허용 앱, 관리자 권한 도우미가 설치돼 있는지 (모르면 None)."""
        self._apps = list(apps)
        self._helper_installed = helper_installed
        self._update_warning()

    # ------------------------------------------------------------- 화면
    def _reload(self) -> None:
        self.list.clear()
        for site in self.sites:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, theme.px(36)))
            self.list.addItem(item)
            self.list.setItemWidget(item, SiteRow(site, self.remove_site))
        self.list.setVisible(bool(self.sites))
        self.list.setEnabled(self.restrict)
        self.add_btn.setEnabled(self.restrict)
        if not self.restrict:
            self.empty.setText(
                f"켜면 집중 중에 {SUPPORTED_NAMES}에서 고른 사이트만 열 수 있습니다. "
                "끄면 허용한 브라우저에서 모든 사이트가 열립니다."
            )
        elif not self.sites:
            self.empty.setText(
                "고른 사이트가 없어 브라우저에서 아무 사이트도 열 수 없습니다 (내 PC의 PDF 같은 파일은 열림)."
            )
        else:
            self.empty.setText(
                "다른 주소로 넘어가는 사이트(예: 로그인 페이지)는 그 주소도 추가하세요. "
                "집중을 시작할 때 열려 있던 브라우저는 다시 시작해야 적용됩니다."
            )
        self._update_warning()

    def _update_warning(self) -> None:
        lines = []
        if self.restrict:
            if not any(a in browser_policy.SUPPORTED_EXES for a in self._apps):
                lines.append(f"⚠ 허용 앱에 {SUPPORTED_NAMES} 중 하나가 없어 사이트를 열 수 없습니다.")
            others = [browser_policy.OTHER_BROWSERS[a] for a in self._apps if a in browser_policy.OTHER_BROWSERS]
            if others:
                lines.append(f"⚠ {', '.join(others)}에는 사이트 제한이 적용되지 않아 모든 사이트가 열립니다.")
            if self._helper_installed is False:
                lines.append(
                    "⚠ 관리자 권한 도우미가 있어야 적용됩니다 (⚙ 설정에서 설치). "
                    "없으면 집중 중에 브라우저가 모두 최소화됩니다."
                )
        self.warning.setText("\n".join(lines))
        self.warning.setVisible(bool(lines))

    # ------------------------------------------------------------- 편집
    def _on_toggled(self, on: bool) -> None:
        self.restrict = on
        self._reload()
        self.changed.emit()

    def _add(self) -> None:
        text, ok = QInputDialog.getText(
            self,
            "사이트 추가",
            "열 수 있게 할 사이트 주소 (여러 개는 쉼표나 띄어쓰기로 구분):\n\n"
            "• notion.so  →  notion.so와 www.·app. 같은 하위 도메인 모두\n"
            "• .notion.so  →  notion.so만\n"
            "• docs.google.com/document  →  이 주소로 시작하는 페이지만",
        )
        if not ok:
            return
        self.add_sites(text)

    def add_sites(self, text: str) -> List[str]:
        """주소들을 추가하고, 쓸 수 없어 건너뛴 항목을 돌려줍니다 (있으면 알림)."""
        bad: List[str] = []
        added = False
        for part in re.split(r"[\s,]+", text or ""):
            if not part:
                continue
            site = normalize_site(part)
            if not site:
                bad.append(part)
            elif site not in self.sites:
                self.sites.append(site)
                added = True
        if added:
            self._reload()
            self.changed.emit()
        if bad:
            QMessageBox.warning(self, "사이트 추가", "사이트 주소로 쓸 수 없어 건너뛰었습니다:\n" + "\n".join(bad))
        return bad

    def remove_site(self, site: str) -> None:
        self.sites = [s for s in self.sites if s != site]
        self._reload()
        self.changed.emit()

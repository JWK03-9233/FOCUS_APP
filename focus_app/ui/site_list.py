"""모드의 허용 사이트 편집 (메인 창의 모드 편집과 집중 중 '허용 앱 편집' 창에서 같이 씀).

한 번 추가한 사이트는 '저장한 사이트' 목록(``library``)에 남고, 모드에서는 쓸 사이트만 체크합니다.
값만 들고 있다가 바뀔 때마다 ``changed``(체크·제한 여부)나 ``library_changed``(저장한 사이트 목록)를
보냅니다. 모드·설정에 반영하는 것은 쓰는 쪽이 합니다.
"""

from __future__ import annotations

import re
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from focus_app import browser_policy
from focus_app.config import normalize_site
from focus_app.ui import icons
from focus_app.ui.scroll import ExpandedList

SUPPORTED_NAMES = "·".join(b.name for b in browser_policy.BROWSERS)


def site_scope(site: str) -> str:
    """사이트 항목 옆에 붙는 설명."""
    if "/" in site:
        return "이 주소로 시작하는 페이지만"
    if site.startswith("."):
        return "이 주소만 (하위 도메인 제외)"
    return "하위 도메인 포함"


class SiteRow(QWidget):
    """저장한 사이트 목록의 한 줄: 체크(이 모드에서 쓰기), 지구본, 주소, 범위 설명, 삭제 버튼."""

    def __init__(self, site: str, checked: bool, on_toggle, on_delete=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 4, 2)
        row.setSpacing(10)
        self.check = QCheckBox()
        self.check.setChecked(checked)
        self.check.setToolTip("체크한 사이트만 이 모드에서 열 수 있습니다")
        self.check.toggled.connect(lambda on: on_toggle(site, on))
        row.addWidget(self.check)
        icon = QLabel()
        icon.setPixmap(icons.globe_icon().pixmap(20, 20))
        row.addWidget(icon)
        title = QLabel(site.lstrip("."))
        title.setStyleSheet("font-weight: 600;")
        row.addWidget(title)
        scope = QLabel(site_scope(site))
        scope.setObjectName("hint")
        row.addWidget(scope, 1)
        self.delete_btn = QPushButton("✕")
        self.delete_btn.setObjectName("iconButton")
        self.delete_btn.setToolTip("저장한 사이트 목록에서 지우기")
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.clicked.connect(lambda: on_delete(site))
        self.delete_btn.setVisible(on_delete is not None)
        row.addWidget(self.delete_btn)


class SiteEditor(QWidget):
    changed = Signal()
    library_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.restrict = False
        self.sites: List[str] = []  # 이 모드에서 쓸 사이트 (체크한 것)
        self.library: List[str] = []  # 저장한 사이트 전체 (체크 안 한 것 포함)
        self.remove_only = False  # 집중 중 '빼기만': 처음 체크돼 있던 사이트 안에서 체크만 풀 수 있음
        self._pool: List[str] = []
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

        self.list = ExpandedList()  # 안쪽 스크롤 없이 모두 펼침
        self.list.setObjectName("appList")
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
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
    def set_values(self, restrict: bool, sites: List[str], library: Optional[List[str]] = None) -> None:
        """library를 주지 않으면 지금 저장한 사이트 목록을 그대로 두고, 체크한 사이트는 목록에 합칩니다."""
        self.restrict = bool(restrict)
        self.sites = list(dict.fromkeys(sites))
        base = self.library if library is None else library
        self.library = list(dict.fromkeys([*base, *self.sites]))
        self.check.blockSignals(True)
        self.check.setChecked(self.restrict)
        self.check.blockSignals(False)
        self._reload()

    def set_remove_only(self, on: bool) -> None:
        """빼기만 할 수 있게 합니다: 지금 체크한 사이트만 보이고 추가·삭제·제한 끄기는 못 함."""
        self.remove_only = bool(on)
        self._pool = list(self.sites)
        self.check.setEnabled(not on)
        self.add_btn.setVisible(not on)
        self._reload()

    def set_context(self, apps: List[str], helper_installed: Optional[bool]) -> None:
        """경고 문구에 쓰는 정보: 모드의 허용 앱, 관리자 권한 도우미가 설치돼 있는지 (모르면 None)."""
        self._apps = list(apps)
        self._helper_installed = helper_installed
        self._reload()  # 안내 문구가 허용 앱(브라우저가 있는지)에 따라 달라짐

    # ------------------------------------------------------------- 화면
    def _reload(self) -> None:
        self.list.clear()
        shown = self._pool if self.remove_only else self.library
        on_delete = None if self.remove_only else self.delete_site
        for site in shown:
            self.list.add_row(SiteRow(site, site in self.sites, self._on_row_toggled, on_delete), 36)
        self.list.setVisible(bool(shown))
        self.list.setEnabled(self.restrict)
        self.add_btn.setEnabled(self.restrict)
        if self.remove_only:
            self.empty.setText(
                "체크를 풀면 그 사이트를 지금 집중에서 뺍니다. 새 사이트를 넣으려면 '허용 앱·사이트 편집'을 쓰세요."
                if self.restrict else "이 모드는 사이트를 제한하지 않습니다."
            )
        elif not self.restrict:
            self.empty.setText(
                f"켜면 집중 중에 {SUPPORTED_NAMES}에서 고른 사이트만 열 수 있습니다. "
                "끄면 허용한 브라우저에서 모든 사이트가 열립니다."
            )
        elif not self.sites:
            self.empty.setText(
                ("저장한 사이트 중 쓸 사이트에 체크하세요. " if self.library else "")
                + "고른 사이트가 없어 브라우저에서 아무 사이트도 열 수 없습니다 (내 PC의 PDF 같은 파일은 열림)."
            )
        else:
            browser = any(a in browser_policy.SUPPORTED_EXES for a in self._apps)
            self.empty.setText(
                ("" if browser else f"브라우저를 허용 앱에 넣지 않아도 {SUPPORTED_NAMES}에서 이 사이트들만 열 수 있습니다. ")
                + "다른 주소로 넘어가는 사이트(예: 로그인 페이지)는 그 주소도 추가하세요. "
                "집중을 시작할 때 열려 있던 브라우저는 다시 시작해야 적용됩니다."
            )
        self._update_warning()

    def _update_warning(self) -> None:
        lines = []
        if self.restrict:
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

    def add_sites(self, text: str, check: bool = False) -> List[str]:
        """주소들을 저장한 사이트 목록에 추가하고, 쓸 수 없어 건너뛴 항목을 돌려줍니다 (있으면 알림).

        새로 추가한 사이트는 체크하지 않은 채로 둡니다 (쓸 사이트는 직접 체크). check=True면 바로 체크.
        """
        bad: List[str] = []
        added = new_in_library = False
        for part in re.split(r"[\s,]+", text or ""):
            if not part:
                continue
            site = normalize_site(part)
            if not site:
                bad.append(part)
                continue
            if check and site not in self.sites:
                self.sites.append(site)
                added = True
            if site not in self.library:
                self.library.append(site)
                new_in_library = True
        if added or new_in_library:
            self._reload()
        if new_in_library:
            self.library_changed.emit()
        if added:
            self.changed.emit()
        if bad:
            QMessageBox.warning(self, "사이트 추가", "사이트 주소로 쓸 수 없어 건너뛰었습니다:\n" + "\n".join(bad))
        return bad

    def _on_row_toggled(self, site: str, on: bool) -> None:
        if on and self.remove_only and site not in self._pool:
            return
        if on and site not in self.sites:
            self.sites.append(site)
        elif not on and site in self.sites:
            self.sites = [s for s in self.sites if s != site]
        else:
            return
        self.changed.emit()

    def remove_site(self, site: str) -> None:
        """체크만 풉니다 (저장한 사이트 목록에는 남음)."""
        if site not in self.sites:
            return
        self.sites = [s for s in self.sites if s != site]
        self._reload()
        self.changed.emit()

    def delete_site(self, site: str) -> None:
        """저장한 사이트 목록에서 아예 지웁니다 (체크돼 있었으면 이 모드에서도 빠짐)."""
        was_used = site in self.sites
        self.library = [s for s in self.library if s != site]
        self.sites = [s for s in self.sites if s != site]
        self._reload()
        self.library_changed.emit()
        if was_used:
            self.changed.emit()

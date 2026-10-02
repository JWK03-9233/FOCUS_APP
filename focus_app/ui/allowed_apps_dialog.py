"""집중 중에 지금 모드의 허용 앱·사이트 목록만 고치는 대화상자.

- 편집: 해제 문자열을 입력한 뒤에만 열림. 추가·빼기 모두 가능.
- 빼기만(``remove_only``): 해제 문자열 없이 열림. 지금 허용된 앱·사이트를 빼기만 할 수 있음.

타이머와 차단은 그대로 계속되며, 저장하면 바뀐 목록이 즉시 적용되고 모드에도 저장됩니다.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QWidget,
)

from focus_app import web_apps
from focus_app.config import Profile, Settings, normalize_exe
from focus_app.ui import app_catalog
from focus_app.ui.app_catalog import AppEntry
from focus_app.ui.app_picker import AppPickerDialog
from focus_app.ui.main_window import AppRow
from focus_app.ui.site_list import SiteEditor
from focus_app.ui.scroll import ExpandedList, scroll_layout


class AllowedAppsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        profile: Profile,
        parent: QWidget | None = None,
        on_settings_changed: Optional[Callable[[], None]] = None,
        helper_installed: Optional[bool] = None,
        remove_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.remove_only = remove_only
        self._on_settings_changed = on_settings_changed
        self.profile_name = profile.name
        self._apps: List[str] = profile.normalized_apps()  # 저장 전까지는 복사본만 고침
        self._new_entries: Dict[str, AppEntry] = {}
        self._helper_installed = helper_installed
        self.setWindowTitle("허용 앱·사이트 빼기" if remove_only else "허용 앱·사이트 편집")
        self.setMinimumSize(500, 600)

        layout = scroll_layout(self)  # 내용이 많으면 창 전체를 스크롤
        layout.setSpacing(10)
        title = QLabel(f"<b>{profile.name}</b> 모드의 허용 앱과 사이트")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        hint = QLabel(
            "집중은 그대로 계속됩니다. 저장하면 바뀐 목록이 바로 적용됩니다."
            + (" 여기서는 빼기만 할 수 있습니다." if remove_only else "")
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        head = QHBoxLayout()
        self.count = QLabel("")
        self.count.setObjectName("sectionTitle")
        head.addWidget(self.count, 1)
        add = QPushButton("+  앱 추가")
        add.setObjectName("secondary")
        add.clicked.connect(self._add)
        add.setVisible(not remove_only)
        head.addWidget(add)
        layout.addLayout(head)

        self.list = ExpandedList()  # 안쪽 스크롤 없이 모두 펼침 (넘치면 창 전체 스크롤)
        self.list.setObjectName("appList")
        self.list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self.list, 3)

        self.sites = SiteEditor()
        self.sites.set_values(profile.restrict_sites, profile.normalized_sites(), settings.saved_sites)
        self.sites.set_remove_only(remove_only)
        layout.addWidget(self.sites, 2)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("저장")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self._reload()

    def _name(self, exe: str) -> str:
        entry = self._new_entries.get(exe)
        return entry.name if entry else self.settings.app_display_name(exe)

    def _path(self, exe: str) -> str:
        entry = self._new_entries.get(exe)
        return (entry.path if entry else self.settings.app_path(exe)) or app_catalog.find_installed_path(exe)

    def _reload(self) -> None:
        self.list.clear()
        self.count.setText(f"쓸 수 있는 앱 ({len(self._apps)}개)")
        self.sites.set_context(self._apps, self._helper_installed)
        for exe in self._apps:
            row = AppRow(self._name(exe), exe, self._path(exe), self.remove_app)
            self.list.add_row(row, 40)

    def _add(self) -> None:
        dlg = AppPickerDialog(
            self.profile_name,
            self._apps,
            parent=self,
            favorites=self.settings.favorite_apps,
            on_favorites_changed=self._save_favorite_apps,
            hidden=self.settings.hidden_apps,
            on_hidden_changed=self._save_hidden_apps,
            app_names=self.settings.app_display_name,
            app_paths=self._path,
        )
        try:
            if dlg.exec() != AppPickerDialog.DialogCode.Accepted:
                return
            entries = dlg.selected_entries()
        finally:
            dlg.deleteLater()
        self.add_entries(entries)

    def _save_favorite_apps(self, favorites: List[str]) -> None:
        # 즐겨찾기는 허용 앱 편집을 취소해도 유지 (차단과 무관한 표시 설정)
        self.settings.favorite_apps = list(favorites)
        if self._on_settings_changed is not None:
            self._on_settings_changed()

    def _save_hidden_apps(self, hidden: List[str]) -> None:
        # 숨긴 앱도 허용 앱 편집을 취소해도 유지 (차단과 무관한 표시 설정)
        self.settings.hidden_apps = list(hidden)
        if self._on_settings_changed is not None:
            self._on_settings_changed()

    def add_entries(self, entries: List[AppEntry]) -> None:
        if self.remove_only:
            return
        for e in entries:
            exe = normalize_exe(e.exe)
            if exe and exe not in self._apps:
                self._apps.append(exe)
                self._new_entries[exe] = e
        # 웹 앱(Google Keep 등)은 사이트 제한을 켜면 그 주소도 허용해야 열림 -> 허용 사이트에 미리 넣음
        extra = web_apps.sites_for_new_apps([e.exe for e in entries], self.sites.sites)
        if extra:
            self.sites.set_values(self.sites.restrict, self.sites.sites + extra)
        self._reload()

    def remove_app(self, exe: str) -> None:
        exe = normalize_exe(exe)
        self._apps = [a for a in self._apps if a != exe]
        self._reload()

    def apply_to(self, settings: Settings) -> Profile:
        """편집 결과를 설정의 해당 모드에 반영하고 그 모드를 돌려줍니다."""
        profile = settings.get_profile(self.profile_name)
        if profile is None:
            raise ValueError(f"모드를 찾을 수 없습니다: {self.profile_name}")
        if self.remove_only:
            # 빼기만: 원래 목록에 있던 것만 남김 (어떤 경로로도 추가되지 않게 한 번 더 확인)
            before_apps, before_sites = profile.normalized_apps(), profile.normalized_sites()
            profile.allowed_apps = [a for a in self._apps if a in before_apps]
            profile.allowed_sites = [s for s in self.sites.sites if s in before_sites]
            return profile
        profile.allowed_apps = list(self._apps)
        profile.restrict_sites = self.sites.restrict
        profile.allowed_sites = list(self.sites.sites)
        gone = [s for s in settings.saved_sites if s not in self.sites.library]
        settings.saved_sites = list(self.sites.library)
        for other in settings.profiles:
            for site in gone:
                other.remove_site(site)
        for exe, e in self._new_entries.items():
            if exe in self._apps:
                settings.remember_app(exe, e.name, e.path)
        return profile

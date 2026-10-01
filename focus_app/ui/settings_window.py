"""설정 창: 프로필과 허용 앱 목록 편집, 일반 설정.

집중 모드가 켜져 있는 동안에는 읽기 전용으로 열립니다 (몰래 앱을 추가하는 우회 방지).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from focus_app import winapi
from focus_app.config import Profile, Settings, normalize_exe
from focus_app.enforcer import SYSTEM_EXES


class SettingsWindow(QDialog):
    def __init__(
        self,
        settings: Settings,
        locked: bool,
        on_saved: Optional[Callable[[Settings], None]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.locked = locked
        self.on_saved = on_saved
        self.setWindowTitle("FocusApp 설정" + (" (집중 모드 중 - 읽기 전용)" if locked else ""))
        self.resize(760, 520)

        root = QVBoxLayout(self)
        if locked:
            banner = QLabel("집중 모드가 켜져 있어 설정을 바꿀 수 없습니다. 해제한 뒤 편집하세요.")
            banner.setStyleSheet("background: #fff3cd; color: #7a5a00; padding: 8px; border-radius: 4px;")
            banner.setWordWrap(True)
            root.addWidget(banner)

        tabs = QTabWidget()
        tabs.addTab(self._build_profiles_tab(), "프로필 / 허용 앱")
        tabs.addTab(self._build_general_tab(), "일반")
        root.addWidget(tabs)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.save_btn = QPushButton("저장")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(not locked)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.save_btn)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self._reload_profiles()

    # ------------------------------------------------------------ 프로필 탭
    def _build_profiles_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        splitter = QSplitter()

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("프로필"))
        self.profile_list = QListWidget()
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        ll.addWidget(self.profile_list)
        pb = QHBoxLayout()
        self.add_profile_btn = QPushButton("추가")
        self.add_profile_btn.clicked.connect(self._add_profile)
        self.rename_profile_btn = QPushButton("이름 변경")
        self.rename_profile_btn.clicked.connect(self._rename_profile)
        self.remove_profile_btn = QPushButton("삭제")
        self.remove_profile_btn.clicked.connect(self._remove_profile)
        for b in (self.add_profile_btn, self.rename_profile_btn, self.remove_profile_btn):
            b.setEnabled(not self.locked)
            pb.addWidget(b)
        ll.addLayout(pb)
        splitter.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.block_checkbox = QCheckBox("이 프로필에서는 허용 목록 외 모든 앱을 차단")
        self.block_checkbox.setEnabled(not self.locked)
        self.block_checkbox.toggled.connect(self._on_block_toggled)
        rl.addWidget(self.block_checkbox)
        rl.addWidget(QLabel("허용 앱 (실행 파일 이름)"))
        self.app_list = QListWidget()
        self.app_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        rl.addWidget(self.app_list)
        ab = QHBoxLayout()
        self.add_running_btn = QPushButton("실행 중인 앱에서 추가")
        self.add_running_btn.clicked.connect(self._add_from_running)
        self.add_manual_btn = QPushButton("이름으로 추가")
        self.add_manual_btn.clicked.connect(self._add_manual)
        self.add_browse_btn = QPushButton("파일 찾기")
        self.add_browse_btn.clicked.connect(self._add_browse)
        self.remove_app_btn = QPushButton("제거")
        self.remove_app_btn.clicked.connect(self._remove_apps)
        for b in (self.add_running_btn, self.add_manual_btn, self.add_browse_btn, self.remove_app_btn):
            b.setEnabled(not self.locked)
            ab.addWidget(b)
        rl.addLayout(ab)
        hint = QLabel(
            "작업 표시줄·시작 메뉴·작업 관리자 등 시스템 요소와 이 앱 자신은 목록과 관계없이 항상 허용됩니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #666;")
        rl.addWidget(hint)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter)
        return w

    def _current_profile(self) -> Optional[Profile]:
        item = self.profile_list.currentItem()
        if item is None:
            return None
        return self.settings.get_profile(item.text())

    def _reload_profiles(self, select: Optional[str] = None) -> None:
        select = select or (self._current_profile().name if self._current_profile() else self.settings.active_profile)
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for p in self.settings.profiles:
            self.profile_list.addItem(QListWidgetItem(p.name))
        self.profile_list.blockSignals(False)
        items = self.profile_list.findItems(select, Qt.MatchFlag.MatchExactly)
        self.profile_list.setCurrentItem(items[0] if items else self.profile_list.item(0))
        self._reload_apps()

    def _reload_apps(self) -> None:
        self.app_list.clear()
        p = self._current_profile()
        if p is None:
            return
        self.block_checkbox.blockSignals(True)
        self.block_checkbox.setChecked(p.block_everything)
        self.block_checkbox.blockSignals(False)
        for app in p.normalized_apps():
            self.app_list.addItem(app)
        self.app_list.setEnabled(p.block_everything)

    def _on_profile_selected(self, *_args) -> None:
        self._reload_apps()

    def _on_block_toggled(self, on: bool) -> None:
        p = self._current_profile()
        if p is not None:
            p.block_everything = on
            self.app_list.setEnabled(on)

    def _add_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "프로필 추가", "프로필 이름:")
        if not ok:
            return
        try:
            self.settings.add_profile(name)
        except ValueError as exc:
            QMessageBox.warning(self, "프로필 추가", str(exc))
            return
        self._reload_profiles(select=name.strip())

    def _rename_profile(self) -> None:
        p = self._current_profile()
        if p is None:
            return
        name, ok = QInputDialog.getText(self, "이름 변경", "새 이름:", text=p.name)
        if not ok:
            return
        try:
            self.settings.rename_profile(p.name, name)
        except ValueError as exc:
            QMessageBox.warning(self, "이름 변경", str(exc))
            return
        self._reload_profiles(select=name.strip())

    def _remove_profile(self) -> None:
        p = self._current_profile()
        if p is None:
            return
        answer = QMessageBox.question(self, "프로필 삭제", f"'{p.name}' 프로필을 삭제할까요?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.settings.remove_profile(p.name)
        except ValueError as exc:
            QMessageBox.warning(self, "프로필 삭제", str(exc))
            return
        self._reload_profiles(select=self.settings.active_profile)

    def _add_app_name(self, name: str) -> None:
        p = self._current_profile()
        if p is None:
            return
        n = normalize_exe(name)
        if not n:
            return
        if n in SYSTEM_EXES:
            QMessageBox.information(self, "허용 앱", f"{n}은(는) 시스템 요소로 항상 허용되므로 추가할 필요가 없습니다.")
            return
        if p.add_app(n):
            self._reload_apps()

    def _add_from_running(self) -> None:
        windows = winapi.list_visible_windows()
        if not windows:
            QMessageBox.information(self, "실행 중인 앱", "실행 중인 창을 찾지 못했습니다. (Windows에서만 지원)")
            return
        menu = QMenu(self)
        seen = set()
        for info in sorted(windows, key=lambda i: (i.exe_name, i.title)):
            if info.exe_name in seen or info.exe_name in SYSTEM_EXES:
                continue
            seen.add(info.exe_name)
            title = info.title if len(info.title) <= 50 else info.title[:47] + "…"
            act = menu.addAction(f"{info.exe_name}  -  {title}")
            act.setData(info.exe_name)
        if menu.isEmpty():
            QMessageBox.information(self, "실행 중인 앱", "추가할 수 있는 앱이 없습니다.")
            return
        chosen = menu.exec(self.add_running_btn.mapToGlobal(self.add_running_btn.rect().bottomLeft()))
        if chosen is not None:
            self._add_app_name(str(chosen.data()))

    def _add_manual(self) -> None:
        name, ok = QInputDialog.getText(self, "이름으로 추가", "실행 파일 이름 (예: chrome.exe):")
        if ok and name.strip():
            if "." not in name:
                name = name.strip() + ".exe"
            self._add_app_name(name)

    def _add_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "실행 파일 선택", "", "실행 파일 (*.exe);;모든 파일 (*)")
        if path:
            self._add_app_name(Path(path).name)

    def _remove_apps(self) -> None:
        p = self._current_profile()
        if p is None:
            return
        for item in self.app_list.selectedItems():
            p.remove_app(item.text())
        self._reload_apps()

    # ------------------------------------------------------------- 일반 탭
    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        box = QGroupBox("감시")
        form = QFormLayout(box)
        self.poll_spin = QSpinBox()
        self.poll_spin.setRange(100, 5000)
        self.poll_spin.setSingleStep(50)
        self.poll_spin.setSuffix(" ms")
        self.poll_spin.setValue(self.settings.poll_interval_ms)
        form.addRow("포그라운드 창 확인 주기", self.poll_spin)
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 1440)
        self.duration_spin.setSuffix(" 분")
        self.duration_spin.setValue(self.settings.default_duration_minutes)
        form.addRow("기본 집중 시간", self.duration_spin)
        self.notify_check = QCheckBox("앱을 차단할 때 트레이 알림 표시")
        self.notify_check.setChecked(self.settings.show_block_notifications)
        form.addRow("", self.notify_check)
        layout.addWidget(box)

        box2 = QGroupBox("해제 마찰")
        form2 = QFormLayout(box2)
        self.code_len_spin = QSpinBox()
        self.code_len_spin.setRange(8, 128)
        self.code_len_spin.setSuffix(" 글자")
        self.code_len_spin.setValue(self.settings.unlock_code_length)
        form2.addRow("해제 문자열 길이", self.code_len_spin)
        self.quit_check = QCheckBox("집중 모드 중 종료에도 문자열 입력 요구")
        self.quit_check.setChecked(self.settings.require_unlock_for_quit)
        form2.addRow("", self.quit_check)
        self.switch_check = QCheckBox("집중 모드 중 프로필 전환에도 문자열 입력 요구")
        self.switch_check.setChecked(self.settings.require_unlock_for_profile_switch)
        form2.addRow("", self.switch_check)
        self.emergency_spin = QSpinBox()
        self.emergency_spin.setRange(1, 240)
        self.emergency_spin.setSuffix(" 분")
        self.emergency_spin.setValue(self.settings.emergency_delay_minutes)
        form2.addRow("비상 해제 지연", self.emergency_spin)
        note = QLabel(
            "비상 해제는 오작동에 대비한 수단입니다. 트레이에서 요청하면 지연 시간이 지난 뒤에야 차단이 풀리며, "
            "그동안 차단은 계속되고 언제든 취소할 수 있습니다."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #666;")
        form2.addRow(note)
        layout.addWidget(box2)
        layout.addStretch(1)

        for widget in (
            self.poll_spin,
            self.duration_spin,
            self.notify_check,
            self.code_len_spin,
            self.quit_check,
            self.switch_check,
            self.emergency_spin,
        ):
            widget.setEnabled(not self.locked)
        return w

    # ------------------------------------------------------------- 저장
    def _save(self) -> None:
        if self.locked:
            return
        s = self.settings
        s.poll_interval_ms = int(self.poll_spin.value())
        s.default_duration_minutes = int(self.duration_spin.value())
        s.show_block_notifications = self.notify_check.isChecked()
        s.unlock_code_length = int(self.code_len_spin.value())
        s.require_unlock_for_quit = self.quit_check.isChecked()
        s.require_unlock_for_profile_switch = self.switch_check.isChecked()
        s.emergency_delay_minutes = int(self.emergency_spin.value())
        try:
            s.save()
        except OSError as exc:
            QMessageBox.critical(self, "저장 실패", f"설정을 저장하지 못했습니다:\n{exc}")
            return
        if self.on_saved:
            self.on_saved(s)
        self.accept()

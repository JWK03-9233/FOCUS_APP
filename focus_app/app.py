"""트레이 아이콘과 집중 세션을 묶는 애플리케이션 컨트롤러."""

from __future__ import annotations

import copy
import logging
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from focus_app.config import Settings
from focus_app.enforcer import ForegroundWindow
from focus_app.monitor import AllowlistMonitor
from focus_app.session import FocusSession, format_duration
from focus_app.ui import icons
from focus_app.ui.settings_window import SettingsWindow
from focus_app.ui.start_dialog import StartDialog
from focus_app.ui.unlock_dialog import confirm_with_code
from focus_app.version import APP_NAME, __version__

log = logging.getLogger(__name__)


class FocusApp:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.settings = Settings.load()
        self.session: Optional[FocusSession] = None
        self.monitor: Optional[AllowlistMonitor] = None
        self._settings_window: Optional[SettingsWindow] = None
        self._dialog_open = False

        self.tray = QSystemTrayIcon(icons.idle_icon())
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll)
        self.status_timer = QTimer()
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self._refresh_status)
        self.status_timer.start()

        self._resume_saved_session()
        self._refresh_status()

    # ------------------------------------------------------------- 메뉴
    def _build_menu(self) -> None:
        m = self.menu
        m.clear()
        self.status_action = QAction("대기 중")
        self.status_action.setEnabled(False)
        m.addAction(self.status_action)
        m.addSeparator()

        self.start_action = QAction("집중 모드 시작…")
        self.start_action.triggered.connect(self.start_focus)
        m.addAction(self.start_action)
        self.stop_action = QAction("집중 모드 해제…")
        self.stop_action.triggered.connect(self.stop_focus)
        m.addAction(self.stop_action)

        self.profile_menu = QMenu("프로필")
        self.profile_group = QActionGroup(self.profile_menu)
        self.profile_group.setExclusive(True)
        self._rebuild_profile_menu()
        m.addMenu(self.profile_menu)
        m.addSeparator()

        self.settings_action = QAction("설정…")
        self.settings_action.triggered.connect(self.open_settings)
        m.addAction(self.settings_action)
        self.emergency_action = QAction("비상 해제 요청…")
        self.emergency_action.triggered.connect(self.request_emergency)
        m.addAction(self.emergency_action)
        self.cancel_emergency_action = QAction("비상 해제 취소")
        self.cancel_emergency_action.triggered.connect(self.cancel_emergency)
        m.addAction(self.cancel_emergency_action)
        m.addSeparator()
        about = QAction(f"{APP_NAME} v{__version__}")
        about.setEnabled(False)
        m.addAction(about)
        self.quit_action = QAction("종료")
        self.quit_action.triggered.connect(self.quit)
        m.addAction(self.quit_action)

    def _rebuild_profile_menu(self) -> None:
        self.profile_menu.clear()
        for act in self.profile_group.actions():
            self.profile_group.removeAction(act)
        for name in self.settings.profile_names():
            act = QAction(name, self.profile_menu)
            act.setCheckable(True)
            act.setChecked(name == self.settings.active_profile)
            act.triggered.connect(lambda _=False, n=name: self.switch_profile(n))
            self.profile_group.addAction(act)
            self.profile_menu.addAction(act)

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.session is None:
                self.start_focus()
            else:
                self.stop_focus()

    # ------------------------------------------------------------ 상태 표시
    @property
    def active(self) -> bool:
        return self.session is not None

    def _refresh_status(self) -> None:
        if self.session is None:
            text = "대기 중"
            tip = f"{APP_NAME} - 대기 중 (프로필: {self.settings.active_profile})"
            self.tray.setIcon(icons.idle_icon())
        else:
            s = self.session
            remaining = s.remaining_seconds()
            blocked = self.monitor.block_count if self.monitor else 0
            text = f"집중 중 [{s.profile}] 남은 시간 {format_duration(remaining)} · 차단 {blocked}회"
            tip = f"{APP_NAME} - {text}"
            if s.emergency_at is not None:
                left = format_duration(s.emergency_remaining_seconds())
                text += f" · 비상 해제까지 {left}"
                tip += f"\n비상 해제까지 {left}"
                self.tray.setIcon(icons.emergency_icon())
            else:
                self.tray.setIcon(icons.active_icon())
            reason = s.expiry_reason()
            if reason is not None:
                self._end_session(reason=reason)
                return
        self.status_action.setText(text)
        self.tray.setToolTip(tip)
        self.start_action.setEnabled(not self.active)
        self.stop_action.setEnabled(self.active)
        self.emergency_action.setEnabled(self.active and (self.session.emergency_at is None))
        self.cancel_emergency_action.setVisible(self.active and self.session.emergency_at is not None)

    # ------------------------------------------------------------- 세션
    def _resume_saved_session(self) -> None:
        saved = FocusSession.load()
        if saved is None:
            return
        if saved.is_expired() or self.settings.get_profile(saved.profile) is None:
            FocusSession.clear()
            return
        log.info("저장된 세션을 이어갑니다: %s", saved.profile)
        self._begin(saved, resumed=True)

    def start_focus(self) -> None:
        if self.active or self._dialog_open:
            return
        self._dialog_open = True
        try:
            dlg = StartDialog(self.settings)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            profile_name, minutes = dlg.result_values()
        finally:
            self._dialog_open = False
        self.settings.active_profile = profile_name
        self._safe_save_settings()
        self._rebuild_profile_menu()
        self._begin(FocusSession.start(profile_name, minutes))

    def _begin(self, session: FocusSession, resumed: bool = False) -> None:
        profile = self.settings.get_profile(session.profile) or self.settings.current_profile()
        self.session = session
        session.save()
        self.monitor = AllowlistMonitor(profile=copy.deepcopy(profile), on_block=self._on_block)
        self.poll_timer.start(self.settings.poll_interval_ms)
        if self._settings_window is not None:
            self._settings_window.close()
        self._refresh_status()
        remaining = format_duration(session.remaining_seconds())
        self.tray.showMessage(
            APP_NAME,
            ("이전 세션을 이어갑니다. " if resumed else "집중 모드를 시작했습니다. ")
            + f"프로필: {session.profile}, 남은 시간: {remaining}",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def stop_focus(self) -> None:
        if not self.active or self._dialog_open:
            return
        if self._confirm("집중 모드 해제"):
            self._end_session(reason="manual")

    def _end_session(self, reason: str) -> None:
        self.poll_timer.stop()
        self.monitor = None
        self.session = None
        FocusSession.clear()
        self._refresh_status()
        msg = {
            "manual": "집중 모드를 해제했습니다.",
            "expired": "정한 시간이 끝나 집중 모드가 해제되었습니다.",
            "emergency": "비상 해제가 적용되어 집중 모드가 해제되었습니다.",
        }.get(reason, "집중 모드가 해제되었습니다.")
        self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.MessageIcon.Information, 4000)

    def _poll(self) -> None:
        if self.monitor is None or self.session is None:
            return
        self.monitor.poll()

    def _on_block(self, window: ForegroundWindow) -> None:
        if self.settings.show_block_notifications:
            self.tray.showMessage(
                APP_NAME,
                f"허용되지 않은 앱을 최소화했습니다: {window.exe_name}",
                QSystemTrayIcon.MessageIcon.Warning,
                2000,
            )

    # --------------------------------------------------------- 프로필 전환
    def switch_profile(self, name: str) -> None:
        if name == self.settings.active_profile:
            return
        if self.active and self.settings.require_unlock_for_profile_switch:
            if not self._confirm(f"프로필 전환 ({name})"):
                self._rebuild_profile_menu()  # 체크 상태 되돌림
                return
        self.settings.active_profile = name
        self._safe_save_settings()
        if self.active and self.session is not None and self.monitor is not None:
            self.session.profile = name
            self.session.save()
            profile = self.settings.get_profile(name) or self.settings.current_profile()
            self.monitor.set_profile(copy.deepcopy(profile))
        self._rebuild_profile_menu()
        self._refresh_status()

    # ------------------------------------------------------------- 설정
    def open_settings(self) -> None:
        if self._settings_window is not None:
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        # 집중 모드 중에는 복사본을 보여주어 어떤 변경도 반영되지 않게 함
        target = copy.deepcopy(self.settings) if self.active else self.settings
        win = SettingsWindow(target, locked=self.active, on_saved=self._on_settings_saved)
        self._settings_window = win
        win.finished.connect(self._on_settings_closed)
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_settings_closed(self, _result: int) -> None:
        self._settings_window = None
        if not self.active:
            # 저장하지 않고 닫았을 수 있으므로 디스크 상태로 되돌림
            self.settings = Settings.load()
            self._rebuild_profile_menu()
            self._refresh_status()

    def _on_settings_saved(self, settings: Settings) -> None:
        self.settings = settings
        self._rebuild_profile_menu()
        self._refresh_status()

    def _safe_save_settings(self) -> None:
        try:
            self.settings.save()
        except OSError:
            log.exception("설정 저장 실패")

    # ---------------------------------------------------------- 비상 해제
    def request_emergency(self) -> None:
        if not self.active or self.session is None or self._dialog_open:
            return
        delay = self.settings.emergency_delay_minutes
        self._dialog_open = True
        try:
            answer = QMessageBox.question(
                None,
                "비상 해제",
                f"비상 해제는 오작동에 대비한 수단입니다.\n\n요청하면 {delay}분 뒤에 차단이 풀리며, "
                "그동안 차단은 계속됩니다. 언제든 취소할 수 있습니다.\n\n요청할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        finally:
            self._dialog_open = False
        if answer != QMessageBox.StandardButton.Yes or self.session is None:
            return
        self.session.request_emergency(delay)
        self.session.save()
        self._refresh_status()

    def cancel_emergency(self) -> None:
        if self.session is None:
            return
        self.session.cancel_emergency()
        self.session.save()
        self._refresh_status()

    # ------------------------------------------------------------- 종료
    def quit(self) -> None:
        if self.active and self.settings.require_unlock_for_quit:
            if not self._confirm("프로그램 종료"):
                return
        # 세션 파일은 남겨 두어, 재실행 시 남은 시간 동안 차단을 이어가게 함 (해제 후 종료는 파일이 이미 지워짐)
        self.tray.hide()
        self.app.quit()

    # ------------------------------------------------------------- 공통
    def _confirm(self, purpose: str) -> bool:
        if self._dialog_open:
            return False
        self._dialog_open = True
        try:
            return confirm_with_code(self.settings.unlock_code_length, purpose)
        finally:
            self._dialog_open = False

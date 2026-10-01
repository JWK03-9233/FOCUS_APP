"""메인 창, 트레이 아이콘, 집중 세션을 묶는 애플리케이션 컨트롤러."""

from __future__ import annotations

import copy
import logging
from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from focus_app.config import Settings
from focus_app.enforcer import ForegroundWindow
from focus_app.monitor import AllowlistMonitor
from focus_app.session import FocusSession, format_duration
from focus_app.ui import app_catalog, icons
from focus_app.ui.main_window import MainWindow
from focus_app.ui.preferences_dialog import PreferencesDialog
from focus_app.ui.theme import STYLESHEET
from focus_app.ui.unlock_dialog import confirm_with_code
from focus_app.version import APP_NAME, __version__

log = logging.getLogger(__name__)


class FocusApp:
    def __init__(self, app: QApplication, show_window: bool = True) -> None:
        self.app = app
        app.setStyleSheet(STYLESHEET)
        self.settings = Settings.load()
        self.session: Optional[FocusSession] = None
        self.monitor: Optional[AllowlistMonitor] = None
        self._dialog_open = False
        self._told_about_tray = False

        app_catalog.installed_apps.preload()  # 앱 고르기 창을 빨리 열 수 있게 미리 읽어 둠

        # --- 메인 창
        self.window = MainWindow(self.settings)
        self.window.start_requested.connect(self.start_focus)
        self.window.stop_requested.connect(self.stop_focus)
        self.window.emergency_requested.connect(self.request_emergency)
        self.window.cancel_emergency_requested.connect(self.cancel_emergency)
        self.window.settings_changed.connect(self._safe_save_settings)
        self.window.preferences_requested.connect(self.open_preferences)
        self.window.quit_requested.connect(self.quit)
        self.window.on_hidden_to_tray = self._on_window_hidden

        # --- 트레이
        self._icons = {"idle": icons.idle_icon(), "active": icons.active_icon(), "emergency": icons.emergency_icon()}
        self._icon_state = "idle"
        self.tray = QSystemTrayIcon(self._icons["idle"])
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
        if show_window:
            self.show_window()

    # ------------------------------------------------------------- 창
    def show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_window_hidden(self) -> None:
        if not self._told_about_tray:
            self._told_about_tray = True
            self.tray.showMessage(
                APP_NAME,
                "FocusApp은 작업 표시줄 오른쪽 트레이에서 계속 실행됩니다. 아이콘을 누르면 창이 다시 열립니다.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    # ------------------------------------------------------------- 트레이 메뉴
    def _build_menu(self) -> None:
        m = self.menu
        m.clear()
        self.status_action = QAction("대기 중", m)
        self.status_action.setEnabled(False)
        m.addAction(self.status_action)
        m.addSeparator()
        self.open_action = QAction("FocusApp 열기", m)
        self.open_action.triggered.connect(self.show_window)
        m.addAction(self.open_action)
        self.stop_action = QAction("집중 끝내기…", m)
        self.stop_action.triggered.connect(self.stop_focus)
        m.addAction(self.stop_action)
        self.emergency_action = QAction("비상 해제…", m)
        self.emergency_action.triggered.connect(self.request_emergency)
        m.addAction(self.emergency_action)
        self.cancel_emergency_action = QAction("비상 해제 취소", m)
        self.cancel_emergency_action.triggered.connect(self.cancel_emergency)
        m.addAction(self.cancel_emergency_action)
        m.addSeparator()
        about = QAction(f"{APP_NAME} v{__version__}", m)
        about.setEnabled(False)
        m.addAction(about)
        self.quit_action = QAction("종료", m)
        self.quit_action.triggered.connect(self.quit)
        m.addAction(self.quit_action)

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def _set_icon(self, state: str) -> None:
        # 매초 같은 아이콘을 다시 설정하면 트레이가 깜빡일 수 있어 바뀔 때만 교체
        if state != self._icon_state:
            self._icon_state = state
            self.tray.setIcon(self._icons[state])

    # ------------------------------------------------------------ 상태 표시
    @property
    def active(self) -> bool:
        return self.session is not None

    def _refresh_status(self) -> None:
        if self.session is None:
            text = "대기 중"
            tip = f"{APP_NAME} - 대기 중"
            self._set_icon("idle")
        else:
            s = self.session
            reason = s.expiry_reason()
            if reason is not None:
                self._end_session(reason=reason)
                return
            remaining = s.remaining_seconds()
            blocked = self.monitor.block_count if self.monitor else 0
            left = "제한 없음" if remaining is None else f"{format_duration(remaining)} 남음"
            text = f"집중 중: {s.profile} · {left}"
            tip = f"{APP_NAME} - {text}"
            if s.emergency_at is not None:
                e_left = format_duration(s.emergency_remaining_seconds())
                text += f" · 비상 해제까지 {e_left}"
                tip += f"\n비상 해제까지 {e_left}"
                self._set_icon("emergency")
            else:
                self._set_icon("active")
            self.window.update_running(s, blocked)
        self.status_action.setText(text)
        self.tray.setToolTip(tip)
        pending = self.active and self.session.emergency_at is not None
        self.stop_action.setVisible(self.active)
        self.emergency_action.setVisible(self.active and not pending)
        self.cancel_emergency_action.setVisible(pending)

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

    def start_focus(self, profile_name: str, minutes: Optional[int]) -> None:
        if self.active or self.settings.get_profile(profile_name) is None:
            return
        self.settings.active_profile = profile_name
        self._safe_save_settings()
        self._begin(FocusSession.start(profile_name, minutes))

    def _begin(self, session: FocusSession, resumed: bool = False) -> None:
        profile = self.settings.get_profile(session.profile) or self.settings.current_profile()
        self.session = session
        self._safe_save_session()
        self.monitor = AllowlistMonitor(profile=copy.deepcopy(profile), on_block=self._on_block)
        self.poll_timer.start(self.settings.poll_interval_ms)
        self.window.show_running(session, profile)
        self._refresh_status()
        remaining = session.remaining_seconds()
        left = "직접 끝낼 때까지" if remaining is None else f"{format_duration(remaining)} 동안"
        self.tray.showMessage(
            APP_NAME,
            ("이전 집중을 이어갑니다. " if resumed else "집중을 시작했습니다. ") + f"{session.profile} · {left}",
            QSystemTrayIcon.MessageIcon.Information,
            4000,
        )

    def stop_focus(self) -> None:
        if not self.active or self._dialog_open:
            return
        # 문자열을 입력하는 동안 시간이 다 되어 이미 끝났을 수 있으므로 다시 확인
        if self._confirm("집중 끝내기") and self.session is not None:
            self._end_session(reason="manual")

    def _end_session(self, reason: str) -> None:
        if self.session is None:
            return
        session, monitor = self.session, self.monitor
        self.poll_timer.stop()
        self.monitor = None
        self.session = None
        FocusSession.clear()
        self._refresh_status()

        minutes = session.elapsed_seconds() // 60 if session else 0
        blocked = monitor.block_count if monitor else 0
        summary = f"{minutes}분 동안 집중했어요." + (f" 다른 앱을 {blocked}번 막았어요." if blocked else "")
        msg = {
            "manual": "집중을 끝냈습니다.",
            "expired": "정한 시간이 끝났습니다. 수고했어요!",
            "emergency": "비상 해제가 적용되어 집중이 끝났습니다.",
        }.get(reason, "집중이 끝났습니다.")
        self.window.show_setup()
        self.window.show_notice(f"<b>{msg}</b>  {summary}")
        if reason != "manual":
            self.show_window()
        self.tray.showMessage(APP_NAME, f"{msg} {summary}", QSystemTrayIcon.MessageIcon.Information, 5000)

    def _poll(self) -> None:
        if self.monitor is None or self.session is None:
            return
        self.monitor.poll()

    def _on_block(self, window: ForegroundWindow) -> None:
        if self.settings.show_block_notifications:
            self.tray.showMessage(
                APP_NAME,
                f"집중 중이라 {self.settings.app_display_name(window.exe_name)}을(를) 최소화했어요.",
                QSystemTrayIcon.MessageIcon.Warning,
                2000,
            )

    # ------------------------------------------------------------- 설정
    def open_preferences(self) -> None:
        if self.active or self._dialog_open:
            return
        self._dialog_open = True
        try:
            dlg = PreferencesDialog(self.settings, parent=self.window)
            try:
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self._safe_save_settings()
            finally:
                dlg.deleteLater()
        finally:
            self._dialog_open = False

    def _safe_save_session(self) -> None:
        # 저장에 실패해도(동기화 프로그램이 파일을 잡고 있는 등) 차단은 계속되어야 함.
        # 재실행 시 이어가기만 못 할 뿐이므로 기록만 남김.
        if self.session is None:
            return
        try:
            self.session.save()
        except OSError:
            log.exception("세션 저장 실패")

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
                self.window if self.window.isVisible() else None,
                "비상 해제",
                f"프로그램이 잘못 동작할 때를 위한 비상 수단입니다.\n\n"
                f"요청하면 {delay}분 뒤에 집중이 끝납니다. 그동안 차단은 계속되고, 언제든 취소할 수 있습니다.\n\n"
                "요청할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
        finally:
            self._dialog_open = False
        if answer != QMessageBox.StandardButton.Yes or self.session is None:
            return
        self.session.request_emergency(delay)
        self._safe_save_session()
        self._refresh_status()

    def cancel_emergency(self) -> None:
        if self.session is None:
            return
        self.session.cancel_emergency()
        self._safe_save_session()
        self._refresh_status()

    # ------------------------------------------------------------- 종료
    def quit(self) -> None:
        if self._dialog_open:
            return
        if self.active and self.settings.require_unlock_for_quit:
            if not self._confirm("FocusApp 종료"):
                return
        # 세션 파일은 남겨 두어, 재실행 시 남은 시간 동안 차단을 이어가게 함 (해제 후 종료는 파일이 이미 지워짐)
        self.tray.hide()
        self.window.allow_close = True
        self.window.close()  # closeEvent에서 창 위치·크기를 저장
        self.app.quit()

    # ------------------------------------------------------------- 공통
    def _confirm(self, purpose: str) -> bool:
        if self._dialog_open:
            return False
        self._dialog_open = True
        try:
            parent = self.window if self.window.isVisible() else None
            return confirm_with_code(self.settings.unlock_code_length, purpose, parent=parent)
        finally:
            self._dialog_open = False

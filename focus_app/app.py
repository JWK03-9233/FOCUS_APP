"""메인 창, 트레이 아이콘, 집중 세션을 묶는 애플리케이션 컨트롤러."""

from __future__ import annotations

import copy
import logging
import time
from typing import List, Optional, Tuple

import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from focus_app import browser_policy, helper, taskmgr_lock, updater, winapi
from focus_app.config import Profile, Settings, data_dir, site_url
from focus_app.enforcer import ForegroundWindow
from focus_app.monitor import AllowlistMonitor
from focus_app.session import FocusSession, format_duration
from focus_app.ui import app_catalog, icons
from focus_app.ui.main_window import MainWindow
from focus_app.ui.allowed_apps_dialog import AllowedAppsDialog
from focus_app.ui.end_dialog import FocusEndDialog
from focus_app.ui.preferences_dialog import PreferencesDialog
from focus_app.ui.window_state import WindowStateManager
from focus_app.ui.unlock_dialog import confirm_with_code
from focus_app.ui.update_dialog import UpdateDialog, _Bridge, _safe_emit, run_in_thread
from focus_app.version import APP_NAME, __version__

log = logging.getLogger(__name__)

POLICY_APPLY_WAIT = 15.0  # 초. 사이트 제한이 이만큼 안 걸리면 도우미가 일을 못 하는 것으로 보고 알림


class FocusApp:
    def __init__(self, app: QApplication, show_window: bool = True, check_updates: bool = False) -> None:
        self.app = app
        self.settings = Settings.load()
        # 공통 스타일(저장된 화면 크기로) 적용 + 모든 창의 확대·축소와 위치·크기 기억
        self.window_state = WindowStateManager(app, self.settings, self._safe_save_settings)
        self.session: Optional[FocusSession] = None
        self.monitor: Optional[AllowlistMonitor] = None
        self._dialog_open = False

        app_catalog.installed_apps.preload()  # 앱 고르기 창을 빨리 열 수 있게 미리 읽어 둠

        # --- 메인 창
        self.window = MainWindow(self.settings)
        self.window.start_requested.connect(self.start_focus)
        self.window.stop_requested.connect(self.stop_focus)
        self.window.launch_app_requested.connect(self.launch_app)
        self.window.cancel_emergency_requested.connect(self.cancel_emergency)
        self.window.settings_changed.connect(self._safe_save_settings)
        self.window.preferences_requested.connect(self.open_preferences)
        self.window.quit_requested.connect(self.quit)
        self.window.update_requested.connect(self.open_update)
        self.window.edit_apps_requested.connect(self.edit_apps_during_focus)
        self.window.open_site_requested.connect(self.open_site)
        self.window.restart_browsers_requested.connect(lambda: self.restart_browsers())
        self.window.on_hidden_to_tray = self._on_window_hidden

        # --- 트레이
        self._icons = {"idle": icons.idle_icon(), "active": icons.active_icon(), "emergency": icons.emergency_icon()}
        self._icon_state = "idle"
        self.tray = QSystemTrayIcon(self._icons["idle"])
        self.menu = QMenu()
        self._app_actions: list = []
        self._build_menu()
        self.menu.aboutToShow.connect(self._refresh_app_actions)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self._poll)
        self.status_timer = QTimer()
        self.status_timer.setInterval(1000)
        self.status_timer.timeout.connect(self._refresh_status)
        self.status_timer.start()

        self._helper_ok = False  # 관리자 권한 도우미가 지금 감시 중인지 (2초마다 갱신)
        self._helper_checked = 0.0
        self._helper_installed = False  # 도우미 작업이 등록되어 있는지 (집중을 시작할 때 확인)
        self._helper_started = 0.0  # 마지막으로 도우미를 띄운 때 (꺼졌을 때 너무 자주 다시 띄우지 않게)
        self._warned_elevated = False
        self._end_popup: Optional[FocusEndDialog] = None

        # --- 사이트 제한 (도우미가 쓴 브라우저 정책의 상태를 표시 파일에서 읽음)
        # 작업 스레드는 결과를 여기에 두기만 하고, 화면 반영은 UI 스레드의 상태 타이머가 함 (_take_worker_results)
        self._helper_check_result: Optional[bool] = None
        self._restart_result: Optional[list] = None  # 다시 시작하지 못한 브라우저 이름 목록
        self._policy_state: Optional[Tuple[List[str], float]] = None  # (적용된 사이트, 적용 시각)
        self._policy_checked = 0.0
        self._sites_since = 0.0  # 사이트 제한을 요청한 때 (적용이 너무 늦으면 알림)
        self._restarting = False  # 브라우저를 다시 시작하는 중
        self._gate_noticed = False  # 이번 집중에서 브라우저를 막은 이유를 창으로 알렸는지
        self._check_helper_installed()

        self._update_bridge = _Bridge(app)
        self._update_bridge.checked.connect(self._on_update_checked)
        self._latest: Optional[updater.ReleaseInfo] = None

        self._resume_saved_session()
        if self.session is None and self._locks_engaged():
            self._start_helper()  # 지난번에 꺼 둔 작업 관리자·사이트 제한을 도우미가 되돌리게 함
        self._refresh_status()
        if show_window:
            self.show_window()
        if check_updates and self.settings.check_updates_on_start:
            QTimer.singleShot(3000, self._check_updates_in_background)

    # ------------------------------------------------------------- 창
    def show_window(self) -> None:
        if self.session is not None:
            self.window.set_open_apps(winapi.running_exe_names())
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_window_hidden(self) -> None:
        """창을 닫아 트레이로 숨겼을 때. 알림은 앱을 막았을 때만 띄우므로 따로 안내하지 않음."""

    # ------------------------------------------------------------- 트레이 메뉴
    def _build_menu(self) -> None:
        m = self.menu
        m.clear()
        self.status_action = QAction("대기 중", m)
        self.status_action.setEnabled(False)
        m.addAction(self.status_action)
        # 집중 중이면 여기에 '지금 쓸 수 있는 앱'이 들어감 (메뉴를 열 때마다 _refresh_app_actions가 채움)
        self.apps_separator = m.addSeparator()
        self.open_action = QAction("FocusApp 열기", m)
        self.open_action.triggered.connect(self.show_window)
        m.addAction(self.open_action)
        self.stop_action = QAction("집중 끝내기…", m)
        self.stop_action.triggered.connect(self.stop_focus)
        m.addAction(self.stop_action)
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

    def _allowed_now(self) -> list:
        """집중 중에 쓸 수 있는 허용 앱 (실행 파일 이름). 앱을 막지 않는 모드거나 대기 중이면 빈 목록."""
        if self.session is None:
            return []
        profile = self.settings.get_profile(self.session.profile)
        if profile is None or not profile.block_everything:
            return []
        return profile.normalized_apps()

    def _refresh_app_actions(self) -> None:
        """트레이 메뉴의 '지금 쓸 수 있는 앱' 부분을 다시 채웁니다."""
        for action in self._app_actions:
            self.menu.removeAction(action)
            action.deleteLater()
        self._app_actions = []
        apps = self._allowed_now()
        if not apps:
            return
        before = self.apps_separator
        header = QAction("지금 쓸 수 있는 앱", self.menu)
        header.setEnabled(False)
        self.menu.insertAction(before, header)
        self._app_actions.append(header)
        for exe in apps:
            name = self.settings.app_display_name(exe)
            path = self.settings.app_path(exe) or app_catalog.find_installed_path(exe)
            action = QAction(app_catalog.app_icon(path, name), f"   {name}", self.menu)
            action.triggered.connect(lambda _=False, e=exe: self.launch_app(e))
            self.menu.insertAction(before, action)
            self._app_actions.append(action)
        sites = self._desired_sites()
        if sites:
            header = QAction("지금 열 수 있는 사이트", self.menu)
            header.setEnabled(False)
            self.menu.insertAction(before, header)
            self._app_actions.append(header)
            globe = icons.globe_icon()
            for site in sites:
                action = QAction(globe, f"   {site.lstrip('.')}", self.menu)
                action.triggered.connect(lambda _=False, st=site: self.open_site(st))
                self.menu.insertAction(before, action)
                self._app_actions.append(action)

    def launch_app(self, exe: str) -> None:
        """허용 앱을 엽니다 (진행 화면의 앱 아이콘이나 트레이 메뉴에서)."""
        if exe not in self._allowed_now():
            return
        if app_catalog.launch_app(exe, self.settings.app_path(exe)):
            log.info("허용 앱 실행: %s", exe)
            return
        log.warning("허용 앱을 열 수 없음: %s", exe)

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
        self._take_worker_results()
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
            if self.window.isVisible():  # 창이 보일 때만 확인 (실행 중인 앱 옆에 점, 사이트 제한 상태)
                self.window.set_open_apps(winapi.running_exe_names())
                self._refresh_site_status()
        self.status_action.setText(text)
        self.tray.setToolTip(tip)
        pending = self.active and self.session.emergency_at is not None
        self.stop_action.setVisible(self.active)
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
        self._warned_elevated = False
        self.monitor = AllowlistMonitor(
            profile=copy.deepcopy(profile),
            on_block=self._on_block,
            handles=self._main_handles,
            on_block_failed=self._on_block_failed,
            gate=self._browser_gate,
        )
        self._policy_state = None
        self._policy_checked = 0.0
        self._sites_since = time.monotonic()
        self._gate_noticed = False
        self._start_helper()
        self.poll_timer.start(self.settings.poll_interval_ms)
        self.window.show_running(session, profile)
        self._refresh_status()

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
        had_sites = self._desired_sites() is not None
        self.poll_timer.stop()
        self.monitor = None
        self.session = None
        self._policy_state = None
        FocusSession.clear()
        if self._locks_engaged():
            self._start_helper()  # 도우미가 꺼져 있었다면 띄워서 작업 관리자·사이트 제한을 되돌리게 함
        self._refresh_status()

        focused = session.elapsed_seconds()
        if session.ends_at is not None:  # 앱이 꺼져 있다 다시 켜진 경우 정한 시간보다 길게 세지 않음
            focused = min(focused, int(session.ends_at - session.started_at))
        minutes = focused // 60
        blocked = monitor.block_count if monitor else 0
        summary = f"{minutes}분 동안 집중했어요." + (f" 다른 앱을 {blocked}번 막았어요." if blocked else "")
        msg = {
            "manual": "집중을 끝냈습니다.",
            "expired": "정한 시간이 끝났습니다. 수고했어요!",
            "emergency": "비상 해제가 적용되어 집중이 끝났습니다.",
        }.get(reason, "집중이 끝났습니다.")
        self.window.show_setup()
        browsers = self._running_browsers() if had_sites else []
        if browsers:
            # 브라우저는 정책을 시작할 때와 15분마다만 읽으므로, 그대로 두면 잠시 사이트가 계속 막혀 있음
            names = ", ".join(browser_policy.browser_name(e) for e in browsers)
            self.window.show_notice(
                f"<b>{msg}</b>  {summary}<br>{names}은(는) 다시 시작하면 모든 사이트가 바로 열립니다 "
                "(그대로 두면 15분 안에 풀림).",
                "브라우저 다시 시작", self._restart_after_release,
            )
        else:
            self.window.show_notice(f"<b>{msg}</b>  {summary}")
        if reason != "manual":
            # 직접 끝낸 게 아니면 놓치지 않게: 창을 앞으로 가져오고, 닫을 때까지 떠 있는 알림 창을 띄움.
            # 집중 중에 최소화된 앱들은 그대로 둠 (한꺼번에 다시 열지 않음)
            self.show_window()
            self._show_end_popup(reason, session.profile, focused, blocked)

    def _show_end_popup(self, reason: str, mode_name: str, focused: int, blocked: int) -> None:
        if self._end_popup is not None:
            self._end_popup.close()
        popup = FocusEndDialog(reason, mode_name, focused, blocked, parent=self.window)
        popup.destroyed.connect(lambda *_: setattr(self, "_end_popup", None))
        self._end_popup = popup
        popup.show()
        # 다른 앱을 쓰고 있어도 앞으로 오도록 (Windows는 배경 앱이 포커스를 가져가는 것을 막으므로 우회)
        QTimer.singleShot(100, self._bring_end_popup_to_front)

    def _bring_end_popup_to_front(self) -> None:
        for widget in (self.window, self._end_popup):
            if widget is not None and widget.isVisible():
                try:
                    winapi.bring_to_front(int(widget.winId()))
                except Exception:  # noqa: BLE001 - 앞으로 못 가져와도 창은 떠 있음
                    log.exception("집중 끝 알림 창을 앞으로 가져오지 못함")

    def _poll(self) -> None:
        if self.monitor is None or self.session is None:
            return
        now = time.monotonic()
        if now - self._helper_checked >= 2.0:
            self._helper_checked = now
            self._helper_ok = helper.helper_alive()
            if not self._helper_ok and self._helper_installed and now - self._helper_started >= 10.0:
                log.info("도우미가 꺼져 있어 다시 띄웁니다.")
                self._start_helper(check_registered=False)
        if now - self._policy_checked >= 1.0:
            self._policy_checked = now
            self._policy_state = browser_policy.applied(data_dir()) if self._desired_sites() is not None else None
        self.monitor.poll()

    # ------------------------------------------------------ 관리자 권한 도우미
    def _main_handles(self, window: ForegroundWindow) -> bool:
        """본 앱이 맡을 창: 도우미가 감시 중이면 관리자 권한 창은 도우미에게 맡김."""
        return not (self._helper_ok and winapi.process_elevated(window.pid))

    def _locks_engaged(self) -> bool:
        """도우미가 바꿔 둔 설정(작업 관리자 끄기, 사이트 제한)이 남아 있는지."""
        return taskmgr_lock.engaged(data_dir()) or browser_policy.engaged(data_dir())

    def _check_helper_installed(self) -> None:
        def work() -> None:
            try:
                self._helper_check_result = helper.is_registered()
            except Exception:  # noqa: BLE001
                log.exception("도우미 설치 여부 확인 실패")

        run_in_thread(work, "helper-check")

    def _take_worker_results(self) -> None:
        """작업 스레드가 남긴 결과를 화면에 반영합니다 (UI 스레드에서만 호출)."""
        if not shiboken6.isValid(self.window):
            return  # 창이 이미 지워짐 (테스트 등에서 컨트롤러만 남은 경우)
        installed, self._helper_check_result = self._helper_check_result, None
        if installed is not None:
            self._on_helper_installed(installed)
        failed, self._restart_result = self._restart_result, None
        if failed is not None:
            self._on_restart_done(failed)

    def _on_helper_installed(self, installed: bool) -> None:
        self._helper_installed = installed
        self.window.set_helper_installed(installed)

    def _start_helper(self, check_registered: bool = True) -> None:
        self._helper_started = time.monotonic()

        def work() -> None:
            try:
                if check_registered:
                    self._helper_installed = helper.is_registered()
                    self._helper_check_result = self._helper_installed
                if self._helper_installed and helper.start(check_registered=False):
                    log.info("관리자 권한 도우미 실행 요청")
            except Exception:  # noqa: BLE001
                log.exception("도우미 실행 실패")

        run_in_thread(work, "helper-start")

    def _on_block_failed(self, window: ForegroundWindow) -> None:
        """일반 권한으로는 최소화할 수 없는 창 (관리자 권한으로 실행된 앱)."""
        name = self.settings.app_display_name(window.exe_name)
        if helper.is_registered():
            self._start_helper()
            msg = f"관리자 권한으로 실행된 {name}을(를) 막는 중입니다. 도우미가 곧 처리합니다."
        else:
            if self._warned_elevated:
                return
            self._warned_elevated = True
            msg = (
                f"{name}은(는) 관리자 권한으로 실행되어 최소화할 수 없습니다. "
                "집중이 끝난 뒤 ⚙ 설정에서 '관리자 권한 도우미'를 설치하면 막을 수 있습니다."
            )
        self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.MessageIcon.Warning, 5000)

    def _on_block(self, window: ForegroundWindow) -> None:
        if self._is_gated_browser(window):
            self._on_browser_gated(window)
            return
        if self.settings.show_block_notifications:
            self.tray.showMessage(
                APP_NAME,
                f"집중 중이라 {self.settings.app_display_name(window.exe_name)}을(를) 최소화했어요.",
                QSystemTrayIcon.MessageIcon.Warning,
                2000,
            )

    # ------------------------------------------------------ 집중 중 앱 편집
    def edit_apps_during_focus(self) -> None:
        """해제 문자열을 입력하면 집중을 끝내지 않고 지금 모드의 허용 앱만 고칩니다."""
        if not self.active or self._dialog_open:
            return
        if not self._confirm("허용 앱 편집"):
            return
        session = self.session
        profile = self.settings.get_profile(session.profile) if session else None
        if session is None or profile is None:
            return  # 입력하는 사이 집중이 끝났음
        self._dialog_open = True
        try:
            dlg = AllowedAppsDialog(
                self.settings, profile, parent=self._dialog_parent(), on_settings_changed=self._safe_save_settings,
                helper_installed=self.window.helper_installed,
            )
            try:
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                if self.session is not session:
                    return  # 편집하는 사이 집중이 끝났음 (저장할 모드도 모니터도 없음)
                profile = dlg.apply_to(self.settings)
            finally:
                dlg.deleteLater()
        finally:
            self._dialog_open = False
        self._safe_save_settings()
        before = self._desired_sites()
        if self.monitor is not None:
            self.monitor.set_profile(copy.deepcopy(profile))
        if self._desired_sites() != before:
            self._sites_since = time.monotonic()  # 도우미가 새 사이트 목록을 쓸 때까지 기다림
            self._policy_checked = 0.0
        self.window.show_running(session, profile)
        self._refresh_status()
        log.info("집중 중 허용 앱 변경: %s -> %s, 사이트 %s", profile.name, profile.normalized_apps(),
                 profile.normalized_sites() if profile.limits_sites() else "제한 없음")

    # ------------------------------------------------------------- 업데이트
    def _check_updates_in_background(self) -> None:
        token, bridge = self.settings.github_token, self._update_bridge

        def work() -> None:
            try:
                _safe_emit(bridge.checked, updater.fetch_latest(token))
            except Exception as exc:  # noqa: BLE001 - 자동 확인 실패는 조용히 기록만
                log.info("자동 업데이트 확인 실패: %s", exc)

        run_in_thread(work, "update-check-startup")

    def _on_update_checked(self, info: updater.ReleaseInfo) -> None:
        self._latest = info
        if info.newer:
            self.window.set_update_available(info.version)
            # critical이면 (집중 중이 아닐 때) 업데이트 창을 바로 띄움. 그 외에는 창의 업데이트 버튼만 강조
            # (알림은 앱을 막았을 때만 띄움)
            if info.urgency == "critical" and not self.active and not self._dialog_open:
                QTimer.singleShot(0, self.open_update)

    def open_update(self) -> None:
        if self._dialog_open:
            return
        if self.active:
            QMessageBox.information(self._dialog_parent(), "업데이트", "집중이 끝난 뒤에 업데이트할 수 있습니다.")
            return
        self._dialog_open = True
        try:
            dlg = UpdateDialog(self.settings.github_token, parent=self._dialog_parent())
            dlg.install_requested.connect(self._install_update)
            try:
                dlg.exec()
                if dlg.info is not None:
                    self._on_update_checked(dlg.info)
                    if not dlg.info.newer:
                        self.window.set_update_available(None)
            finally:
                dlg.deleteLater()
        finally:
            self._dialog_open = False

    def _install_update(self, kind: str, prepared, work_dir) -> None:
        if self.active:
            return
        try:
            updater.launch_update(kind, prepared, work_dir, data_dir() / "update.log")
        except (updater.UpdateError, OSError) as exc:
            QMessageBox.warning(self._dialog_parent(), "업데이트", str(exc))
            return
        log.info("업데이트를 위해 종료합니다.")
        self._shutdown()

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
        self._check_helper_installed()  # 설정에서 도우미를 설치하거나 지웠을 수 있음

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

    # ---------------------------------------------------------- 비상 해제 (예전 버전에서 요청해 둔 것만 취소 가능)
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
        if self.session is not None:
            helper.mark_quit(self.session)  # 정식으로 끈 것이니 도우미가 다시 띄우지 않게
        self._shutdown()

    def _shutdown(self) -> None:
        self.tray.hide()
        self.window_state.flush()  # 막 옮기거나 크기를 바꾼 창이 있으면 바로 저장
        self.window.allow_close = True
        self.window.close()  # closeEvent에서 창 위치·크기를 저장
        self.app.quit()

    # ------------------------------------------------------------- 사이트 제한
    def _session_profile(self) -> Optional[Profile]:
        """지금 집중 중인 모드 (감시에 쓰는 복사본). 집중 중이 아니면 None."""
        if self.session is None:
            return None
        if self.monitor is not None:
            return self.monitor.profile
        return self.settings.get_profile(self.session.profile)

    def _desired_sites(self) -> Optional[List[str]]:
        """지금 집중에 걸어야 하는 허용 사이트 (사이트 제한이 없으면 None)."""
        return browser_policy.desired_sites(self._session_profile())

    def _policy_ready(self) -> Optional[float]:
        """원하는 사이트 목록이 브라우저 정책에 적용됐으면 그 적용 시각, 아니면 None."""
        sites, state = self._desired_sites(), self._policy_state
        if sites is None or state is None or state[0] != sites:
            return None
        return state[1]

    def _allowed_browsers(self) -> List[str]:
        profile = self._session_profile()
        apps = profile.normalized_apps() if profile is not None else []
        return [exe for exe in apps if exe in browser_policy.SUPPORTED_EXES]

    def _browser_gate(self, window: ForegroundWindow) -> bool:
        """허용 브라우저라도 사이트 제한이 아직 안 걸려 있으면 막음 (False)."""
        if window.exe_name not in browser_policy.SUPPORTED_EXES or self._desired_sites() is None:
            return True
        applied_at = self._policy_ready()
        if applied_at is None:
            return False  # 도우미가 아직 정책을 못 씀 (또는 도우미가 없음): 모든 사이트가 열리므로 막음
        return not browser_policy.needs_restart(winapi.process_start_time(window.pid), applied_at)

    def _is_gated_browser(self, window: ForegroundWindow) -> bool:
        profile = self._session_profile()
        return (profile is not None and profile.allows(window.exe_name)
                and window.exe_name in browser_policy.SUPPORTED_EXES)

    def _on_browser_gated(self, window: ForegroundWindow) -> None:
        name = browser_policy.browser_name(window.exe_name)
        if self._policy_ready() is None:
            msg = f"사이트 제한을 아직 적용하지 못해 {name}을(를) 최소화했어요."
        else:
            msg = f"{name}은(는) 다시 시작해야 사이트 제한이 적용돼요. FocusApp 창에서 '브라우저 다시 시작'을 누르세요."
        self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.MessageIcon.Information, 4000)
        if not self._gate_noticed:
            self._gate_noticed = True
            self.show_window()  # 다시 시작 버튼이 있는 진행 화면을 보여 줌

    def _refresh_site_status(self) -> None:
        """진행 화면의 사이트 제한 상태 띠를 갱신합니다."""
        if self._desired_sites() is None:
            self.window.set_site_status("", False)
            return
        applied_at = self._policy_ready()
        if applied_at is None:
            waited = time.monotonic() - self._sites_since
            if self.window.helper_installed is False:  # 아직 확인 전이면 None
                text = ("⚠ 관리자 권한 도우미가 없어 사이트 제한을 쓸 수 없습니다. 그동안 브라우저는 최소화됩니다. "
                        "집중이 끝난 뒤 ⚙ 설정에서 도우미를 설치하세요.")
            elif waited >= POLICY_APPLY_WAIT:
                text = ("⚠ 사이트 제한을 적용하지 못하고 있습니다 (도우미 기록 helper.log 확인). "
                        "그동안 브라우저는 최소화됩니다.")
            else:
                text = "사이트 제한을 적용하는 중…"
            self.window.set_site_status(text, False)
            return
        if self._restarting:
            self.window.set_site_status("브라우저를 다시 시작하는 중…", False)
            return
        stale = browser_policy.stale_browsers(self._allowed_browsers(), applied_at)
        if not stale:
            self.window.set_site_status("", False)
            return
        names = ", ".join(browser_policy.browser_name(e) for e in stale)
        left = max(1, int((applied_at + browser_policy.RELOAD_INTERVAL - time.time()) // 60) + 1)
        self.window.set_site_status(
            f"{names}은(는) 사이트 제한을 걸기 전부터 열려 있어, 다시 시작하기 전까지 최소화됩니다 "
            f"(그대로 두면 {left}분 안에 저절로 적용).", True,
        )

    def _browser_path(self, exe: str) -> str:
        for pid in browser_policy.running_pids(exe):
            path = winapi.process_image_path(pid)
            if path:
                return path
        return self.settings.app_path(exe) or app_catalog.find_installed_path(exe)

    def _pick_browser(self) -> Tuple[str, str]:
        """사이트를 열 브라우저 (실행 파일, 경로): 허용한 지원 브라우저 중 실행 중인 것을 먼저. 없으면 ("", "")."""
        browsers = self._allowed_browsers()
        browsers.sort(key=lambda e: not browser_policy.running_pids(e))
        for exe in browsers:
            path = self._browser_path(exe)
            if path:
                return exe, path
        return "", ""

    def open_site(self, site: str) -> None:
        """허용 사이트를 허용한 브라우저로 엽니다 (진행 화면이나 트레이 메뉴에서)."""
        sites = self._desired_sites()
        if sites is None or site not in sites:
            return
        exe, path = self._pick_browser()
        if not exe:
            self.tray.showMessage(APP_NAME, "사이트를 열 브라우저를 찾지 못했어요.",
                                  QSystemTrayIcon.MessageIcon.Warning, 4000)
            return
        applied_at = self._policy_ready()
        if applied_at is None:
            self.tray.showMessage(APP_NAME, "사이트 제한을 아직 적용하지 못해 브라우저를 열 수 없어요.",
                                  QSystemTrayIcon.MessageIcon.Warning, 4000)
            return
        url = site_url(site)
        if browser_policy.stale_browsers([exe], applied_at):
            self.restart_browsers(url=url, only=[exe])
            return
        if browser_policy.open_url(path, url):
            log.info("허용 사이트 열기: %s (%s)", url, exe)

    def _running_browsers(self) -> List[str]:
        return [b.exe for b in browser_policy.BROWSERS if browser_policy.running_pids(b.exe)]

    def restart_browsers(self, url: str = "", only: Optional[List[str]] = None, after_release: bool = False) -> None:
        """브라우저를 다시 시작해 새 정책을 읽게 합니다 (확인을 받은 뒤, 열려 있던 탭은 다시 열림)."""
        if self._restarting or self._dialog_open:
            return
        if after_release:
            targets = self._running_browsers()
        else:
            applied_at = self._policy_ready()
            if applied_at is None:
                return
            targets = only if only is not None else browser_policy.stale_browsers(self._allowed_browsers(), applied_at)
        if not targets:
            return
        names = ", ".join(browser_policy.browser_name(e) for e in targets)
        why = ("집중이 끝나 사이트 제한을 풀었습니다." if after_release
               else "사이트 제한은 브라우저를 다시 시작해야 적용됩니다.")
        self._dialog_open = True
        try:
            box = QMessageBox(QMessageBox.Icon.Question, "브라우저 다시 시작",
                              f"{names}을(를) 다시 시작할까요?\n\n{why}\n열려 있던 탭은 다시 열리지만, "
                              "입력하던 내용이나 받고 있던 파일은 사라질 수 있어요.", parent=self._dialog_parent())
            restart = box.addButton("다시 시작", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(restart)
            try:
                box.exec()
                if box.clickedButton() is not restart:
                    return
            finally:
                box.deleteLater()
        finally:
            self._dialog_open = False
        paths = {exe: self._browser_path(exe) for exe in targets}
        self._restarting = True
        def work() -> None:
            failed = []
            for i, exe in enumerate(targets):
                try:
                    if not browser_policy.restart_browser(exe, paths[exe], url if i == 0 else ""):
                        failed.append(browser_policy.browser_name(exe))
                except Exception:  # noqa: BLE001
                    log.exception("브라우저 다시 시작 실패: %s", exe)
                    failed.append(browser_policy.browser_name(exe))
            self._restart_result = failed

        run_in_thread(work, "browser-restart")
        if self.session is not None:
            self._refresh_site_status()

    def _on_restart_done(self, failed: list) -> None:
        self._restarting = False
        if failed:
            QMessageBox.warning(self._dialog_parent(), "브라우저 다시 시작",
                                f"{', '.join(failed)}을(를) 다시 시작하지 못했습니다. 직접 완전히 닫았다가 다시 열어 주세요.")
        if self.session is not None:
            self._refresh_site_status()

    def _restart_after_release(self, waited: float = 0.0) -> None:
        """집중이 끝난 뒤: 도우미가 정책을 되돌린 다음에 브라우저를 다시 시작 (먼저 하면 제한이 남음)."""
        if self.session is not None:
            return
        if browser_policy.engaged(data_dir()):
            if waited >= 10.0:
                QMessageBox.information(self._dialog_parent(), "브라우저 다시 시작",
                                        "아직 사이트 제한을 푸는 중입니다. 잠시 뒤에 브라우저를 직접 다시 시작해 주세요.")
                return
            QTimer.singleShot(500, lambda: self._restart_after_release(waited + 0.5))
            return
        self.restart_browsers(after_release=True)

    # ------------------------------------------------------------- 공통
    def _dialog_parent(self):
        return self.window if self.window.isVisible() else None

    def _confirm(self, purpose: str) -> bool:
        if self._dialog_open:
            return False
        self._dialog_open = True
        try:
            parent = self.window if self.window.isVisible() else None
            return confirm_with_code(
                self.settings.unlock_code_length, purpose, parent=parent,
                complexity=self.settings.unlock_code_complexity,
            )
        finally:
            self._dialog_open = False

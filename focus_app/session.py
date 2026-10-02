"""집중 세션 상태 (프로필, 시작/종료 시각, 비상 해제 예약).

파일로 저장해 두어 앱이 비정상 종료된 뒤 다시 실행되면 남은 시간 동안
차단을 이어갑니다.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from focus_app.config import data_dir

log = logging.getLogger(__name__)


@dataclass
class FocusSession:
    profile: str
    started_at: float  # time.time()
    ends_at: Optional[float]  # None이면 수동 해제 전까지 무제한
    emergency_at: Optional[float] = None  # 비상 해제가 적용되는 시각

    # ------------------------------------------------------------- 생성
    @classmethod
    def start(cls, profile: str, duration_minutes: Optional[int], now: Optional[float] = None) -> "FocusSession":
        now = time.time() if now is None else now
        ends = None if not duration_minutes or duration_minutes <= 0 else now + duration_minutes * 60
        return cls(profile=profile, started_at=now, ends_at=ends)

    # ------------------------------------------------------------- 상태
    def remaining_seconds(self, now: Optional[float] = None) -> Optional[int]:
        if self.ends_at is None:
            return None
        now = time.time() if now is None else now
        return max(0, int(round(self.ends_at - now)))

    def elapsed_seconds(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        return max(0, int(now - self.started_at))

    def is_expired(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        if self.ends_at is not None and now >= self.ends_at:
            return True
        if self.emergency_at is not None and now >= self.emergency_at:
            return True
        return False

    def expiry_reason(self, now: Optional[float] = None) -> Optional[str]:
        """만료되었다면 그 이유("expired" 또는 "emergency"), 아니면 None."""
        now = time.time() if now is None else now
        if self.ends_at is not None and now >= self.ends_at:
            return "expired"
        if self.emergency_at is not None and now >= self.emergency_at:
            return "emergency"
        return None

    def emergency_remaining_seconds(self, now: Optional[float] = None) -> Optional[int]:
        if self.emergency_at is None:
            return None
        now = time.time() if now is None else now
        return max(0, int(round(self.emergency_at - now)))

    def request_emergency(self, delay_minutes: int, now: Optional[float] = None) -> float:
        now = time.time() if now is None else now
        self.emergency_at = now + max(1, delay_minutes) * 60
        return self.emergency_at

    def extend(self, minutes: int, now: Optional[float] = None) -> bool:
        """끝나는 시각을 minutes분 늦춥니다. '끝낼 때까지'면 늘릴 시간이 없어 False."""
        if self.ends_at is None or minutes <= 0:
            return False
        now = time.time() if now is None else now
        self.ends_at = max(self.ends_at, now) + minutes * 60
        return True

    def cancel_emergency(self) -> None:
        self.emergency_at = None

    # ------------------------------------------------------------- 영속화
    @staticmethod
    def path() -> Path:
        return data_dir() / "session.json"

    def save(self, path: Optional[Path] = None) -> None:
        path = path or self.path()
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self)), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["FocusSession"]:
        path = path or cls.path()
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                profile=str(raw["profile"]),
                started_at=float(raw["started_at"]),
                ends_at=None if raw.get("ends_at") is None else float(raw["ends_at"]),
                emergency_at=None if raw.get("emergency_at") is None else float(raw["emergency_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @classmethod
    def clear(cls, path: Optional[Path] = None) -> None:
        path = path or cls.path()
        # 도우미가 마침 이 파일을 읽는 중이면 Windows에서는 지울 수 없음 (PermissionError).
        # 남겨 두면 도우미가 계속 차단하므로 잠깐 기다렸다 다시 시도합니다.
        for attempt in range(40):
            try:
                path.unlink()
                return
            except FileNotFoundError:
                return
            except PermissionError:
                if attempt == 39:
                    log.exception("세션 파일을 지우지 못했습니다: %s", path)
                    return
                time.sleep(0.05)


def format_minutes(minutes: int) -> str:
    """시간 버튼 표시용: 25분, 2시간, 1시간 30분."""
    h, m = divmod(max(0, int(minutes)), 60)
    if h and m:
        return f"{h}시간 {m}분"
    if h:
        return f"{h}시간"
    return f"{m}분"


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return "제한 없음"
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}시간 {m:02d}분 {s:02d}초"
    return f"{m}분 {s:02d}초"

"""해제용 랜덤 문자열 생성과 검증."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

# 0/O, 1/l/I 처럼 헷갈리는 글자는 제외
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def generate_code(length: int = 32) -> str:
    length = max(8, int(length))
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def group_code(code: str, group: int = 4) -> str:
    """읽기 쉽도록 4글자 단위로 공백을 넣어 표시합니다. 입력 시에는 공백 무시."""
    return " ".join(code[i : i + group] for i in range(0, len(code), group))


def normalize_input(text: str) -> str:
    return "".join(text.split())


@dataclass
class UnlockChallenge:
    """한 번의 해제 시도를 나타냅니다. 틀리면 새 문자열이 발급됩니다."""

    length: int = 32
    code: str = field(default="")
    attempts: int = 0

    def __post_init__(self) -> None:
        if not self.code:
            self.refresh()

    def refresh(self) -> str:
        self.code = generate_code(self.length)
        return self.code

    @property
    def display(self) -> str:
        return group_code(self.code)

    def verify(self, text: str) -> bool:
        self.attempts += 1
        ok = secrets.compare_digest(normalize_input(text), self.code)
        if not ok:
            self.refresh()
        return ok

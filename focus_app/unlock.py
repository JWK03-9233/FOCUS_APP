"""해제용 랜덤 문자열 생성과 검증."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

# 0/O, 1/l/I 처럼 헷갈리는 글자는 제외
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
# 키보드로 바로 칠 수 있고 따옴표·역슬래시처럼 헷갈리기 쉬운 것은 뺀 기호
SYMBOLS = "!@#$%^&*-+=?~"
AMBIGUOUS = "0O1lI"

# 복잡도: 설정 값 -> (화면 이름, 꼭 한 번씩은 들어갈 글자 묶음들)
COMPLEXITY = {
    "basic": ("기본 — 영문 대소문자·숫자", ("ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789")),
    "symbols": (
        "기호 포함 — 영문 대소문자·숫자·기호",
        ("ABCDEFGHJKLMNPQRSTUVWXYZ", "abcdefghijkmnpqrstuvwxyz", "23456789", SYMBOLS),
    ),
    "max": (
        "최대 — 기호 + 헷갈리는 글자(0/O, 1/l/I)까지",
        ("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz", "0123456789", SYMBOLS),
    ),
}
DEFAULT_COMPLEXITY = "basic"
MIN_LENGTH = 32  # 설정에서 고를 수 있는 가장 짧은 길이
MAX_LENGTH = 256


def clean_complexity(value: str) -> str:
    return value if value in COMPLEXITY else DEFAULT_COMPLEXITY


def alphabet(complexity: str = DEFAULT_COMPLEXITY) -> str:
    return "".join(COMPLEXITY[clean_complexity(complexity)][1])


def generate_code(length: int = 32, complexity: str = DEFAULT_COMPLEXITY) -> str:
    """랜덤 문자열. 복잡도에 든 글자 묶음(대문자·소문자·숫자·기호)이 각각 한 번 이상 들어갑니다."""
    length = max(8, int(length))
    groups = COMPLEXITY[clean_complexity(complexity)][1]
    chars = "".join(groups)
    code = [secrets.choice(group) for group in groups]  # 묶음마다 최소 한 글자
    code += [secrets.choice(chars) for _ in range(length - len(code))]
    # 묶음 순서대로 앞에 몰리지 않게 섞음 (secrets 기반)
    for i in range(len(code) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        code[i], code[j] = code[j], code[i]
    return "".join(code)


def group_code(code: str, group: int = 4) -> str:
    """읽기 쉽도록 4글자 단위로 공백을 넣어 표시합니다. 입력 시에는 공백 무시."""
    return " ".join(code[i : i + group] for i in range(0, len(code), group))


def normalize_input(text: str) -> str:
    return "".join(text.split())


@dataclass
class UnlockChallenge:
    """한 번의 해제 시도를 나타냅니다. 틀리면 새 문자열이 발급됩니다."""

    length: int = 32
    complexity: str = DEFAULT_COMPLEXITY
    code: str = field(default="")
    attempts: int = 0

    def __post_init__(self) -> None:
        if not self.code:
            self.refresh()

    def refresh(self) -> str:
        self.code = generate_code(self.length, self.complexity)
        return self.code

    @property
    def display(self) -> str:
        return group_code(self.code)

    def verify(self, text: str) -> bool:
        self.attempts += 1
        # 문자열끼리 비교하면 한글 등 ASCII가 아닌 글자가 섞였을 때 TypeError가 나므로 바이트로 비교
        ok = secrets.compare_digest(normalize_input(text).encode("utf-8"), self.code.encode("utf-8"))
        if not ok:
            self.refresh()
        return ok

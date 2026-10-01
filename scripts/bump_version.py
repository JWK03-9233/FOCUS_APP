"""버전을 올립니다: python scripts/bump_version.py 0.3.0

focus_app/version.py와 pyproject.toml의 버전을 바꾸고, CHANGELOG.md 맨 위에 새 절을 만듭니다.
이 변경을 커밋해 main에 push하면 GitHub Actions가 테스트·빌드 후 릴리스를 올립니다.
"""

from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        print("사용법: python scripts/bump_version.py <주.부.수> (예: 0.3.0)")
        return 2
    new = argv[1]
    version_py = ROOT / "focus_app" / "version.py"
    text = version_py.read_text(encoding="utf-8")
    old = re.search(r'__version__ = "([^"]+)"', text).group(1)
    if tuple(map(int, new.split("."))) <= tuple(map(int, re.findall(r"\d+", old)[:3])):
        print(f"새 버전({new})은 지금 버전({old})보다 커야 합니다.")
        return 1
    version_py.write_text(text.replace(f'__version__ = "{old}"', f'__version__ = "{new}"'), encoding="utf-8")

    pyproject = ROOT / "pyproject.toml"
    pyproject.write_text(
        re.sub(r'(?m)^version = "[^"]+"', f'version = "{new}"', pyproject.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    changelog = ROOT / "CHANGELOG.md"
    body = changelog.read_text(encoding="utf-8") if changelog.exists() else "# 변경 기록\n"
    if f"## [{new}]" not in body:
        head, _, rest = body.partition("\n## ")
        entry = f"## [{new}] - {datetime.date.today():%Y-%m-%d}\n\n- (바뀐 점을 적어 주세요)\n"
        body = f"{head.rstrip()}\n\n{entry}" + (f"\n## {rest}" if rest else "")
        changelog.write_text(body, encoding="utf-8")

    print(f"{old} -> {new}")
    print("다음: CHANGELOG.md에 바뀐 점을 적고 커밋한 뒤 main에 push하면 릴리스가 자동으로 올라갑니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

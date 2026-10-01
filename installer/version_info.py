"""exe에 넣을 Windows 버전 정보(파일 속성 > 자세히) 텍스트를 만듭니다.

제품명·버전·회사 정보가 있으면 백신의 오탐(false positive)이 줄어듭니다.
PyInstaller spec에서 빌드할 때마다 focus_app/version.py 기준으로 생성합니다.
"""

from __future__ import annotations

import re


def _four(version: str) -> tuple:
    nums = [int(n) for n in re.findall(r"\d+", version)[:4]]
    return tuple(nums + [0] * (4 - len(nums)))


def generate_version_info(version: str, app_name: str = "FocusApp", company: str = "JWK03-9233") -> str:
    v = _four(version)
    dotted = ".".join(map(str, v))
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('041204B0', [
        StringStruct('CompanyName', '{company}'),
        StringStruct('FileDescription', '{app_name} - 허용 목록 기반 집중 모드'),
        StringStruct('FileVersion', '{dotted}'),
        StringStruct('InternalName', '{app_name}'),
        StringStruct('LegalCopyright', 'Copyright (c) {company}'),
        StringStruct('OriginalFilename', '{app_name}.exe'),
        StringStruct('ProductName', '{app_name}'),
        StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [0x0412, 1200])])
  ]
)
"""

# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: pyinstaller installer/FocusApp.spec
import os
import sys

root = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))
sys.path.insert(0, root)
sys.path.insert(0, os.path.join(root, "installer"))

from focus_app.version import __version__  # noqa: E402
from version_info import generate_version_info  # noqa: E402

# exe 파일 속성에 들어갈 버전 정보 (빌드할 때마다 version.py 기준으로 새로 만듦)
version_file = os.path.join(root, "build", "version_info.txt")
os.makedirs(os.path.dirname(version_file), exist_ok=True)
with open(version_file, "w", encoding="utf-8") as f:
    f.write(generate_version_info(__version__))

a = Analysis(
    [os.path.join(root, "focus_app", "__main__.py")],
    pathex=[root],
    binaries=[],
    datas=[(os.path.join(root, "focus_app", "assets"), os.path.join("focus_app", "assets"))],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FocusApp",
    console=False,  # 트레이 앱이므로 콘솔 창 없음
    icon=os.path.join(root, "focus_app", "assets", "focus_icon.ico"),
    version=version_file,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FocusApp")

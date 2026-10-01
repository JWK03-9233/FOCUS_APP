# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: pyinstaller installer/FocusApp.spec
import os

root = os.path.abspath(os.path.join(os.path.dirname(SPEC), ".."))

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
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FocusApp")

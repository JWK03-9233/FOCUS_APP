@echo off
rem PyInstaller로 단일 폴더 배포본(dist\FocusApp)을 만듭니다.
cd /d "%~dp0\.."
pip install -r requirements-dev.txt
pyinstaller --noconfirm installer\FocusApp.spec

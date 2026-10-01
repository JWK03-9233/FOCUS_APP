@echo off
rem 콘솔 창 없이 FocusApp을 띄웁니다. (pythonw로 따로 실행하고 이 창은 바로 닫힘)
cd /d "%~dp0\.."
start "" pythonw -m focus_app

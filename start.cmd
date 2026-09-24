@echo off
rem Start de webinterface van ai-debat en open de browser.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe web.py
) else (
  python web.py
)
pause

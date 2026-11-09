@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\sync_local_content.py
pause

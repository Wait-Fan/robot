@echo off
setlocal
cd /d "%~dp0"
if not defined PACKING_PYTHON (
    if exist "E:\program\python3.13\python.exe" (
        set "PACKING_PYTHON=E:\program\python3.13\python.exe"
    ) else (
        set "PACKING_PYTHON=python"
    )
)
"%PACKING_PYTHON%" main.py
if errorlevel 1 (
    echo.
    echo Install the PyQt5 UI dependencies with the same Python interpreter:
    echo "%PACKING_PYTHON%" -m pip install -r requirements-ga.txt
    pause
)

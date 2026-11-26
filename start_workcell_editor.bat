@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not defined PACKING_PYTHON (
    if exist "E:\program\python3.13\python.exe" (
        set "PACKING_PYTHON=E:\program\python3.13\python.exe"
    ) else (
        set "PACKING_PYTHON=python"
    )
)
"%PACKING_PYTHON%" main.py --workcell-editor --robot-model fanuc_r2000ic210l
set "WORKCELL_EXIT=%ERRORLEVEL%"
if not "%WORKCELL_EXIT%"=="0" pause
exit /b %WORKCELL_EXIT%

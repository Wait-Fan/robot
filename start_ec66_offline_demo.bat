@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if not defined PACKING_PYTHON set "PACKING_PYTHON=E:\program\python3.13\python.exe"
"%PACKING_PYTHON%" main.py --algorithm robot2025 --input-json examples\ec66_offline_demo.json --robot-scene examples\ec66_scene_demo.json --paper-config examples\ec66_ga_demo.json --output-json output\ec66_offline_demo_plan.json --output-csv output\ec66_offline_demo_positions.csv --no-show
set "APP_EXIT=%ERRORLEVEL%"
echo.
echo [INFO] Software test scene only. No hardware commands are sent.
echo [INFO] Results: output\ec66_offline_demo_plan.json
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%

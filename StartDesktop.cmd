@echo off
setlocal
set "ZHIJING_DESKTOP_ROOT=%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
if not defined ZHIJING_DATA_DIR set "ZHIJING_DATA_DIR=%ZHIJING_DESKTOP_ROOT%data"
if exist "%ZHIJING_DESKTOP_ROOT%.conda\python.exe" (
    set "ZHIJING_DESKTOP_PYTHON=%ZHIJING_DESKTOP_ROOT%.conda\python.exe"
    set "ZHIJING_DESKTOP_PYTHONW=%ZHIJING_DESKTOP_ROOT%.conda\pythonw.exe"
    set "PATH=%ZHIJING_DESKTOP_ROOT%.conda;%ZHIJING_DESKTOP_ROOT%.conda\Library\bin;%ZHIJING_DESKTOP_ROOT%.conda\Scripts;%PATH%"
) else if exist "%ZHIJING_DESKTOP_ROOT%.venv\Scripts\python.exe" (
    set "ZHIJING_DESKTOP_PYTHON=%ZHIJING_DESKTOP_ROOT%.venv\Scripts\python.exe"
    set "ZHIJING_DESKTOP_PYTHONW=%ZHIJING_DESKTOP_ROOT%.venv\Scripts\pythonw.exe"
) else (
    echo Project Python was not found. Set up the project-local Conda environment first.
    pause
    exit /b 1
)
if /I "%~1"=="--check" (
    "%ZHIJING_DESKTOP_PYTHON%" "%ZHIJING_DESKTOP_ROOT%desktop.py" %*
    exit /b
)
if exist "%ZHIJING_DESKTOP_PYTHONW%" (
    start "" "%ZHIJING_DESKTOP_PYTHONW%" "%ZHIJING_DESKTOP_ROOT%desktop.py" %*
) else (
    start "" "%ZHIJING_DESKTOP_PYTHON%" "%ZHIJING_DESKTOP_ROOT%desktop.py" %*
)
exit /b

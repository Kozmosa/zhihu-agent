@echo off
setlocal
set "ZHIJING_ROOT=%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
if not defined ZHIJING_DATA_DIR set "ZHIJING_DATA_DIR=%ZHIJING_ROOT%data"
if exist "%ZHIJING_ROOT%.conda\python.exe" (
    set "ZHIJING_PYTHON=%ZHIJING_ROOT%.conda\python.exe"
    set "PATH=%ZHIJING_ROOT%.conda;%ZHIJING_ROOT%.conda\Library\bin;%ZHIJING_ROOT%.conda\Scripts;%PATH%"
) else if exist "%ZHIJING_ROOT%.venv\Scripts\python.exe" (
    set "ZHIJING_PYTHON=%ZHIJING_ROOT%.venv\Scripts\python.exe"
) else if exist "%ZHIJING_ROOT%..\codex\envs\zhijing\Scripts\python.exe" (
    set "ZHIJING_PYTHON=%ZHIJING_ROOT%..\codex\envs\zhijing\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found. Use a Python 3.12+ environment with project dependencies.
        pause
        exit /b 1
    )
    set "ZHIJING_PYTHON=python"
)
"%ZHIJING_PYTHON%" "%ZHIJING_ROOT%main.py" --open-browser %*
set "ZHIJING_EXIT=%ERRORLEVEL%"
if not "%ZHIJING_EXIT%"=="0" (
    echo.
    echo ZhiJing Agent exited with code %ZHIJING_EXIT%. Review the error above.
    pause
)
exit /b %ZHIJING_EXIT%

@echo off
rem Set up the virtual environment if needed, then run md-view.py.
rem
rem Creates .venv on first run and installs requirements.txt into it. The
rem dependencies are installed again whenever requirements.txt changes.
rem Every argument is passed through to md-view.py, for example:
rem     run.bat samples\demo.md
rem     run.bat --dark samples\flow.mmd
rem
rem Author: bd78 (https://github.com/bd78)
setlocal

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "REQS=%ROOT%requirements.txt"
rem Copy of the requirements.txt last installed; shared with run.ps1.
set "STAMP=%VENV%\requirements.installed"

rem 1. Create the virtual environment on first run.
if exist "%PYTHON%" goto :deps
echo Creating virtual environment in %VENV%
where py >nul 2>&1
if errorlevel 1 goto :try_python
py -3 -m venv "%VENV%"
goto :check_venv

:try_python
where python >nul 2>&1
if errorlevel 1 (
    echo Python 3.9+ was not found. Install it from https://www.python.org/ and try again. 1>&2
    exit /b 1
)
python -m venv "%VENV%"

:check_venv
if errorlevel 1 (
    echo Creating the virtual environment failed. 1>&2
    exit /b 1
)

rem 2. Install dependencies when requirements.txt is new or has changed.
:deps
if not exist "%STAMP%" goto :install
fc /b "%REQS%" "%STAMP%" >nul 2>&1
if not errorlevel 1 goto :run

:install
echo Installing dependencies from requirements.txt
"%PYTHON%" -m pip install --disable-pip-version-check -r "%REQS%"
if errorlevel 1 (
    echo pip install failed. 1>&2
    exit /b 1
)
copy /y "%REQS%" "%STAMP%" >nul

rem 3. Run the viewer with every argument passed through.
:run
"%PYTHON%" "%ROOT%md-view.py" %*
exit /b %ERRORLEVEL%

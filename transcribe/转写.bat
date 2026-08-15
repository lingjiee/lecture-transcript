@echo off
REM ===================================================================
REM  Double-click me (or make a desktop shortcut to me).
REM
REM  Settings come from local.cfg sitting next to this file. That file
REM  is git-ignored, so machine-specific paths never fight with the
REM  repo. Copy local.cfg.example to local.cfg to start.
REM
REM  Data folder is resolved in this order:
REM    1. a folder dropped onto this file
REM    2. LECTURE_HOME in local.cfg          <- the normal way
REM    3. LECTURE_HOME environment variable
REM    4. this folder
REM ===================================================================

setlocal
REM local.cfg is UTF-8. Without this, a data path containing non-ASCII
REM characters is read in the OEM codepage and every exist-check fails.
chcp 65001 >nul
cd /d "%~dp0"

set "HOME_DIR="
set "MODEL="
set "PYTHON_EXE="

REM --- local.cfg (KEY=VALUE per line, # starts a comment) -------------
if exist "%~dp0local.cfg" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0local.cfg") do (
        if /i "%%A"=="LECTURE_HOME" set "HOME_DIR=%%B"
        if /i "%%A"=="MODEL"        set "MODEL=%%B"
        if /i "%%A"=="PYTHON"       set "PYTHON_EXE=%%B"
    )
)

if not defined HOME_DIR if defined LECTURE_HOME set "HOME_DIR=%LECTURE_HOME%"

REM A dropped FOLDER overrides everything; a dropped FILE is handled below.
if not "%~1"=="" if exist "%~1\" set "HOME_DIR=%~1"

if not defined HOME_DIR   set "HOME_DIR=%~dp0"
if not defined MODEL      set "MODEL=small"
if not defined PYTHON_EXE set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"

set "PYTHONUTF8=1"
set "SCRIPT_FILE=%~dp0transcribe.py"

REM Print the resolved settings BEFORE any check, so failures are readable.
echo Transcribing  [model: %MODEL%]
echo   data folder: %HOME_DIR%
echo   python:      %PYTHON_EXE%
echo.

if not exist "%PYTHON_EXE%" goto missing_python
if not exist "%SCRIPT_FILE%" goto missing_script

echo Do not close this window.
echo.

if "%~1"=="" goto batch
if exist "%~1\" goto batch
"%PYTHON_EXE%" -u "%SCRIPT_FILE%" "%~1" --home "%HOME_DIR%" --model %MODEL% 2>&1
goto finished

:batch
"%PYTHON_EXE%" -u "%SCRIPT_FILE%" --home "%HOME_DIR%" --model %MODEL% 2>&1
goto finished

:missing_python
echo ERROR: Python not found at the path above.
echo Either create the venv (see README), or set PYTHON= in local.cfg
echo to an existing interpreter.
goto failed

:missing_script
echo ERROR: transcribe.py not found: "%SCRIPT_FILE%"
goto failed

:finished
REM `if errorlevel N` means ">= N", so the larger code must be tested first.
REM 2 = nothing to transcribe, which is not a failure worth alarming about.
if errorlevel 2 goto nothing_to_do
if errorlevel 1 goto failed
echo.
echo Done. The .srt files are in the output folder.
echo Next: hand the .srt to the cleaner agent in Claude Code.
goto end

:nothing_to_do
echo.
echo Nothing to do. Put files in the inbox folder shown above and run again.
goto end

:failed
echo.
echo Something failed. Copy the error shown above.

:end
echo.
pause

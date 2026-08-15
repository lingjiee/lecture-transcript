@echo off
REM ===================================================================
REM  Copy this file into YOUR DATA FOLDER (the one holding 待转写\),
REM  then edit the two lines below once. Double-click to run.
REM
REM  It transcribes everything in <this folder>\待转写 into <this folder>\输出.
REM ===================================================================

setlocal
cd /d "%~dp0"

REM --- edit these two ------------------------------------------------
set "REPO=D:\projects\lecture-transcript"
set "MODEL=small"
REM   small = default, GPU, fast.  medium / large-v3 = slower, CPU only.
REM -------------------------------------------------------------------

set "PYTHONUTF8=1"
set "PYTHON_EXE=%REPO%\.venv\Scripts\python.exe"
set "SCRIPT_FILE=%REPO%\transcribe\transcribe.py"

if not exist "%PYTHON_EXE%" goto missing_python
if not exist "%SCRIPT_FILE%" goto missing_script

echo Transcribing  [model: %MODEL%]
echo   data folder: %~dp0
echo.
echo   No file dropped  -^> batch: everything in the inbox folder
echo   File dropped     -^> that one file only
echo.
echo Do not close this window.
echo.

if "%~1"=="" goto batch
"%PYTHON_EXE%" -u "%SCRIPT_FILE%" "%~1" --home "%~dp0" --model %MODEL% 2>&1
goto finished

:batch
"%PYTHON_EXE%" -u "%SCRIPT_FILE%" --home "%~dp0" --model %MODEL% 2>&1
goto finished

:missing_python
echo ERROR: Python environment not found: "%PYTHON_EXE%"
echo Check the REPO path above, and that you ran the setup step in the README.
goto failed

:missing_script
echo ERROR: transcribe.py not found: "%SCRIPT_FILE%"
echo Check the REPO path above.
goto failed

:finished
if errorlevel 1 goto failed
echo.
echo Done. The .srt files are in the output folder.
echo Next: hand the .srt to the cleaner agent in Claude Code.
goto end

:failed
echo.
echo Something failed. Copy the error shown above.

:end
echo.
pause

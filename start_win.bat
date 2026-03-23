@echo off
setlocal enableextensions enabledelayedexpansion
chcp 65001 >nul

rem === Change to the directory of this script ===
pushd "%~dp0" >nul 2>&1

rem === Optional: activate your conda env (uncomment and edit if needed) ===
rem call "%USERPROFILE%\miniconda3\Scripts\activate.bat" your_env_name

rem === Pick a Python interpreter ===
set "PY_CMD="
set "PY_ARGS="

rem Prefer the official Windows launcher if available
where py >nul 2>nul && (
  set "PY_CMD=py" && set "PY_ARGS=-3"
)

rem Fallbacks: python / python3 on PATH
if not defined PY_CMD where python >nul 2>nul && set "PY_CMD=python"
if not defined PY_CMD where python3 >nul 2>nul && set "PY_CMD=python3"

rem If still not found, allow override via PY_PATH.txt (first line = full path to python.exe)
if not defined PY_CMD if exist "PY_PATH.txt" (
  for /f "usebackq delims=" %%P in ("PY_PATH.txt") do (
    if not defined PY_CMD set "PY_CMD=%%P"
  )
)

rem Additional common locations (Conda/Anaconda and typical installs)
if not defined PY_CMD if exist "%USERPROFILE%\.conda\envs\zhoujie\python.exe" set "PY_CMD=%USERPROFILE%\.conda\envs\zhoujie\python.exe"
if not defined PY_CMD if exist "%USERPROFILE%\miniconda3\python.exe" set "PY_CMD=%USERPROFILE%\miniconda3\python.exe"
if not defined PY_CMD if exist "%USERPROFILE%\anaconda3\python.exe" set "PY_CMD=%USERPROFILE%\anaconda3\python.exe"
if not defined PY_CMD if exist "%ProgramFiles%\Python311\python.exe" set "PY_CMD=%ProgramFiles%\Python311\python.exe"
if not defined PY_CMD if exist "%ProgramFiles%\Python310\python.exe" set "PY_CMD=%ProgramFiles%\Python310\python.exe"
if not defined PY_CMD if exist "%ProgramFiles%\Python39\python.exe" set "PY_CMD=%ProgramFiles%\Python39\python.exe"

if not defined PY_CMD (
  echo [ERROR] Python not found.
  echo   - Option A: Install Python 3 from python.org and ensure 'py' or 'python' is in PATH.
  echo   - Option B: Create a file PY_PATH.txt with the full path to your python.exe
  echo       e.g. C:\Users\zhoujie\.conda\envs\zhoujie\python.exe
  echo.
  pause
  popd >nul 2>&1
  exit /b 1
)

echo [INFO] Using Python: %PY_CMD% %PY_ARGS%
echo [INFO] Launching dashboard via run.py ...
"%PY_CMD%" %PY_ARGS% run.py
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
  echo [ERROR] run.py exited with code %CODE%
)
echo.
echo Press any key to close this window...
pause >nul
popd >nul 2>&1
exit /b %CODE%

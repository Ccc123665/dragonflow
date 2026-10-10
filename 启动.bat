@echo off
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "ENTRY=%ROOT%src\main.py"

if not exist "%ENTRY%" (
  echo.
  echo   [错误] 找不到 %ENTRY%
  echo   请确认 启动.bat 和 src 目录在同一层。
  echo.
  pause
  exit /b 1
)

rem ---- 依次寻找可用的 Python（优先项目自带 .venv）----
set "PY="

if exist "%ROOT%.venv\Scripts\pythonw.exe" (
  set "PY=%ROOT%.venv\Scripts\pythonw.exe"
  goto :found
)
if exist "%USERPROFILE%\.workbuddy-ai\binaries\python\envs\df\Scripts\pythonw.exe" (
  set "PY=%USERPROFILE%\.workbuddy-ai\binaries\python\envs\df\Scripts\pythonw.exe"
  goto :found
)

rem 系统里的 pythonw（先查 py 启动器，再查 PATH）
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
  if not defined PY set "PY=%%i"
)
if not defined PY (
  for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined PY set "PY=%%i"
  )
)

:found
if not defined PY (
  echo.
  echo   [错误] 没有找到可用的 Python 环境。
  echo.
  echo   请在本目录执行下面两行，创建项目自带的运行环境：
  echo       python -m venv .venv
  echo       .venv\Scripts\pip install -r requirements.txt
  echo.
  echo   或者直接使用打包好的 EXE。
  echo.
  pause
  exit /b 1
)

echo   正在启动 DragonFlow ...
start "" "%PY%" "%ENTRY%"
endlocal
exit /b 0

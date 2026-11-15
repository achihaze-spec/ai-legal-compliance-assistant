@echo off
title Bot Office
cd /d "%~dp0"
echo.
echo  ===  Bot Office  ===
echo.
where py >nul 2>nul && (set PY=py -3) || (
  where python >nul 2>nul && (set PY=python) || (
    echo  Wala pang Python sa computer na ito.
    echo  1. I-download sa https://www.python.org/downloads/
    echo  2. Sa installer, i-check ang "Add python.exe to PATH"
    echo  3. I-double-click ulit ang file na ito.
    start https://www.python.org/downloads/
    pause
    exit /b 1
  )
)
if not exist ".venv\Scripts\python.exe" (
  echo  Unang beses: nag-i-install... ^(1-3 minuto^)
  %PY% -m venv .venv || (echo  Hindi nagawa ang .venv & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt || (echo  May problema sa pag-install. Tingnan ang mensahe sa itaas. & pause & exit /b 1)
echo.
echo  Bukas na ang opisina sa browser mo: http://localhost:8800
echo  Huwag isara ang window na ito habang ginagamit. Para ihinto: isara ang window.
echo.
set BOT_OFFICE_OPEN=1
".venv\Scripts\python.exe" server.py
pause

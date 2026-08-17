@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Auto-install dependencies if missing
python -c "import bs4, requests" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies...
  pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Install failed. Please check network, then run: pip install -r requirements.txt
    pause
    exit /b 1
  )
)

echo Fetching GitHub projects created in the last 7 days...
python github_trending.py --source new --days 7 --sort total --html github-new-repos-weekly.html
if errorlevel 1 (
  echo.
  echo Fetch failed. Please check your network connection.
  pause
  exit /b 1
)

echo Done. Opening report...
set "BROWSER="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined BROWSER if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined BROWSER if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "BROWSER=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"

if defined BROWSER (
  start "" "%BROWSER%" "github-new-repos-weekly.html"
) else (
  rem Fallback: relies on .html file association
  start "" "github-new-repos-weekly.html"
)

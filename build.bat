@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Kill a running app instance first so the exe can be overwritten
taskkill /F /IM GitHubStarsApp.exe >nul 2>&1

echo [1/2] Installing PyInstaller + pywebview...
python -m pip install pyinstaller pywebview
if errorlevel 1 (
  echo PyInstaller install failed. Please check network.
  pause
  exit /b 1
)

echo [2/2] Generating icon...
python make_icon.py

echo [3/3] Building GitHubStarsApp.exe ...
python -m PyInstaller --onefile --noconsole --clean --icon icon.ico --version-file version_info.txt --add-data "index.html;." --collect-all webview --name GitHubStarsApp github_stars_app.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Done! The app is at: dist\GitHubStarsApp.exe
pause

@echo off
setlocal

set "PORT=9222"
set "PROFILE=C:\mcp-browser-profile"

echo ========================================================
echo   Launching Chrome with Remote Debugging
echo   Port:        %PORT%
echo   Profile Dir: %PROFILE%
echo ========================================================

rem Find Chrome executable
set "CHROME_PATH="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
) else if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
) else if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%LocalAppData%\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_PATH%"=="" (
    echo [ERROR] Chrome executable not found in standard paths.
    pause
    exit /b 1
)

rem Create profile directory if it does not exist
if not exist "%PROFILE%" (
    mkdir "%PROFILE%"
)

echo [INFO] Starting Chrome...
start "" "%CHROME_PATH%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%" --disable-blink-features=AutomationControlled

echo [SUCCESS] Chrome launched on port %PORT%.
echo [REMINDER] In this browser window, navigate to https://gemini.google.com/app and log in if you haven't yet.
echo ========================================================

@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AI Copilot - Launcher

REM ---------------------------------------------------------------------------
REM  Local developer launcher: starts the FastAPI backend and the Vite frontend
REM  in their own windows, waits until both respond, then opens the browser.
REM  Stop the project by closing the "AI Copilot Backend" / "AI Copilot Frontend"
REM  windows. This script never kills processes and never reads backend\.env.
REM ---------------------------------------------------------------------------

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "FRONTEND=%ROOT%frontend"
set "PY=%BACKEND%\.venv\Scripts\python.exe"
set "CURL=%SystemRoot%\System32\curl.exe"
set "HEALTH=http://127.0.0.1:8000/api/health"
set "APP_TITLE=<title>AI Bioprocess Copilot</title>"

echo.
echo ==========================================
echo  AI Copilot for Scalable Cell-Culture
echo  Bioprocess Design
echo ==========================================
echo.

REM ---- Pre-flight checks ----------------------------------------------------
if not exist "%PY%" (
  echo ERROR: Python virtual environment not found:
  echo   %PY%
  echo Create it with:
  echo   cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\python -m pip install -r requirements.txt
  goto :fail
)
where npm >nul 2>&1 || (
  echo ERROR: npm was not found on PATH. Install Node.js from https://nodejs.org and reopen this window.
  goto :fail
)
if not exist "%FRONTEND%\node_modules" (
  echo ERROR: Frontend dependencies are missing. Run once:
  echo   cd frontend ^&^& npm install
  goto :fail
)
if not exist "%CURL%" (
  echo ERROR: %CURL% not found ^(included with Windows 10 1803 and later^).
  goto :fail
)
set "ENVARG="
if exist "%BACKEND%\.env" (
  set "ENVARG=--env-file .env"
) else (
  echo NOTE: backend\.env not found - the app runs, but Gemini AI features stay "not configured".
)

REM ---- [1/3] Backend --------------------------------------------------------
echo [1/3] Starting backend...
call :http_ok "%HEALTH%"
if not errorlevel 1 (
  echo       A backend is already responding on port 8000 - reusing it.
  goto :frontend
)
call :port_busy 8000
if not errorlevel 1 (
  echo.
  echo ERROR: Port 8000 is in use by another program that is not answering %HEALTH%.
  echo Close that program ^(or an old "AI Copilot Backend" window^) and run this launcher again.
  netstat -ano | findstr /r /c:":8000 .*LISTENING"
  goto :fail
)
REM Relative paths inside the backend folder avoid quoting problems with spaces in the project path.
start "AI Copilot Backend" /D "%BACKEND%" cmd /k .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000 %ENVARG%

:frontend
REM ---- [2/3] Frontend -------------------------------------------------------
echo [2/3] Starting frontend...
REM Reuse a running copy of this app's Vite server; otherwise take the first free port.
set "FEPORT="
set "FEREUSE="
for %%P in (5173 5174 5175 5176 5177 5178 5179 5180) do (
  if not defined FEREUSE (
    "%CURL%" -s --max-time 2 "http://127.0.0.1:%%P/" 2>nul | findstr /l /c:"%APP_TITLE%" >nul && (
      set "FEPORT=%%P"
      set "FEREUSE=1"
    )
  )
)
if defined FEREUSE (
  echo       This app's frontend is already running on port !FEPORT! - reusing it.
  goto :wait
)
for %%P in (5173 5174 5175 5176 5177 5178 5179 5180) do (
  if not defined FEPORT (
    call :port_busy %%P
    if errorlevel 1 set "FEPORT=%%P"
  )
)
if not defined FEPORT (
  echo ERROR: No free frontend port between 5173 and 5180.
  goto :fail
)
if not "%FEPORT%"=="5173" echo       Port 5173 is busy - using port %FEPORT% instead.
REM --strictPort: Vite uses exactly this port (or fails visibly) so the opened URL is always correct.
start "AI Copilot Frontend" /D "%FRONTEND%" cmd /k npm run dev -- --host 127.0.0.1 --port %FEPORT% --strictPort

:wait
REM ---- [3/3] Readiness ------------------------------------------------------
set "FEURL=http://127.0.0.1:%FEPORT%/"
echo [3/3] Waiting for services...
call :wait_url "%HEALTH%" 60
if errorlevel 1 (
  echo.
  echo Backend failed to start.
  echo Inspect the "AI Copilot Backend" window for the error.
  goto :fail
)
echo.
echo Backend:  READY  ^(http://127.0.0.1:8000^)
call :wait_url "%FEURL%" 60
if errorlevel 1 (
  echo.
  echo Frontend failed to start.
  echo Inspect the "AI Copilot Frontend" window for the error.
  goto :fail
)
echo Frontend: READY  ^(%FEURL%^)
echo.
echo Opening:
echo %FEURL%
start "" "%FEURL%"
echo.
echo Project started successfully.
echo To stop it, close the "AI Copilot Backend" and "AI Copilot Frontend" windows.
echo.
echo This launcher window can be closed.
pause
endlocal
exit /b 0

:fail
echo.
echo Startup did not complete.
pause
endlocal
exit /b 1

REM ---- Helpers ----------------------------------------------------------------
REM :http_ok URL  -> errorlevel 0 when the URL answers with HTTP 2xx/3xx
:http_ok
"%CURL%" -s -f -o nul --max-time 2 "%~1" >nul 2>&1
exit /b %errorlevel%

REM :port_busy PORT -> errorlevel 0 when something is LISTENING on that local port
:port_busy
netstat -ano | findstr /r /c:":%~1 .*LISTENING" >nul
exit /b %errorlevel%

REM :wait_url URL SECONDS -> errorlevel 0 once the URL responds, 1 after SECONDS
:wait_url
set /a "_tries=0"
:wait_url_loop
call :http_ok "%~1"
if not errorlevel 1 exit /b 0
set /a "_tries+=1"
if !_tries! geq %~2 exit /b 1
<nul set /p "=."
REM ping is used as a 1 s delay because "timeout" fails when input is redirected.
ping -n 2 127.0.0.1 >nul
goto :wait_url_loop

@echo off
REM ============================================================================
REM  Vega session launcher — called by Windows Task Scheduler twice a day.
REM  Usage:  run_session.cmd open    |    run_session.cmd close
REM
REM  For "random time" posting, set the trigger's built-in random delay in Task
REM  Scheduler (recommended), OR set VEGA_MAX_DELAY_MIN below to sleep a random
REM  number of minutes here before writing.
REM ============================================================================
setlocal
cd /d "%~dp0.."

set SESSION=%1
if "%SESSION%"=="" set SESSION=adhoc

REM --- Optional: which Hermes provider/model to use (defaults match Trinity) ---
REM set HERMES_BIN=hermes
REM set HERMES_PROVIDER=openai-codex
REM set HERMES_MODEL=gpt-5.5

REM --- Optional in-script random delay (minutes). Prefer the trigger setting. ---
if not "%VEGA_MAX_DELAY_MIN%"=="" (
  for /f %%D in ('powershell -NoProfile -Command "Get-Random -Maximum (%VEGA_MAX_DELAY_MIN%*60)"') do set DELAY=%%D
  echo [vega] random delay: %DELAY%s
  powershell -NoProfile -Command "Start-Sleep -Seconds %DELAY%"
)

echo [vega] writing %SESSION% entry...
python tools\new_entry.py --session %SESSION%
set RC=%ERRORLEVEL%
echo [vega] done (exit %RC%)
endlocal & exit /b %RC%

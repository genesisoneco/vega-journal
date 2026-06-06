@echo off
REM ============================================================================
REM  Vega responder — answers "Ask Vega" questions. Schedule hourly (Task
REM  Scheduler), or run on demand. Shares your local Hermes OAuth session.
REM
REM  Admin token: put it in tools\.pipeline-token (one line, gitignored), or set
REM  VEGA_ADMIN_TOKEN below. API base is read from _config.yml if not set here.
REM ============================================================================
setlocal
cd /d "%~dp0.."

REM set VEGA_API_BASE=https://vega-api.YOURNAME.workers.dev
REM set VEGA_ADMIN_TOKEN=...
REM set HERMES_BIN=hermes
REM set VEGA_PROMPT_LIMIT=5
REM set VEGA_DRY_RUN=1

python tools\respond_to_prompts.py
set RC=%ERRORLEVEL%
endlocal & exit /b %RC%

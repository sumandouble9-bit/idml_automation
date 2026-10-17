@echo off
title Spanish Automated Formatting Pipeline
cd /d "%~dp0"
setlocal
set FORCE_INJECT=1

echo ========================================================================
echo   IDML SPANISH AUTOMATED PIPELINE (4-STAGE MASTER WORKFLOW)
echo ========================================================================
echo.
echo Starting processing...
echo.
python Scripts\spanish\unified_pipeline_es.py %*
echo.
echo ========================================================================
echo Processing finished. Output files are in "Output".
echo ========================================================================
pause
endlocal

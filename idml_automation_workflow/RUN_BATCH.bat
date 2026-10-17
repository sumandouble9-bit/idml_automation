@echo off
title IDML Automated Formatting Pipeline - Batch Runner
cd /d "%~dp0"

echo ========================================================================
echo   IDML AUTOMATED FORMATTING PIPELINE (19-TASK WORKFLOW)
echo ========================================================================
echo.
echo Input Folder:     %~dp0Input
echo Reference Folder: %~dp0Reference
echo Output Folder:    %~dp0Output
echo.
echo Starting processing...
echo.

python run_pipeline.py

echo.
echo ========================================================================
echo Processing finished. Formatted files are in the "Output" folder.
echo ========================================================================
echo.
pause

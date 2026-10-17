@echo off
title IDML Automated Formatting Pipeline - Single File Runner
cd /d "%~dp0"

if "%~1"=="" (
    echo.
    echo [ERROR] No IDML file specified.
    echo.
    echo How to use:
    echo   1. Drag and drop any IDML file onto this RUN_SINGLE_FILE.bat icon.
    echo   OR
    echo   2. Run from command line: RUN_SINGLE_FILE.bat "path\to\book.idml"
    echo.
    pause
    exit /b 1
)

echo ========================================================================
echo   Processing: %~nx1
echo ========================================================================
echo.

python run_pipeline.py "%~1" --output "%~dp0Output\%~n1_FINAL.idml"

echo.
echo ========================================================================
echo Output saved to: %~dp0Output\%~n1_FINAL.idml
echo ========================================================================
echo.
pause

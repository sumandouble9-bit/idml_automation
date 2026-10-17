@echo off
setlocal
cd /d "%~dp0"
echo ===============================================================================
echo        STAGE 1: TYPOGRAPHY AND STRUCTURAL FORMATTING
echo ===============================================================================
echo.
python step1_format.py
if errorlevel 1 (
    echo.
    echo [!] Step 1 encountered errors.
    pause
    exit /b 1
)
echo.
echo [OK] Stage 1 Completed Successfully!
pause
endlocal

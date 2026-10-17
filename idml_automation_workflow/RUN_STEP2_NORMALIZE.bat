@echo off
setlocal
cd /d "%~dp0"
echo ===============================================================================
echo        STAGE 2: DOCUMENT SETUP NORMALIZATION (5.5x8.5 in, Margins, Bleeds)
echo ===============================================================================
echo.
python step2_normalize.py
if errorlevel 1 (
    echo.
    echo [!] Step 2 encountered errors.
    pause
    exit /b 1
)
echo.
echo [OK] Stage 2 Completed Successfully!
pause
endlocal

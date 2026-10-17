@echo off
setlocal
cd /d "%~dp0"
set FORCE_INJECT=1
echo ===============================================================================
echo        STAGE 3: EPUB IMAGE & CAPTION INJECTION (via Adobe InDesign)
echo ===============================================================================
echo.
python step3_inject_images.py
if errorlevel 1 (
    echo.
    echo [!] Step 3 encountered errors.
    pause
    exit /b 1
)
echo.
echo [OK] Stage 3 Completed Successfully!
pause
endlocal

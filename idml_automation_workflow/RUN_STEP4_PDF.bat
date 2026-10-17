@echo off
setlocal
cd /d "%~dp0"
echo ===============================================================================
echo        STAGE 4: HIGH-QUALITY PRINT PDF EXPORT (via Adobe InDesign)
echo ===============================================================================
echo.
python step4_export_pdf.py
if errorlevel 1 (
    echo.
    echo [!] Step 4 encountered errors.
    pause
    exit /b 1
)
echo.
echo [OK] Stage 4 Completed Successfully!
pause
endlocal

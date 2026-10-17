@echo off
title IDML Pipeline Verification Test Suite
cd /d "%~dp0"

echo ========================================================================
echo   RUNNING VERIFICATION TEST SUITE (19 TASKS)
echo ========================================================================
echo.

python -c "
import unittest, os, sys
from pathlib import Path

sys.path.insert(0, 'Scripts')
from Tests.test_idml_pipeline import TestIDMLPipelineTasks

output_dir = Path('Output')
final_files = sorted(output_dir.glob('*_FINAL.idml'))
if not final_files:
    print('No *_FINAL.idml files found in Output directory. Run RUN_BATCH.bat first!')
    sys.exit(1)

print(f'Testing {len(final_files)} generated IDML files:\n')
passed = 0
failed = 0

for f in final_files:
    print('=' * 60)
    print(f'TESTING: {f.name}')
    os.environ['OUTPUT_IDML'] = str(f.resolve())
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestIDMLPipelineTasks)
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)
    if res.wasSuccessful():
        passed += 1
    else:
        failed += 1

print('=' * 60)
print(f'OVERALL: {passed} passed, {failed} failed.')
"

echo.
echo ========================================================================
echo Test suite finished.
echo ========================================================================
echo.
pause

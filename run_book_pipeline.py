import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
RUNNER = ROOT_DIR / "idml_automation_workflow" / "run_book_pipeline.py"

if __name__ == "__main__":
    cmd = [sys.executable, str(RUNNER)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd))

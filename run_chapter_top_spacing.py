import sys
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
RUNNER = ROOT_DIR / "book_workflow" / "core" / "chapter_top_spacing.py"

if __name__ == "__main__":
    cmd = [sys.executable, str(RUNNER)] + sys.argv[1:]
    sys.exit(subprocess.call(cmd))

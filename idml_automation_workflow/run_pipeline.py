"""
Unified IDML Pipeline Entry Point
Delegates directly to run_unified_dual_pipeline for end-to-end multi-language processing.
Supports:
    python run_pipeline.py                 # process all books
    python run_pipeline.py 9789361422768   # process only this book (positional)
    python run_pipeline.py --book 18239    # process only this book (flag)
    python run_pipeline.py --limit 10      # process first 10 books
"""

import sys
from pathlib import Path

WF_DIR = Path(__file__).resolve().parent
if str(WF_DIR) not in sys.path:
    sys.path.insert(0, str(WF_DIR))

from run_unified_dual_pipeline import main

if __name__ == "__main__":
    main()

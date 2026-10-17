"""
Unified Pipeline Master Runner (Workflow Alias)
Directly invokes run_unified_dual_pipeline.py
"""
import sys
from pathlib import Path

WF_DIR = Path(__file__).resolve().parent
if str(WF_DIR) not in sys.path:
    sys.path.insert(0, str(WF_DIR))

from run_unified_dual_pipeline import main

if __name__ == "__main__":
    main()

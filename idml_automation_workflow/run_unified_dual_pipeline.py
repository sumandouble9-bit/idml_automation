"""Unified dual-language pipeline entry point (thin shim).

All logic now lives in the modular pipeline_engine package. This keeps the
familiar command working:

    python run_unified_dual_pipeline.py 9789361422768
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_engine import main

if __name__ == "__main__":
    main()

"""Entry point for the unified, modular book pipeline.

Thin CLI wrapper: all logic lives in pipeline_engine. Replaces the old
run_unified_dual_pipeline.py once the new engine is verified in InDesign.

    python run_book_pipeline.py 9789361422768
    python run_book_pipeline.py --lang es --step all
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_engine import main

if __name__ == "__main__":
    main()

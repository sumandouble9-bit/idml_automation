"""
Standalone CLI Runner for Chapter Heading Top Spacing
=====================================================
Usage:
    # Run on all files in idml_automation_workflow/Output/
    python run_chapter_top_spacing.py

    # Run on a specific IDML file or directory
    python run_chapter_top_spacing.py path/to/my_book.idml --output-dir path/to/output
    python run_chapter_top_spacing.py path/to/idml_folder/ --in-place
"""

import sys
from pathlib import Path

# Add core directory to path
CORE_DIR = Path(__file__).resolve().parent / "core"
sys.path.insert(0, str(CORE_DIR))

from chapter_top_spacing import main

if __name__ == "__main__":
    main()

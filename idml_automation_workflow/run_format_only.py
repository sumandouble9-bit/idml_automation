"""
Root Pipeline Runner for IDML Automation Workflow:
Run this script with zero arguments to format all files in the 'Input' folder
and save the final formatted books to the 'Output' folder.

Usage:
    python run_pipeline.py
    python run_pipeline.py "Input/my_book.idml"
    python run_pipeline.py "path/to/folder" --output "path/to/output"
"""

import sys
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = WORKFLOW_DIR / "Scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline import main as master_main

if __name__ == "__main__":
    # If no arguments provided, default to batch processing Input -> Output
    if len(sys.argv) == 1:
        input_dir = WORKFLOW_DIR / "Input"
        output_dir = WORKFLOW_DIR / "Output"
        ref_dir = WORKFLOW_DIR / "Reference"
        ref_files = list(ref_dir.glob("*.idml"))
        ref_file = ref_files[0] if ref_files else None

        sys.argv.append(str(input_dir))
        if ref_file:
            sys.argv.extend(["--reference", str(ref_file)])
        sys.argv.extend(["--output", str(output_dir)])

    sys.exit(master_main())

"""
STEP 1 ONLY — Normalize document setup (trim / margins / bleed).

    python run_step1_normalize.py                 # all books in input_files/
    python run_step1_normalize.py 9789361422768   # only this book

Input : input_files/
Output: page_resize_output/
Runs ONLY this step; does not touch the other stages or re-run the pipeline.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pipeline as rp

if __name__ == "__main__":
    rp._mkdirs()
    print(f"[STEP 1 only] Normalize — {'book ' + rp.ONLY if rp.ONLY else 'all books'}")
    rp.step1_normalize()
    print(f"\nDone. Output: {rp.PAGE_RESIZE}")

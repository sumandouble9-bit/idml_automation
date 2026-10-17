"""
STEP 2 ONLY — Format to reference layout (typography / pages).

    python run_step2_format.py                 # all books in page_resize_output/
    python run_step2_format.py 9789361422768   # only this book

Input : page_resize_output/   (output of step 1)
Output: formate_document/
Runs ONLY this step; does not touch the other stages or re-run the pipeline.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pipeline as rp

if __name__ == "__main__":
    rp._mkdirs()
    print(f"[STEP 2 only] Format — {'book ' + rp.ONLY if rp.ONLY else 'all books'}")
    rp.step2_format()
    print(f"\nDone. Output: {rp.FORMAT_DIR}")

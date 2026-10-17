"""
STEP 3 ONLY — Inject EPUB images + captions.

    python run_step3_inject.py                 # all books in formate_document/
    python run_step3_inject.py 9789361422768   # only this book

Input : formate_document/   (output of step 2)
Output: final_output_files/idml_files/
Runs ONLY this step; does not touch the other stages or re-run the pipeline.
NOTE: injection skips a book whose *_injected.idml already exists. To force a
re-inject, delete that book's file from final_output_files/idml_files/ first.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pipeline as rp

if __name__ == "__main__":
    rp._mkdirs()
    print(f"[STEP 3 only] Inject — {'book ' + rp.ONLY if rp.ONLY else 'all books'}")
    rp.step3_inject()
    print(f"\nDone. Output: {rp.IMG_BASE / 'idml_files'}")

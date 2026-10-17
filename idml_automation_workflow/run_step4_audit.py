"""
STEP 4 ONLY — Audit + export PDFs.

    python run_step4_audit.py                 # all injected books
    python run_step4_audit.py 9789361422768   # only this book

Input : final_output_files/idml_files/   (output of step 3)
Output: final_output_files/pdf_files/        (passed)
        final_output_files/rejected_files/   (failed: idml_files + pdf_files)
Runs ONLY this step; does not touch the other stages or re-run the pipeline.
NOTE: audit skips a book whose PDF already exists in pass OR reject. To force a
re-audit, delete that book's PDF from pdf_files/ and rejected_files/pdf_files/.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_pipeline as rp

if __name__ == "__main__":
    rp._mkdirs()
    print(f"[STEP 4 only] Audit — {'book ' + rp.ONLY if rp.ONLY else 'all books'}")
    rp.step4_audit()
    print(f"\nDone. PDFs: {rp.IMG_BASE / 'pdf_files'}  Rejected: {rp.REJ_BASE}")

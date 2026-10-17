"""
Step 2 Runner: Document Setup Normalization
Standardizes IDML document geometry (5.5 x 8.5 in trim size, margins 36/54/36/36 pt, facing pages, bleeds).
Reads from Output/Formatted/ and outputs to Output/page_resize_output/.
"""

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT_DIR / "Scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pages import normalize_document_setup


def run_step2(input_target=None):
    formatted_dir = ROOT_DIR / "Output" / "Formatted"
    raw_dir = ROOT_DIR / "input_files"
    if not raw_dir.is_dir() or not any(raw_dir.glob("*.idml")):
        if (ROOT_DIR.parent / "input_files").is_dir():
            raw_dir = ROOT_DIR.parent / "input_files"

    output_dir = ROOT_DIR / "Output" / "page_resize_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_target:
        p = Path(input_target).resolve()
        files = [p] if p.is_file() else sorted(p.glob("*.idml"))
    elif formatted_dir.exists() and any(formatted_dir.glob("*.idml")):
        files = sorted(formatted_dir.glob("*.idml"))
    else:
        files = sorted(raw_dir.glob("*.idml"))

    files = [f for f in files if not f.name.startswith("~") and not f.name.startswith(".")]
    if not files:
        print(f"[!] No IDML files found to normalize.")
        return 1

    print("=" * 70)
    print("STEP 2: Document Setup Normalization (5.5x8.5 in, Margins, Bleeds)")
    print(f"Files to process: {len(files)}")
    print(f"Output folder:    {output_dir}")
    print("=" * 70)

    success, failed = 0, 0
    for idx, f in enumerate(files, 1):
        clean_stem = f.stem.replace("_formatted", "").replace("_normalized", "")
        out_f = output_dir / f"{clean_stem}_normalized.idml"
        print(f"\n[{idx}/{len(files)}] Normalizing: {f.name} -> {out_f.name}")
        try:
            normalize_document_setup.normalize_one_file(str(f), str(out_f))
            print(f"     [OK] Normalized: {out_f.name}")
            success += 1
        except Exception as e:
            print(f"     [FAIL] Error normalizing {f.name}: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"Step 2 Complete: {success} succeeded, {failed} failed.")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 2: Document Setup Normalization")
    parser.add_argument("input", nargs="?", default=None, help="Target IDML or folder (default: Output/Formatted/)")
    args = parser.parse_args()
    sys.exit(run_step2(args.input))

"""
Batch Runner for Automated IDML Pipeline:
Runs the full pipeline across all IDML files in an input folder.
"""

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline import process_idml, resolve_reference


def main():
    parser = argparse.ArgumentParser(
        description="Run IDML formatting pipeline on every IDML in a folder."
    )
    parser.add_argument("input_folder", help="Input directory containing IDML files")
    parser.add_argument(
        "--reference",
        "-r",
        default=None,
        help="Path to Reference IDML file",
    )
    parser.add_argument(
        "--output_folder",
        "-o",
        default=None,
        help="Output directory for formatted IDML files",
    )
    args = parser.parse_args()

    input_folder = Path(args.input_folder).resolve()
    if not input_folder.is_dir():
        sys.exit(f"Input directory not found: {input_folder}")

    reference = resolve_reference(args.reference)
    if not reference or not reference.is_file():
        sys.exit(f"Reference IDML not found: {args.reference or 'Reference/'}")

    output_folder = (
        Path(args.output_folder).resolve()
        if args.output_folder
        else SCRIPTS_DIR.parent / "Output" / "Formatted"
    )
    output_folder.mkdir(parents=True, exist_ok=True)

    files = sorted(input_folder.glob("*.idml"))
    if not files:
        sys.exit(f"No IDML files found in: {input_folder}")

    print("=" * 72)
    print("RUNNING BATCH IDML PIPELINE")
    print(f"Input folder:  {input_folder}")
    print(f"Reference:     {reference.name}")
    print(f"Output folder: {output_folder}")
    print(f"Found {len(files)} IDML file(s).")
    print("=" * 72)

    ok = 0
    failed = 0

    for f in files:
        out_file = output_folder / f"{f.stem}_FINAL.idml"
        print(f"\nProcessing: {f.name} -> {out_file.name}")
        try:
            rep = process_idml(f, reference, out_file)
            print(f"  SUCCESS ({rep['elapsed_seconds']}s)")
            ok += 1
        except Exception as exc:
            print(f"  FAILED: {exc}")
            failed += 1

    print("\n" + "=" * 72)
    print(f"Finished: {ok} successful, {failed} failed.")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

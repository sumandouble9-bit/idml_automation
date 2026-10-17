"""
Step 4 Runner: High-Quality Print PDF Export
Converts injected IDML files into publication-ready Print PDFs using Adobe InDesign.
Ensures document fonts are active and embedded with zero font substitution.
Reads from Output/injected_idml_files/ and outputs to Output/pdf_files/.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT_DIR / "Scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import convert_to_pdf


def run_step4(input_target=None, output_dir=None):
    injected_dir = ROOT_DIR / "Output" / "injected_idml_files"
    norm_dir = ROOT_DIR / "Output" / "page_resize_output"

    if output_dir:
        final_pdf_dir = Path(output_dir).resolve()
    else:
        final_pdf_dir = ROOT_DIR / "Output" / "pdf_files"

    final_pdf_dir.mkdir(parents=True, exist_ok=True)

    if input_target:
        target_path = Path(input_target).resolve()
    elif injected_dir.exists() and any(injected_dir.glob("*.idml")):
        target_path = injected_dir
    else:
        target_path = norm_dir

    print("=" * 70)
    print("STEP 4: High-Quality Print PDF Export (via Adobe InDesign)")
    print(f"Target path:   {target_path}")
    print(f"Output folder: {final_pdf_dir}")
    print("=" * 70)

    try:
        convert_to_pdf.convert_batch(
            target_path=str(target_path),
            output_dir=str(final_pdf_dir),
        )

        # Optional convenience copy to Desktop
        desktop_dir = Path.home() / "Desktop"
        if desktop_dir.is_dir():
            desktop_out = desktop_dir / "PDF_Output"
            try:
                desktop_out.mkdir(parents=True, exist_ok=True)
                for pdf_f in final_pdf_dir.glob("*.pdf"):
                    shutil.copy2(str(pdf_f), str(desktop_out / pdf_f.name))
                print(f"[Notice] PDFs also copied to Desktop: {desktop_out}")
            except Exception:
                pass

        print("\n" + "=" * 70)
        print("Step 4 Complete!")
        print(f"Exported PDFs available in: {final_pdf_dir}")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"\n[!] Error during Step 4: {e}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 4: PDF Export")
    parser.add_argument("input", nargs="?", default=None, help="Target IDML or folder (default: Output/injected_idml_files/)")
    parser.add_argument("--output", default=None, help="Custom output folder for PDFs")
    args = parser.parse_args()
    sys.exit(run_step4(args.input, args.output))

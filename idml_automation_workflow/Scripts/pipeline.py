"""
1. Book size (5.5 x 8.5 in), page margins, bleed margin (3mm)
2. Preserve formatting and positioning of title page as per reference
3. Preserve formatting and positioning of copyright page (with dynamic ISBN/year)
4. Preserve formatting and positioning of TOC page (with dot leaders and indexing)
5. Preserve formatting and positioning of About the Author page
6. Apply correct font family (Palatino Linotype) and size (9.65pt) to body text
7. Restore bold formatting wherever bold character styles are applied
8. Restore italic formatting wherever italic character styles are applied
9. Fix title-page font size and font style according to reference layout
10. Preserve title-page "by" credit styling separately from title and author text
11. Separate chapter number and chapter title when they appear on the same run-on line
12. Preserve correct H1, H2, H3 and other heading styles and text position (center, left, right)
13. Restore superscript formatting for footnote/reference markers
14. Restore subscript formatting wherever used
15. Remove/merge duplicate Bold, Italic, Underline and All Caps character styles
16. Ensure correct Bold/Italic/Underline/All Caps character styles apply intended formatting
17. Verify Underline and All Caps formatting throughout the book
18. Verify index content formatting and spacing
19. Verify footnote content formatting and placement

Usage:
    # Single file:
    python Scripts/pipeline.py "Input/18239 1.idml" --reference "Reference/11671 LES MISÉRABLES.idml" --output "Output/Formatted/18239 1_FINAL.idml"

    # Batch folder:
    python Scripts/pipeline.py "Input" --reference "Reference/11671 LES MISÉRABLES.idml" --output "Output/Formatted"
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

# Ensure Scripts/ is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core import font_manager
from core.idml_utils import (
    unzip,
    validate_zip,
    zipdir,
)
from pages import (
    author_page,
    copyright_page,
    document_setup,
    title_page,
    toc_page,
    typography_and_styles,
)


def process_idml(target_path, reference_path, output_path):
    target = Path(target_path).resolve()
    reference = Path(reference_path).resolve()
    output = Path(output_path).resolve()

    if not target.is_file():
        raise FileNotFoundError(f"Target IDML not found: {target}")
    if not reference.is_file():
        raise FileNotFoundError(f"Reference IDML not found: {reference}")

    output.parent.mkdir(parents=True, exist_ok=True)
    start_time = time.time()

    report = {
        "target": str(target),
        "reference": str(reference),
        "output": str(output),
        "stages": {},
    }

    with tempfile.TemporaryDirectory(prefix="idml_pipeline_") as tmp:
        tmp_path = Path(tmp)
        work_dir = tmp_path / "work"
        ref_dir = tmp_path / "ref"
        work_dir.mkdir()
        ref_dir.mkdir()

        # Unpack IDMLs
        unzip(target, work_dir)
        unzip(reference, ref_dir)

        # -------------------------------------------------------------
        # Stage 0: Font Management & Document Fonts Bundling
        # -------------------------------------------------------------
        print("  [0/6] Dynamically resolving, downloading, and bundling all document font families...")
        report["stages"]["font_manager"] = font_manager.resolve_idml_fonts_and_fallbacks(
            work_dir, output.parent
        )

        # -------------------------------------------------------------
        # Stage 1: Document Setup (Task 1)
        # -------------------------------------------------------------
        print("  [1/6] Setting book size, page margins, bleeds, and master spreads...")
        report["stages"]["document_setup"] = document_setup.apply(work_dir, ref_dir)

        # -------------------------------------------------------------
        # Stage 2: Title Page (Tasks 2, 9, 10)
        # -------------------------------------------------------------
        print("  [2/6] Formatting Title Page (typography, separate 'by')...")
        report["stages"]["title_page"] = title_page.apply(work_dir, ref_dir)

        # -------------------------------------------------------------
        # Stage 3: Copyright Page (Task 3)
        # -------------------------------------------------------------
        print("  [3/6] Formatting Copyright Page (dynamic ISBN/year, Double 9 Books)...")
        report["stages"]["copyright_page"] = copyright_page.apply(work_dir, ref_dir, book_name=target.stem)

        # -------------------------------------------------------------
        # Stage 4: TOC Page (Task 4)
        # -------------------------------------------------------------
        print("  [4/6] Formatting TOC Page (indexing, dot leaders, clean numbering)...")
        report["stages"]["toc_page"] = toc_page.apply(work_dir, ref_dir)

        # -------------------------------------------------------------
        # Stage 5: About the Author Page (Task 5)
        # -------------------------------------------------------------
        print("  [5/6] Formatting About the Author Page...")
        report["stages"]["author_page"] = author_page.apply(work_dir, ref_dir)

        # -------------------------------------------------------------
        # Stage 6: Typography, Character Styles & Story Cleanup
        # (Tasks 6, 7, 8, 11, 12, 13, 14, 15, 16, 17, 18, 19)
        # -------------------------------------------------------------
        print("  [6/6] Applying Typography, headings, body text, and character styles...")
        report["stages"]["typography_and_styles"] = typography_and_styles.apply(
            work_dir, ref_dir, book_name=target.stem
        )

        # -------------------------------------------------------------
        # Stage 7: EPUB Style Enrichment (Bold, Italic, Underline)
        # -------------------------------------------------------------
        print("  [7/7] Enriching inline typography from EPUB (bold, italic, underline)...")
        from core import epub_style_enricher
        report["stages"]["epub_enrichment"] = epub_style_enricher.enrich_extracted_idml(
            work_dir, book_name=target.stem, lang="en"
        )

        # Repack IDML
        zipdir(work_dir, output)
        zip_ok = validate_zip(output)
        report["zip_valid"] = zip_ok
        if not zip_ok:
            raise RuntimeError(f"Generated IDML failed ZIP validation: {output}")

        # Postprocess generated IDML to guarantee canonical Palatino Linotype font inheritance and keeps
        from core import typography_postprocessor
        try:
            report["stages"]["typography_postprocessor"] = typography_postprocessor.postprocess_idml(output)
        except Exception as e_post:
            print(f"  Note: typography_postprocessor encountered: {e_post}")

    elapsed = time.time() - start_time
    report["elapsed_seconds"] = round(elapsed, 2)

    # Save JSON report
    report_file = output.with_name(f"{output.stem}_report.json")
    report_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return report


def resolve_reference(ref_arg):
    if ref_arg:
        p = Path(ref_arg).resolve()
        if p.is_file():
            return p
    # Look in Reference/ directory
    ref_dir = SCRIPTS_DIR.parent / "Reference"
    candidates = list(ref_dir.glob("*.idml"))
    if candidates:
        return candidates[0]
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Automated EPUB-to-IDML Formatting Pipeline."
    )
    parser.add_argument(
        "target",
        help="Path to an IDML file OR a directory containing IDML files.",
    )
    parser.add_argument(
        "--reference",
        "-r",
        default=None,
        help="Path to the reference IDML file.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output IDML file or directory for output files.",
    )
    args = parser.parse_args()

    target_path = Path(args.target).resolve()
    if not target_path.exists():
        sys.exit(f"Target not found: {target_path}")

    reference_path = resolve_reference(args.reference)
    if not reference_path or not reference_path.is_file():
        sys.exit(f"Reference IDML not found: {args.reference or 'Reference/'}")

    print("=" * 72)
    print("AUTOMATED IDML FORMATTING PIPELINE")
    print(f"Reference: {reference_path.name}")
    print("=" * 72)

    if target_path.is_file():
        # Single file execution
        if args.output:
            out_path = Path(args.output).resolve()
            if out_path.is_dir() or not out_path.suffix:
                out_path = out_path / f"{target_path.stem}_FINAL.idml"
        else:
            out_path = SCRIPTS_DIR.parent / "Output" / "Formatted" / f"{target_path.stem}_FINAL.idml"

        print(f"\nProcessing: {target_path.name} -> {out_path.name}")
        report = process_idml(target_path, reference_path, out_path)
        print(f"Successfully created: {out_path} ({report['elapsed_seconds']}s)")
        return 0

    elif target_path.is_dir():
        # Batch folder execution
        idml_files = sorted(target_path.glob("*.idml"))
        if not idml_files:
            sys.exit(f"No IDML files found in directory: {target_path}")

        out_dir = Path(args.output).resolve() if args.output else (SCRIPTS_DIR.parent / "Output" / "Formatted")
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"Found {len(idml_files)} IDML file(s) in {target_path}")
        print(f"Output directory: {out_dir}\n")

        successes = 0
        failures = 0

        for f in idml_files:
            out_file = out_dir / f"{f.stem}_FINAL.idml"
            print("-" * 72)
            print(f"Processing: {f.name}")
            try:
                rep = process_idml(f, reference_path, out_file)
                print(f"  -> SUCCESS ({rep['elapsed_seconds']}s): {out_file.name}")
                successes += 1
            except Exception as e:
                print(f"  -> FAILED: {e}")
                failures += 1

        print("=" * 72)
        print(f"Batch Processing Complete: {successes} succeeded, {failures} failed.")
        print("=" * 72)
        return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

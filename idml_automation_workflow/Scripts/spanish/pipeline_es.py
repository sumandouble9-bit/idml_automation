"""
Spanish Master Stage 1 Pipeline Runner:
Applies complete Spanish book formatting:
1. Book size (5.5 x 8.5 in), page margins, bleed margin (3mm)
2. Preserves and formats Spanish Title Page (with italic 'Por')
3. Spanish Copyright Page (with dynamic ISBN/year, Spanish legal text)
4. Spanish TOC ('Contenido' with dot leaders, clean numbering, EPUB sync)
5. Spanish About the Author Page ('Sobre la autoría' / 'Sobre el autor')
6. Palatino Linotype 9.65pt on body text, Gill Sans MT 16pt on headings
7. Accurately splits Spanish run-on chapters and aligns with TOC
8. Preserves 100% of tables and internal cell formatting
9. Underline, bold, and italic cleanup
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
SPANISH_DIR = Path(__file__).resolve().parent

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SPANISH_DIR) not in sys.path:
    sys.path.insert(0, str(SPANISH_DIR))

from core import font_manager
from core.idml_utils import (
    unzip,
    validate_zip,
    zipdir,
)
from pages import document_setup

import title_page_es
import copyright_page_es
import toc_page_es
import author_page_es
import typography_and_styles_es


def process_idml_es(target_path, reference_path, output_path):
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
        "language": "es",
        "stages": {},
    }

    with tempfile.TemporaryDirectory(prefix="idml_es_pipeline_") as tmp:
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
        print("  [0/6] Dynamically resolving and bundling fonts...")
        report["stages"]["font_manager"] = font_manager.resolve_idml_fonts_and_fallbacks(
            work_dir, output.parent
        )

        # -------------------------------------------------------------
        # Stage 1: Document Setup
        # -------------------------------------------------------------
        print("  [1/6] Setting book size, page margins, bleeds, and master spreads...")
        report["stages"]["document_setup"] = document_setup.apply(work_dir, ref_dir)

        # -------------------------------------------------------------
        # Stage 2: Spanish Title Page
        # -------------------------------------------------------------
        print("  [2/6] Formatting Spanish Title Page (typography, italic 'Por')...")
        report["stages"]["title_page_es"] = title_page_es.apply(work_dir, ref_dir)

        # -------------------------------------------------------------
        # Stage 3: Spanish Copyright Page
        # -------------------------------------------------------------
        print("  [3/6] Formatting Spanish Copyright Page (dynamic ISBN/year, legal text)...")
        report["stages"]["copyright_page_es"] = copyright_page_es.apply(work_dir, ref_dir, book_name=target.stem)

        # -------------------------------------------------------------
        # Stage 4: Spanish TOC Page
        # -------------------------------------------------------------
        print("  [4/6] Formatting Spanish TOC Page (Contenido, dot leaders, EPUB sync)...")
        report["stages"]["toc_page_es"] = toc_page_es.apply(work_dir, ref_dir, book_name=target.stem)

        # -------------------------------------------------------------
        # Stage 5: Spanish About the Author Page
        # -------------------------------------------------------------
        print("  [5/6] Formatting Spanish About the Author Page (Sobre la autoría)...")
        report["stages"]["author_page_es"] = author_page_es.apply(work_dir, ref_dir)

        # -------------------------------------------------------------
        # Stage 6: Spanish Typography, Headings, and Table Preservation
        # -------------------------------------------------------------
        print("  [6/6] Applying Spanish Typography, chapter breaks, and table protection...")
        report["stages"]["typography_and_styles_es"] = typography_and_styles_es.apply(
            work_dir, ref_dir, book_name=target.stem
        )

        # -------------------------------------------------------------
        # Stage 7: EPUB Style Enrichment (Bold, Italic, Underline)
        # -------------------------------------------------------------
        print("  [7/7] Enriching Spanish inline typography from EPUB (bold, italic, underline)...")
        from core import epub_style_enricher
        report["stages"]["epub_enrichment"] = epub_style_enricher.enrich_extracted_idml(
            work_dir, book_name=target.stem, lang="es"
        )

        # Repack IDML
        zipdir(work_dir, output)
        zip_ok = validate_zip(output)
        report["zip_valid"] = zip_ok
        if not zip_ok:
            raise RuntimeError(f"Generated IDML failed ZIP validation: {output}")

    elapsed = time.time() - start_time
    report["elapsed_seconds"] = round(elapsed, 2)

    report_file = output.with_name(f"{output.stem}_report.json")
    report_file.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def main():
    parser = argparse.ArgumentParser(description="Spanish IDML Processing Pipeline")
    parser.add_argument("target", help="Target IDML file or directory")
    parser.add_argument("--reference", required=True, help="Reference IDML file")
    parser.add_argument("--output", required=True, help="Output IDML file or directory")

    args = parser.parse_args()
    target_p = Path(args.target).resolve()
    ref_p = Path(args.reference).resolve()
    out_p = Path(args.output).resolve()

    if target_p.is_file():
        process_idml_es(target_p, ref_p, out_p)
    elif target_p.is_dir():
        out_p.mkdir(parents=True, exist_ok=True)
        files = sorted(target_p.glob("*.idml"))
        for f in files:
            out_f = out_p / f"{f.stem}_formatted.idml"
            print(f"\nProcessing {f.name}...")
            process_idml_es(f, ref_p, out_f)


if __name__ == "__main__":
    main()

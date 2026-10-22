#!/usr/bin/env python3
"""
CLI entry point for 1st Module: Formatting_idml
Double Nine Books IDML Automation

Usage:
  python run_formatting.py --book 18670 --list-chapters
  python run_formatting.py --book 18670 --chapter 1
  python run_formatting.py --book 18670 --all
  python run_formatting.py --book 18722 --all
"""

import sys
import argparse
from pathlib import Path

# Add workspace root to sys.path
WORKSPACE_ROOT = Path(__file__).parent.resolve()
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from Formatting_idml.pipeline import FormattingIDMLPipeline


def main():
    parser = argparse.ArgumentParser(description="Formatting_idml: 1st Module for IDML Typography & Asset Formatting")
    parser.add_argument("--book", type=str, required=True, help="Book ID to format (e.g. 18670 or 18722)")
    parser.add_argument("--chapter", type=int, default=None, help="Specific chapter number to process in isolation (e.g. 1)")
    parser.add_argument("--all", action="store_true", help="Process the whole book across all chapters")
    parser.add_argument("--list-chapters", action="store_true", help="List all chapters discovered in the book")
    parser.add_argument("--skip-jsx", action="store_true", help="Run pure Python normalization (no InDesign GUI required)")
    parser.add_argument("--preview-pages", type=int, nargs="+", help="Page numbers to render to high-res PNG previews (e.g. --preview-pages 7 8 28 29)")

    args = parser.parse_args()

    pipeline = FormattingIDMLPipeline(book_id=args.book, workspace_root=str(WORKSPACE_ROOT))

    if args.preview_pages:
        from Formatting_idml.pdf_exporter import PdfExporter
        pdf_file = pipeline.output_base / f"{pipeline.input_idml.stem}_print.pdf"
        if not pdf_file.exists():
            print(f"[ERROR] PDF not found for preview rendering: {pdf_file}")
            print("Please run the formatting pipeline with InDesign enabled first.")
            return
        exporter = PdfExporter()
        out_dir = pipeline.output_base / "previews"
        rendered = exporter.render_spread_previews(str(pdf_file), args.preview_pages, str(out_dir))
        print(f"\n[PASS] Rendered {len(rendered)} high-resolution page previews to: {out_dir}")
        for r in rendered:
            print(f"  - {r.name}")
        return

    if args.list_chapters:
        pipeline.setup_environment()
        pipeline.chapter_processor.print_chapter_manifest(pipeline.doc)
        return

    if args.chapter:
        print(f"\n=======================================================")
        print(f" Formatting_idml  Isolated Chapter Mode")
        print(f" Book: {args.book} | Chapter: {args.chapter}")
        print(f"=======================================================")
        pipeline.run_chapter(chapter_num=args.chapter, skip_jsx=args.skip_jsx)
        print(f"\n[PASS] Isolated Chapter {args.chapter} formatting complete.\n")
        return

    # Default to whole book
    print(f"\n=======================================================")
    print(f" Formatting_idml  Full Book Mode")
    print(f" Book: {args.book} | All Chapters")
    print(f"=======================================================")
    pipeline.run_all(skip_jsx=args.skip_jsx)
    print(f"\n[PASS] Full book formatting complete for {args.book}.\n")


if __name__ == "__main__":
    main()

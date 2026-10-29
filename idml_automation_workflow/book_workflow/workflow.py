"""BookWorkflow: master orchestrator coordinating all production stages for IDML publishing.

Provides a clean, modular, object-oriented architecture that automates:
  Stage 1: Document Formatting & Typography
  Stage 2: Document Setup & Normalization
  Stage 3: EPUB Asset, Image & Caption Injection
  Stage 4: Quality Gate, TOC Sync & Print PDF Export
"""

import argparse
import sys
from typing import List, Optional

from .book_discovery import BookDiscovery
from .models.book import Book
from .paths import WorkflowPaths
from .stages.export_stage import QualityAuditAndExportStage
from .stages.formatting_stage import DocumentFormattingStage
from .stages.injection_stage import AssetInjectionStage
from .stages.normalization_stage import DocumentNormalizationStage


class BookWorkflow:
    """Master workflow engine managing document processing across production stages."""

    def __init__(self, paths: Optional[WorkflowPaths] = None):
        self.paths = (paths or WorkflowPaths()).register_on_syspath()
        self.discovery = BookDiscovery(self.paths)
        self.formatting = DocumentFormattingStage(self.paths)
        self.normalization = DocumentNormalizationStage(self.paths)
        self.injection = AssetInjectionStage(self.paths)
        self.export = QualityAuditAndExportStage(self.paths)

    def discover(
        self,
        book: Optional[str] = None,
        language: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Book]:
        """Discovers matching manuscripts in the input directory."""
        books = self.discovery.discover(only_book=book, target_language=language, limit=limit)
        print(f"Discovered {len(books)} book(s) matching criteria.")
        print(f"  Spanish books: {sum(1 for b in books if b.language_code == 'es')}")
        print(f"  English books: {sum(1 for b in books if b.language_code == 'en')}")
        return books

    def run(
        self,
        book: Optional[str] = None,
        language: Optional[str] = None,
        step: str = "all",
        limit: Optional[int] = None,
        force: bool = False,
    ):
        """Executes the specified stage(s) across discovered books."""
        force_run = force or bool(book)
        books = self.discover(book=book, language=language, limit=limit)
        if not books:
            print("No matching books found to process.")
            return

        if step in ("all", "1"):
            self.formatting.run(books)
        if step in ("all", "2"):
            self.normalization.run(books)
        if step in ("all", "3"):
            self.injection.inject(books, force=force_run)
            self.injection.fix_chapter_double_breaks(books)
        if step == "3d":
            self.injection.fix_chapter_double_breaks(books)
        if step in ("all", "3b"):
            self.injection.fill_bottom_gaps(books)
        if step in ("all", "4"):
            self.export.run(books, force=force_run)


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Book Production Workflow Engine")
    parser.add_argument("book_pos", nargs="?", default=None, help="Optional positional book identifier (ISBN or filename)")
    parser.add_argument("--book", default=None, help="Process single book by ISBN or filename")
    parser.add_argument("--lang", choices=["all", "es", "en"], default="all", help="Filter by language")
    parser.add_argument(
        "--step",
        choices=["all", "1", "2", "3", "3d", "3b", "3c", "4"],
        default="all",
        help="Workflow step to run (1=Format, 2=Normalize, 3=Inject, 3b=GapFill, 4=Export PDF)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of books to process")
    parser.add_argument("--force", action="store_true", help="Force processing even if already completed")
    return parser


def main(argv=None):
    args, _unknown = build_arg_parser().parse_known_args(argv)
    language = None if args.lang == "all" else args.lang
    BookWorkflow().run(
        book=args.book or args.book_pos,
        language=language,
        step=args.step,
        limit=args.limit,
        force=args.force,
    )


# Backward-compatibility alias
Pipeline = BookWorkflow

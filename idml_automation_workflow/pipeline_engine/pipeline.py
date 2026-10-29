"""Pipeline: the single orchestrator for the whole book production flow.

Replaces the procedural main() in run_unified_dual_pipeline.py with one class that
composes the stages. Step selection and ordering match the original exactly
(formatting -> normalization -> injection[/3d] -> gap-fill -> export).
"""

import argparse

from .book_discovery import BookDiscovery
from .paths import ProjectPaths
from .stages.export import ExportStage
from .stages.formatting import FormattingStage
from .stages.injection import InjectionStage
from .stages.normalization import NormalizationStage


class Pipeline:
    # Builds the stages from ProjectPaths and runs the requested step(s) over a
    # discovered set of books.
    def __init__(self, paths=None):
        self.paths = (paths or ProjectPaths()).register_on_syspath()
        self.discovery = BookDiscovery(self.paths)
        self.formatting = FormattingStage(self.paths)
        self.normalization = NormalizationStage(self.paths)
        self.injection = InjectionStage(self.paths)
        self.export = ExportStage(self.paths)

    def discover(self, book=None, language=None, limit=None):
        # Find the books to process and print the language breakdown.
        books = self.discovery.discover(only_book=book, target_language=language, limit=limit)
        print(f"Discovered {len(books)} books matching criteria.")
        print(f"  Spanish books: {sum(1 for b in books if b.language_code == 'es')}")
        print(f"  English books: {sum(1 for b in books if b.language_code == 'en')}")
        return books

    def run(self, book=None, language=None, step="all", limit=None, force=False):
        # Run the selected pipeline step(s), mirroring the original dispatch.
        force_run = force or bool(book)
        books = self.discover(book=book, language=language, limit=limit)

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
    # CLI identical to the original unified runner.
    parser = argparse.ArgumentParser(description="Unified Dual-Language Pipeline")
    parser.add_argument("book_pos", nargs="?", default=None, help="Optional positional book identifier")
    parser.add_argument("--book", default=None, help="Process single book by ISBN/name")
    parser.add_argument("--lang", choices=["all", "es", "en"], default="all", help="Filter by language")
    parser.add_argument("--step", choices=["all", "1", "2", "3", "3d", "3b", "3c", "4"], default="all",
                        help="Pipeline step to run")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of books to process")
    parser.add_argument("--force", action="store_true", help="Force injection even if already processed")
    return parser


def main(argv=None):
    # Parse arguments and run the pipeline.
    args, _unknown = build_arg_parser().parse_known_args(argv)
    language = None if args.lang == "all" else args.lang
    Pipeline().run(
        book=args.book or args.book_pos,
        language=language,
        step=args.step,
        limit=args.limit,
        force=args.force,
    )

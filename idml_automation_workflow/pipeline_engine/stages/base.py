"""PipelineStage: common contract and helpers for every pipeline step."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class StageResult:
    # Outcome of running one stage over a batch of books.
    name: str
    succeeded: int = 0
    failed: int = 0
    notes: List[str] = field(default_factory=list)

    def record(self, ok, note=None):
        # Tally one book's result and optionally keep a human-readable note.
        if ok:
            self.succeeded += 1
        else:
            self.failed += 1
        if note:
            self.notes.append(note)


class PipelineStage:
    # Base class for a stage. Subclasses set `name`, `title` and implement
    # process_book(); run() handles the batch loop, banner and tally uniformly.
    name = "stage"
    title = "PIPELINE STAGE"

    def __init__(self, paths):
        self.paths = paths

    def banner(self, book_count):
        # Print the section header identical in spirit to the original steps.
        line = "=" * 70
        print(f"\n{line}\n{self.title}\nTotal books: {book_count}\n{line}")

    def process_book(self, book):
        # Process a single book; return True on success. Subclasses override.
        raise NotImplementedError

    def run(self, books):
        # Run the stage across every book, printing per-book progress and a
        # final tally, and returning a StageResult.
        self.banner(len(books))
        result = StageResult(self.name)
        for index, book in enumerate(books, 1):
            try:
                ok = self.process_book(book)
                result.record(bool(ok))
            except Exception as exc:
                print(f"       [FAIL] Error: {exc}")
                result.record(False, f"{book.stem}: {exc}")
        print(f"\n{self.title} finished: {result.succeeded} succeeded, {result.failed} failed.")
        return result

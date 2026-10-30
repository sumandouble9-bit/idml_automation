from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class StageResult:
    """Holds execution outcome and metrics for a workflow stage."""
    stage_name: str
    success: bool = True
    processed_count: int = 0
    failure_count: int = 0
    errors: List[str] = field(default_factory=list)

    def record(self, ok: bool, error_msg: str = ""):
        if ok:
            self.processed_count += 1
        else:
            self.failure_count += 1
            self.success = False
            if error_msg:
                self.errors.append(error_msg)


class WorkflowStage(ABC):
    """Abstract base class that all production workflow stages implement."""

    name: str = "base"
    title: str = "Base Workflow Stage"

    def __init__(self, paths):
        self.paths = paths

    def print_header(self, details: str = ""):
        line = "=" * 70
        print(f"\n{line}\n{self.title}")
        if details:
            print(details)
        print(line)

    @abstractmethod
    def run(self, books: list, force: bool = False) -> StageResult:
        """Executes this stage across a collection of books."""
        pass


class PipelineStage(WorkflowStage):
    """Helper subclass for stages that iterate book-by-book."""

    def process_book(self, book) -> bool:
        raise NotImplementedError

    def run(self, books: list, force: bool = False) -> StageResult:
        self.print_header()
        result = StageResult(self.name)
        for book in books:
            try:
                ok = self.process_book(book)
                result.record(ok)
            except Exception as exc:
                print(f"       [!] Error processing {book.stem}: {exc}")
                result.record(False, str(exc))
        return result

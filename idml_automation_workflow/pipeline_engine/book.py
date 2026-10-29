"""Book: one manuscript flowing through the pipeline."""

from dataclasses import dataclass
from pathlib import Path

from .config import get_language


@dataclass
class Book:
    # A single input IDML plus its detected language. `stem` is the shared base
    # name the per-stage output files are derived from.
    path: Path
    language_code: str

    @property
    def stem(self):
        # Base filename without extension, used to name all derived outputs.
        return self.path.stem

    @property
    def language(self):
        # The LanguageConfig for this book.
        return get_language(self.language_code)

    @property
    def display_language(self):
        # Human-readable language label for progress output.
        return self.language.display_name

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config.languages import get_language, LanguageConfig


@dataclass
class Book:
    """Encapsulates a single manuscript through all workflow stages.
    
    Provides convenient access to stage paths, metadata, ISBN extraction,
    and language-specific publishing configurations.
    """
    path: Path
    language_code: str = "en"
    epub_path: Optional[Path] = None

    @property
    def stem(self) -> str:
        """Base name of the input IDML without extension."""
        return self.path.stem

    @property
    def isbn(self) -> str:
        """Extracts the 10 or 13 digit ISBN from the filename or path."""
        m = re.search(r"\b(97[89]\d{10}|\d{9}[\dX])\b", self.stem)
        return m.group(1) if m else self.stem

    @property
    def language(self) -> LanguageConfig:
        """Language configuration and formatting rules for this book."""
        return get_language(self.language_code)

    @property
    def display_language(self) -> str:
        """Human-readable display name for console logging."""
        return self.language.display_name

    def is_spanish(self) -> bool:
        return self.language_code.lower() == "es"

    def is_english(self) -> bool:
        return self.language_code.lower() == "en"

    def has_epub(self) -> bool:
        return self.epub_path is not None and self.epub_path.is_file()

    def __repr__(self) -> str:
        return f"<Book {self.stem} ({self.display_language})>"

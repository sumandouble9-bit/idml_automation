"""BookDiscovery: identifies manuscripts and matches them with metadata and EPUB assets."""

from pathlib import Path
from typing import List, Optional

from .config import detect_language
from .models.book import Book


class BookDiscovery:
    """Discovers books in the input directory, identifies language, and matches EPUB assets."""

    def __init__(self, paths):
        self.paths = paths

    def _selection_candidates(self, only_book: str):
        clean = only_book.replace(".idml", "")
        candidates = {clean}
        try:
            from .core.isbn_manager import get_book_isbn_info
            info = get_book_isbn_info(clean)
            if info:
                for key in ("sp_epub_isbn", "sp_print_isbn", "sr_no"):
                    if info.get(key):
                        candidates.add(info[key])
        except Exception:
            pass
        return candidates

    def _find_epub(self, book_path: Path) -> Optional[Path]:
        stem = book_path.stem
        # Direct match: stem.epub
        direct = self.paths.epub_dir / f"{stem}.epub"
        if direct.is_file():
            return direct
        # ISBN match
        m = Book(book_path).isbn
        if m:
            by_isbn = self.paths.epub_dir / f"{m}.epub"
            if by_isbn.is_file():
                return by_isbn
        # Glob match
        for f in self.paths.epub_dir.glob("*.epub"):
            if m and m in f.name:
                return f
            if stem in f.name:
                return f
        return None

    def discover(
        self,
        only_book: Optional[str] = None,
        target_language: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Book]:
        idmls = sorted(
            f for f in self.paths.input_dir.glob("*.idml")
            if not f.name.startswith("~") and not f.name.startswith(".")
        )
        if only_book:
            candidates = self._selection_candidates(only_book)
            idmls = [b for b in idmls if any(c in b.stem for c in candidates)]

        books: List[Book] = []
        for path in idmls:
            language_code = detect_language(path)
            if target_language and language_code != target_language:
                continue
            epub_path = self._find_epub(path)
            books.append(Book(path=path, language_code=language_code, epub_path=epub_path))

        if limit and limit > 0:
            books = books[:limit]
        return books

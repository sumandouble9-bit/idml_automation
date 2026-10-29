"""BookDiscovery: find input IDMLs and tag each with its detected language.

Faithful port of get_all_books: optional single-book selection (expanded through
ISBN metadata), language filtering and an optional limit.
"""

from .book import Book
from .config import detect_language


class BookDiscovery:
    def __init__(self, paths):
        self.paths = paths

    def _selection_candidates(self, only_book):
        # Expand a requested book id into itself plus its known ISBN/serial aliases.
        clean = only_book.replace(".idml", "")
        candidates = {clean}
        try:
            from core.isbn_manager import get_book_isbn_info
            info = get_book_isbn_info(clean)
            if info:
                for key in ("sp_epub_isbn", "sp_print_isbn", "sr_no"):
                    if info.get(key):
                        candidates.add(info[key])
        except Exception:
            pass
        return candidates

    def discover(self, only_book=None, target_language=None, limit=None):
        # Return the ordered list of Books matching the selection/filters.
        idmls = sorted(
            f for f in self.paths.input_dir.glob("*.idml")
            if not f.name.startswith("~") and not f.name.startswith(".")
        )
        if only_book:
            candidates = self._selection_candidates(only_book)
            idmls = [b for b in idmls if any(c in b.stem for c in candidates)]

        books = []
        for path in idmls:
            language_code = detect_language(path)
            if target_language and language_code != target_language:
                continue
            books.append(Book(path=path, language_code=language_code))

        if limit and limit > 0:
            books = books[:limit]
        return books

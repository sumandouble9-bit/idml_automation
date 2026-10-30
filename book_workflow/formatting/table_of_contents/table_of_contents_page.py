from ..base_page import FormatPage


class TableOfContentsPage(FormatPage):
    report_key = "toc_page"
    progress_label = "[4/6] Formatting TOC Page (indexing, dot leaders, clean numbering)..."

    def apply(self, work_dir, reference_dir, book):
        # Spanish TOC also takes the book name (EPUB sync); English does not.
        if book.language_code == "es":
            from . import toc_page_es
            return toc_page_es.apply(work_dir, reference_dir, book_name=book.stem)
        from . import toc_page_en
        return toc_page_en.apply(work_dir, reference_dir)

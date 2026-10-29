"""AuthorPage: format the 'About the Author' page for any language."""

from ..base_page import FormatPage


class AuthorPage(FormatPage):
    report_key = "author_page"
    progress_label = "[5/6] Formatting About the Author Page..."

    def apply(self, work_dir, reference_dir, book):
        # Dispatch to the language's author-page implementation.
        if book.language_code == "es":
            from . import author_page_es
            return author_page_es.apply(work_dir, reference_dir)
        from . import author_page_en
        return author_page_en.apply(work_dir, reference_dir)

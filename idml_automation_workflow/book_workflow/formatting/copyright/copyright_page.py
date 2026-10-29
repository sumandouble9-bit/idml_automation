"""CopyrightPage: format the copyright page for any language."""

from ..base_page import FormatPage


class CopyrightPage(FormatPage):
    report_key = "copyright_page"
    progress_label = "[3/6] Formatting Copyright Page (dynamic ISBN/year)..."

    def apply(self, work_dir, reference_dir, book):
        # Dispatch to the language's copyright implementation, passing the name.
        if book.language_code == "es":
            from . import copyright_page_es
            return copyright_page_es.apply(work_dir, reference_dir, book_name=book.stem)
        from . import copyright_page_en
        return copyright_page_en.apply(work_dir, reference_dir, book_name=book.stem)

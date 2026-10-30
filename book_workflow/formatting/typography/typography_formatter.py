from ..base_page import FormatPage


class TypographyFormatter(FormatPage):
    report_key = "typography_and_styles"
    progress_label = "[6/6] Applying Typography, headings, body text, and character styles..."

    def apply(self, work_dir, reference_dir, book):
        # Dispatch to the language's typography implementation, passing the name.
        if book.language_code == "es":
            from . import typography_es
            return typography_es.apply(work_dir, reference_dir, book_name=book.stem)
        from . import typography_en
        return typography_en.apply(work_dir, reference_dir, book_name=book.stem)

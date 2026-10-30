from ..base_page import FormatPage


class TitlePage(FormatPage):
    report_key = "title_page"
    progress_label = "[2/6] Formatting Title Page..."

    def apply(self, work_dir, reference_dir, book):
        # Dispatch to the language's proven title-page implementation.
        if book.language_code == "es":
            from . import title_page_es
            return title_page_es.apply(work_dir, reference_dir)
        from . import title_page_en
        return title_page_en.apply(work_dir, reference_dir)

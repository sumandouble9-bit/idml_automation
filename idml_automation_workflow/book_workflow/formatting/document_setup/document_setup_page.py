"""DocumentSetupPage: trim size, margins, bleeds and master spreads.

Shared across every language (English and Spanish use the same document setup),
so there is no per-language branch here.
"""

from ..base_page import FormatPage


class DocumentSetupPage(FormatPage):
    report_key = "document_setup"
    progress_label = "[1/6] Setting book size, page margins, bleeds, and master spreads..."

    def apply(self, work_dir, reference_dir, book):
        # Apply the shared document setup to the extracted working folder.
        from . import document_setup_impl
        return document_setup_impl.apply(work_dir, reference_dir)

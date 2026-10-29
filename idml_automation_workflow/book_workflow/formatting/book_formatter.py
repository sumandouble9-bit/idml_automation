"""BookFormatter: OOP engine coordinating document typography and page-by-page layout."""

import json
import tempfile
import time
from pathlib import Path

from .author.author_page import AuthorPage
from .copyright.copyright_page import CopyrightPage
from .document_setup.document_setup_page import DocumentSetupPage
from .table_of_contents.table_of_contents_page import TableOfContentsPage
from .title.title_page import TitlePage
from .typography.typography_formatter import TypographyFormatter
from ..core import font_manager, epub_style_enricher, typography_postprocessor
from ..core.idml_utils import unzip, validate_zip, zipdir


class BookFormatter:
    """Orchestrates formatting stages: fonts -> document setup -> title -> copyright -> TOC -> author -> typography."""

    PAGE_SEQUENCE = (
        DocumentSetupPage,
        TitlePage,
        CopyrightPage,
        TableOfContentsPage,
        AuthorPage,
        TypographyFormatter,
    )

    def __init__(self, reference_file):
        self.reference_file = Path(reference_file)

    def format(self, book, output_path) -> dict:
        target = Path(book.path).resolve()
        reference = self.reference_file.resolve()
        output = Path(output_path).resolve()
        if not target.is_file():
            raise FileNotFoundError(f"Target IDML not found: {target}")
        if not reference.is_file():
            raise FileNotFoundError(f"Reference IDML not found: {reference}")

        output.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        report = {
            "target": str(target),
            "reference": str(reference),
            "output": str(output),
            "language": book.language_code,
            "stages": {},
        }

        with tempfile.TemporaryDirectory(prefix="idml_pipeline_") as tmp:
            tmp_path = Path(tmp)
            work_dir = tmp_path / "work"
            ref_dir = tmp_path / "ref"
            work_dir.mkdir()
            ref_dir.mkdir()

            unzip(target, work_dir)
            unzip(reference, ref_dir)

            print("  [0/6] Dynamically resolving, downloading, and bundling all document font families...")
            report["stages"]["font_manager"] = font_manager.resolve_idml_fonts_and_fallbacks(
                work_dir, output.parent
            )

            for page_class in self.PAGE_SEQUENCE:
                page = page_class()
                page.announce()
                report["stages"][page.report_key] = page.apply(work_dir, ref_dir, book)

            print("  [7/7] Enriching inline typography from EPUB (bold, italic, underline)...")
            report["stages"]["epub_enrichment"] = epub_style_enricher.enrich_extracted_idml(
                work_dir, book_name=target.stem, lang=book.language_code
            )

            zipdir(work_dir, output)
            zip_ok = validate_zip(output)
            report["zip_valid"] = zip_ok
            if not zip_ok:
                raise RuntimeError(f"Generated IDML failed ZIP validation: {output}")

            if book.language.runs_internal_typography_postprocess:
                try:
                    report["stages"]["typography_postprocessor"] = typography_postprocessor.postprocess_idml(output)
                except Exception as exc:
                    print(f"  Note: typography_postprocessor encountered: {exc}")

        report["elapsed_seconds"] = round(time.time() - start_time, 2)
        return report

"""Stage 1: Dual-Language Document Typography & Structural Formatting."""

from pathlib import Path
from .base_stage import PipelineStage, StageResult
from ..formatting.book_formatter import BookFormatter


class DocumentFormattingStage(PipelineStage):
    """Stage 1: Applies dual-language typography, page hierarchy, and structural formatting."""

    name = "formatting"
    title = "STEP 1: DUAL-LANGUAGE TYPOGRAPHY & STRUCTURAL FORMATTING"

    def _postprocessor_for(self, language_code: str):
        if language_code.lower() == "es":
            from ..formatting.typography.typography_postprocessor_es import postprocess_idml_es
            return postprocess_idml_es
        from ..core.typography_postprocessor import postprocess_idml as postprocess_idml_en
        return postprocess_idml_en

    def process_book(self, book) -> bool:
        self.paths.format_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.paths.format_dir / f"{book.stem}_formatted.idml"
        print(f"Formatting {book.display_language}: {book.path.name} -> {out_file.name}")

        BookFormatter(self.paths.reference_file).format(book, out_file)

        try:
            self._postprocessor_for(book.language_code)(out_file)
        except Exception as exc:
            print(f"       Note: postprocessor {exc}")

        try:
            from ..core.chapter_top_spacing import apply_chapter_top_spacing
            apply_chapter_top_spacing(out_file, out_file, sequence_pages=True, verbose=False)
        except Exception as exc:
            print(f"       Note: chapter spacing {exc}")

        print(f"       [OK] Success: {out_file.name}")
        return True


# Alias
FormattingStage = DocumentFormattingStage

"""FormattingStage: dual-language typography and structural formatting.

Runs the unified BookFormatter (one engine for every language), then applies the
language's external typography post-processor and chapter top spacing — exactly
the original run_step1_formatting sequence, now with no duplicated code path.
"""

from ..formatting import BookFormatter
from .base import PipelineStage


class FormattingStage(PipelineStage):
    name = "formatting"
    title = "STEP 2: DUAL-LANGUAGE TYPOGRAPHY & STRUCTURAL FORMATTING"

    def _postprocessor_for(self, language_code):
        # Return the external typography post-processor for a language (applied
        # after formatting, as the original step 1 did).
        if language_code == "es":
            from ..formatting.typography.typography_postprocessor_es import postprocess_idml_es
            return postprocess_idml_es
        from core.typography_postprocessor import postprocess_idml as postprocess_idml_en
        return postprocess_idml_en

    def process_book(self, book):
        # Format one book with the unified engine, then run its post-processor and
        # chapter top spacing.
        self.paths.format_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.paths.format_dir / f"{book.stem}_formatted.idml"
        print(f"Formatting {book.display_language}: {book.path.name} -> {out_file.name}")

        BookFormatter(self.paths.reference_file).format(book, out_file)

        try:
            self._postprocessor_for(book.language_code)(out_file)
        except Exception as exc:
            print(f"       Note: postprocessor {exc}")

        try:
            from core.chapter_top_spacing import apply_chapter_top_spacing
            apply_chapter_top_spacing(out_file, out_file, sequence_pages=True, verbose=False)
        except Exception as exc:
            print(f"       Note: chapter spacing {exc}")

        print(f"       [OK] Success: {out_file.name}")
        return True

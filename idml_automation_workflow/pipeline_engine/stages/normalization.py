"""NormalizationStage: enforce trim size, margins and bleeds (5.5x8.5 in).

Wraps the proven normalize_document_setup.normalize_one_file. Unchanged from
run_step2_normalization, including the fallback to the raw book when the
formatted file is missing.
"""

from .base import PipelineStage


class NormalizationStage(PipelineStage):
    name = "normalization"
    title = "STEP 1: DOCUMENT SETUP NORMALIZATION (5.5x8.5 in, Margins, Bleeds)"

    def process_book(self, book):
        # Normalize one book's document setup, reading the formatted file when
        # present and otherwise the raw input, writing *_normalized.idml.
        self.paths.norm_dir.mkdir(parents=True, exist_ok=True)
        in_file = self.paths.format_dir / f"{book.stem}_formatted.idml"
        if not in_file.exists():
            in_file = book.path
        out_file = self.paths.norm_dir / f"{book.stem}_normalized.idml"
        print(f"Normalizing: {in_file.name} -> {out_file.name}")

        from ..formatting.document_setup import normalize_document_setup
        normalize_document_setup.normalize_one_file(str(in_file), str(out_file))
        print(f"       [OK] Success: {out_file.name}")
        return True

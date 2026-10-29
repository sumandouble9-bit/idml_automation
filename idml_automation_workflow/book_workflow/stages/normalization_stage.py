"""Stage 2: Document Setup Normalization (Trim size, Margins, Bleeds)."""

from pathlib import Path
from .base_stage import PipelineStage


class DocumentNormalizationStage(PipelineStage):
    """Stage 2: Enforces 5.5 x 8.5 in trim size, standard margins, bleeds, and master spreads."""

    name = "normalization"
    title = "STEP 2: DOCUMENT SETUP NORMALIZATION (5.5x8.5 in, Margins, Bleeds)"

    def process_book(self, book) -> bool:
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


# Alias
NormalizationStage = DocumentNormalizationStage

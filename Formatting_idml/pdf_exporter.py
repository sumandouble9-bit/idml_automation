"""
Formatting_idml: PdfExporter
Facade uniting InDesign COM automation, PDF validation quality gates,
and high-resolution preview rendering.
Follows Single Responsibility and Dependency Inversion principles by delegating
COM automation to InDesignRunner and quality checks to Validator.
"""

from pathlib import Path
from typing import List, Optional, Tuple

from bridge.indesign_runner import InDesignRunner
from validate.validator import Validator


class PdfExporter:
    """
    Coordinates PDF generation, validation, and preview rendering:
    - Delegates InDesign COM automation to InDesignRunner
    - Delegates quality-gate assertions to Validator
    - Renders high-resolution PNG spreads for visual review
    """

    def __init__(
        self,
        bridge: Optional[InDesignRunner] = None,
        validator: Optional[Validator] = None,
        version_str: str = "InDesign.Application",
        default_preset: str = "[PDF/X-1a:2001]"
    ):
        self.bridge = bridge or InDesignRunner(version_str=version_str)
        self.validator = validator or Validator()
        self.default_preset = default_preset

    @staticmethod
    def clear_recovery_data():
        """Purges InDesign automatic recovery files (delegated to bridge)."""
        InDesignRunner.clear_recovery_data()

    def get_app(self):
        """Gets or restarts a clean InDesign COM instance (delegated to bridge)."""
        return self.bridge.get_app()

    def export(self, idml_path: str, output_pdf_path: str, logo_path: Optional[str] = None) -> bool:
        """
        Executes InDesign layout repair, autoflows stories, applies adaptive image sizing,
        and exports high-quality print PDF/X with two-page facing spreads.
        """
        return self.bridge.export_pdf(idml_path, output_pdf_path, logo_path=logo_path)

    def validate_pdf(self, pdf_path: str) -> Tuple[bool, List[str]]:
        """
        Validates exported PDF using polymorphic quality rules from the validate engine.
        Asserts image clarity, visibility thresholds, and absence of dead white space.
        """
        passed, report = self.validator.validate_pdf(pdf_path)
        flat_errors: List[str] = []
        for errors in report.values():
            flat_errors.extend(errors)
        return passed, flat_errors

    def render_spread_previews(
        self,
        pdf_path: str,
        page_numbers: List[int],
        output_dir: str,
        dpi: int = 144
    ) -> List[Path]:
        """
        Renders selected pages to crisp PNG images for immediate visual inspection.
        """
        try:
            import pymupdf
        except ImportError:
            try:
                import fitz as pymupdf
            except ImportError:
                raise ImportError("PyMuPDF (pymupdf) is required for preview rendering.")

        doc = pymupdf.open(pdf_path)
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        rendered: List[Path] = []

        scale = dpi / 72.0
        matrix = pymupdf.Matrix(scale, scale)

        for p_num in page_numbers:
            if 1 <= p_num <= len(doc):
                page = doc[p_num - 1]
                pix = page.get_pixmap(matrix=matrix)
                target = out_path / f"page_{p_num}_preview.png"
                pix.save(str(target))
                rendered.append(target)

        return rendered

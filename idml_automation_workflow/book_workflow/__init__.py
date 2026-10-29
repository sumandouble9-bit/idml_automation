"""Book Workflow: An automated, modular, object-oriented publishing engine for IDML & InDesign.

Transforms raw IDML manuscript exports into standardized, beautifully typeset, print-ready PDFs.
"""

__version__ = "2.0.0"

from .workflow import BookWorkflow, Pipeline, main
from .models.book import Book
from .paths import WorkflowPaths, ProjectPaths
from .stages import (
    WorkflowStage,
    DocumentFormattingStage,
    DocumentNormalizationStage,
    AssetInjectionStage,
    QualityAuditAndExportStage,
)

__all__ = [
    "BookWorkflow",
    "Pipeline",
    "Book",
    "WorkflowPaths",
    "ProjectPaths",
    "WorkflowStage",
    "DocumentFormattingStage",
    "DocumentNormalizationStage",
    "AssetInjectionStage",
    "QualityAuditAndExportStage",
    "main",
]

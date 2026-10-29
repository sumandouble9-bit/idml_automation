"""WorkflowPaths: single source of truth for all project directories and deliverables."""

import sys
from pathlib import Path


class WorkflowPaths:
    """Manages input, intermediate, and final output directories for the publishing engine."""

    def __init__(self, workflow_dir=None):
        self.workflow_dir = Path(workflow_dir) if workflow_dir else Path(__file__).resolve().parent.parent
        self.repo_dir = self.workflow_dir.parent
        self.package_dir = self.workflow_dir / "book_workflow"
        self.core_dir = self.package_dir / "core"
        self.scripts_dir = self.workflow_dir / "Scripts"
        self.injection_dir = self.workflow_dir / "injection"
        self.table_dir = self.workflow_dir / "table"

        self.input_dir = self._first_existing_with_idml([
            self.repo_dir / "idml_input_files",
            self.workflow_dir / "idml_input_files",
            self.repo_dir / "input_files",
            self.workflow_dir / "input_files",
            self.repo_dir / "Input",
        ], default=self.repo_dir / "input_files")

        self.epub_dir = self._first_existing_with_glob([
            self.repo_dir / "epub_input_files",
            self.workflow_dir / "epub_input_files",
        ], pattern="*.epub", default=self.repo_dir / "epub_input_files")

        self.reference_file = self._resolve_reference()

        # Intermediate output directories
        self.format_dir = self.workflow_dir / "Output" / "Formatted"
        self.norm_dir = self.workflow_dir / "Output" / "page_resize_output"

        # Final deliverable directories
        self.final_output_root = self.workflow_dir / "final_output_files"
        self.final_idml_dir = self.final_output_root / "idml_files"
        self.final_pdf_dir = self.final_output_root / "pdf_files"
        self.renamed_out_dir = self.final_output_root / "renamed_output_files"

    @staticmethod
    def _first_existing_with_idml(candidates, default):
        for cand in candidates:
            if cand.is_dir() and any(cand.glob("*.idml")):
                return cand
        return default

    @staticmethod
    def _first_existing_with_glob(candidates, pattern, default):
        for cand in candidates:
            if cand.is_dir() and any(cand.glob(pattern)):
                return cand
        return default

    def _resolve_reference(self):
        for ref_dir in (self.workflow_dir / "Reference", self.repo_dir / "Reference"):
            if ref_dir.is_dir():
                refs = sorted(ref_dir.glob("*.idml"))
                chosen = next((r for r in refs if "MIS" in r.name.upper()), refs[0] if refs else None)
                if chosen:
                    return chosen
        return self.workflow_dir / "Reference" / "11671 LES MISÉRABLES.idml"

    def register_on_syspath(self):
        """Ensures all module directories are importable across scripts."""
        for path in (
            self.workflow_dir,
            self.package_dir,
            self.core_dir,
            self.scripts_dir,
            self.injection_dir,
            self.table_dir,
        ):
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)
        return self


# Backward compatibility alias
ProjectPaths = WorkflowPaths

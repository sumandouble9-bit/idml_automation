"""ProjectPaths: one place that resolves every directory the pipeline uses.

Reproduces the dynamic input/epub/reference/output resolution that lived at the
top of run_unified_dual_pipeline.py, and registers the script packages on
sys.path so the proven stage implementations stay importable.
"""

import sys
from pathlib import Path


class ProjectPaths:
    # Resolved, cached locations for inputs, intermediate outputs and the script
    # packages. Construct once and pass to the pipeline/stages.
    def __init__(self, workflow_dir=None):
        self.workflow_dir = Path(workflow_dir) if workflow_dir else Path(__file__).resolve().parent.parent
        self.repo_dir = self.workflow_dir.parent
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

        self.format_dir = self.workflow_dir / "Output" / "Formatted"
        self.norm_dir = self.workflow_dir / "Output" / "page_resize_output"
        self.final_output_root = self.workflow_dir / "final_output_files"
        self.final_idml_dir = self.final_output_root / "idml_files"
        self.final_pdf_dir = self.final_output_root / "pdf_files"
        self.renamed_out_dir = self.final_output_root / "renamed_output_files"

    @staticmethod
    def _first_existing_with_idml(candidates, default):
        # First candidate directory that exists and contains at least one IDML.
        for cand in candidates:
            if cand.is_dir() and any(cand.glob("*.idml")):
                return cand
        return default

    @staticmethod
    def _first_existing_with_glob(candidates, pattern, default):
        # First candidate directory that exists and matches the given glob.
        for cand in candidates:
            if cand.is_dir() and any(cand.glob(pattern)):
                return cand
        return default

    def _resolve_reference(self):
        # Prefer a reference IDML whose name contains "MIS"; else the first found.
        for ref_dir in (self.workflow_dir / "Reference", self.repo_dir / "Reference"):
            if ref_dir.is_dir():
                refs = sorted(ref_dir.glob("*.idml"))
                chosen = next((r for r in refs if "MIS" in r.name.upper()), refs[0] if refs else None)
                if chosen:
                    return chosen
        return self.workflow_dir / "Reference" / "11671 LES MISÉRABLES.idml"

    def register_on_syspath(self):
        # Put the workflow and script packages on sys.path so the proven stage
        # implementations (pipeline engine, core.*, injection, table) import.
        for path in (self.workflow_dir, self.scripts_dir, self.injection_dir, self.table_dir):
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)
        return self

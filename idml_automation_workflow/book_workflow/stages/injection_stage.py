"""Stage 3: EPUB Asset, Image & Caption Injection via Adobe InDesign."""

import os
import subprocess
import sys
from pathlib import Path

from .base_stage import WorkflowStage, StageResult


class AssetInjectionStage(WorkflowStage):
    """Stage 3: Injects figures, images, and captions from EPUB, resolves overset, and fills gaps."""

    name = "injection"
    title = "STEP 3: EPUB ASSET, IMAGE & CAPTION INJECTION (via Adobe InDesign)"

    def _logo_path(self) -> str:
        candidates = (
            self.paths.workflow_dir / "logo" / "LEAF-BOUND-trimmed.png",
            self.paths.workflow_dir / "logo" / "LEAF-BOUND.png",
            self.paths.repo_dir / "input_files" / "logo" / "LEAF-BOUND-trimmed.png",
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return ""

    def inject(self, books, force=False) -> int:
        self.paths.final_idml_dir.mkdir(parents=True, exist_ok=True)
        self.print_header(
            f"Input directory:  {self.paths.norm_dir}\n"
            f"EPUB directory:   {self.paths.epub_dir}\n"
            f"Output directory: {self.paths.final_idml_dir}"
        )

        env = dict(os.environ)
        env["INJECT_INPUT"] = str(self.paths.norm_dir)
        env["INJECT_OUTBASE"] = str(self.paths.final_output_root)
        env["EPUB_DIR"] = str(self.paths.epub_dir)
        logo = self._logo_path()
        if logo:
            env["LOGO_PATH"] = logo
        env["INJECT_ONLY"] = ",".join(f"{book.stem}_normalized.idml" for book in books)
        if force:
            env["INJECT_FORCE"] = "1"

        script = self.paths.injection_dir / "inject_with_epub_captions.py"
        result = subprocess.run([sys.executable, "-u", str(script)], env=env)
        return result.returncode

    def fix_chapter_double_breaks(self, books):
        line = "=" * 70
        print(f"\n{line}\nSTEP 3d: CHAPTER DOUBLE-BREAK FIX (remove blank page before body chapters)")
        print(f"Target directory: {self.paths.final_idml_dir}\n{line}")

        from ..core.chapter_break_fix import apply_to_idml as fix_chapter_breaks
        stems = {book.stem for book in books}
        targets = [f for f in self.paths.final_idml_dir.glob("*_injected.idml")
                   if any(stem in f.name for stem in stems)]
        for idml in targets:
            try:
                fixed = fix_chapter_breaks(idml)
                print(f"  {idml.name}: chapter double-break fixed={fixed}")
            except Exception as exc:
                print(f"  {idml.name}: [!] chapter break fix failed: {exc}")

    def fill_bottom_gaps(self, books):
        line = "=" * 70
        print(f"\n{line}\nSTEP 3b: TEXT BOTTOM-GAP FILLING (Reflow body lines down to bottom margin)")
        print(f"Input/Output: {self.paths.final_idml_dir}\n{line}")

        env = dict(os.environ)
        env["GAPFIX_INPUT"] = str(self.paths.final_idml_dir)
        env["GAPFIX_OUTPUT"] = str(self.paths.final_idml_dir)
        script = self.paths.workflow_dir / "fix_text_bottom_gap.py"
        for book in books:
            print(f"  Fixing bottom gap for: {book.stem}")
            subprocess.run([sys.executable, "-u", str(script), book.stem], env=env)

    def run(self, books: list, force: bool = False) -> StageResult:
        result = StageResult(self.name)
        code = self.inject(books, force=force)
        result.record(code == 0)
        self.fix_chapter_double_breaks(books)
        self.fill_bottom_gaps(books)
        return result


# Alias
InjectionStage = AssetInjectionStage

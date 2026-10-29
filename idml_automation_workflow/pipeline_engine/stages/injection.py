"""InjectionStage: EPUB image & caption injection plus post-injection fixes.

Faithfully reproduces run_step3_injection (image/caption injection via a
subprocess that drives InDesign), run_step3d (chapter double-break fix) and
run_step3b (text bottom-gap fill). Operates on the whole batch at once, so it
overrides run() instead of the per-book loop.
"""

import os
import subprocess
import sys

from .base import StageResult


class InjectionStage:
    name = "injection"
    title = "STEP 3: EPUB IMAGE & CAPTION INJECTION (via Adobe InDesign)"

    def __init__(self, paths):
        self.paths = paths

    def _logo_path(self):
        # First existing publisher-logo candidate, matching the original order.
        candidates = (
            self.paths.workflow_dir / "logo" / "LEAF-BOUND-trimmed.png",
            self.paths.workflow_dir / "logo" / "LEAF-BOUND.png",
            self.paths.repo_dir / "input_files" / "logo" / "LEAF-BOUND-trimmed.png",
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return ""

    def inject(self, books, force=False):
        # Run the image/caption injection subprocess for the batch of books.
        self.paths.final_idml_dir.mkdir(parents=True, exist_ok=True)
        line = "=" * 70
        print(f"\n{line}\n{self.title}")
        print(f"Input directory:  {self.paths.norm_dir}")
        print(f"EPUB directory:   {self.paths.epub_dir}")
        print(f"Output directory: {self.paths.final_idml_dir}\n{line}")

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
        # Remove the blank page before body chapters on the injected IDMLs.
        line = "=" * 70
        print(f"\n{line}\nSTEP 3d: CHAPTER DOUBLE-BREAK FIX (remove blank page before body chapters)")
        print(f"Target directory: {self.paths.final_idml_dir}\n{line}")

        from core.chapter_break_fix import apply_to_idml as fix_chapter_breaks
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
        # Reflow body text down to the bottom margin on each injected IDML.
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

    def run(self, books, force=False):
        # Inject images/captions, then apply the chapter-break and gap-fill fixes.
        result = StageResult(self.name)
        code = self.inject(books, force=force)
        result.record(code == 0)
        self.fix_chapter_double_breaks(books)
        self.fill_bottom_gaps(books)
        return result

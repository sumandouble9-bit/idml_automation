"""Stage 4: Quality Audit Gate, TOC Sync & Print PDF Export via InDesign."""

import shutil
import sys
import zipfile
from pathlib import Path

from .base_stage import WorkflowStage, StageResult


class QualityAuditAndExportStage(WorkflowStage):
    """Stage 4: Audits document integrity, exports print-quality PDF, and syncs TOC numbers."""

    name = "export"
    title = "STEP 4: HIGH-QUALITY PRINT PDF EXPORT & QUALITY AUDIT (via Adobe InDesign)"

    def _target_idmls(self, stems):
        injected = [f for f in self.paths.final_idml_dir.glob("*_injected.idml")
                    if any(stem in f.name for stem in stems)]
        if injected:
            return injected
        normalized = [f for f in self.paths.norm_dir.glob("*_normalized.idml")
                      if any(stem in f.name for stem in stems)]
        if normalized:
            return normalized
        return [f for f in self.paths.format_dir.glob("*_formatted.idml")
                if any(stem in f.name for stem in stems)]

    def _caption_map(self, isbn: str):
        epub = self.paths.epub_dir / f"{isbn}.epub"
        if not epub.exists():
            return {}
        try:
            from ..core import epub_tools
            return epub_tools.build_caption_map(str(epub))
        except Exception:
            try:
                import epub_tools
                return epub_tools.build_caption_map(str(epub))
            except Exception:
                return {}

    def _audit(self, doc: Path, isbn: str, caption_map: dict):
        reasons = []
        source = self.paths.input_dir / f"{isbn}.idml"
        if not (source.exists() and "_injected" in doc.name):
            return reasons

        try:
            import check_missing_paragraphs
            reasons.extend(check_missing_paragraphs.check(str(source), str(doc), caption_map))
        except Exception as exc:
            print(f"  [warn] paragraph check skipped for {isbn}: {exc}")

        try:
            placeholders = 0
            with zipfile.ZipFile(str(doc)) as archive:
                for name in archive.namelist():
                    if name.startswith("Stories/") and name.endswith(".xml"):
                        placeholders += archive.read(name).decode("utf-8", "replace").count("###Insert")
            if placeholders:
                reasons.append(f"MISSING_IMAGES: {placeholders} placeholder(s) left unplaced")
        except Exception as exc:
            print(f"  [warn] image-placeholder check skipped for {isbn}: {exc}")

        try:
            import check_sidebyside
            ok, detail = check_sidebyside.check(str(source), str(doc))
            if not ok:
                reasons.append("SIDEBYSIDE not side-by-side: " + detail)
        except Exception as exc:
            print(f"  [warn] side-by-side check skipped for {isbn}: {exc}")

        try:
            import check_word_spacing_and_block
            reasons.extend(check_word_spacing_and_block.check(str(doc)))
        except Exception as exc:
            print(f"  [warn] word-spacing/block check skipped for {isbn}: {exc}")

        try:
            import check_caption
            reasons.extend(check_caption.check(str(doc), caption_map))
        except Exception as exc:
            print(f"  [warn] caption check skipped for {isbn}: {exc}")

        return reasons

    def _reject(self, doc: Path, isbn: str, reasons: list, reject_dir: Path) -> Path:
        reject_dir.mkdir(parents=True, exist_ok=True)
        try:
            from ..core.isbn_manager import get_output_base_name
            dest = reject_dir / f"{get_output_base_name(isbn)}.idml"
        except Exception:
            dest = reject_dir / doc.name

        shutil.move(str(doc), str(dest))
        with open(str(dest) + ".reasons.txt", "w", encoding="utf-8") as handle:
            handle.write("\n".join(["REJECTED:"] + list(reasons)))
        print(f"  [REJECT] {isbn}: {reasons[0][:90]} -> rejected_files/ (PDF still generated)")
        return dest

    def _register_check_paths(self):
        for path in (self.paths.workflow_dir / "test_cases", self.paths.injection_dir):
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)

    def run(self, books: list, force: bool = False) -> StageResult:
        result = StageResult(self.name)
        try:
            import convert_to_pdf
        except ImportError:
            from ..core import pdf_export as convert_to_pdf

        self.paths.final_pdf_dir.mkdir(parents=True, exist_ok=True)
        self.print_header(
            f"Source IDMLs:  {self.paths.final_idml_dir}\n"
            f"PDF Directory: {self.paths.final_pdf_dir}"
        )

        stems = {book.stem for book in books}
        target_idmls = self._target_idmls(stems)

        self._register_check_paths()
        reject_dir = self.paths.final_output_root / "rejected_files" / "idml_files"
        kept, rejected = [], []
        for doc in target_idmls:
            isbn = doc.stem.replace("_injected", "").replace("_normalized", "").replace("_formatted", "")
            caption_map = self._caption_map(isbn)
            reasons = self._audit(doc, isbn, caption_map)
            if reasons:
                try:
                    rejected.append(self._reject(doc, isbn, reasons, reject_dir))
                except Exception as exc:
                    print(f"  [warn] could not move rejected {isbn}: {exc}")
            else:
                kept.append(doc)
        target_idmls = kept

        if target_idmls:
            print(f"Exporting {len(target_idmls)} IDML document(s) to PDF...")
            for doc in target_idmls:
                convert_to_pdf.convert_batch(target_path=str(doc), output_dir=str(self.paths.final_pdf_dir), force=force)
                result.record(True)
        else:
            print("No books passed the integrity gate; exporting rejected books only.")

        if rejected:
            reject_pdf = self.paths.final_output_root / "rejected_files" / "pdf_files"
            reject_pdf.mkdir(parents=True, exist_ok=True)
            print(f"Exporting {len(rejected)} REJECTED document(s) to rejected_files/pdf_files for review...")
            for doc in rejected:
                try:
                    convert_to_pdf.convert_batch(target_path=str(doc), output_dir=str(reject_pdf), force=force)
                except Exception as exc:
                    print(f"  [warn] could not export rejected PDF {doc.name}: {exc}")

        if not target_idmls:
            return result

        self._sync_toc_and_rename(target_idmls, convert_to_pdf, force)
        print("\nStep 4 Complete! Verified PDF and IDML files available in:", self.paths.final_pdf_dir)
        return result

    def _sync_toc_and_rename(self, target_idmls, convert_to_pdf, force):
        from ..core.toc_synchronizer import sync_idml_toc_from_pdf
        from ..core.isbn_manager import get_output_base_name

        print("\nVerifying TOC page synchronization against generated PDFs...")
        for idml in target_idmls:
            clean_stem = idml.stem.replace("_injected", "").replace("_normalized", "").replace("_formatted", "")
            base_out = get_output_base_name(clean_stem)
            pdf_candidates = [
                self.paths.final_pdf_dir / f"{base_out}.pdf",
                self.paths.final_pdf_dir / f"{clean_stem}.pdf",
                self.paths.final_pdf_dir / f"{idml.stem}.pdf",
            ]
            pdf = next((p for p in pdf_candidates if p.exists()), None)
            if pdf:
                synced = sync_idml_toc_from_pdf(idml, pdf)
                if synced > 0:
                    print(f"  [TOC Sync] Synchronized {synced} TOC entry(ies) in {idml.name}. Refreshing final PDF...")
                    convert_to_pdf.convert_batch(target_path=str(idml), output_dir=str(self.paths.final_pdf_dir), force=True)
                else:
                    print(f"  [TOC Verified] {idml.name} TOC is 100% in sync with {pdf.name}.")
            if base_out:
                renamed_dir = self.paths.final_output_root / "renamed_output_files"
                renamed_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(idml, renamed_dir / f"{base_out}.idml")
                print(f"  [Renamed IDML] Saved {base_out}.idml into renamed_output_files/")


# Alias
ExportStage = QualityAuditAndExportStage

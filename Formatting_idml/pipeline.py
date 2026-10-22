"""
Formatting_idml: Master Pipeline
Clean, organized, OOP facade uniting all Formatting_idml components:
EpubParser, CaptionInjector, ImageLayoutManager, TextStyleNormalizer, and ChapterProcessor.
Supports isolated chapter-by-chapter iteration and full-book execution.
"""

import sys
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

from package.idml_package import IDMLPackage
from model.document import DocumentModel
from setup.style_transfer import StyleTransfer
from setup.doc_setup import DocSetup
from Formatting_idml.epub_parser import EpubParser, EpubFormattingMap
from Formatting_idml.caption_injector import CaptionInjector
from Formatting_idml.image_layout_manager import ImageLayoutManager
from Formatting_idml.text_style_normalizer import TextStyleNormalizer
from Formatting_idml.chapter_processor import ChapterProcessor, ChapterInfo


class FormattingIDMLPipeline:
    """
    1st Module: Formatting_idml
    Clean, OOP orchestrator for formatting IDML books with EPUB-grounded styling,
    table preservation, adaptive image injection, and chapter-wise reporting.
    """

    def __init__(self, book_id: str, workspace_root: Optional[str] = None):
        self.book_id = book_id
        self.root = Path(workspace_root).resolve() if workspace_root else Path(__file__).parent.parent.resolve()

        self.input_idml = self.root / "idml_input_files" / f"{book_id}.idml"
        if not self.input_idml.exists():
            # Check direct path
            self.input_idml = Path(book_id).resolve()

        self.matching_epub = self.root / "epub_input_files" / f"{self.input_idml.stem}.epub"
        self.output_base = self.root / "output_files" / self.input_idml.stem
        self.output_base.mkdir(parents=True, exist_ok=True)
        self.work_dir = self.output_base / f"work_{self.input_idml.stem}"

        self.donor_idml = self.root / "reference_idml_files" / "reference_donor.idml"
        self.logo_path = self.root / "logo" / "LEAF-BOUND-trimmed.png"

        # Initialize OOP components
        self.chapter_processor = ChapterProcessor()
        self.normalizer = TextStyleNormalizer()
        self.layout_manager = ImageLayoutManager()

        self.pkg: Optional[IDMLPackage] = None
        self.doc: Optional[DocumentModel] = None
        self.fmap: Optional[EpubFormattingMap] = None
        self.image_map: Dict[str, Path] = {}

    def setup_environment(self):
        """Unpacks IDML package and loads object model."""
        print(f"\n[Step 1] Initializing IDML Object Model: {self.input_idml.name}...")
        self.pkg = IDMLPackage(str(self.input_idml))
        self.pkg.unpack(self.work_dir)
        self.doc = DocumentModel(self.pkg)
        self.doc.load()
        print(f"         Loaded {len(self.doc.stories)} stories and {len(self.doc.spreads)} spreads.")

        # Parse EPUB if available
        if self.matching_epub.exists():
            print(f"[Step 2] Parsing EPUB for authoritative styling and assets: {self.matching_epub.name}...")
            parser = EpubParser(str(self.matching_epub))
            assets_dir = self.output_base / f"{self.input_idml.stem}_assets"
            self.image_map = parser.extract_assets(str(assets_dir))
            self.fmap = parser.parse_formatting()
            print(f"         Extracted {len(self.image_map)} images.")
            print(f"         Extracted {len(self.fmap.captions)} captions, {len(self.fmap.italic_phrases)} italic phrases, "
                  f"{len(self.fmap.bold_phrases)} bold phrases, {self.fmap.table_count} tables.")
        else:
            print(f"[Step 2] No matching EPUB found at {self.matching_epub.name}; using default styles.")
            self.fmap = EpubFormattingMap()

    def apply_geometry_and_styles(self):
        """Applies page geometry, margins, and catalog styles from reference donor."""
        print(f"[Step 3] Applying page geometry and reference catalog styles...")
        if self.donor_idml.exists() and self.doc.styles_root is not None:
            style_transfer = StyleTransfer(str(self.donor_idml))
            style_transfer.sync_fonts(self.work_dir)
            updated, added = style_transfer.apply(self.doc.styles_root)
            print(f"         Transferred {updated} updated styles and {added} catalog styles.")

        doc_setup = DocSetup()
        if self.doc.preferences_root is not None:
            doc_setup.apply_preferences(self.doc.preferences_root)

        for spread_dir in [self.work_dir / "Spreads", self.work_dir / "MasterSpreads"]:
            if spread_dir.exists():
                for sp in spread_dir.glob("*.xml"):
                    with open(sp, "r", encoding="utf-8") as f:
                        content = f.read()
                    with open(sp, "w", encoding="utf-8") as f:
                        f.write(doc_setup.normalize_spread_xml(content))

    def format_story_content(self, chapter_num: Optional[int] = None):
        """
        Executes normalization across stories:
        - Removes redundant chapter page breaks
        - Remaps paragraph styles (strictly preserving tables)
        - Maps authoritative EPUB bold/italic/underline styling
        - Preserves table cells, bold headers, and font sizes
        - Splits packed placeholders and injects structured image tokens
        - Strips manual Word overrides
        - Merges character runs safely
        """
        target_label = f"Chapter {chapter_num}" if chapter_num else "Full Book (All Chapters)"
        print(f"\n[Step 4] Formatting Story Typography & Tables ({target_label})...")

        # Scope indices if chapter_num is provided
        target_chapter: Optional[ChapterInfo] = None
        if chapter_num:
            target_chapter = self.chapter_processor.get_chapter_by_number(self.doc, chapter_num)
            if not target_chapter:
                print(f"[ERROR] Chapter {chapter_num} not found!")
                return

        caption_injector = CaptionInjector(
            caption_map=self.fmap.captions if self.fmap else {},
            caption_style_map=self.fmap.caption_styles if self.fmap else {}
        )

        total_breaks = 0
        total_remapped = 0
        total_epub_styled = 0
        total_tables_preserved = 0
        total_images_resolved = 0
        total_overrides_stripped = 0
        total_runs_merged = 0

        for s_name, story in self.doc.stories.items():
            scope_range = None
            if target_chapter:
                if s_name != target_chapter.story_name:
                    continue
                scope_range = range(target_chapter.start_para_idx, target_chapter.end_para_idx)

            # 1. Remove redundant empty page-break paragraphs before headings
            total_breaks += self.normalizer.remove_redundant_chapter_page_breaks(story)

            # 2. Remap paragraph styles (strictly protecting table cells)
            total_remapped += self.normalizer.remap_paragraph_styles(story, scope_indices=scope_range)

            # 3. Map authoritative EPUB bold/italic/underline inline styling
            if self.fmap:
                total_epub_styled += self.normalizer.map_epub_formatting(story, self.fmap)

            # 4. Strictly preserve table cells, bold headers, and font sizes
            total_tables_preserved += self.normalizer.preserve_table_formatting(story)

            # 5. Split packed image placeholders
            caption_injector.split_packed_placeholders(story)

            # 6. Inject atomic image tokens with EPUB captions attached
            total_images_resolved += caption_injector.process_story(story, self.image_map)

            # 7. Strip manual Word overrides on body text (protecting tables and styles)
            total_overrides_stripped += self.normalizer.strip_body_overrides(story, scope_indices=scope_range)

            # 8. Merge adjacent identical runs safely (with table/footnote protection)
            total_runs_merged += self.normalizer.merge_character_runs_safely(story)

        print(f"         Removed {total_breaks} redundant empty chapter page-breaks.")
        print(f"         Remapped {total_remapped} paragraph ranges.")
        print(f"         Mapped {total_epub_styled} bold/italic/underline styling runs from EPUB.")
        print(f"         Preserved {total_tables_preserved} table cells with exact font styles & sizes.")
        print(f"         Resolved {total_images_resolved} image tokens with atomic captions.")
        print(f"         Stripped {total_overrides_stripped} manual Word formatting overrides.")
        print(f"         Merged {total_runs_merged} character runs.")

        # Save document XML
        self.doc.save()

    def pack_and_export(self, skip_jsx: bool = False) -> Path:
        """Packs modified IDML and triggers InDesign PDF/X export."""
        output_idml = self.output_base / f"{self.input_idml.stem}_formatted.idml"
        self.pkg.pack(str(output_idml))
        print(f"\n[Step 5] Formatted IDML saved to: {output_idml}")

        if not skip_jsx:
            from Formatting_idml.pdf_exporter import PdfExporter
            print(f"\n[Step 6] Triggering InDesign Layout Repair & PDF/X Export via PdfExporter...")
            exporter = PdfExporter()
            output_pdf = self.output_base / f"{self.input_idml.stem}_print.pdf"
            success = exporter.export(str(output_idml), str(output_pdf), logo_path=str(self.logo_path) if self.logo_path.exists() else None)
            if success:
                print(f"         [PASS] PDF/X Exported to: {output_pdf}")
                print(f"\n[Step 7] Running Post-Layout PDF Quality Validation...")
                passed, errors = exporter.validate_pdf(str(output_pdf))
                if passed:
                    print(f"         [PASS] All PDF quality gates PASSED! (Images clear, zero dead white space)")
                else:
                    print(f"         [WARN] PDF validation warnings: {errors[:3]}")
            return output_pdf
        return output_idml

    def run_chapter(self, chapter_num: int, skip_jsx: bool = True):
        """Runs isolated chapter formatting for quick inspection and debugging."""
        self.setup_environment()
        self.chapter_processor.print_chapter_manifest(self.doc)
        self.apply_geometry_and_styles()
        self.format_story_content(chapter_num=chapter_num)
        return self.pack_and_export(skip_jsx=skip_jsx)

    def run_all(self, skip_jsx: bool = False):
        """Runs formatting for the full book across all chapters."""
        self.setup_environment()
        self.chapter_processor.print_chapter_manifest(self.doc)
        self.apply_geometry_and_styles()
        self.format_story_content(chapter_num=None)
        return self.pack_and_export(skip_jsx=skip_jsx)

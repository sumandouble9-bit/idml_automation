"""
Formatting_idml: ChapterProcessor
OOP coordinator for chapter-by-chapter discovery, isolated chapter execution,
and structured chapter-wise metrics reporting.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from model.document import DocumentModel
from model.story import StoryModel


@dataclass
class ChapterInfo:
    """Stores metadata and boundaries for an individual chapter."""
    number: int
    title: str
    story_name: str
    start_para_idx: int
    end_para_idx: int
    paragraph_count: int
    image_count: int
    table_count: int


class ChapterProcessor:
    """
    Manages chapter boundaries, enabling isolated chapter-by-chapter processing
    and full-book execution with chapter-wise metrics reporting.
    """

    CHAPTER_HEADING_KEYWORDS = ["chapter", "preface", "appendix", "index", "introduction"]

    def __init__(self, chapter_style: str = "chapter_name"):
        self.chapter_style = chapter_style

    def discover_chapters(self, doc: DocumentModel) -> List[ChapterInfo]:
        """
        Discovers all chapters across document stories by finding chapter headings
        and measuring paragraph/image/table boundaries.
        """
        chapters: List[ChapterInfo] = []
        chap_counter = 1

        for s_name, story in doc.stories.items():
            p_ranges = story.get_paragraph_ranges()
            if not p_ranges:
                continue

            # Find chapter start indices in this story
            break_indices: List[Tuple[int, str]] = []
            for idx, p in enumerate(p_ranges):
                applied = p.get("AppliedParagraphStyle", "").lower()
                text = story.get_text_content(p).strip()

                is_chap = False
                if self.chapter_style in applied and "chapter_name01" not in applied:
                    is_chap = True
                elif any(text.upper().startswith(kw.upper()) for kw in ["CHAPTER ", "APPENDIX "]):
                    is_chap = True
                elif bool(re.match(r"^[IVXLCDM]+\s+[A-Z]", text)):
                    is_chap = True

                if is_chap and text:
                    break_indices.append((idx, text))

            # Build ChapterInfo objects
            for i, (start_idx, title) in enumerate(break_indices):
                end_idx = break_indices[i + 1][0] if (i + 1) < len(break_indices) else len(p_ranges)
                chap_paras = p_ranges[start_idx:end_idx]

                # Count images and tables in this chapter
                img_count = sum(
                    1 for p in chap_paras
                    if "###Insert" in story.get_text_content(p) or "###IMAGE_TOKEN" in story.get_text_content(p)
                )
                tbl_count = sum(len(p.findall(".//Table")) for p in chap_paras)

                clean_title = re.sub(r"\s+", " ", title)[:80].strip()
                chapters.append(ChapterInfo(
                    number=chap_counter,
                    title=clean_title,
                    story_name=s_name,
                    start_para_idx=start_idx,
                    end_para_idx=end_idx,
                    paragraph_count=(end_idx - start_idx),
                    image_count=img_count,
                    table_count=tbl_count,
                ))
                chap_counter += 1

        return chapters

    def get_chapter_by_number(self, doc: DocumentModel, chapter_num: int) -> Optional[ChapterInfo]:
        """Retrieves chapter metadata for a specific chapter number."""
        chapters = self.discover_chapters(doc)
        for c in chapters:
            if c.number == chapter_num:
                return c
        return None

    def print_chapter_manifest(self, doc: DocumentModel):
        """Prints a human-readable manifest of all discovered chapters."""
        chapters = self.discover_chapters(doc)
        print(f"\nDiscovered {len(chapters)} Chapters in Document:")
        print(f"{'#':<4} | {'Story':<16} | {'Paras':<6} | {'Imgs':<5} | {'Tables':<6} | Title")
        print("-" * 75)
        for c in chapters:
            print(f"{c.number:<4} | {c.story_name:<16} | {c.paragraph_count:<6} | {c.image_count:<5} | {c.table_count:<6} | {c.title}")
        print("-" * 75 + "\n")

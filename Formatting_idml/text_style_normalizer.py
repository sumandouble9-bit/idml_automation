"""
Formatting_idml: TextStyleNormalizer
OOP normalizer for paragraph and character styling.
Maps authoritative italic, bold, and underline styling from EPUB files,
normalizes Word/DOCX imports, strictly preserves table styling and font sizes,
and eliminates redundant empty chapter page-breaks.
"""

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Set, Optional
from model.story import StoryModel
from Formatting_idml.epub_parser import EpubFormattingMap


class TextStyleNormalizer:
    """
    Normalizes typographic styles across IDML stories:
    1. Maps exact italic, bold, and underline styling from EPUB files to character styles.
    2. Strictly preserves table formatting (bold headers, italic labels, regular text, font sizes).
    3. Safely deduplicates adjacent character runs without disturbing nested tables or footnotes.
    4. Eliminates redundant empty page-break paragraphs before chapter headings.
    """

    CHAR_STYLE_REMAP: Dict[str, str] = {
        "italicalign": "italic",
        "ittalicalign": "italic",
        "italic_text": "italic",
        "bold_text": "boldtext",
        "bold": "boldtext",
        "underline_text": "underline",
    }

    PARAGRAPH_STYLE_REMAP: Dict[str, str] = {
        "Normal": "body_text",
        "Body Text": "body_text",
        "BodyText": "body_text",
        "Heading 1": "chapter_name",
        "Heading 2": "subhead",
        "Heading 3": "subhead",
        "Title": "title",
        "Subtitle": "subhead",
    }

    # Attributes to strip from body text to eliminate dirty Word overrides
    BODY_OVERRIDES_TO_STRIP: Set[str] = {
        "Justification",
        "FirstLineIndent",
        "LeftIndent",
        "RightIndent",
        "SpaceBefore",
        "SpaceAfter",
        "PointSize",
        "Leading",
        "Tracking",
        "AppliedFont",
        "FillColor",
    }

    def __init__(self, custom_para_remap: Optional[Dict[str, str]] = None):
        self.para_remap = dict(self.PARAGRAPH_STYLE_REMAP)
        if custom_para_remap:
            self.para_remap.update(custom_para_remap)

    def remove_redundant_chapter_page_breaks(self, story: StoryModel) -> int:
        """
        Removes empty page-break paragraphs (imported from Word Ctrl+Enter)
        that precede chapter titles, eliminating blank pages after chapters.
        """
        p_ranges = story.get_paragraph_ranges()
        if not p_ranges:
            return 0

        removed_count = 0
        to_remove = set()

        for idx, p_elem in enumerate(p_ranges):
            raw_text = "".join(c.text for c in p_elem.findall(".//Content") if c.text)
            clean_text = raw_text.replace("\u2029", "").replace("\u2028", "").strip()

            xml_str = ET.tostring(p_elem, encoding="utf-8").decode("utf-8")
            has_break = "ParagraphBreakType" in xml_str or "NextPage" in xml_str

            if len(clean_text) == 0 and has_break:
                # Look ahead for next non-empty paragraph
                is_before_heading = False
                for ahead_idx in range(idx + 1, min(idx + 5, len(p_ranges))):
                    ahead_p = p_ranges[ahead_idx]
                    ahead_txt = "".join(c.text for c in ahead_p.findall(".//Content") if c.text).strip()
                    if ahead_txt:
                        ahead_style = ahead_p.get("AppliedParagraphStyle", "").lower()
                        if any(kw in ahead_style for kw in ["chapter", "heading", "title", "toc"]) or \
                           any(kw in ahead_txt.upper() for kw in ["CHAPTER", "PREFACE", "APPENDIX", "INDEX", "CONTENTS"]):
                            is_before_heading = True
                        break

                if is_before_heading:
                    to_remove.add(p_elem)

        for p in to_remove:
            if story.remove_paragraph(p):
                removed_count += 1

        # Strip ParagraphBreakType from non-empty paragraphs preceding chapter_name
        for idx, p_elem in enumerate(p_ranges):
            if p_elem in to_remove:
                continue
            for csr in p_elem.findall(".//CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib and idx + 1 < len(p_ranges):
                    nxt_style = p_ranges[idx + 1].get("AppliedParagraphStyle", "")
                    if "chapter_name" in nxt_style:
                        del csr.attrib["ParagraphBreakType"]

        return removed_count

    @staticmethod
    def get_table_paragraph_set(story: StoryModel) -> Set[ET.Element]:
        """Precomputes a set of all ParagraphStyleRange elements inside tables for O(1) checks."""
        return set(p for cell in story.root.findall(".//Cell") for p in cell.iter() if p.tag.endswith("ParagraphStyleRange"))

    def remap_paragraph_styles(self, story: StoryModel, scope_indices: Optional[range] = None) -> int:
        """
        Remaps paragraph styles in the story, strictly protecting table cells
        from being converted to general body text.
        """
        p_ranges = story.get_paragraph_ranges()
        if not p_ranges:
            return 0

        table_p_set = self.get_table_paragraph_set(story)
        remap_count = 0
        indices = scope_indices if scope_indices is not None else range(len(p_ranges))

        for i in indices:
            if i >= len(p_ranges):
                break
            p_elem = p_ranges[i]

            # Protect table cells: do not remap paragraphs inside tables
            if p_elem in table_p_set:
                continue

            applied = p_elem.get("AppliedParagraphStyle", "")
            style_name = applied.split("/")[-1] if "/" in applied else applied

            if style_name in self.para_remap:
                target = self.para_remap[style_name]
                prefix = applied[:applied.rfind("/") + 1] if "/" in applied else "ParagraphStyle/"
                p_elem.set("AppliedParagraphStyle", f"{prefix}{target}")
                remap_count += 1

        return remap_count

    def map_epub_formatting(self, story: StoryModel, fmap: EpubFormattingMap) -> int:
        """
        Applies authoritative italic, bold, and underline formatting extracted from EPUB
        to CharacterStyleRange runs in the IDML story.
        """
        p_ranges = story.get_paragraph_ranges()
        if not p_ranges:
            return 0

        mapped_count = 0

        for p_elem in p_ranges:
            for csr in p_elem.findall(".//CharacterStyleRange"):
                text = "".join(c.text for c in csr.findall(".//Content") if c.text).strip()
                if not text:
                    continue

                applied = csr.get("AppliedCharacterStyle", "")
                style_name = applied.split("/")[-1] if "/" in applied else applied

                # 1. Normalize character style aliases
                if style_name in self.CHAR_STYLE_REMAP:
                    target = self.CHAR_STYLE_REMAP[style_name]
                    prefix = applied[:applied.rfind("/") + 1] if "/" in applied else "CharacterStyle/"
                    csr.set("AppliedCharacterStyle", f"{prefix}{target}")
                    mapped_count += 1
                    continue

                # 2. Map from local FontStyle overrides
                font_style = csr.get("FontStyle", "").lower()
                if "italic" in font_style and "bold" not in font_style:
                    csr.set("AppliedCharacterStyle", "CharacterStyle/italic")
                    mapped_count += 1
                    continue
                elif "bold" in font_style:
                    csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                    mapped_count += 1
                    continue

                # 3. Match against authoritative EPUB styling sets
                if text in fmap.italic_phrases:
                    csr.set("AppliedCharacterStyle", "CharacterStyle/italic")
                    mapped_count += 1
                elif text in fmap.bold_phrases:
                    csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                    mapped_count += 1
                elif text in fmap.underline_phrases:
                    csr.set("AppliedCharacterStyle", "CharacterStyle/underline")
                    mapped_count += 1

        return mapped_count

    def preserve_table_formatting(self, story: StoryModel) -> int:
        """
        Walks every table in the story and ensures that cell text formatting
        (bold, italic, regular font style and font size) is explicitly preserved.
        """
        table_cells = story.root.findall(".//Cell")
        if not table_cells:
            return 0

        preserved_cells = 0
        for cell in table_cells:
            for p_elem in cell.findall(".//ParagraphStyleRange"):
                # Preserve cell paragraph alignment and style
                for csr in p_elem.findall(".//CharacterStyleRange"):
                    font_style = csr.get("FontStyle", "")
                    point_size = csr.get("PointSize", "")

                    # Ensure semantic character style is set for bold/italic in tables
                    if "Bold" in font_style:
                        csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                    elif "Italic" in font_style:
                        csr.set("AppliedCharacterStyle", "CharacterStyle/italic")

                    # Keep PointSize on cell character ranges intact
                    if point_size:
                        csr.set("PointSize", point_size)

            preserved_cells += 1

        return preserved_cells

    def strip_body_overrides(self, story: StoryModel, scope_indices: Optional[range] = None) -> int:
        """
        Strips local manual Word overrides on body paragraphs, while strictly
        protecting tables, bold, italic, and underline styling.
        """
        p_ranges = story.get_paragraph_ranges()
        if not p_ranges:
            return 0

        table_p_set = self.get_table_paragraph_set(story)
        stripped_count = 0
        indices = scope_indices if scope_indices is not None else range(len(p_ranges))

        for i in indices:
            if i >= len(p_ranges):
                break
            p_elem = p_ranges[i]

            # NEVER strip overrides inside tables
            if p_elem in table_p_set:
                continue

            applied = p_elem.get("AppliedParagraphStyle", "")
            # Only strip body text and subheads; keep title and chapter headers intact
            if "body_text" not in applied and "subhead" not in applied:
                continue

            # Strip paragraph-level overrides
            for attr in list(p_elem.attrib.keys()):
                if attr in self.BODY_OVERRIDES_TO_STRIP:
                    del p_elem.attrib[attr]
                    stripped_count += 1

            # Strip character-level overrides (protecting italic/bold/underline)
            for csr in p_elem.findall(".//CharacterStyleRange"):
                c_style = csr.get("AppliedCharacterStyle", "")
                for attr in list(csr.attrib.keys()):
                    # Preserve font style on semantic character styles
                    if attr == "FontStyle" and ("italic" in c_style.lower() or "bold" in c_style.lower()):
                        continue
                    if attr in self.BODY_OVERRIDES_TO_STRIP:
                        del csr.attrib[attr]
                        stripped_count += 1

        return stripped_count

    def merge_character_runs_safely(self, story: StoryModel) -> int:
        """
        Merges adjacent identical CharacterStyleRange elements safely, with guards
        preventing removal of nested tables, footnotes, or frames.
        """
        p_ranges = story.get_paragraph_ranges()
        if not p_ranges:
            return 0

        merged_count = 0
        complex_tags = ("Table", "Footnote", "Rectangle", "Oval", "GraphicLine", "Polygon", "Group", "TextFrame", "Br")

        for p_elem in p_ranges:
            char_ranges = p_elem.findall(".//CharacterStyleRange")
            if len(char_ranges) <= 1:
                continue

            parent_map = {child: parent for parent in p_elem.iter() for child in parent}
            idx = 0
            while idx < len(char_ranges) - 1:
                current_c = char_ranges[idx]
                next_c = char_ranges[idx + 1]

                if current_c.attrib == next_c.attrib and parent_map.get(current_c) == parent_map.get(next_c):
                    # Safety guard: ensure next_c contains no nested complex structures
                    has_complex = any(c.tag.endswith(complex_tags) for c in next_c)
                    if has_complex:
                        idx += 1
                        continue

                    curr_contents = [c for c in current_c if c.tag.endswith("Content")]
                    next_contents = [c for c in next_c if c.tag.endswith("Content")]

                    if len(curr_contents) == 1 and len(next_contents) == 1:
                        curr_contents[0].text = (curr_contents[0].text or "") + (next_contents[0].text or "")
                        par = parent_map.get(next_c, p_elem)
                        par.remove(next_c)
                        char_ranges.pop(idx + 1)
                        merged_count += 1
                        continue
                idx += 1

        return merged_count

    @staticmethod
    def _is_inside_table(p_elem: ET.Element, story: StoryModel) -> bool:
        """Checks if a ParagraphStyleRange is nested inside a table cell."""
        for cell in story.root.findall(".//Cell"):
            if p_elem in list(cell.iter()):
                return True
        return False

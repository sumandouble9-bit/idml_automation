import xml.etree.ElementTree as ET
from typing import List, Generator, Tuple, Optional
from pathlib import Path


class StoryModel:
    """
    Encapsulates an InDesign Story XML, allowing inspection and manipulation
    of ParagraphStyleRange and CharacterStyleRange elements.
    """

    def __init__(self, story_path: Path, root: ET.Element):
        self.story_path = story_path
        self.root = root
        self.story_elem = self._find_story_element()

    def _find_story_element(self) -> Optional[ET.Element]:
        for elem in self.root.iter():
            if elem.tag == "Story" or (elem.tag.endswith("Story") and "packaging" not in elem.tag):
                return elem
        return self.root

    def get_paragraph_ranges(self) -> List[ET.Element]:
        """Returns all ParagraphStyleRange elements in the story."""
        return [
            elem for elem in self.root.iter()
            if elem.tag.endswith("ParagraphStyleRange")
        ]

    def get_text_content(self, element: ET.Element) -> str:
        """Extracts text content from a ParagraphStyleRange or CharacterStyleRange."""
        texts = []
        for content in element.iter():
            if content.tag.endswith("Content") and content.text:
                texts.append(content.text)
            elif content.tag.endswith("Br"):
                texts.append("\n")
        return "".join(texts)

    def get_all_paragraphs_with_styles(self) -> List[Tuple[ET.Element, str, str]]:
        """
        Returns a list of tuples: (ParagraphStyleRange_element, style_name, full_text)
        """
        results = []
        for p_range in self.get_paragraph_ranges():
            applied = p_range.get("AppliedParagraphStyle", "")
            style_name = applied.split("/")[-1] if "/" in applied else applied
            text = self.get_text_content(p_range)
            results.append((p_range, style_name, text))
        return results

    def find_chapter_boundaries(self, chapter_style_pattern: str = "chapter_name") -> List[int]:
        """
        Finds the 0-based indices of ParagraphStyleRange elements that denote a chapter start.
        """
        p_ranges = self.get_paragraph_ranges()
        chapter_indices = []
        for idx, p in enumerate(p_ranges):
            applied = p.get("AppliedParagraphStyle", "")
            if chapter_style_pattern in applied and "chapter_name01" not in applied:
                chapter_indices.append(idx)
        return chapter_indices

    def set_content_text(self, char_range: ET.Element, new_text: str):
        """Sets text for a CharacterStyleRange by updating or creating Content elements."""
        content_elems = [c for c in char_range if c.tag.endswith("Content")]
        if content_elems:
            content_elems[0].text = new_text
            for extra in content_elems[1:]:
                char_range.remove(extra)
        else:
            ns = ""
            if "}" in char_range.tag:
                ns = char_range.tag.split("}")[0] + "}"
            new_content = ET.SubElement(char_range, f"{ns}Content")
            new_content.text = new_text

    def remove_paragraph(self, p_elem: ET.Element) -> bool:
        """Removes a ParagraphStyleRange from the story element."""
        if self.story_elem is not None:
            try:
                self.story_elem.remove(p_elem)
                return True
            except ValueError:
                pass
        for parent in self.root.iter():
            if p_elem in list(parent):
                parent.remove(p_elem)
                return True
        return False

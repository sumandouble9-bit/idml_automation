"""
Formatting_idml: CaptionInjector
Refactored, OOP implementation of image placeholder preparation, caption binding,
figure-label relocation, and fused/duplicate caption cleanup.
Based on inject_with_epub_captions.py and epub_caption_apply.py.
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from model.story import StoryModel


class CaptionInjector:
    """
    Manages image placeholder tokens, caption extraction, and atomic attachment.
    Ensures images never appear out of order or with duplicate/fused captions.
    """

    PLACEHOLDER_REGEX = re.compile(r"###Insert\s+(image\d+\.\w+)\s+here###", re.IGNORECASE)
    ILLUSTRATION_REGEX = re.compile(r"\[Illustration(?:\s*\([^)]*\))?:\s*([^\]]+)\]", re.IGNORECASE)
    FIGURE_LABEL_REGEX = re.compile(r"^(?:figs?|figure|img|image)\.?\s*\d+\.?$", re.IGNORECASE)

    def __init__(
        self,
        caption_map: Optional[Dict[str, str]] = None,
        caption_style_map: Optional[Dict[str, str]] = None
    ):
        self.caption_map = caption_map or {}
        self.caption_style_map = caption_style_map or {}

    def split_packed_placeholders(self, story: StoryModel) -> int:
        """
        Splits a single paragraph that packs multiple image placeholders into separate
        stacked paragraphs, ensuring each placeholder has its own paragraph in document order.
        """
        p_ranges = story.get_paragraph_ranges()
        if not p_ranges or story.story_elem is None:
            return 0

        split_count = 0
        for p_elem in list(p_ranges):
            text = story.get_text_content(p_elem)
            matches = list(self.PLACEHOLDER_REGEX.finditer(text))
            if len(matches) <= 1:
                continue

            # This paragraph packs 2+ image placeholders: split it
            parent = story.story_elem
            try:
                p_idx = list(parent).index(p_elem)
            except ValueError:
                continue

            # Remove the packed paragraph and insert split copies
            parent.remove(p_elem)
            for m in matches:
                img_name = m.group(1)
                new_p = ET.Element(p_elem.tag, p_elem.attrib)
                csr = ET.SubElement(new_p, "CharacterStyleRange")
                csr.set("AppliedCharacterStyle", "CharacterStyle/$ID/[No character style]")
                cnt = ET.SubElement(csr, "Content")
                cnt.text = f"###Insert {img_name} here###"
                ET.SubElement(csr, "Br")
                parent.insert(p_idx, new_p)
                p_idx += 1
                split_count += 1

        return split_count

    def process_story(self, story: StoryModel, image_map: Dict[str, Path]) -> int:
        """
        Finds image placeholders, extracts adjacent or EPUB captions, and injects
        atomic tokens: ###IMAGE_TOKEN: path=... | cap=...###
        """
        p_ranges = story.get_paragraph_ranges()
        if not p_ranges:
            return 0

        resolved_count = 0

        for idx, p_elem in enumerate(p_ranges):
            p_text = story.get_text_content(p_elem)
            match = self.PLACEHOLDER_REGEX.search(p_text)
            if not match:
                continue

            img_filename = match.group(1)
            img_path = image_map.get(img_filename)
            if not img_path:
                # Look case-insensitively
                for k, v in image_map.items():
                    if k.lower() == img_filename.lower():
                        img_path = v
                        break

            if not img_path or not Path(img_path).exists():
                continue

            clean_path = str(img_path).replace("\\", "/")

            # Resolve caption and exact font style:
            caption_text, caption_style = self._resolve_caption_and_style(idx, p_ranges, img_filename)

            # Build structured atomic token
            token = f"###IMAGE_TOKEN: path={clean_path} | cap={caption_text} | style={caption_style}###"

            # Reconstruct p_elem cleanly with single CharacterStyleRange
            for child in list(p_elem):
                p_elem.remove(child)

            csr = ET.SubElement(p_elem, "CharacterStyleRange")
            csr.set("AppliedCharacterStyle", "CharacterStyle/$ID/[No character style]")
            cnt = ET.SubElement(csr, "Content")
            cnt.text = token
            ET.SubElement(csr, "Br")

            # Clean paragraph attributes for center alignment
            p_elem.set("Justification", "CenterAlign")
            if "FirstLineIndent" in p_elem.attrib:
                del p_elem.attrib["FirstLineIndent"]

            resolved_count += 1

        # Post-pass: wipe any remaining raw [Illustration...] tags
        self._purge_raw_illustration_tags(story)

        return resolved_count

    def _resolve_caption_and_style(self, idx: int, p_ranges: List[ET.Element], img_filename: str) -> Tuple[str, str]:
        """Finds caption and exact font style from EPUB map or adjacent story paragraphs."""
        # 1. Check authoritative EPUB map first
        epub_cap = ""
        epub_style = "Regular"
        for k, v in self.caption_map.items():
            if k.lower() == img_filename.lower():
                epub_cap = v
                break
        for k, s in self.caption_style_map.items():
            if k.lower() == img_filename.lower():
                epub_style = s
                break

        # Check ONLY the immediate preceding paragraph for standalone short figure label (e.g. "Fig. 1")
        if idx > 0:
            prev_p = p_ranges[idx - 1]
            prev_txt = "".join(c.text for c in prev_p.findall(".//Content") if c.text).strip()
            if "###IMAGE_TOKEN" not in prev_txt and "###Insert" not in prev_txt:
                if self.FIGURE_LABEL_REGEX.match(prev_txt):
                    for c in prev_p.findall(".//Content"):
                        c.text = ""

        if epub_cap:
            return epub_cap, epub_style

        # 2. Fallback to inline [Illustration: ...] if no EPUB entry
        p_elem = p_ranges[idx]
        raw_text = "".join(c.text for c in p_elem.findall(".//Content") if c.text)
        if "[Illustration" in raw_text:
            m = re.search(r"(\[Illustration(?:\s*\([^)]*\))?:\s*[^\]]+\])", raw_text, re.IGNORECASE)
            if m:
                return m.group(1).strip(), "Regular"

        return "", "Regular"

    def _purge_raw_illustration_tags(self, story: StoryModel):
        """Sweeps story to delete any remaining raw [Illustration: ...] strings outside of tokens."""
        for p_elem in story.get_paragraph_ranges():
            p_text = "".join(c.text for c in p_elem.findall(".//Content") if c.text)
            if "###IMAGE_TOKEN" not in p_text and "###Insert" not in p_text and "[Illustration" in p_text:
                cleaned = self.ILLUSTRATION_REGEX.sub("", p_text).strip()
                contents = p_elem.findall(".//Content")
                if not cleaned:
                    for c in contents:
                        c.text = ""
                elif contents:
                    contents[0].text = cleaned
                    for c in contents[1:]:
                        c.text = ""

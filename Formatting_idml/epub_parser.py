"""
Formatting_idml: EpubParser
Extracts images, figure captions, and exact bold/italic/underline inline styling
from EPUB XHTML files to normalize and format IDML/DOCX stories.
"""

import os
import re
import html
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Optional


@dataclass
class EpubFormattingMap:
    """Stores authoritative formatting extracted from EPUB XHTML documents."""
    captions: Dict[str, str] = field(default_factory=dict)
    caption_styles: Dict[str, str] = field(default_factory=dict)
    italic_phrases: Set[str] = field(default_factory=set)
    bold_phrases: Set[str] = field(default_factory=set)
    underline_phrases: Set[str] = field(default_factory=set)
    table_count: int = 0


class EpubParser:
    """
    Parses EPUB archives to extract:
    1. Images and illustrations (.jpg, .png, etc.)
    2. Figure captions mapped to image filenames
    3. Authoritative text styling (italic, bold, underline, tables)
    """

    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".svg")

    def __init__(self, epub_path: str):
        self.epub_path = Path(epub_path).resolve()
        if not self.epub_path.exists():
            raise FileNotFoundError(f"EPUB file not found: {self.epub_path}")

    def extract_assets(self, output_dir: str) -> Dict[str, Path]:
        """Extracts all image files from the EPUB archive into output_dir."""
        out_path = Path(output_dir).resolve()
        out_path.mkdir(parents=True, exist_ok=True)
        extracted: Dict[str, Path] = {}

        with zipfile.ZipFile(self.epub_path, "r") as z:
            for item in z.namelist():
                if item.lower().endswith(self.IMAGE_EXTENSIONS):
                    filename = Path(item).name
                    target = out_path / filename
                    with z.open(item) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    extracted[filename] = target

        return extracted

    def parse_formatting(self) -> EpubFormattingMap:
        """
        Parses all XHTML/HTML files in the EPUB to extract:
        - Image captions
        - Italic phrases (<i>, <em>)
        - Bold phrases (<b>, <strong>)
        - Underlined phrases (<u>)
        - Table counts
        """
        fmap = EpubFormattingMap()

        with zipfile.ZipFile(self.epub_path, "r") as z:
            xhtml_names = [n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]

            for xname in xhtml_names:
                try:
                    content = z.read(xname).decode("utf-8", errors="ignore")
                except Exception:
                    continue

                # 1. Extract Captions & Inline Styles
                self._extract_captions_from_xhtml(content, fmap.captions, fmap.caption_styles)

                # 2. Extract Italics: <i>...</i> and <em>...</em>
                for tag in ["i", "em"]:
                    for match in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", content, re.DOTALL | re.IGNORECASE):
                        clean_text = self._clean_tag_content(match.group(1))
                        if 2 <= len(clean_text) <= 120 and "\n" not in clean_text:
                            fmap.italic_phrases.add(clean_text)

                # 3. Extract Bolds: <b>...</b> and <strong>...</strong>
                for tag in ["b", "strong"]:
                    for match in re.finditer(rf"<{tag}[^>]*>(.*?)</{tag}>", content, re.DOTALL | re.IGNORECASE):
                        clean_text = self._clean_tag_content(match.group(1))
                        if 2 <= len(clean_text) <= 120 and "\n" not in clean_text:
                            fmap.bold_phrases.add(clean_text)

                # 4. Extract Underlines: <u>...</u>
                for match in re.finditer(r"<u[^>]*>(.*?)</u>", content, re.DOTALL | re.IGNORECASE):
                    clean_text = self._clean_tag_content(match.group(1))
                    if 2 <= len(clean_text) <= 120 and "\n" not in clean_text:
                        fmap.underline_phrases.add(clean_text)

                # 5. Count Tables
                fmap.table_count += len(re.findall(r"<table[^>]*>", content, re.IGNORECASE))

        return fmap

    @staticmethod
    def _clean_tag_content(raw: str) -> str:
        """Removes nested HTML tags, unescapes entities, and normalizes whitespace."""
        clean = re.sub(r"<[^>]+>", " ", raw)
        clean = html.unescape(clean)
        clean = clean.replace("\u00a0", " ")
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    @classmethod
    def _extract_captions_from_xhtml(cls, content: str, out_captions: Dict[str, str], out_styles: Optional[Dict[str, str]] = None):
        """Finds figures and images in XHTML and maps exact caption text along with its exact font styling."""
        # 1. First parse structured <figure> blocks with <figcaption> (exact HTML5/EPUB3 structure)
        for fig_match in re.finditer(r"(?is)<figure\b[^>]*>(.*?)</figure>", content):
            fig_content = fig_match.group(1)
            img_m = re.search(r'(?is)<img\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', fig_content)
            cap_m = re.search(r"(?is)<figcaption\b[^>]*>(.*?)</figcaption>", fig_content)
            if not img_m or not cap_m:
                continue

            src_filename = Path(img_m.group(1)).name
            raw_cap = cap_m.group(1)
            clean_cap = cls._clean_tag_content(raw_cap)
            if not clean_cap:
                continue

            lower_cap = raw_cap.lower()
            is_bold = ("<b" in lower_cap or "<strong" in lower_cap)
            is_italic = ("<i" in lower_cap or "<em" in lower_cap)
            style = "Bold" if is_bold else ("Italic" if is_italic else "Regular")

            out_captions[src_filename] = clean_cap
            if out_styles is not None:
                out_styles[src_filename] = style

        # 2. Fallback for standalone <img> tags not inside <figure>
        img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', re.IGNORECASE)
        for match in img_pattern.finditer(content):
            src_filename = Path(match.group(1)).name
            if src_filename in out_captions:
                continue

            end_pos = match.end()
            following_chunk = content[end_pos:end_pos + 500]
            clean = cls._clean_tag_content(following_chunk)
            if not clean:
                continue

            lower_chunk = following_chunk.lower()
            is_bold = ("<b" in lower_chunk or "<strong" in lower_chunk)
            is_italic = ("<i" in lower_chunk or "<em" in lower_chunk)
            style = "Bold" if is_bold else ("Italic" if is_italic else "Regular")

            if clean.startswith("[Illustration") or len(clean) <= 180:
                out_captions[src_filename] = clean
                if out_styles is not None:
                    out_styles[src_filename] = style

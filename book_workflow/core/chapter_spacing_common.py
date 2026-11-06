import argparse
import math
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from toc_synchronizer import sync_idml_toc_from_pdf
except ImportError:
    try:
        from .toc_synchronizer import sync_idml_toc_from_pdf
    except ImportError:
        sync_idml_toc_from_pdf = None

# Packaging namespace required for Adobe InDesign IDML
IDPKG_NS = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
ET.register_namespace("idPkg", IDPKG_NS)

# Constants reverse-engineered from reference '18049 Impressions Of A War Correspondent.indd'
REF_SPACE_BEFORE = "14.5"               # 14.5 pt top gap for chapters
REF_SPACE_AFTER = "30"                  # 30 pt space after chapter heading
REF_POINT_SIZE = "16"
LS = "\u2028"                           # Unicode Forced Line Break (Line Separator)

# Regex patterns for detecting chapter heading candidates
_CHAPTER_PREFIX = (
    r"(?:CHAPTER|CAP[IÍ]TULO|PART|PARTE|SECTION|SECCI[OÓ]N|CANTO|ACTO|TOMO|VOLUME|VOLUMEN)"
)
_BOOK_PREFIX = (
    r"(?:BOOK|LIBRO)\s+(?:[IVXLCDM0-9]+|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|"
    r"SEVENTH|EIGHTH|NINTH|TENTH|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|"
    r"PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[EÉ]PTIMO|OCTAVO|NOVENO|D[EÉ]CIMO|"
    r"UNO|DOS|TRES|CUATRO|CINCO|SEIS|SIETE|OCHO|NUEVE|DIEZ)\b"
)
CHAPTER_PREFIX_RE = re.compile(
    rf"^\s*(?:{_CHAPTER_PREFIX}\s+(?:[IVXLCDM0-9]+|[A-ZÁÉÍÓÚÑa-záéíóúñ]+)|{_BOOK_PREFIX})\b",
    re.I,
)
STANDALONE_HEADINGS_RE = re.compile(
    r"^\s*(?:PREFACE|PREFACIO|PROLOGUE|PR[OÓ]LOGO|EPILOGUE|EP[IÍ]LOGO|INTRODUCTION|"
    r"INTRODUCCI[OÓ]N|CONCLUSION|CONCLUSI[OÓ]N|NOTES|NOTAS|APPENDIX|AP[EÉ]NDICE|"
    r"GLOSSARY|GLOSARIO)\s*$",
    re.I,
)

TOC_STYLE_KEYS = ("toc", "content", "index")
HEADING_STYLE_KEYS = ("chapter", "sub-heading", "centre_align", "center1", "after_chapter")


def _lname(tag: str) -> str:
    """Extract local XML tag name without namespace."""
    return tag.rsplit("}", 1)[-1]


def _get_text(elem: ET.Element) -> str:
    """Extract all text inside Content elements of an XML element."""
    return "".join(c.text or "" for c in elem.iter() if _lname(c.tag) == "Content").strip()


def is_chapter_heading(psr: ET.Element, prev_psr: ET.Element = None) -> bool:
    """Determine if a ParagraphStyleRange is a chapter heading."""
    style = psr.attrib.get("AppliedParagraphStyle", "").lower()
    
    # Never touch Table of Contents or Index rows
    if any(k in style for k in TOC_STYLE_KEYS):
        return False
        
    # Running headers on master pages or spread items are skipped
    if "master_" in style or "header" in style or "footer" in style:
        return False
        
    txt = _get_text(psr)
    if not txt or "###Insert" in txt:
        return False
        
    # Table of contents rows typically end with page numbers (e.g. "... 15")
    if re.search(r"[\t\.\s]{2,}\d+$", txt):
        return False
        
    # Style is explicitly chapter_name (and not running header or after_chapter)
    if "chapter_name" in style and not "after_chapter" in style:
        return True
    if "chapter_name01" in style:
        return True

    # Heading text matches chapter/part prefix or standalone section heading
    if CHAPTER_PREFIX_RE.match(txt):
        return True
    if STANDALONE_HEADINGS_RE.match(txt):
        if any(k in style for k in HEADING_STYLE_KEYS):
            return True
            
    return False


def is_empty_psr(psr) -> bool:
    """Check if a ParagraphStyleRange has no visible content.

    Only the Content text counts (itertext() would also pick up font names stored in Properties, so a BOM-only line
    carrying a font could never look empty), and a paragraph holding an anchored object is never empty.
    """
    if any(_lname(e.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table", "TextFrame", "GraphicLine", "Group")
           for e in psr.iter()):
        return False
    txt = "".join(c.text or "" for c in psr.iter() if _lname(c.tag) == "Content")
    cleaned = re.sub(r"[\s\ufeff\u2028\u00a0\r\n]+", "", txt)
    return len(cleaned) == 0


__all__ = [
    'IDPKG_NS',
    'REF_SPACE_BEFORE',
    'REF_SPACE_AFTER',
    'REF_POINT_SIZE',
    'LS',
    '_CHAPTER_PREFIX',
    '_BOOK_PREFIX',
    'CHAPTER_PREFIX_RE',
    'STANDALONE_HEADINGS_RE',
    'TOC_STYLE_KEYS',
    'HEADING_STYLE_KEYS',
    '_lname',
    '_get_text',
    'is_chapter_heading',
    'is_empty_psr',
]

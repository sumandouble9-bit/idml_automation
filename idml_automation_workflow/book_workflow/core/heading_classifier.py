import re
import html
import xml.etree.ElementTree as ET
from typing import Optional, Tuple, Set, Dict, Any

# Number maps
ROMAN_MAP = {
    'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
    'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10,
    'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15,
    'xvi': 16, 'xvii': 17, 'xviii': 18, 'xix': 19, 'xx': 20,
    'xxi': 21, 'xxii': 22, 'xxiii': 23, 'xxiv': 24, 'xxv': 25,
    'xxvi': 26, 'xxvii': 27, 'xxviii': 28, 'xxix': 29, 'xxx': 30,
    'xxxi': 31, 'xxxii': 32, 'xxxiii': 33, 'xxxiv': 34, 'xxxv': 35,
    'xxxvi': 36, 'xxxvii': 37, 'xxxviii': 38, 'xxxix': 39, 'xl': 40,
    'xli': 41, 'xlii': 42, 'xliii': 43, 'xliv': 44, 'xlv': 45,
    'xlvi': 46, 'xlvii': 47, 'xlviii': 48, 'xlix': 49, 'l': 50,
}

SPANISH_ORDINALS = {
    'primer': 1, 'primero': 1, 'primera': 1,
    'segundo': 2, 'segunda': 2,
    'tercer': 3, 'tercero': 3, 'tercera': 3,
    'cuarto': 4, 'cuarta': 4,
    'quinto': 5, 'quinta': 5,
    'sexto': 6, 'sexta': 6,
    'septimo': 7, 'septima': 7, 'séptimo': 7, 'séptima': 7,
    'octavo': 8, 'octava': 8,
    'noveno': 9, 'novena': 9,
    'decimo': 10, 'decima': 10, 'décimo': 10, 'décima': 10,
}

ENGLISH_ORDINALS = {
    'first': 1, 'second': 2, 'third': 3, 'fourth': 4, 'fifth': 5,
    'sixth': 6, 'seventh': 7, 'eighth': 8, 'ninth': 9, 'tenth': 10,
}

# Regex patterns
RE_PART_OR_BOOK = re.compile(
    r"^(?:PART|PARTE|BOOK|LIBRO|VOLUME|VOLUMEN|TOMO|ACT|ACTO|SECTION|SECCI[ÓO]N)\b",
    re.I
)

RE_CHAPTER_KEYWORD = re.compile(
    r"^(?:CHAPTER|CAP[ÍI]TULO|CH\.|CHAP\.)\b",
    re.I
)

RE_SPANISH_ORDINAL_CHAP = re.compile(
    r"^(?:primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|s[ée]ptim[oa]|octav[oa]|noven[oa]|d[ée]cim[oa])\s+cap[íi]tulo\b",
    re.I
)

RE_ENGLISH_ORDINAL_CHAP = re.compile(
    r"^(?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+chapter\b",
    re.I
)

RE_NUMBERED_HEADING = re.compile(
    r"^(?:[IVXLCDM]+\b\.?\s+[A-ZÁÉÍÓÚÑ]|\d+\.\s+[A-ZÁÉÍÓÚÑ])",
    re.I
)

RE_FRONT_BACK_MATTER = re.compile(
    r"^(?:PREFACE|PREFACIO|PREFATORY NOTE|FOREWORD|INTRODUCTION|INTRODUCCI[ÓO]N|PROLOGUE|PR[ÓO]LOGO|EPILOGUE|EP[ÍI]LOGO|APPENDIX|AP[ÉE]NDICE|NOTES?|NOTAS(\s+AL\s+PIE)?|FOOT-?NOTES?|GLOSSARY|GLOSARIO|INDEX|[ÍI]NDICE|BIBLIOGRAPHY|BIBLIOGRAF[ÍI]A|CONCLUSI[ÓO]N|CONCLUSION)\b",
    re.I
)


def normalize_heading_str(s: str) -> str:
    """Normalizes a heading string for matching by removing noise, punctuation, and whitespace."""
    if not s:
        return ""
    s = s.split('\t')[0]
    s = html.unescape(s)
    s = re.sub(r'[\u2014\u2013\-\:\_\/\.\,]+', ' ', s)
    s = re.sub(r'[\r\n\u2028]+', ' ', s)
    s = re.sub(r'[^\w\s]', '', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def is_part_or_book_heading(text: str) -> bool:
    """Returns True if the text represents a super-ordinate division (Part, Book, Volume, etc.)."""
    cleaned = text.strip()
    return bool(RE_PART_OR_BOOK.search(cleaned)) and len(cleaned) < 100


def is_chapter_heading(text: str) -> bool:
    """Returns True if the text represents a chapter-level heading."""
    cleaned = text.strip()
    if len(cleaned) > 140:
        return False
    if RE_CHAPTER_KEYWORD.search(cleaned):
        return True
    if RE_SPANISH_ORDINAL_CHAP.search(cleaned) or RE_ENGLISH_ORDINAL_CHAP.search(cleaned):
        return True
    if RE_NUMBERED_HEADING.search(cleaned):
        return True
    return False


def is_frontmatter_or_backmatter(text: str) -> bool:
    """Returns True if the text is a frontmatter or backmatter heading."""
    cleaned = text.strip()
    return bool(RE_FRONT_BACK_MATTER.search(cleaned)) and len(cleaned) < 60


def extract_heading_number(text: str, lang: str = "es") -> Optional[int]:
    """Extracts chapter or part integer number from heading text."""
    cleaned = text.strip()
    m_ord = re.search(r'\b(primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|s[ée]ptim[oa]|octav[oa]|noven[oa]|d[ée]cim[oa])\b', cleaned, re.I)
    if m_ord:
        w = m_ord.group(1).lower().replace('á', 'a').replace('é', 'e')
        for k, v in SPANISH_ORDINALS.items():
            if k in w:
                return v

    m_eng_ord = re.search(r'\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b', cleaned, re.I)
    if m_eng_ord:
        w = m_eng_ord.group(1).lower()
        if w in ENGLISH_ORDINALS:
            return ENGLISH_ORDINALS[w]

    m_num = re.match(r'^\s*(\d{1,3})\.\s+[A-ZÁÉÍÓÚÑ]', cleaned)
    if m_num:
        return int(m_num.group(1))

    m_chap = re.search(r'\b(?:cap[íi]tulo|chapter|chap\.?|parte|part|book|libro)\s+([ivxlcdm0-9]+)\b', cleaned, re.I)
    if m_chap:
        val = m_chap.group(1).lower()
        if val.isdigit():
            return int(val)
        if val in ROMAN_MAP:
            return ROMAN_MAP[val]

    m_roman = re.match(r'^\s*([ivxlcdm]+)\b', cleaned, re.I)
    if m_roman:
        val = m_roman.group(1).lower()
        if val in ROMAN_MAP:
            return ROMAN_MAP[val]

    return None


def split_runon_heading(text: str, lang: str = "es") -> Tuple[Optional[str], str, bool]:
    """
    Splits run-on headings that combine Part + Chapter, Book + Part, or Chapter + Title into separate components.
    Returns (super_heading_text, main_heading_text, was_separated).
    """
    # 0. Check explicit line break \u2028 separating Book/Part from Chapter/Part
    if "\u2028" in text:
        parts = [p.strip() for p in text.split("\u2028") if p.strip()]
        if len(parts) >= 2:
            p0, p1 = parts[0], parts[1]
            if (is_part_or_book_heading(p0) or bool(re.search(r"\b(?:BOOK|LIBRO|PART|PARTE)\b", p0, re.I))) and (
                is_chapter_heading(p1) or is_part_or_book_heading(p1) or bool(re.match(r"^(?:PART|PARTE|CHAPTER|CAP[ÍI]TULO)\b", p1, re.I))
            ):
                return p0, p1, True

    cleaned = text.strip().replace("\r", " ").replace("\n", " ")

    # 1. Spanish Parte/Libro + Capítulo run-on
    m_sp = re.match(r"^(PARTE\s+[^\n\r]+?)(CAP[ÍI]TULO\s+[IVXLCDM0-9]+.*)$", cleaned, re.I)
    if m_sp:
        part_raw = m_sp.group(1).strip()
        chap_raw = m_sp.group(2).strip()
        _, chap_txt, _ = split_runon_heading(chap_raw, lang=lang)
        return part_raw, chap_txt, True

    # 2. English Part/Book + Chapter run-on
    m_en = re.match(r"^((?:PART|BOOK)\s+[^\n\r]+?)(CHAPTER\s+[IVXLCDM0-9]+.*)$", cleaned, re.I)
    if m_en:
        part_raw = m_en.group(1).strip()
        chap_raw = m_en.group(2).strip()
        _, chap_txt, _ = split_runon_heading(chap_raw, lang=lang)
        return part_raw, chap_txt, True

    # 3. Book + Part/Chapter run-on (e.g. "THE FIRST BOOK OF OPTICKSPART I." or "BOOK I PART I")
    m_book_part = re.match(
        r"^((?:THE\s+)?(?:[A-Z0-9\s\-]+?\b(?:BOOK|LIBRO)\s+[^\n\r]+?))(?:\s*|\b)(PART\s+[IVXLCDM0-9]+.*|PARTE\s+[IVXLCDM0-9]+.*|CHAPTER\s+[IVXLCDM0-9]+.*|CAP[ÍI]TULO\s+[IVXLCDM0-9]+.*)$",
        cleaned,
        re.I,
    )
    if m_book_part:
        book_raw = m_book_part.group(1).strip()
        part_raw = m_book_part.group(2).strip()
        return book_raw, part_raw, True

    # 4. Spanish CAPÍTULO [num] - Title run-on
    m_chap_es = re.match(r"^(CAP[ÍI]TULO\s+[IVXLCDM0-9]+)\s*[\.\:\-\u2013\u2014]\s*(.+)$", cleaned, re.I)
    if m_chap_es:
        num = m_chap_es.group(1).strip()
        title = m_chap_es.group(2).strip()
        return None, f"{num}\u2028{title}", True

    # 5. English CHAPTER [num] - Title run-on
    m_chap_en = re.match(r"^(CHAPTER\s+[IVXLCDM0-9]+)\s*[\.\:\-\u2013\u2014]\s*(.+)$", cleaned, re.I)
    if m_chap_en:
        num = m_chap_en.group(1).strip()
        title = m_chap_en.group(2).strip()
        return None, f"{num}\u2028{title}", True

    return None, cleaned, False


def should_pair_headings(
    prev_norm: Optional[str],
    curr_norm: str,
    prev_text: Optional[str],
    curr_text: str,
    seen_body_since_prev: bool,
    same_chap_pairs: Optional[Set[Tuple[str, str]]] = None,
    prev_num: Optional[int] = None,
    curr_num: Optional[int] = None,
) -> bool:
    """
    Modular determination whether `curr_text` should share the SAME page as `prev_text`.

    Rules:
    1. If body text has appeared since the previous heading -> NEVER pair (always fresh page).
    2. If no previous heading exists -> cannot pair (starts its own page).
    3. If previous heading was a Part/Book division and current heading is a Chapter -> ALWAYS SAME PAGE.
    4. If previous heading was a Chapter and current heading is a subtitle / sub-heading -> ALWAYS SAME PAGE.
    5. If EPUB explicitly declared both headings in the same XHTML file / section -> ALWAYS SAME PAGE.
    6. If both headings share the same chapter number -> ALWAYS SAME PAGE.
    """
    if seen_body_since_prev:
        return False
    if not prev_norm or not prev_text:
        return False

    # Check 1: Explicit EPUB same-chapter pairing
    if same_chap_pairs:
        if (prev_norm, curr_norm) in same_chap_pairs or (curr_norm, prev_norm) in same_chap_pairs:
            return True
        if any(
            ((pa in curr_norm or curr_norm in pa) and (pb in prev_norm or prev_norm in pb)) or
            ((pb in curr_norm or curr_norm in pb) and (pa in prev_norm or prev_norm in pa))
            for (pa, pb) in same_chap_pairs
        ):
            return True

    # Check 2: Shared chapter number
    if curr_num is not None and prev_num is not None and str(curr_num) == str(prev_num):
        return True

    # Check 3: Super-heading (Part/Book) followed immediately by Chapter heading
    if is_part_or_book_heading(prev_text) and (is_chapter_heading(curr_text) or not is_part_or_book_heading(curr_text)):
        return True

    # Check 4: Chapter heading followed immediately by Subheading / Title
    if is_chapter_heading(prev_text) and not is_chapter_heading(curr_text) and not is_part_or_book_heading(curr_text):
        return True

    # Check 5: Multiple consecutive headings introducing the chapter without intervening text
    if not is_frontmatter_or_backmatter(curr_text) and not is_frontmatter_or_backmatter(prev_text):
        if is_chapter_heading(curr_text) and is_part_or_book_heading(prev_text):
            return True

    return False


def apply_paired_heading_format(
    psr: ET.Element,
    text: str,
    font_name: str = "Gill Sans MT",
    space_before: str = "14",
    space_after: str = "30",
    language: str = "es",
):
    """
    Formats a heading to appear on the SAME page as the preceding heading,
    removing forced page breaks and setting appropriate spacing and keep options.
    """
    psr.set("AppliedParagraphStyle", "ParagraphStyle/after_chapter_name_heading")
    psr.set("Justification", "CenterAlign")
    psr.set("FirstLineIndent", "0")
    psr.set("SpaceBefore", str(space_before))
    psr.set("SpaceAfter", str(space_after))
    psr.set("KeepWithNext", "2")
    psr.set("StartParagraph", "Anywhere")
    psr.set("ParagraphBreakType", "Anywhere")
    psr.set("KeepAllLinesTogether", "true")
    psr.set("KeepLinesTogether", "true")

    lang_tag = "$ID/Spanish: Standard" if language == "es" else "$ID/English: USA"
    psr.set("AppliedLanguage", lang_tag)

    # Clean existing children
    for child in list(psr):
        psr.remove(child)

    csr = ET.SubElement(psr, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Bold",
        "PointSize": "16",
        "AppliedLanguage": lang_tag,
    })
    props = ET.SubElement(csr, "Properties")
    app_font = ET.SubElement(props, "AppliedFont", {"type": "string"})
    app_font.text = font_name
    cnt = ET.SubElement(csr, "Content")
    cnt.text = text
    ET.SubElement(csr, "Br")


def sanitize_styles_xml(styles_root: ET.Element):
    """
    Sanitizes ParagraphStyle definitions in Styles.xml so that:
    1. 'after_chapter_name_heading' NEVER carries StartParagraph='NextPage' or ParagraphBreakType='NextPage'
    2. 'chapter_name' is CenterAlign with FirstLineIndent=0
    3. 'Sub-heading' keeps with next and is CenterAlign
    """
    for cs in styles_root.iter():
        if cs.tag.endswith("ParagraphStyle"):
            self_id = cs.attrib.get("Self", "")
            if "after_chapter_name_heading" in self_id:
                cs.attrib["StartParagraph"] = "Anywhere"
                cs.attrib["ParagraphBreakType"] = "Anywhere"
                cs.set("SpaceBefore", "14")
                cs.set("SpaceAfter", "24")
                cs.set("KeepWithNext", "2")
                cs.set("Justification", "CenterAlign")
                cs.set("FirstLineIndent", "0")
            elif "chapter_name" in self_id and "after" not in self_id:
                cs.set("Justification", "CenterAlign")
                cs.set("FirstLineIndent", "0")
            elif "sub-heading" in self_id.lower():
                cs.set("Justification", "CenterAlign")
                cs.set("KeepWithNext", "2")


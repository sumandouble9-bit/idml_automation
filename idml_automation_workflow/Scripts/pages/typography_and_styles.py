"""
Typography and Styles Module:
Implements:
- Task 6: Apply correct font family (Palatino Linotype) and font size (9.65pt) to body text
- Task 7: Restore bold formatting wherever bold character styles are applied
- Task 8: Restore italic formatting wherever italic character styles are applied
- Task 11: Separate chapter number and chapter title when they appear on the same run-on line
- Task 12: Preserve correct H1, H2, H3 and other heading styles and text position (center, left, right)
- Task 13: Restore superscript formatting for footnote/reference markers
- Task 14: Restore subscript formatting wherever used
- Task 15: Remove/merge duplicate Bold, Italic, Underline and All Caps character styles
- Task 16: Ensure correct Bold/Italic/Underline/All Caps character styles apply intended formatting
- Task 17: Verify Underline and All Caps formatting throughout the book
- Task 18: Verify index content formatting and spacing
- Task 19: Verify footnote content formatting and placement
"""

import copy
import html
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.idml_utils import (
    content_text,
    copy_named_styles,
    find_main_story,
    lname,
    sync_fonts,
    write_xml,
    get_epub_dir,
    load_epub_heading_hierarchy,
)
from core.heading_classifier import (
    normalize_heading_str,
    is_part_or_book_heading,
    is_chapter_heading,
    is_frontmatter_or_backmatter,
    extract_heading_number,
    split_runon_heading,
    should_pair_headings,
    apply_paired_heading_format,
    sanitize_styles_xml,
)

# Canonical character style mappings
CANONICAL_CHAR_STYLES = {
    "bold": "CharacterStyle/boldtext",
    "italic": "CharacterStyle/italicalign",
    "underline": "CharacterStyle/underlinalign",
    "upper": "CharacterStyle/upper",
}

MERGE_MAP = {
    # Bold variants (Task 8: delete and merge b -> boldtext)
    "CharacterStyle/b": "CharacterStyle/boldtext",
    "CharacterStyle/bold": "CharacterStyle/boldtext",
    "CharacterStyle/Bold": "CharacterStyle/boldtext",
    # Italic variants (Task 8: delete and merge i -> italicalign)
    "CharacterStyle/i": "CharacterStyle/italicalign",
    "CharacterStyle/HTML Cite": "CharacterStyle/italicalign",
    "CharacterStyle/Emphasis": "CharacterStyle/italicalign",
    # Underline variants (Task 8: delete and merge u -> underlinalign)
    "CharacterStyle/u": "CharacterStyle/underlinalign",
    "CharacterStyle/underline": "CharacterStyle/underlinalign",
    "CharacterStyle/Underline": "CharacterStyle/underlinalign",
    # Caps variants
    "CharacterStyle/caps": "CharacterStyle/upper",
    "CharacterStyle/allcaps": "CharacterStyle/upper",
    "CharacterStyle/AllCaps": "CharacterStyle/upper",
}

ELEM_REGEX = r'(?:He|Li|Be|Ne|Na|Mg|Al|Si|Cl|Ar|Ca|Sc|Ti|Cr|Mn|Fe|Co|Ni|Cu|Zn|Ga|Ge|As|Se|Br|Kr|Rb|Sr|Zr|Nb|Mo|Tc|Ru|Rh|Pd|Ag|Cd|In|Sn|Sb|Te|Xe|Cs|Ba|La|Ce|Pr|Nd|Pm|Sm|Eu|Gd|Tb|Dy|Ho|Er|Tm|Yb|Lu|Hf|Ta|Re|Os|Ir|Pt|Au|Hg|Tl|Pb|Bi|Po|At|Rn|Fr|Ra|Ac|Th|Pa|H|B|C|N|O|F|P|S|K|V|Y|I|W|U)'
CHEM_REGEX = re.compile(rf'\b((?:{ELEM_REGEX}\d*){ELEM_REGEX}\d+(?:{ELEM_REGEX}\d*)*|(?:{ELEM_REGEX}\d+){ELEM_REGEX}+(?:{ELEM_REGEX}\d*)*|\b(?:H2|O2|N2)\b)\b')
REF_MARKER_REGEX = re.compile(r'(\[\d{1,4}[a-z]?\]|\[[ivxLCDM]+\]|\[[\*\u2020\u2021]\])')


def _tokenize_chem(txt):
    """Tokenizes text into (string, is_subscript) tuples for chemical formula digits."""
    tokens = []
    last_end = 0
    for m in CHEM_REGEX.finditer(txt):
        start, end = m.span(1)
        if start > last_end:
            tokens.append((txt[last_end:start], False))
        formula = m.group(1)
        for part in re.split(r"(\d+)", formula):
            if not part:
                continue
            if re.match(r"^\d+$", part):
                tokens.append((part, True))
            else:
                tokens.append((part, False))
        last_end = end
    if last_end < len(txt):
        tokens.append((txt[last_end:], False))
    return tokens



def _create_page_break_spacer():
    """Clean page-break spacer paragraph with single Br and no soft breaks or blank returns."""
    spacer_psr = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/Normal",
    })
    csr_brk = ET.SubElement(spacer_psr, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "ParagraphBreakType": "NextPage",
    })
    ET.SubElement(csr_brk, "Br")
    return spacer_psr


def _is_page_break_spacer(element):
    """Check if element is already a clean page-break spacer paragraph."""
    if lname(element.tag) != "ParagraphStyleRange":
        return False
    # A paragraph containing a Table is NEVER a page break spacer!
    if any(lname(c.tag) == "Table" for c in element.iter()):
        return False
    # A paragraph containing real text is NEVER a page break spacer!
    txt = content_text(element).replace("\u2028", "").replace("\ufeff", "").strip()
    if txt:
        return False
    for c in element.iter():
        if c.attrib.get("ParagraphBreakType") == "NextPage":
            return True
    return False


def _is_blank_page_spacer(element):
    """Check if element is a dedicated blank page spacer paragraph."""
    if lname(element.tag) != "ParagraphStyleRange":
        return False
    return "\ufeff" in content_text(element)


def _apply_heading_page_break(psr, parent):
    """Cleans preceding empty paragraphs and redundant page break spacers before psr; StartParagraph='NextPage' natively breaks to the new page."""
    if parent is None:
        return
    try:
        idx = list(parent).index(psr)
        while idx > 0:
            prev_child = list(parent)[idx - 1]
            if any(lname(c.tag) == "Table" for c in prev_child.iter()):
                break
            if lname(prev_child.tag) == "ParagraphStyleRange":
                if _is_blank_page_spacer(prev_child):
                    break
                prev_txt = content_text(prev_child).replace("\u2028", "").replace("\ufeff", "").strip()
                if not prev_txt or _is_page_break_spacer(prev_child):
                    parent.remove(prev_child)
                    idx -= 1
                else:
                    break
            else:
                break
        # Strip trailing NextPage on the preceding non-empty paragraph to eliminate blank pages
        if idx > 0:
            prev_child = list(parent)[idx - 1]
            if not _is_blank_page_spacer(prev_child):
                if prev_child.attrib.get("ParagraphBreakType") == "NextPage":
                    del prev_child.attrib["ParagraphBreakType"]
                for c in prev_child.iter():
                    if c.attrib.get("ParagraphBreakType") == "NextPage":
                        del c.attrib["ParagraphBreakType"]
    except ValueError:
        pass


def _apply_preface_page_break(psr, parent):
    """Cleans preceding empty paragraphs and redundant page break spacers before preface; StartParagraph='NextPage' natively breaks to the new page."""
    if parent is None:
        return
    try:
        idx = list(parent).index(psr)
        while idx > 0:
            prev_child = list(parent)[idx - 1]
            if any(lname(c.tag) == "Table" for c in prev_child.iter()):
                break
            if lname(prev_child.tag) == "ParagraphStyleRange":
                if _is_blank_page_spacer(prev_child):
                    break
                prev_txt = content_text(prev_child).replace("\u2028", "").replace("\ufeff", "").strip()
                if not prev_txt or _is_page_break_spacer(prev_child):
                    parent.remove(prev_child)
                    idx -= 1
                else:
                    break
            else:
                break
        if idx > 0:
            prev_child = list(parent)[idx - 1]
            if not _is_blank_page_spacer(prev_child):
                if prev_child.attrib.get("ParagraphBreakType") == "NextPage":
                    del prev_child.attrib["ParagraphBreakType"]
                for c in prev_child.iter():
                    if c.attrib.get("ParagraphBreakType") == "NextPage":
                        del c.attrib["ParagraphBreakType"]
    except ValueError:
        pass


def _ensure_font_prop(csr, font_name, point_size=None, leading=None):
    props = next((c for c in csr if lname(c.tag) == "Properties"), None)
    if props is None:
        props = ET.Element(csr.tag.replace("CharacterStyleRange", "Properties"))
        csr.insert(0, props)
    af = next((c for c in props if lname(c.tag) == "AppliedFont"), None)
    if af is None:
        af = ET.Element(props.tag.replace("Properties", "AppliedFont"))
        af.set("type", "string")
        props.append(af)
    af.text = font_name
    if point_size is not None:
        csr.set("PointSize", str(point_size))
    if leading is not None:
        ld = next((c for c in props if lname(c.tag) == "Leading"), None)
        if ld is None:
            ld = ET.Element(props.tag.replace("Properties", "Leading"))
            ld.set("type", "unit")
            props.append(ld)
        ld.text = str(leading)


def _split_soft_lines(psr):
    """Visual lines of a paragraph, split at <Br> forced breaks AND   soft
    breaks. Verse/poetry = several short forced lines; such paragraphs must be set
    ragged-left (LeftAlign), never justified, or InDesign stretches the words."""
    lines, cur = [], ""
    for e in psr.iter():
        tag = lname(e.tag)
        if tag == "Content" and e.text:
            cur += e.text
        elif tag == "Br":
            lines.append(cur); cur = ""
    if cur:
        lines.append(cur)
    out = []
    for seg in lines:
        out.extend(seg.split(" "))
    return [l for l in out if l.strip()]


def _is_true_verse(psr):
    """True ONLY for genuine verse/poetry: three or more forced lines where
    (almost) every line is short. A prose paragraph that merely contains one
    forced break (an epigraph attribution before the body, or a break right
    after a heading) is NOT verse and must stay justified."""
    lines = _split_soft_lines(psr)
    if len(lines) < 3:
        return False
    short = [l for l in lines if len(l.strip()) < 55]
    long_ = [l for l in lines if len(l.strip()) > 80]
    return len(short) >= 3 and len(short) >= len(lines) - 1 and not long_


def _enforce_paragraph_style_font(ps, font_name="Palatino Linotype", point_size="9.65", leading="12"):
    """Enforces font family, point size, and leading in a ParagraphStyle definition."""
    ps.set("PointSize", str(point_size))
    props = next((c for c in ps if lname(c.tag) == "Properties"), None)
    if props is None:
        props = ET.Element(ps.tag.replace("ParagraphStyle", "Properties"))
        ps.insert(0, props)
    af = next((c for c in props if lname(c.tag) == "AppliedFont"), None)
    if af is None:
        af = ET.Element(props.tag.replace("Properties", "AppliedFont"))
        af.set("type", "string")
        props.append(af)
    af.text = font_name
    ld = next((c for c in props if lname(c.tag) == "Leading"), None)
    if ld is None:
        ld = ET.Element(props.tag.replace("Properties", "Leading"))
        ld.set("type", "unit")
        props.append(ld)
    ld.text = str(leading)


def _format_clean_heading(psr, style_name, font_name, text_content, space_after="30", point_size=None):
    """Rebuilds a heading PSR with single clean CSR, font, bold, centered, and space after."""
    psr.set("AppliedParagraphStyle", style_name)
    psr.set("Justification", "CenterAlign")
    psr.set("FirstLineIndent", "0")
    _page_chapter = (("chapter" in style_name.lower() and "after" not in style_name.lower()) or "master_chapter" in style_name.lower())
    psr.set("SpaceBefore", "14.5" if _page_chapter else "3")
    psr.set("SpaceAfter", str(space_after))
    psr.set("KeepWithNext", "2")
    if "chapter" in style_name.lower() and "after" not in style_name.lower():
        psr.set("StartParagraph", "NextPage")
        psr.set("KeepAllLinesTogether", "true")
        psr.set("KeepLinesTogether", "true")
    elif "after" in style_name.lower():
        psr.set("StartParagraph", "Anywhere")
        psr.set("ParagraphBreakType", "Anywhere")
        psr.set("KeepAllLinesTogether", "true")
        psr.set("KeepLinesTogether", "true")
    else:
        if "StartParagraph" in psr.attrib:
            del psr.attrib["StartParagraph"]
        psr.set("KeepAllLinesTogether", "true")
        psr.set("KeepLinesTogether", "true")
    if "ParagraphBreakType" in psr.attrib and "after" not in style_name.lower():
        del psr.attrib["ParagraphBreakType"]

    for child in list(psr):
        psr.remove(child)

    pt_size = point_size
    if pt_size is None:
        pt_size = "16"

    csr = ET.SubElement(psr, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Bold",
        "PointSize": str(pt_size),
    })
    _ensure_font_prop(csr, font_name, point_size=pt_size)
    cnt = ET.SubElement(csr, "Content")
    cnt.text = text_content
    ET.SubElement(csr, "Br")


def _clean_subheading_page_break(psr, parent):
    """
    Ensures a subheading or same-page heading DOES NOT start on a separate page.
    Removes any preceding NextPage page break spacer and clears ParagraphBreakType/StartParagraph.
    """
    if "ParagraphBreakType" in psr.attrib:
        del psr.attrib["ParagraphBreakType"]
    if "StartParagraph" in psr.attrib:
        del psr.attrib["StartParagraph"]
    for c in psr.iter():
        if "ParagraphBreakType" in c.attrib:
            del c.attrib["ParagraphBreakType"]
        if "StartParagraph" in c.attrib:
            del c.attrib["StartParagraph"]
    psr.set("KeepWithNext", "2")
    psr.set("KeepLinesTogether", "true")

    if parent is None:
        return

    try:
        idx = list(parent).index(psr)
        while idx > 0:
            prev_child = list(parent)[idx - 1]
            if any(lname(c.tag) == "Table" for c in prev_child.iter()):
                break
            if lname(prev_child.tag) == "ParagraphStyleRange":
                if _is_page_break_spacer(prev_child) and not _is_blank_page_spacer(prev_child):
                    parent.remove(prev_child)
                    idx -= 1
                else:
                    break
            else:
                break
        if idx > 0:
            prev_child = list(parent)[idx - 1]
            if prev_child.attrib.get("ParagraphBreakType") == "NextPage":
                del prev_child.attrib["ParagraphBreakType"]
            for c in prev_child.iter():
                if c.attrib.get("ParagraphBreakType") == "NextPage":
                    del c.attrib["ParagraphBreakType"]
    except ValueError:
        pass


def _normalize_table_content(table_elem, epub_fmt=None):
    """Cleans up fonts, font size, corrupted superscripts, and strips rogue italics inside Table cells, binding styling to EPUB."""
    lower_italics = set()
    lower_bolds = set()
    if epub_fmt:
        lower_italics = {re.sub(r"\s+", " ", s).strip().lower() for s in epub_fmt.get("italic", set()) if s}
        lower_bolds = {re.sub(r"\s+", " ", s).strip().lower() for s in epub_fmt.get("bold", set()) if s}

    for cell in table_elem.iter():
        if lname(cell.tag) == "Cell":
            for c_psr in cell.iter():
                if lname(c_psr.tag) == "ParagraphStyleRange":
                    c_psr.set("FirstLineIndent", "0")
                    for c_csr in c_psr.iter():
                        if lname(c_csr.tag) == "CharacterStyleRange":
                            _ensure_font_prop(c_csr, "Palatino Linotype", point_size="9.65", leading="12")
                            pos = c_csr.attrib.get("Position", "")
                            if pos == "Superscript":
                                txt = "".join(c.text or "" for c in c_csr.iter() if lname(c.tag) == "Content").strip()
                                if not REF_MARKER_REGEX.match(txt):
                                    del c_csr.attrib["Position"]

                            c_txt = "".join(c.text or "" for c in c_csr.iter() if lname(c.tag) == "Content").strip()
                            clean_c = re.sub(r"\s+", " ", c_txt).strip().lower()

                            is_epub_it = bool(clean_c and (clean_c in lower_italics or any(clean_c in it or it in clean_c for it in lower_italics if len(it) >= 3 and len(clean_c) >= 3)))
                            is_epub_bd = bool(clean_c and (clean_c in lower_bolds or any(clean_c in bd or bd in clean_c for bd in lower_bolds if len(bd) >= 3 and len(clean_c) >= 3)))

                            if is_epub_it:
                                c_csr.set("AppliedCharacterStyle", "CharacterStyle/italic")
                                c_csr.set("FontStyle", "Italic")
                            elif is_epub_bd:
                                c_csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                                c_csr.set("FontStyle", "Bold")
                            else:
                                curr_cs = c_csr.attrib.get("AppliedCharacterStyle", "")
                                if curr_cs in ("CharacterStyle/italicalign", "CharacterStyle/italic"):
                                    c_csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                                c_csr.set("FontStyle", "Regular")



def _format_clean_subheading(psr, font_name, text_content, space_before="18", space_after="12", point_size=14):
    """Formats a subheading to flow cleanly inline on the same page with proper spacing."""
    psr.set("AppliedParagraphStyle", "ParagraphStyle/Sub-heading")
    psr.set("Justification", "CenterAlign")
    psr.set("FirstLineIndent", "0")
    psr.set("SpaceBefore", str(space_before))
    psr.set("SpaceAfter", str(space_after))
    psr.set("KeepWithNext", "1")
    if "ParagraphBreakType" in psr.attrib:
        del psr.attrib["ParagraphBreakType"]

    for child in list(psr):
        psr.remove(child)

    pt_size = str(point_size)
    csr = ET.SubElement(psr, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Bold",
        "PointSize": pt_size,
    })
    _ensure_font_prop(csr, font_name, point_size=pt_size, leading=str(int(float(pt_size)) + 4))
    cnt = ET.SubElement(csr, "Content")
    cnt.text = text_content
    ET.SubElement(csr, "Br")


ROMAN_MAP = {
    'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10,
    'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15, 'xvi': 16, 'xvii': 17, 'xviii': 18,
    'xix': 19, 'xx': 20, 'xxi': 21, 'xxii': 22, 'xxiii': 23, 'xxiv': 24, 'xxv': 25, 'xxvi': 26,
    'xxvii': 27, 'xxviii': 28, 'xxix': 29, 'xxx': 30, 'xxxi': 31, 'xxxii': 32, 'xxxiii': 33,
    'xxxiv': 34, 'xxxv': 35, 'xxxvi': 36, 'xxxvii': 37, 'xxxviii': 38, 'xxxix': 39, 'xl': 40,
    'xli': 41, 'xlii': 42, 'xliii': 43, 'xliv': 44, 'xlv': 45, 'xlvi': 46, 'xlvii': 47,
    'xlviii': 48, 'xlix': 49, 'l': 50, 'li': 51, 'lii': 52, 'liii': 53, 'liv': 54, 'lv': 55,
    'lvi': 56, 'lvii': 57, 'lviii': 58, 'lix': 59, 'lx': 60, 'lxi': 61, 'lxii': 62, 'lxiii': 63,
    'lxiv': 64, 'lxv': 65, 'lxvi': 66, 'lxvii': 67, 'lxviii': 68, 'lxix': 69, 'lxx': 70
}


def _extract_chap_number(text):
    """Extracts integer chapter number from text (Roman or Arabic)."""
    m = re.search(r'\b(?:chapter|chap\.?)\s+([ivxlcdm0-9]+)\b', text, re.I)
    if m:
        val = m.group(1).lower()
        if val.isdigit():
            return int(val)
        if val in ROMAN_MAP:
            return ROMAN_MAP[val]
    m2 = re.match(r'^([ivxlcdm]+)\b', text, re.I)
    if m2:
        val = m2.group(1).lower()
        if val in ROMAN_MAP:
            return ROMAN_MAP[val]
    return None


def _normalize_heading_str(s):
    """Normalizes heading text for robust matching against TOC entries and EPUB headings."""
    if not s:
        return ""
    s = s.split('\t')[0]  # strip tab and page number
    s = html.unescape(s)
    s = re.sub(r'[\u2014\u2013\-\:\_\/\.\,]+', ' ', s)
    s = re.sub(r'[\r\n\u2028]+', ' ', s)
    s = re.sub(r'[^\w\s]', '', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def _extract_doc_toc_entries(target_dir):
    """
    Extracts all Table of Contents (TOC) entries from the document's stories.
    Returns:
      (raw_entries, norm_entries, chap_numbers)
    """
    stories_dir = Path(target_dir) / "Stories"
    entries = []
    if stories_dir.is_dir():
        for sf in stories_dir.glob("*.xml"):
            try:
                r = ET.parse(sf).getroot()
            except Exception:
                continue
            for psr in r.iter():
                if lname(psr.tag) == "ParagraphStyleRange":
                    st = psr.attrib.get("AppliedParagraphStyle", "")
                    if any(k in st.lower() for k in ["toc", "content_ch", "tochead", "tocch"]):
                        hl = [h for h in psr.iter() if lname(h.tag) == "HyperlinkTextSource"]
                        if hl:
                            for h in hl:
                                t = content_text(h).strip()
                                if t:
                                    for part in re.split(r"\t\d*", t):
                                        part = part.strip()
                                        if part:
                                            entries.append(part)
                        else:
                            txt = content_text(psr).strip()
                            if txt:
                                for line in re.split(r"[\r\n\u2028]+", txt):
                                    line = line.strip()
                                    if line:
                                        for part in re.split(r"\t\d*", line):
                                            part = part.strip()
                                            if part:
                                                entries.append(part)

    raw_entries = [
        e for e in entries
        if not any(k in e.lower() for k in ["table of contents", "contents", "double 9 books"])
    ]
    norm_entries = set(_normalize_heading_str(e) for e in raw_entries if _normalize_heading_str(e))
    chap_numbers = set()
    for e in raw_entries:
        for m in re.finditer(r"\b(?:chapter|chap\.?)\s+([ivxlcdm0-9]+)\b", e, re.I):
            val = m.group(1).lower()
            if val.isdigit():
                chap_numbers.add(int(val))
            elif val in ROMAN_MAP:
                chap_numbers.add(ROMAN_MAP[val])
        c = _extract_chap_number(e)
        if c is not None:
            chap_numbers.add(c)
    return raw_entries, norm_entries, chap_numbers


def _clean_chapter_runon(text):
    """
    Separates chapter numbers and chapter titles when on the same run-on line.
    Returns:
      (book_heading, chapter_heading, changed)
    """
    cleaned = text.strip().replace("\r", " ").replace("\n", " ")

    # 1. Book header + Chapter header run-on
    m_book_chap = re.match(
        r"^(BOOK\s+[^\n\r]+?)(CHAPTER\s+[IVXLCDM0-9]+.*)$",
        cleaned,
        re.I,
    )
    if m_book_chap:
        book_raw = m_book_chap.group(1).strip()
        chap_raw = m_book_chap.group(2).strip()
        # Clean book_raw
        m_b = re.match(r"^(BOOK\s+[^\u2014\u2013\-]+?)[\u2014\u2013\-]\s*(.+)$", book_raw, re.I)
        book_txt = f"{m_b.group(1).strip()}\u2028{m_b.group(2).strip()}" if m_b else book_raw
        # Clean chap_raw
        _, chap_txt, _ = _clean_chapter_runon(chap_raw)
        return book_txt, chap_txt, True

    # 2. Part header + Chapter header run-on
    m_part_chap = re.match(
        r"^(PART\s+[^\n\r]+?)(CHAPTER\s+[IVXLCDM0-9]+.*)$",
        cleaned,
        re.I,
    )
    if m_part_chap:
        part_raw = m_part_chap.group(1).strip()
        chap_raw = m_part_chap.group(2).strip()
        _, chap_txt, _ = _clean_chapter_runon(chap_raw)
        return part_raw, chap_txt, True

    # 3. Chapter Num + Title with punctuation/dash separator
    m_chap = re.match(
        r"^(CHAPTER\s+[IVXLCDM0-9]+)\s*[\.\:\-\u2013\u2014]\s*(.+)$",
        cleaned,
        re.I,
    )
    if m_chap:
        num = m_chap.group(1).strip()
        title = m_chap.group(2).strip()
        return None, f"{num}\u2028{title}", True

    # 4. Chapter Num + Title with space only (e.g. 'CHAPTER I THE SCOPE')
    m_chap_sp = re.match(
        r"^(CHAPTER\s+[IVXLCDM0-9]+)\s+([A-Z\s]{3,}.*)$",
        cleaned,
    )
    if m_chap_sp:
        num = m_chap_sp.group(1).strip()
        title = m_chap_sp.group(2).strip()
        return None, f"{num}\u2028{title}", True

    # 5. Roman Numeral + Title (e.g. 'I ROBINSON WITH HIS PARENTS')
    m_rom = re.match(r"^([IVXLCDM]+)\s+([A-Z\s]{4,}.*)$", cleaned)
    if m_rom:
        num = m_rom.group(1).strip()
        title = m_rom.group(2).strip()
        return None, f"{num}\u2028{title}", True

    # 5b. Roman Numeral + Title run-on (without space, e.g. 'IROBINSON', 'VTHE')
    m_rom_nosp = re.match(
        r"^(XLII|XLI|XL|XXXIX|XXXVIII|XXXVII|XXXVI|XXXV|XXXIV|XXXIII|XXXII|XXXI|XXX|XXIX|XXVIII|XXVII|XXVI|XXV|XXIV|XXIII|XXII|XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)(ROBINSON|THE|ANOTHER|DELIVERANCE|GETTING|SAVING|A\s+|HOW\s+)(.*)$",
        cleaned,
    )
    if m_rom_nosp:
        num = m_rom_nosp.group(1).strip()
        title = (m_rom_nosp.group(2) + m_rom_nosp.group(3)).strip()
        return None, f"{num}\u2028{title}", True

    # 6. Opticks Part run-on
    m_opt = re.match(r"^(THE FIRST BOOK OF OPTICKS)\s*(PART\s+[IVXLCDM0-9]+.*)$", cleaned, re.I)
    if m_opt:
        return m_opt.group(1).strip(), m_opt.group(2).strip(), True

    return None, cleaned, False


def _load_epub_underlines(target_dir, book_name=None):
    """
    Extracts legitimate underline text strings from the corresponding EPUB in epub_input_files/.
    If no specific EPUB matches, loads the union of valid underline strings across all EPUBs.
    """
    epub_dir = SCRIPTS_DIR.parent / "epub_input_files"
    if not epub_dir.exists():
        epub_dir = Path(target_dir).resolve().parent.parent / "epub_input_files"

    valid_strings = set()
    if not epub_dir.exists():
        return valid_strings

    target_epubs = []
    # 1. Match by book_name if provided
    if book_name:
        clean_name = re.sub(r'(_formatted|\.idml)$', '', str(book_name), flags=re.I).strip()
        matched = list(epub_dir.glob(f"*{clean_name}*.epub"))
        if matched:
            target_epubs.extend(matched)

    # 2. Check for ISBN in target_dir Stories if not matched
    if not target_epubs:
        stories_dir = Path(target_dir) / "Stories"
        if stories_dir.exists():
            for sp in stories_dir.glob("*.xml"):
                try:
                    txt = sp.read_text(encoding="utf-8", errors="ignore")
                    m = re.findall(r"978\d{10}", txt)
                    for isbn in m:
                        matched = list(epub_dir.glob(f"*{isbn}*.epub"))
                        if matched:
                            target_epubs.extend(matched)
                            break
                    if target_epubs:
                        break
                except Exception:
                    pass

    # 3. Fallback: inspect all EPUBs in the directory
    if not target_epubs:
        target_epubs = list(epub_dir.glob("*.epub"))

    for ep in target_epubs:
        try:
            with zipfile.ZipFile(ep) as z:
                for name in z.namelist():
                    if name.endswith((".html", ".xhtml", ".htm")):
                        raw = z.read(name).decode("utf-8", errors="ignore")
                        u_tags = re.findall(r"<u\b[^>]*>(.*?)</u>", raw, re.DOTALL | re.IGNORECASE)
                        for u in u_tags:
                            clean = re.sub(r"<[^>]+>", "", u)
                            clean = html.unescape(clean).replace("\xa0", " ").strip().lower()
                            if clean:
                                valid_strings.add(clean)
        except Exception:
            pass

    return valid_strings


def _load_epub_tables(target_dir, book_name=None):
    """
    Extracts table metadata and tags from the corresponding EPUB in epub_input_files/.
    Extracts table tag IDs, class attributes, and adjacent headings to ensure tables
    and adjacent headers are faithfully preserved.
    """
    epub_dir = SCRIPTS_DIR.parent / "epub_input_files"
    if not epub_dir.exists():
        epub_dir = Path(target_dir).resolve().parent.parent / "epub_input_files"

    tables_info = []
    if not epub_dir.exists():
        return tables_info

    target_epubs = []
    if book_name:
        clean_name = re.sub(r'(_formatted|\.idml)$', '', str(book_name), flags=re.I).strip()
        matched = list(epub_dir.glob(f"*{clean_name}*.epub"))
        if matched:
            target_epubs.extend(matched)

    if not target_epubs:
        stories_dir = Path(target_dir) / "Stories"
        if stories_dir.exists():
            for sp in stories_dir.glob("*.xml"):
                try:
                    txt = sp.read_text(encoding="utf-8", errors="ignore")
                    m = re.findall(r"978\d{10}", txt)
                    for isbn in m:
                        matched = list(epub_dir.glob(f"*{isbn}*.epub"))
                        if matched:
                            target_epubs.extend(matched)
                            break
                    if target_epubs:
                        break
                except Exception:
                    pass

    if not target_epubs:
        target_epubs = list(epub_dir.glob("*.epub"))

    for ep in target_epubs:
        try:
            with zipfile.ZipFile(ep) as z:
                for name in z.namelist():
                    if name.endswith((".html", ".xhtml", ".htm")):
                        raw = z.read(name).decode("utf-8", errors="ignore")
                        for m in re.finditer(r"<table\b([^>]*)>(.*?)</table>", raw, re.DOTALL | re.IGNORECASE):
                            attrs = m.group(1)
                            content = m.group(2)
                            id_m = re.search(r'id=[\'"]([^\'"]+)[\'"]', attrs, re.I)
                            cls_m = re.search(r'class=[\'"]([^\'"]+)[\'"]', attrs, re.I)
                            tbl_id = id_m.group(1) if id_m else None
                            tbl_cls = cls_m.group(1) if cls_m else None
                            end_pos = m.end()
                            after_snippet = raw[end_pos: min(len(raw), end_pos + 200)]
                            m_head = re.search(r'<p\s+class=[\'"](head\d?|sub-?heading)[\'"][^>]*>(.*?)</p>', after_snippet, re.DOTALL | re.I)
                            head_text = None
                            if m_head:
                                head_text = re.sub(r'<[^>]+>', '', m_head.group(2)).strip()
                            tables_info.append({
                                "epub": ep.name,
                                "file": name,
                                "id": tbl_id,
                                "class": tbl_cls,
                                "after_heading": head_text,
                                "content_snippet": re.sub(r'<[^>]+>', ' ', content)[:60].strip(),
                            })
        except Exception:
            pass

    return tables_info


def process_stories(target_dir, book_name=None):
    stories_dir = Path(target_dir) / "Stories"
    bold_fixed = 0
    italic_fixed = 0
    underline_fixed = 0
    caps_fixed = 0
    super_fixed = 0
    sub_fixed = 0
    chapters_separated = 0
    body_styled = 0
    footnotes_formatted = 0

    # Load legitimate underline strings and table metadata from reference EPUB(s)
    epub_underlines = _load_epub_underlines(target_dir, book_name=book_name)
    epub_tables = _load_epub_tables(target_dir, book_name=book_name)

    # Load EPUB heading hierarchy: h1 (new page) vs h2/h3 (same page)
    res = load_epub_heading_hierarchy(book_name or Path(target_dir).parent.stem)
    if len(res) == 4:
        epub_h1_set, epub_sub_set, epub_toc, epub_h1_meta = res
    else:
        epub_h1_set, epub_sub_set, epub_toc = res
        epub_h1_meta = {"chapter_map": {}, "same_chap_pairs": set()}
    epub_h1_map = epub_h1_meta.get("chapter_map", {})
    same_chap_pairs = epub_h1_meta.get("same_chap_pairs", set())

    # Extract Table of Contents entries from the document
    toc_raw, toc_norms, toc_chaps = _extract_doc_toc_entries(target_dir)
    for norm_e, raw_e in epub_toc:
        toc_norms.add(norm_e)

    epub_fmt = None
    try:
        from core.epub_style_enricher import extract_epub_formatting, find_matching_epub
        epub_f = find_matching_epub(book_name or target_dir)
        if epub_f:
            epub_fmt = extract_epub_formatting(epub_f)
    except Exception:
        pass

    for sp in sorted(stories_dir.glob("*.xml")):
        # NEVER touch dedicated Title Page or Copyright Page stories!
        if (
            sp.name in ["Story_u_title_story.xml", "Story_u_copyright_story.xml"]
            or "copyright" in sp.name.lower()
            or "title_story" in sp.name.lower()
        ):
            continue

        try:
            root = ET.parse(sp).getroot()
        except Exception:
            continue

        changed = False
        psrs = [e for e in root.iter() if lname(e.tag) == "ParagraphStyleRange"]
        if len(psrs) < 5:
            continue

        # Normalize all tables in the story against EPUB
        for tbl in root.iter():
            if lname(tbl.tag) == "Table":
                _normalize_table_content(tbl, epub_fmt=epub_fmt)

        parent_map = {}
        for p in root.iter():
            for child in p:
                parent_map[child] = p

        in_preface = False
        preface_para_count = 0
        needs_page_break_after_preface = False
        in_footnotes = False
        last_h1_norm = None
        last_h1_text = None
        last_h1_num = None
        seen_body_since_h1 = False

        for psr in list(psrs):
            pstyle = psr.attrib.get("AppliedParagraphStyle", "")
            ptxt = content_text(psr).strip()

            # Pre-split compound paragraphs containing both a Table and other text
            has_table = any(lname(c.tag) == "Table" for c in psr.iter())
            if has_table:
                # A block quote can embed its image Table INSIDE a single
                # CharacterStyleRange, with Content both before and after the table.
                # The pre/table/post classifier below splits by CSR, so pre-split any
                # CSR at its Table boundaries to keep the table's in-flow position.
                for _csr in list(psr):
                    if lname(_csr.tag) != "CharacterStyleRange":
                        continue
                    _kids = list(_csr)
                    if not any(lname(_k.tag) == "Table" for _k in _kids):
                        continue
                    _non_tbl = [_k for _k in _kids if lname(_k.tag) not in ("Table", "Properties")]
                    if not _non_tbl:
                        continue
                    _csr_attrib = dict(_csr.attrib)
                    _props = [_k for _k in _kids if lname(_k.tag) == "Properties"]
                    _segments, _cur = [], []
                    for _k in _kids:
                        if lname(_k.tag) == "Properties":
                            continue
                        if lname(_k.tag) == "Table":
                            if _cur:
                                _segments.append(("content", _cur)); _cur = []
                            _segments.append(("table", _k))
                        else:
                            _cur.append(_k)
                    if _cur:
                        _segments.append(("content", _cur))
                    _at = list(psr).index(_csr)
                    psr.remove(_csr)
                    for _stype, _payload in _segments:
                        _ncsr = ET.Element("CharacterStyleRange", _csr_attrib)
                        for _pr in _props:
                            _ncsr.append(copy.deepcopy(_pr))
                        if _stype == "content":
                            for _node in _payload:
                                _ncsr.append(_node)
                        else:
                            _ncsr.append(_payload)
                        psr.insert(_at, _ncsr); _at += 1
                segs = []
                for _c in list(psr):
                    if lname(_c.tag) != "CharacterStyleRange":
                        continue
                    if any(lname(_s.tag) == "Table" for _s in _c.iter()):
                        for _tbl in _c.iter():
                            if lname(_tbl.tag) == "Table":
                                _normalize_table_content(_tbl, epub_fmt=epub_fmt)
                        segs.append(["table", [_c]])
                    elif segs and segs[-1][0] == "content":
                        segs[-1][1].append(_c)
                    else:
                        segs.append(["content", [_c]])

                def _seg_text(_csrs):
                    return "".join(
                        _cc.text or ""
                        for _csr in _csrs
                        for _cc in _csr.iter()
                        if lname(_cc.tag) == "Content"
                    ).strip()

                parent = parent_map.get(psr)
                _has_content = any(s[0] == "content" and _seg_text(s[1]) for s in segs)
                _has_table = any(s[0] == "table" for s in segs)
                if parent is not None and _has_content and _has_table:
                    _orig_style = psr.attrib.get("AppliedParagraphStyle", "")
                    _is_block = any(k in _orig_style.lower() for k in ("quote", "block", "verse", "poem", "extract", "epigraph"))
                    idx = list(parent).index(psr)
                    for child in list(psr):
                        psr.remove(child)
                    ins_idx = idx
                    _seen_table = False
                    for _stype, _csrs in segs:
                        if _stype == "table":
                            seg_psr = ET.Element("ParagraphStyleRange", {
                                "AppliedParagraphStyle": "ParagraphStyle/body_text",
                                "Justification": "LeftAlign",
                                "FirstLineIndent": "0",
                                "SpaceBefore": "6",
                                "SpaceAfter": "6",
                            })
                            _seen_table = True
                        else:
                            _txt = _seg_text(_csrs)
                            if not _txt:
                                continue
                            if (not _seen_table) or _is_block:
                                seg_attrib = dict(psr.attrib)
                                if _is_block:
                                    seg_attrib["Justification"] = "LeftAlign"
                            else:
                                seg_attrib = {
                                    "AppliedParagraphStyle": "ParagraphStyle/body_text",
                                    "FirstLineIndent": "18",
                                    "SpaceBefore": "1.5",
                                    "SpaceAfter": "3",
                                    "Justification": "LeftAlign" if "\u2028" in _txt else "LeftJustified",
                                }
                            seg_psr = ET.Element("ParagraphStyleRange", seg_attrib)
                        for _c in _csrs:
                            seg_psr.append(_c)
                        _last = None
                        for _c in reversed(list(seg_psr)):
                            if lname(_c.tag) == "CharacterStyleRange":
                                _last = _c
                                break
                        if _last is None or not any(lname(_ch.tag) == "Br" for _ch in _last):
                            _brc = ET.SubElement(seg_psr, "CharacterStyleRange", {
                                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                            })
                            ET.SubElement(_brc, "Br")
                        parent.insert(ins_idx, seg_psr)
                        parent_map[seg_psr] = parent
                        ins_idx += 1
                    parent.remove(psr)
                    changed = True
                    continue

            # Check if this psr is nested inside a Table or Cell
            in_cell_or_table = False
            cur_node = parent_map.get(psr)
            while cur_node is not None:
                if lname(cur_node.tag) in ("Cell", "Table"):
                    in_cell_or_table = True
                    break
                cur_node = parent_map.get(cur_node)

            if in_cell_or_table:
                _cell_style = psr.attrib.get("AppliedParagraphStyle", "").lower()
                _cell_lines = _split_soft_lines(psr)
                _is_verse_cell = _is_true_verse(psr)
                if any(k in _cell_style for k in ["chapter", "sub-heading", "head"]):
                    psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                elif any(k in _cell_style for k in ["block", "quote", "verse", "poem"]) or _is_verse_cell:
                    # Block quote / poem inside a table cell (EPUB <td><p class="block1">)
                    # loses its block indent because table CSS overrides the margin.
                    # Re-apply block indent + ragged-left so it stays a block quote.
                    psr.set("LeftIndent", "39.68503937007875")
                    psr.set("RightIndent", "39.68503937007875")
                    psr.set("FirstLineIndent", "0")
                    psr.set("Justification", "LeftAlign")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                continue

            # Check for footnote / back-matter heading (FOOTNOTES, NOTES, ENDNOTES, APPENDIX, EPILOGUE, etc.)
            is_backmatter_heading = (
                not has_table
                and re.match(r"^(FOOT-?NOTES?|END-?NOTES?|NOTES?|APPENDIX|EPILOGUE|GLOSSARY|INDEX|BIBLIOGRAPHY)\b:?\.?$", ptxt, re.I)
                and len(ptxt) < 40
            )

            if is_backmatter_heading:
                in_footnotes = bool(re.search(r"^(FOOT-?NOTES?|END-?NOTES?|NOTES?)\b", ptxt, re.I))
                in_preface = False
                needs_page_break_after_preface = False

                # Ensure fresh separate page with reference top-margin sinkage spacer
                parent = parent_map.get(psr)
                _apply_preface_page_break(psr, parent)

                clean_hd = re.sub(r"[:.]+$", "", ptxt).strip()
                _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
                changed = True
                continue

            # Skip front-matter pages (title, copyright, TOC headings and entries, and about the author)
            if any(k in pstyle.lower() for k in ["verso", "copyright", "doublenine", "main_page_title", "toc", "content_ch", "about_the_auther"]):
                continue
            if _is_blank_page_spacer(psr) or _is_page_break_spacer(psr):
                continue
            if "double 9 books" in ptxt.lower():
                continue
            if any(k in ptxt.lower() for k in ["titlecopyright", "start of content", "copyrightcontents"]):
                continue

            # -------------------------------------------------------------
            # IMAGE PLACEHOLDERS: Isolate placeholder, strip hard breaks & captions
            # -------------------------------------------------------------
            if "###Insert" in ptxt:
                # 1. Strip any forced page breaks so images flow naturally below text
                if "ParagraphBreakType" in psr.attrib:
                    del psr.attrib["ParagraphBreakType"]
                if "StartParagraph" in psr.attrib:
                    del psr.attrib["StartParagraph"]
                for c in list(psr.iter()):
                    if "ParagraphBreakType" in c.attrib:
                        del c.attrib["ParagraphBreakType"]

                # 2. Extract the placeholder tag(s): ###Insert ... ###
                matches = re.findall(r"(###Insert\s+.*?###)", ptxt)
                ph_str = " ".join([m.strip() for m in matches]) if matches else ptxt.strip()

                # If the paragraph ALSO holds real body/quote text (not just the
                # placeholder), preserve that text with its original formatting: strip
                # only the placeholder substring(s) from the runs and move the image
                # placeholder(s) into their own centered paragraph right after it. This
                # prevents whole paragraphs being dropped when an image sits inline.
                _non_ph = re.sub(r"###Insert\s+.*?###", "", ptxt)
                _non_ph = re.sub(r"[\s ﻿ ]+", "", _non_ph)
                _img_parent = parent_map.get(psr)
                if matches and len(_non_ph) >= 5 and _img_parent is not None:
                    for _c in psr.iter():
                        if lname(_c.tag) == "Content" and _c.text and "###Insert" in _c.text:
                            _c.text = re.sub(r"###Insert\s+.*?###", "", _c.text)
                    _ph_psr = ET.Element("ParagraphStyleRange", {
                        "AppliedParagraphStyle": "ParagraphStyle/Normal",
                        "Justification": "CenterAlign",
                        "FirstLineIndent": "0",
                        "SpaceBefore": "6",
                        "SpaceAfter": "6",
                    })
                    _ph_csr = ET.SubElement(_ph_psr, "CharacterStyleRange", {
                        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                    })
                    _pc = ET.SubElement(_ph_csr, "Content")
                    _pc.text = ph_str
                    ET.SubElement(_ph_csr, "Br")
                    try:
                        _idx = list(_img_parent).index(psr)
                        _img_parent.insert(_idx + 1, _ph_psr)
                    except ValueError:
                        pass
                    changed = True
                    continue

                # 3. Placeholder-only paragraph: clean children and rebuild a single CSR.
                for child in list(psr):
                    psr.remove(child)

                psr.set("AppliedParagraphStyle", "ParagraphStyle/Normal")
                psr.set("Justification", "CenterAlign")
                psr.set("FirstLineIndent", "0")
                psr.set("SpaceBefore", "6")
                psr.set("SpaceAfter", "6")

                new_csr = ET.SubElement(psr, "CharacterStyleRange", {
                    "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                })
                cnt = ET.SubElement(new_csr, "Content")
                cnt.text = ph_str
                ET.SubElement(new_csr, "Br")
                changed = True
                continue

            # -------------------------------------------------------------
            # PREFACE / PREFATORY NOTE / FOREWORD / INTRODUCTION / PROLOGUE
            # -------------------------------------------------------------
            is_preface = (
                not has_table
                and any(ptxt.lower().startswith(k) for k in [
                    "preface", "prefatory note", "foreword", "introduction", "prologue", "memoir", "biographical sketch"
                ])
                and len(ptxt) < 60
            )

            if is_preface:
                in_preface = True
                in_footnotes = False
                preface_para_count = 0
                parent = parent_map.get(psr)
                _apply_preface_page_break(psr, parent)

                clean_heading = ptxt.upper()
                if "preface" in ptxt.lower():
                    clean_heading = "PREFACE"
                elif "prefatory note" in ptxt.lower():
                    clean_heading = "PREFATORY NOTE"
                _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_heading, space_after="30")
                changed = True
                continue

            # -------------------------------------------------------------
            # BACKMATTER / CONCLUSION / EPILOGUE / APPENDIX / NOTES / INDEX
            # -------------------------------------------------------------
            is_backmatter = (
                not has_table
                and re.match(
                    r"^(CONCLUSION|EPILOGUE|APPENDIX|NOTES?|FOOT-?NOTES?|GLOSSARY|INDEX|BIBLIOGRAPHY|AFTERWORD)\b:?\.?$",
                    ptxt,
                    re.I,
                )
                and len(ptxt) < 40
            )
            if is_backmatter:
                in_footnotes = bool(re.search(r"^(NOTAS|FOOT-?NOTES?|NOTES?)\b", ptxt, re.I))
                in_preface = False
                parent = parent_map.get(psr)
                _apply_preface_page_break(psr, parent)
                clean_hd = re.sub(r"[:.]+$", "", ptxt).strip().upper()
                _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
                changed = True
                continue

            # -------------------------------------------------------------
            # Task 11 & 12: Chapter Headings Separation and Fresh Page Break
            # -------------------------------------------------------------
            is_heading_candidate = (
                not has_table
                and not in_cell_or_table
                and (
                    (
                        any(k in pstyle.lower() for k in ["chap", "head", "sub-heading"])
                        and not any(k in pstyle.lower() for k in ["toc", "verso", "copy", "main_page", "author", "caption"])
                    ) or (
                        re.match(r"^(chapter|book|part|act|scene)\b", ptxt, re.I)
                        and len(ptxt) < 120
                    ) or (
                        re.match(r"^(definitions?|axioms?|propositions?|theory|experiment|questions?)\b:?\.?$", ptxt, re.I)
                        and len(ptxt) < 60
                    ) or (
                        (
                            re.match(r"^(?:[IVXLCDM]+\b\.?\s+[A-Z][A-Z\s]{3,})", ptxt)
                            or re.match(
                                r"^(XLII|XLI|XL|XXXIX|XXXVIII|XXXVII|XXXVI|XXXV|XXXIV|XXXIII|XXXII|XXXI|XXX|XXIX|XXVIII|XXVII|XXVI|XXV|XXIV|XXIII|XXII|XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)(ROBINSON|THE|ANOTHER|DELIVERANCE|GETTING|SAVING|A\s+|HOW\s+)",
                                ptxt,
                            )
                        )
                        and len(ptxt) < 80
                    ) or (
                        "book of opticks" in ptxt.lower()
                        and len(ptxt) < 80
                    ) or (
                        re.match(r"^(camp\s*fire\s*yarn|yarn\s*no|section\b|axiom\b|prop\b|defin\b)", ptxt, re.I)
                        and len(ptxt) < 100
                    )
                )
            )

            if is_heading_candidate:
                book_part, chap_part, was_separated = split_runon_heading(ptxt, lang="en")
                effective_txt = chap_part if was_separated else ptxt
                norm_p = normalize_heading_str(effective_txt)
                norm_p_clean = re.sub(r'[\s\.\-_]+', '', norm_p)
                toc_clean_map = {re.sub(r'[\s\.\-_]+', '', t): t for t in toc_norms}
                epub_h1_clean_map = {re.sub(r'[\s\.\-_]+', '', h): h for h in epub_h1_set}
                c_num = extract_heading_number(effective_txt, lang="en")

                # Check for Chapter + Subheading run-on (e.g. 'CHAPTER V. CAMPAIGNING.CAMP FIRE YARN...')
                m_chap_sub = re.match(
                    r"^(CHAPTER\s+[IVXLCDM0-9]+(?:[\.\:\-\s]+[A-Za-z\s]+?)?[\.\:\-])\s*(CAMP\s*FIRE\s*YARN.*)$",
                    effective_txt.strip().replace("\r", " ").replace("\n", " "),
                    re.I,
                )
                sub_trailing_text = None
                if m_chap_sub:
                    effective_txt = m_chap_sub.group(1).strip()
                    sub_trailing_text = m_chap_sub.group(2).strip()
                    norm_p = normalize_heading_str(effective_txt)
                    norm_p_clean = re.sub(r'[\s\.\-_]+', '', norm_p)
                    c_num = extract_heading_number(effective_txt, lang="en")

                # Classify: Main Chapter Heading (starts on a new page) vs Subheading (same page)
                is_main = False
                if norm_p in epub_h1_set or norm_p_clean in epub_h1_clean_map:
                    is_main = True
                elif norm_p in epub_sub_set and norm_p not in epub_h1_set and norm_p_clean not in epub_h1_clean_map:
                    is_main = False
                elif len(toc_norms) > 1:
                    if norm_p in toc_norms or norm_p_clean in toc_clean_map:
                        is_main = True
                    elif c_num is not None and c_num in toc_chaps and (is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt)):
                        is_main = True
                    elif any(norm_p.startswith(t) for t in toc_norms if len(t) > 6 and len(norm_p) > 6 and (is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt))):
                        is_main = True
                    elif any(norm_p_clean.startswith(tc) for tc in toc_clean_map if len(tc) > 6 and len(norm_p_clean) > 6 and (is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt))):
                        is_main = True
                else:
                    if is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt):
                        is_main = True
                    elif any(effective_txt.lower().startswith(k) for k in ["conclusion", "epilogue"]):
                        is_main = True

                # If original style was explicitly chapter_name and text is short, treat as main chapter
                if not is_main and any(k in pstyle.lower() for k in ["chapter_name", "chapter"]) and len(ptxt) < 60:
                    is_main = True

                if was_separated and book_part:
                    in_preface = False
                    in_footnotes = False
                    needs_page_break_after_preface = False
                    parent = parent_map.get(psr)
                    chapters_separated += 1
                    changed = True

                    _apply_heading_page_break(psr, parent)

                    if parent is not None:
                        idx = list(parent).index(psr)
                        book_psr = ET.Element("ParagraphStyleRange")
                        _format_clean_heading(book_psr, "ParagraphStyle/Sub-heading", "Gill Sans MT", book_part, space_after="20")
                        book_psr.set("StartParagraph", "NextPage")
                        parent.insert(idx, book_psr)

                    apply_paired_heading_format(psr, chap_part, font_name="Gill Sans MT", space_before="14", space_after="30", language="en")

                    if sub_trailing_text and parent is not None:
                        idx = list(parent).index(psr)
                        sub_psr = ET.Element("ParagraphStyleRange")
                        _format_clean_subheading(sub_psr, "Gill Sans MT", sub_trailing_text, space_before="18", space_after="12", point_size=14)
                        parent.insert(idx + 1, sub_psr)

                    last_h1_norm = normalize_heading_str(chap_part)
                    last_h1_text = chap_part
                    last_h1_num = c_num
                    seen_body_since_h1 = False
                    continue

                if is_main:
                    in_preface = False
                    in_footnotes = False
                    needs_page_break_after_preface = False
                    parent = parent_map.get(psr)

                    curr_h1_num = epub_h1_map.get(norm_p)
                    if curr_h1_num is None:
                        for k, v in epub_h1_map.items():
                            if (len(k) > 6 and len(norm_p) > 6) and (k.startswith(norm_p) or norm_p.startswith(k)):
                                curr_h1_num = v
                                break

                    # Modular check: Should two headings share the SAME page?
                    is_same_page_h1 = should_pair_headings(
                        prev_norm=last_h1_norm,
                        curr_norm=norm_p,
                        prev_text=last_h1_text,
                        curr_text=effective_txt,
                        seen_body_since_prev=seen_body_since_h1,
                        same_chap_pairs=same_chap_pairs,
                        prev_num=last_h1_num,
                        curr_num=curr_h1_num,
                    )

                    if is_same_page_h1:
                        # SAME PAGE: No page break; comes directly below preceding heading
                        _clean_subheading_page_break(psr, parent)
                        apply_paired_heading_format(psr, effective_txt, font_name="Gill Sans MT", space_before="14", space_after="30", language="en")
                        last_h1_norm = norm_p
                        last_h1_text = effective_txt
                        if curr_h1_num is not None:
                            last_h1_num = curr_h1_num
                        seen_body_since_h1 = False
                    else:
                        # SEPARATE PAGE: Fresh page break
                        _apply_heading_page_break(psr, parent)
                        heading_text = effective_txt
                        style_to_use = "ParagraphStyle/Sub-heading" if (
                            ("sub-heading" in pstyle.lower() or is_part_or_book_heading(heading_text))
                            and not heading_text.lower().startswith("chapter")
                            and norm_p not in toc_norms
                        ) else "ParagraphStyle/chapter_name"
                        space_aft = "20" if style_to_use == "ParagraphStyle/Sub-heading" else "30"
                        _format_clean_heading(psr, style_to_use, "Gill Sans MT", heading_text, space_after=space_aft)
                        psr.set("StartParagraph", "NextPage")

                        last_h1_norm = norm_p
                        last_h1_text = heading_text
                        last_h1_num = curr_h1_num
                        seen_body_since_h1 = False

                    if sub_trailing_text and parent is not None:
                        idx = list(parent).index(psr)
                        sub_psr = ET.Element("ParagraphStyleRange")
                        _format_clean_subheading(sub_psr, "Gill Sans MT", sub_trailing_text, space_before="18", space_after="12", point_size=14)
                        parent.insert(idx + 1, sub_psr)

                    changed = True
                    continue
                else:
                    # SUBHEADING: MUST NOT HAVE A PAGE BREAK!
                    # Flows on the SAME PAGE with proper breathing room and orphan prevention
                    parent = parent_map.get(psr)
                    _clean_subheading_page_break(psr, parent)
                    _format_clean_subheading(psr, "Gill Sans MT", ptxt, space_before="18", space_after="12", point_size=14)
                    changed = True
                    continue

            if needs_page_break_after_preface and ptxt:
                needs_page_break_after_preface = False

            # -------------------------------------------------------------
            # PREFACE Body and Signature Handling
            # -------------------------------------------------------------
            if in_preface and ptxt:
                preface_para_count += 1
                is_signature = (
                    len(ptxt) < 60
                    and (
                        bool(re.search(r"([A-Z]\.){2,}", ptxt))
                        or bool(re.search(r"\b(18\d\d|19\d\d|[A-Z]{2,4})\b", ptxt))
                        or "house" in ptxt.lower()
                        or bool(re.match(r"^[A-Z\.\s]{2,15}$", ptxt))
                    )
                )
                psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                psr.set("FirstLineIndent", "18")
                if is_signature:
                    psr.set("SpaceBefore", "6")
                    psr.set("SpaceAfter", "12")
                    needs_page_break_after_preface = True
                    in_preface = False
                else:
                    psr.set("Justification", "LeftAlign" if " " in ptxt else "LeftJustified")
                    psr.set("SpaceBefore", "1.5")
                    psr.set("SpaceAfter", "3")
                    if preface_para_count > 10:
                        in_preface = False

                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                changed = True

            if has_table:
                # Table paragraph: clean alignment, zero indent, preserve internal table cell structures
                psr.set("FirstLineIndent", "0")
                psr.set("Justification", "LeftAlign")
                changed = True
                continue

            # -------------------------------------------------------------
            # Task 19: Footnotes Formatting (Reference Layout Preservation)
            # -------------------------------------------------------------
            is_fn_style = "footnote" in pstyle.lower() or ptxt.startswith("FOOTNOTES:")
            is_quote_style = any(k in pstyle.lower() for k in ["quote", "block", "verse", "poem"])
            _soft_lines = _split_soft_lines(psr)
            has_soft_break = _is_true_verse(psr)

            if (in_footnotes or is_fn_style) and ptxt:
                psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
                psr.set("LeftIndent", "39.68503937007875")
                psr.set("RightIndent", "39.68503937007875")
                psr.set("FirstLineIndent", "0")
                psr.set("SpaceBefore", "1.5")
                psr.set("SpaceAfter", "3")
                psr.set("Justification", "LeftAlign" if has_soft_break else "LeftJustified")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                footnotes_formatted += 1
                changed = True
            elif is_quote_style or has_soft_break:
                psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
                psr.set("Justification", "LeftAlign")  # Ragged-right: prevents InDesign word-stretching on \u2028
                psr.set("LeftIndent", "39.68503937007875")
                psr.set("RightIndent", "39.68503937007875")
                psr.set("FirstLineIndent", "0")
                psr.set("SpaceBefore", "2")
                psr.set("SpaceAfter", "3")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                changed = True
            elif (
                (
                    any(k in pstyle.lower() for k in ["chapter_name", "sub-heading"])
                    and (len(ptxt) > 80 or (len(ptxt) > 40 and "." in ptxt and not re.match(r"^(?:chapter|book|part|act)\b", ptxt, re.I)))
                    and _normalize_heading_str(ptxt) not in toc_norms
                    and not any(_normalize_heading_str(ptxt).startswith(t) for t in toc_norms if len(t) > 6)
                )
                or (
                    any(k in pstyle.lower() for k in ["noindent", "body", "normal", "msonormal", "basic paragraph", "text", "style", "paragraph", "para"])
                    and not any(k in pstyle.lower() for k in ["chapter_name", "sub-heading", "heading", "toc", "verso", "copy", "author", "caption", "quote", "block", "verse", "poem", "fig caption"])
                )
            ):
                if ptxt.strip() and not ptxt.strip().startswith("###Insert"):
                    if "StartParagraph" in psr.attrib:
                        del psr.attrib["StartParagraph"]
                    if "ParagraphBreakType" in psr.attrib:
                        del psr.attrib["ParagraphBreakType"]
                    psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                    psr.set("Justification", "LeftJustified")
                    psr.set("FirstLineIndent", "18")
                    psr.set("SpaceBefore", "1.5")
                    psr.set("SpaceAfter", "3")
                    psr.set("KeepLinesTogether", "true")
                    psr.set("KeepFirstAndLastLines", "true")
                    psr.set("MinLinesAtStart", "2")
                    psr.set("MinLinesAtEnd", "2")
                    for csr in psr.iter():
                        if lname(csr.tag) == "CharacterStyleRange":
                            _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                            if csr.attrib.get("FontStyle") == "Bold" and "bold" not in csr.attrib.get("AppliedCharacterStyle", "").lower():
                                csr.set("FontStyle", "Regular")
                    body_styled += 1
                    changed = True
            elif any(k in pstyle.lower() for k in ["centre", "center"]) and not any(k in pstyle.lower() for k in ["chapter_name", "sub-heading", "heading", "author", "title", "toc"]):
                if ptxt.strip() and not ptxt.strip().startswith("###Insert"):
                    for csr in psr.iter():
                        if lname(csr.tag) == "CharacterStyleRange":
                            _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                    changed = True

            # Safety: genuine verse / quote paragraphs must never be LeftJustified
            if (has_soft_break or is_quote_style) and psr.attrib.get("Justification") == "LeftJustified":
                psr.set("Justification", "LeftAlign")
                changed = True

            if len(ptxt) > 15 and not any(k in pstyle.lower() for k in ["head", "chap", "sub"]):
                seen_body_since_h1 = True

            # -------------------------------------------------------------
            # Unpack multi-child CSRs so each CharacterStyleRange has at most one non-Properties child
            # -------------------------------------------------------------
            for csr in list(psr):
                if lname(csr.tag) == "CharacterStyleRange":
                    non_prop_children = [c for c in list(csr) if lname(c.tag) != "Properties"]
                    if len(non_prop_children) > 1:
                        prop_child = next((c for c in list(csr) if lname(c.tag) == "Properties"), None)
                        idx = list(psr).index(csr)
                        psr.remove(csr)
                        for offset, child in enumerate(non_prop_children):
                            new_csr = ET.Element(csr.tag, attrib=dict(csr.attrib))
                            if prop_child is not None:
                                new_csr.append(copy.deepcopy(prop_child))
                            new_csr.append(child)
                            psr.insert(idx + offset, new_csr)
                        changed = True

            # -------------------------------------------------------------
            # Task 13: Split & restore footnote/reference markers (Superscript)
            # -------------------------------------------------------------
            # 1. Merge adjacent CSRs that split brackets (e.g. '[' and '14]')
            csrs_list = [c for c in list(psr) if lname(c.tag) == "CharacterStyleRange"]
            for i in range(len(csrs_list) - 1):
                c1, c2 = csrs_list[i], csrs_list[i + 1]
                t1 = "".join(e.text or "" for e in c1.iter() if lname(e.tag) == "Content")
                t2 = "".join(e.text or "" for e in c2.iter() if lname(e.tag) == "Content")
                if re.search(r"\[\d*$", t1) and re.match(r"^\d*\]", t2):
                    cnt1 = next((e for e in c1.iter() if lname(e.tag) == "Content"), None)
                    cnt2 = next((e for e in c2.iter() if lname(e.tag) == "Content"), None)
                    if cnt1 is not None and cnt2 is not None:
                        cnt1.text = (cnt1.text or "") + (cnt2.text or "")
                        cnt2.text = ""
                        changed = True

            # 2. Split CSRs containing footnote/reference markers (in body text only, not footnote entries)
            if not (in_footnotes or is_fn_style):
                for csr in list(psr):
                    if lname(csr.tag) != "CharacterStyleRange":
                        continue
                    cnt_elem = next((e for e in csr.iter() if lname(e.tag) == "Content"), None)
                    if cnt_elem is None or not cnt_elem.text:
                        continue
                    txt = cnt_elem.text

                    if REF_MARKER_REGEX.search(txt):
                        parts = REF_MARKER_REGEX.split(txt)
                        if len(parts) > 1:
                            idx = list(psr).index(csr)
                            psr.remove(csr)
                            offset = 0
                            for part in parts:
                                if not part:
                                    continue
                                new_csr = copy.deepcopy(csr)
                                new_cnt = next((e for e in new_csr.iter() if lname(e.tag) == "Content"), None)
                                if new_cnt is not None:
                                    new_cnt.text = part
                                if REF_MARKER_REGEX.match(part):
                                    new_csr.set("Position", "Superscript")
                                    super_fixed += 1
                                else:
                                    if "Position" in new_csr.attrib:
                                        del new_csr.attrib["Position"]
                                psr.insert(idx + offset, new_csr)
                                offset += 1
                            changed = True

            # -------------------------------------------------------------
            # Task 14: Chemical formulas & Subscripts
            # -------------------------------------------------------------
            # 1. Chemical formulas with digits (e.g. K2O, H2O, C5N4, CO2, P2O5)
            for csr in list(psr):
                if lname(csr.tag) != "CharacterStyleRange":
                    continue
                cnt_elem = next((e for e in csr.iter() if lname(e.tag) == "Content"), None)
                if cnt_elem is None or not cnt_elem.text:
                    continue
                txt = cnt_elem.text

                if CHEM_REGEX.search(txt) and not REF_MARKER_REGEX.search(txt):
                    tokens = _tokenize_chem(txt)
                    if any(is_sub for _, is_sub in tokens):
                        idx = list(psr).index(csr)
                        psr.remove(csr)
                        offset = 0
                        for part, is_sub in tokens:
                            if not part:
                                continue
                            c_tok = copy.deepcopy(csr)
                            t_cnt = next((e for e in c_tok.iter() if lname(e.tag) == "Content"), None)
                            if t_cnt is not None:
                                t_cnt.text = part
                            if is_sub:
                                c_tok.set("Position", "Subscript")
                                sub_fixed += 1
                            else:
                                if "Position" in c_tok.attrib:
                                    del c_tok.attrib["Position"]
                            psr.insert(idx + offset, c_tok)
                            offset += 1
                        changed = True

            # 2. Leaked subscripts in input starting with digits or variable indices
            for csr in list(psr):
                if lname(csr.tag) != "CharacterStyleRange":
                    continue
                pos = csr.attrib.get("Position", "")
                cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                if pos == "Subscript" or "subscript" in cstyle.lower():
                    cnt_elem = next((e for e in csr.iter() if lname(e.tag) == "Content"), None)
                    if cnt_elem is None or not cnt_elem.text:
                        continue
                    is_year = bool(re.match(r"^(18\d\d|19\d\d|20\d\d)", txt.strip()))
                    if not is_year and len(txt.strip()) <= 3 and (re.match(r"^\d+$", txt.strip()) or txt.strip() in ("ab", "t1", "t2", "t3", "x1", "x2")):
                        csr.set("Position", "Subscript")
                    elif not is_year and re.match(r"^(\d{1,3})(.*)$", txt, re.S):
                        m = re.match(r"^(\d{1,3})(.*)$", txt, re.S)
                        sub_part, rest_part = m.group(1), m.group(2)
                        idx = list(psr).index(csr)
                        psr.remove(csr)
                        offset = 0
                        if sub_part:
                            c_sub = copy.deepcopy(csr)
                            c_cnt = next((e for e in c_sub.iter() if lname(e.tag) == "Content"), None)
                            if c_cnt is not None:
                                c_cnt.text = sub_part
                            c_sub.set("Position", "Subscript")
                            sub_fixed += 1
                            psr.insert(idx + offset, c_sub)
                            offset += 1
                        if rest_part:
                            c_rest = copy.deepcopy(csr)
                            c_cnt = next((e for e in c_rest.iter() if lname(e.tag) == "Content"), None)
                            if c_cnt is not None:
                                c_cnt.text = rest_part
                            if "Position" in c_rest.attrib:
                                del c_rest.attrib["Position"]
                            psr.insert(idx + offset, c_rest)
                            offset += 1
                        changed = True
                    else:
                        if "Position" in csr.attrib:
                            del csr.attrib["Position"]
                        changed = True

            # -------------------------------------------------------------
            # Tasks 7, 8, 13, 14, 15, 16: Character Styles & Direct Formats
            # -------------------------------------------------------------
            for csr in list(psr):
                if lname(csr.tag) != "CharacterStyleRange":
                    continue

                cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                ctxt = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")

                # Remap merged styles (bold, italic, allcaps)
                if cstyle in MERGE_MAP and not any(k in cstyle.lower() for k in ["underlin", "/u"]):
                    canonical = MERGE_MAP[cstyle]
                    csr.set("AppliedCharacterStyle", canonical)
                    cstyle = canonical
                    changed = True

                # Apply bold
                if "bold" in cstyle.lower() or csr.attrib.get("FontStyle") == "Bold":
                    csr.set("FontStyle", "Bold")
                    bold_fixed += 1
                    changed = True

                # Apply italic
                if "italic" in cstyle.lower() or csr.attrib.get("FontStyle") == "Italic":
                    csr.set("FontStyle", "Italic")
                    italic_fixed += 1
                    changed = True

                # Task 8, 15, 17: Underline Handling & Leaked Underline Cleanup
                is_legit_u = False
                is_u_style = any(k in cstyle.lower() for k in ["underlin", "/u"])
                has_u_attr = csr.attrib.get("Underline") == "true"

                if is_u_style or has_u_attr:
                    c_clean = ctxt.replace("\xa0", " ").strip().lower()
                    if c_clean:
                        if epub_underlines:
                            if c_clean in epub_underlines or any(
                                c_clean == u or (len(c_clean) >= 2 and c_clean in u.split())
                                for u in epub_underlines
                            ):
                                is_legit_u = True
                        elif (
                            is_u_style
                            and len(c_clean) <= 30
                            and not re.search(r"[.?!]\s+[a-z]", c_clean)
                        ):
                            if re.match(
                                r"^(?:footnote(?:\s*\d+)?|\d{1,4}|chapter(?:\s+[ivxlcdm0-9]+)?|chapters(?:\s+[ivxlcdm0-9]+)?|[ivxlcdm]{2,}|[-–—]\d+|p\.\s*\d+)$",
                                c_clean,
                                re.I,
                            ):
                                is_legit_u = True

                    if is_legit_u:
                        csr.set("Underline", "true")
                        csr.set("AppliedCharacterStyle", "CharacterStyle/underlinalign")
                        cstyle = "CharacterStyle/underlinalign"
                        if "Position" in csr.attrib:
                            del csr.attrib["Position"]
                        underline_fixed += 1
                        changed = True
                    else:
                        # Strip leaked/runaway underline
                        if "Underline" in csr.attrib:
                            del csr.attrib["Underline"]
                            changed = True
                        if is_u_style:
                            # Reset style: retain italic/bold if applicable, else [No character style]
                            if csr.attrib.get("FontStyle") == "Italic" or "italic" in cstyle.lower():
                                csr.set("AppliedCharacterStyle", "CharacterStyle/italicalign")
                                cstyle = "CharacterStyle/italicalign"
                            elif csr.attrib.get("FontStyle") == "Bold" or "bold" in cstyle.lower():
                                csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                                cstyle = "CharacterStyle/boldtext"
                            else:
                                csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                                cstyle = r"CharacterStyle/$ID/[No character style]"
                            changed = True

                # Apply all caps
                if "upper" in cstyle.lower() or csr.attrib.get("Capitalization") == "AllCaps":
                    csr.set("Capitalization", "AllCaps")
                    caps_fixed += 1
                    changed = True

                # Task 13: Superscript markers (e.g. [1], [215], 1, 2)
                is_true_super = (
                    not is_legit_u
                    and (
                        bool(REF_MARKER_REGEX.match(ctxt.strip()))
                        or (re.match(r"^(\d{1,3}|\*|\u2020|\u2021)$", ctxt.strip()) and (csr.attrib.get("Position") == "Superscript" or "superscript" in cstyle.lower()))
                        or ("superscript" in cstyle.lower() and len(ctxt.strip()) <= 4)
                    )
                )
                if is_true_super:
                    csr.set("Position", "Superscript")
                    super_fixed += 1
                    changed = True
                elif csr.attrib.get("Position") == "Superscript":
                    # Strip corrupted superscript from regular body text
                    del csr.attrib["Position"]
                    changed = True

                # Task 14: Subscript markers
                is_true_sub = (
                    len(ctxt.strip()) <= 4
                    and (re.match(r"^\d+$", ctxt.strip()) or ctxt.strip() in ("ab", "t1", "t2", "t3", "x1", "x2"))
                    and (csr.attrib.get("Position") == "Subscript" or "subscript" in cstyle.lower())
                )
                if is_true_sub:
                    csr.set("Position", "Subscript")
                    sub_fixed += 1
                    changed = True
                elif csr.attrib.get("Position") == "Subscript":
                    del csr.attrib["Position"]
                    changed = True

                # Fix corrupted Arabic language tag
                if csr.attrib.get("AppliedLanguage") == "$ID/Arabic":
                    csr.set("AppliedLanguage", "$ID/English: USA")
                    changed = True

        # Clean stray soft breaks at paragraph boundaries (skip Normal spacer paragraphs) and ensure no justified soft breaks
        for psr in root.iter():
            if lname(psr.tag) == "ParagraphStyleRange":
                if psr.attrib.get("AppliedParagraphStyle") == "ParagraphStyle/Normal":
                    continue
                for c_elem in psr.iter():
                    if lname(c_elem.tag) == "Content" and c_elem.text:
                        if "\u2028" in c_elem.text:
                            cleaned_t = re.sub(r"^\u2028+", "", c_elem.text)
                            cleaned_t = re.sub(r"\u2028+$", "", cleaned_t)
                            if cleaned_t != c_elem.text:
                                c_elem.text = cleaned_t
                                changed = True
                # Br-aware verse/block safety: ragged-left on any paragraph whose forced
                # lines (<Br> or soft break) make it verse, or that uses a block/quote style.
                _pstyle_l = psr.attrib.get("AppliedParagraphStyle", "").lower()
                _is_block_sty = any(k in _pstyle_l for k in ("block", "quote", "verse", "poem"))
                _is_verse_p = _is_true_verse(psr)
                if _is_verse_p or _is_block_sty:
                    _eff_just = psr.attrib.get("Justification")
                    if _eff_just in ("LeftJustified", None):
                        psr.set("Justification", "LeftAlign")
                        changed = True

        if changed:
            write_xml(root, sp)

    return {
        "bold_fixed": bold_fixed,
        "italic_fixed": italic_fixed,
        "underline_fixed": underline_fixed,
        "caps_fixed": caps_fixed,
        "super_fixed": super_fixed,
        "sub_fixed": sub_fixed,
        "chapters_separated": chapters_separated,
        "body_styled": body_styled,
        "footnotes_formatted": footnotes_formatted,
    }


def update_styles_xml(target_dir, reference_dir):
    """Ensure canonical styles are defined correctly in Resources/Styles.xml."""
    styles_path = Path(target_dir) / "Resources" / "Styles.xml"
    if not styles_path.exists():
        return {}

    root = ET.parse(styles_path).getroot()

    # Copy key styles from reference
    needed = {
        "ParagraphStyle/body_text",
        "ParagraphStyle/chapter_name",
        "ParagraphStyle/Sub-heading",
        "ParagraphStyle/after_chapter_name_heading",
        "ParagraphStyle/chapter_name01",
        "ParagraphStyle/quotes_normal",
        "ParagraphStyle/doublenine_books",
        "ParagraphStyle/verso_title",
        "ParagraphStyle/verso_author",
        "ParagraphStyle/copyright_text",
        "ParagraphStyle/about_the_autherh",
        "ParagraphStyle/toc_normaltext",
        "ParagraphStyle/content_ch",
        "ParagraphStyle/master_chapter_name",
        "CharacterStyle/boldtext",
        "CharacterStyle/italicalign",
        "CharacterStyle/italic",
        "CharacterStyle/underlinalign",
        "CharacterStyle/upper",
        "CharacterStyle/dropcap",
    }
    copy_named_styles(target_dir, reference_dir, needed)

    # Re-parse to enforce canonical character style attributes
    root = ET.parse(styles_path).getroot()
    removed_styles = []

    for cs in list(root.iter()):
        if lname(cs.tag) == "CharacterStyle":
            self_id = cs.attrib.get("Self", "")

            # Enforce formatting on canonical styles
            if self_id == "CharacterStyle/boldtext":
                cs.set("FontStyle", "Bold")
            elif self_id in ("CharacterStyle/italicalign", "CharacterStyle/italic"):
                cs.set("FontStyle", "Italic")
            elif self_id == "CharacterStyle/underlinalign":
                cs.set("Underline", "true")
            elif self_id == "CharacterStyle/upper":
                cs.set("Capitalization", "AllCaps")

            # Remove merged duplicate styles from Styles.xml (keep CharacterStyle/italic for title page)
            elif self_id in MERGE_MAP and self_id != "CharacterStyle/italic":
                parent = next(
                    (p for p in root.iter() if cs in list(p)),
                    None,
                )
                if parent is not None:
                    parent.remove(cs)
                    removed_styles.append(self_id)

    # Books may reference ParagraphStyle/body_text without defining it; create it
    # (cloned from Normal) so every body paragraph gets uniform justified + hyphenated
    # formatting instead of falling back to [Basic Paragraph] defaults.
    _bt_exists = any(
        lname(_p.tag) == "ParagraphStyle" and _p.attrib.get("Self") == "ParagraphStyle/body_text"
        for _p in root.iter()
    )
    _normal_el = next(
        (_p for _p in root.iter()
         if lname(_p.tag) == "ParagraphStyle" and _p.attrib.get("Self") == "ParagraphStyle/Normal"),
        None,
    )
    if not _bt_exists and _normal_el is not None:
        _bt = copy.deepcopy(_normal_el)
        _bt.set("Self", "ParagraphStyle/body_text")
        _bt.set("Name", "body_text")
        _bt.set("NextStyle", "ParagraphStyle/body_text")
        for _par in root.iter():
            if _normal_el in list(_par):
                _par.append(_bt)
                break

    # Enforce heading style font sizes, body/normal Palatino Linotype 9.65pt, and LeftAlign on quotes/verse
    for ps in list(root.iter()):
        if lname(ps.tag) == "ParagraphStyle":
            self_id = ps.attrib.get("Self", "")
            if self_id in (
                "ParagraphStyle/body_text",
                "ParagraphStyle/Normal",
                "ParagraphStyle/$ID/[Basic Paragraph]",
                "ParagraphStyle/$ID/NormalParagraphStyle",
                "ParagraphStyle/$ID/[Normal Paragraph Style]",
                "ParagraphStyle/Normal (Web)",
                "ParagraphStyle/noindent",
                "ParagraphStyle/noindentj",
                "ParagraphStyle/noindent1",
                "ParagraphStyle/bodytext_noendent",
                "ParagraphStyle/bodytext_Noendent",
                "ParagraphStyle/copybody",
                "ParagraphStyle/centre_align",
                "ParagraphStyle/center",
                "ParagraphStyle/center1",
            ) or (
                any(k in self_id.lower() for k in ["body", "normal", "basic", "noindent"])
                and not any(k in self_id.lower() for k in ["quote", "chapter", "sub-heading", "heading", "toc", "author", "title", "caption"])
            ):
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                if self_id in ("ParagraphStyle/body_text", "ParagraphStyle/Normal"):
                    ps.set("Justification", "LeftJustified")
                    ps.set("FirstLineIndent", "18")
                    ps.set("SpaceBefore", "1.5")
                    ps.set("SpaceAfter", "3")
                    # Uniform word spacing (no stretched spaces); justify via character
                    # spacing + hyphenation. Applied to the BODY style only, so poems,
                    # quotes and centered text (other styles) are never affected.
                    ps.set("MinimumWordSpacing", "80")
                    ps.set("DesiredWordSpacing", "100")
                    ps.set("MaximumWordSpacing", "120")
                    ps.set("MinimumLetterSpacing", "0")
                    ps.set("DesiredLetterSpacing", "0")
                    ps.set("MaximumLetterSpacing", "0")
                    ps.set("MinimumGlyphScaling", "100")
                    ps.set("DesiredGlyphScaling", "100")
                    ps.set("MaximumGlyphScaling", "100")
                    ps.set("Hyphenation", "true")
            elif self_id in ("ParagraphStyle/block1", "ParagraphStyle/block", "ParagraphStyle/block2", "ParagraphStyle/verse", "ParagraphStyle/poem", "ParagraphStyle/quotes_normal"):
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                # Block quote / poem: indented both sides (EPUB margin ~4em), ragged-left
                # so forced verse lines never stretch.
                ps.set("Justification", "LeftAlign")
                ps.set("LeftIndent", "39.68503937007875")
                ps.set("RightIndent", "39.68503937007875")
                ps.set("FirstLineIndent", "0")
            elif self_id == "ParagraphStyle/fig caption":
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9", leading="11")
                ps.set("Justification", "CenterAlign")
            elif self_id == "ParagraphStyle/chapter_name":
                ps.set("PointSize", "16")
                ps.set("Hyphenation", "false")
                ps.set("FontStyle", "Bold")
                ps.set("Justification", "CenterAlign")
                ps.set("SpaceBefore", "14.5")
                ps.set("SpaceAfter", "30")
                ps.set("StartParagraph", "NextPage")
                ps.set("KeepAllLinesTogether", "true")
                ps.set("KeepLinesTogether", "true")
                ps.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/Sub-heading":
                ps.set("PointSize", "16")
                ps.set("Hyphenation", "false")
                ps.set("Justification", "CenterAlign")
                ps.set("SpaceAfter", "20")
                ps.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/after_chapter_name_heading":
                ps.set("PointSize", "16")
                ps.set("Hyphenation", "false")
                ps.set("Justification", "CenterAlign")
                ps.set("SpaceAfter", "30")
                ps.set("KeepWithNext", "2")
                ps.set("StartParagraph", "Anywhere")
                if "ParagraphBreakType" in ps.attrib:
                    ps.attrib["ParagraphBreakType"] = "Anywhere"
            elif self_id == "ParagraphStyle/chapter_name01":
                ps.set("PointSize", "12")
                ps.set("Hyphenation", "false")
                ps.set("FontStyle", "Bold")
                ps.set("SpaceBefore", "14.5")
                ps.set("StartParagraph", "NextPage")
                ps.set("KeepAllLinesTogether", "true")
                ps.set("KeepLinesTogether", "true")
                ps.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/quotes_normal":
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                ps.set("Justification", "LeftJustified")
                ps.set("LeftIndent", "39.68503937007875")
                ps.set("RightIndent", "39.68503937007875")
                ps.set("PointSize", "9.65")
                ps.set("AppliedLanguage", "$ID/English: USA")
            elif any(k in self_id.lower() for k in ["quote", "block", "verse", "poem"]):
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                ps.set("Justification", "LeftAlign")
                ps.set("AppliedLanguage", "$ID/English: USA")

        sanitize_styles_xml(root)
    write_xml(root, styles_path)
    fonts_synced = sync_fonts(target_dir, reference_dir)

    return {
        "removed_duplicate_styles": removed_styles,
        "fonts_synced": fonts_synced,
    }


def fix_table_overfit(target_dir, max_width=324.0):
    """
    Scans all stories for <Table> elements.
    If total table width > max_width (324 pt body text width):
    - Proportionally scales each Column SingleColumnWidth so total width == max_width.
    - Sets Cell insets to 2pt to prevent overflow.
    - Scales down font size in cells (<= 8.5pt, leading 10pt) to preserve inside content.
    - Ensures Row AutoGrow is true so height adjusts cleanly.
    """
    stories_dir = Path(target_dir) / "Stories"
    if not stories_dir.exists():
        return 0

    tables_fixed = 0
    for sp in stories_dir.glob("*.xml"):
        try:
            tree = ET.parse(sp)
            root = tree.getroot()
        except Exception:
            continue

        changed = False
        for tbl in root.iter():
            if lname(tbl.tag) == "Table":
                cols = [c for c in tbl.iter() if lname(c.tag) == "Column"]
                if not cols:
                    continue
                col_widths = [float(c.attrib.get("SingleColumnWidth", 0)) for c in cols]
                total_w = sum(col_widths)

                scaled = False
                if total_w > max_width and total_w > 0:
                    scale = max_width / total_w
                    for col, w in zip(cols, col_widths):
                        new_w = round(w * scale, 3)
                        col.set("SingleColumnWidth", str(new_w))
                    scaled = True

                # Adjust cells inside this table
                for cell in tbl.iter():
                    if lname(cell.tag) == "Cell":
                        cell.set("ClipContentToTextCell", "false")
                        if scaled:
                            cell.set("TextLeftInset", "2")
                            cell.set("TextRightInset", "2")
                            cell.set("TextTopInset", "2")
                            cell.set("TextBottomInset", "2")

                            # Adjust cell text point size and leading
                            for csr in cell.iter():
                                if lname(csr.tag) == "CharacterStyleRange":
                                    pts = csr.attrib.get("PointSize")
                                    if pts:
                                        try:
                                            if float(pts) > 8.5:
                                                csr.set("PointSize", "8")
                                        except Exception:
                                            pass
                                    props = next((c for c in csr if lname(c.tag) == "Properties"), None)
                                    if props is not None:
                                        ld = next((c for c in props if lname(c.tag) == "Leading"), None)
                                        if ld is not None:
                                            ld.text = "10"

                # Ensure rows auto grow
                for row in tbl.iter():
                    if lname(row.tag) == "Row":
                        row.set("AutoGrow", "true")

                tables_fixed += 1
                changed = True

        if changed:
            write_xml(root, sp)

    return tables_fixed


def apply(target_dir, reference_dir, book_name=None):
    styles_report = update_styles_xml(target_dir, reference_dir)
    story_report = process_stories(target_dir, book_name=book_name)
    tables_fixed = fix_table_overfit(target_dir, max_width=324.0)
    return {
        "styles_xml": styles_report,
        "stories": story_report,
        "tables_fixed": tables_fixed,
    }

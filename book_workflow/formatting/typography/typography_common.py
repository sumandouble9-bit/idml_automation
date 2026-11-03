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

                            curr_cs = c_csr.attrib.get("AppliedCharacterStyle", "")
                            font_st = c_csr.attrib.get("FontStyle", "")
                            is_cell_it = "italic" in curr_cs.lower() or font_st == "Italic"
                            is_cell_bd = "bold" in curr_cs.lower() or font_st == "Bold"

                            if is_cell_it:
                                c_csr.set("AppliedCharacterStyle", "CharacterStyle/italic")
                                c_csr.set("FontStyle", "Italic")
                            elif is_cell_bd:
                                c_csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                                c_csr.set("FontStyle", "Bold")
                            else:
                                if curr_cs in ("CharacterStyle/italicalign", "CharacterStyle/italic", "CharacterStyle/boldtext"):
                                    c_csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                                if font_st in ("Italic", "Bold"):
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


__all__ = [
    'CANONICAL_CHAR_STYLES',
    'MERGE_MAP',
    'ELEM_REGEX',
    'CHEM_REGEX',
    'REF_MARKER_REGEX',
    '_tokenize_chem',
    '_create_page_break_spacer',
    '_is_page_break_spacer',
    '_is_blank_page_spacer',
    '_apply_heading_page_break',
    '_apply_preface_page_break',
    '_ensure_font_prop',
    '_split_soft_lines',
    '_is_true_verse',
    '_enforce_paragraph_style_font',
    '_format_clean_heading',
    '_clean_subheading_page_break',
    '_normalize_table_content',
    '_format_clean_subheading',
    'ROMAN_MAP',
    '_extract_chap_number',
    '_normalize_heading_str',
    '_extract_doc_toc_entries',
    '_clean_chapter_runon',
    '_load_epub_underlines',
    '_load_epub_tables',
]

import copy
import html
import math
import os
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
    lname,
    parse,
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

CANONICAL_CHAR_STYLES = {
    "bold": "CharacterStyle/boldtext",
    "italic": "CharacterStyle/italicalign",
    "underline": "CharacterStyle/underlinalign",
    "upper": "CharacterStyle/upper",
}

MERGE_MAP = {
    "CharacterStyle/b": "CharacterStyle/boldtext",
    "CharacterStyle/bold": "CharacterStyle/boldtext",
    "CharacterStyle/Bold": "CharacterStyle/boldtext",
    "CharacterStyle/i": "CharacterStyle/italicalign",
    "CharacterStyle/HTML Cite": "CharacterStyle/italicalign",
    "CharacterStyle/Emphasis": "CharacterStyle/italicalign",
    "CharacterStyle/u": "CharacterStyle/underlinalign",
    "CharacterStyle/underline": "CharacterStyle/underlinalign",
    "CharacterStyle/Underline": "CharacterStyle/underlinalign",
    "CharacterStyle/caps": "CharacterStyle/upper",
    "CharacterStyle/allcaps": "CharacterStyle/upper",
    "CharacterStyle/AllCaps": "CharacterStyle/upper",
}

ROMAN_MAP = {
    'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10,
    'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15, 'xvi': 16, 'xvii': 17, 'xviii': 18,
    'xix': 19, 'xx': 20, 'xxi': 21, 'xxii': 22, 'xxiii': 23, 'xxiv': 24, 'xxv': 25, 'xxvi': 26,
    'xxvii': 27, 'xxviii': 28, 'xxix': 29, 'xxx': 30, 'xxxi': 31, 'xxxii': 32, 'xxxiii': 33,
    'xxxiv': 34, 'xxxv': 35, 'xxxvi': 36, 'xxxvii': 37, 'xxxviii': 38, 'xxxix': 39, 'xl': 40,
    'xli': 41, 'xlii': 42, 'xliii': 43, 'xliv': 44, 'xlv': 45, 'xlvi': 46, 'xlvii': 47,
    'xlviii': 48, 'xlix': 49, 'l': 50, 'li': 51, 'lii': 52, 'liii': 53, 'liv': 54, 'lv': 55,
    'lvi': 56, 'lvii': 57, 'lviii': 58, 'lix': 59, 'lx': 60, 'lxi': 61, 'lxii': 62, 'lxiii': 63,
}

SPANISH_ORDINALS = {
    'primer': 1, 'primero': 1, 'primera': 1,
    'segundo': 2, 'segunda': 2,
    'tercer': 3, 'tercero': 3, 'tercera': 3,
    'cuarto': 4, 'cuarta': 4,
    'quinto': 5, 'quinta': 5,
    'sexto': 6, 'sexta': 6,
    'septimo': 7, 'séptimo': 7, 'séptima': 7,
    'octavo': 8, 'octava': 8,
    'noveno': 9, 'novena': 9,
    'decimo': 10, 'décimo': 10, 'décima': 10,
}

REF_MARKER_REGEX = re.compile(r'(\[\d{1,4}[a-z]?\]|\[[ivxLCDM]+\]|\[[\*\u2020\u2021]\])')


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


def _is_page_break_spacer(element):
    if lname(element.tag) != "ParagraphStyleRange":
        return False
    if any(lname(c.tag) == "Table" for c in element.iter()):
        return False
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


def _clean_subheading_page_break(psr, parent):
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


def _split_soft_lines(psr):
    """Visual lines of a paragraph, split at <Br> forced breaks AND   soft
    breaks (verse detection: several short forced lines => ragged-left, not
    justified, so the words are never stretched)."""
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
    (almost) every line is short. Prose with a single forced break is NOT verse."""
    lines = _split_soft_lines(psr)
    if len(lines) < 3:
        return False
    short = [l for l in lines if len(l.strip()) < 55]
    long_ = [l for l in lines if len(l.strip()) > 80]
    return len(short) >= 3 and len(short) >= len(lines) - 1 and not long_


def _ensure_font_prop(csr, font_name, point_size=None, leading=None):
    props = next((c for c in csr if lname(c.tag) == "Properties"), None)
    if props is None:
        props = ET.Element(csr.tag.replace("CharacterStyleRange", "Properties"))
        csr.insert(0, props)
    for af_el in list(props):
        if lname(af_el.tag) == "AppliedFont":
            props.remove(af_el)
    af = ET.Element(props.tag.replace("Properties", "AppliedFont"))
    af.set("type", "string")
    af.text = font_name
    props.append(af)
    if point_size is not None:
        csr.set("PointSize", str(point_size))
    if leading is not None:
        for ld_el in list(props):
            if lname(ld_el.tag) == "Leading":
                props.remove(ld_el)
        ld = ET.Element(props.tag.replace("Properties", "Leading"))
        ld.set("type", "unit")
        ld.text = str(leading)
        props.append(ld)


def _format_clean_heading(psr, style_name, font_name, text_content, space_after="30", point_size=16):
    psr.set("AppliedParagraphStyle", style_name)
    psr.set("Justification", "CenterAlign")
    psr.set("FirstLineIndent", "0")
    psr.set("SpaceBefore", "3")
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
    psr.set("AppliedLanguage", "$ID/Spanish: Standard")
    if "ParagraphBreakType" in psr.attrib and "after" not in style_name.lower():
        del psr.attrib["ParagraphBreakType"]

    for child in list(psr):
        psr.remove(child)

    pt_size = str(point_size)
    csr = ET.SubElement(psr, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Bold",
        "PointSize": pt_size,
        "AppliedLanguage": "$ID/Spanish: Standard",
    })
    _ensure_font_prop(csr, font_name, point_size=pt_size)
    cnt = ET.SubElement(csr, "Content")
    cnt.text = text_content
    ET.SubElement(csr, "Br")


def _format_clean_subheading(psr, font_name, text_content, space_before="18", space_after="12", point_size=14):
    psr.set("AppliedParagraphStyle", "ParagraphStyle/Sub-heading")
    psr.set("Justification", "CenterAlign")
    psr.set("FirstLineIndent", "0")
    psr.set("SpaceBefore", str(space_before))
    psr.set("SpaceAfter", str(space_after))
    psr.set("KeepWithNext", "1")
    psr.set("AppliedLanguage", "$ID/Spanish: Standard")
    if "ParagraphBreakType" in psr.attrib:
        del psr.attrib["ParagraphBreakType"]

    for child in list(psr):
        psr.remove(child)

    pt_size = str(point_size)
    csr = ET.SubElement(psr, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Bold",
        "PointSize": pt_size,
        "AppliedLanguage": "$ID/Spanish: Standard",
    })
    _ensure_font_prop(csr, font_name, point_size=pt_size, leading=str(int(float(pt_size)) + 4))
    cnt = ET.SubElement(csr, "Content")
    cnt.text = text_content
    ET.SubElement(csr, "Br")


def _extract_chap_number_es(text):
    m_ord = re.search(r'\b(primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|s[ée]ptim[oa]|octav[oa]|noven[oa]|d[ée]cim[oa])\s+cap[íi]tulo\b', text, re.I)
    if m_ord:
        w = m_ord.group(1).lower().replace('á', 'a').replace('é', 'e')
        for k, v in SPANISH_ORDINALS.items():
            if k in w:
                return v

    m_num = re.match(r'^\s*(\d{1,3})\.\s+[A-ZÁÉÍÓÚÑ]', text)
    if m_num:
        return int(m_num.group(1))

    m = re.search(r'\b(?:cap[íi]tulo|chapter|chap\.?)\s+([ivxlcdm0-9]+)\b', text, re.I)
    if m:
        val = m.group(1).lower()
        if val.isdigit():
            return int(val)
        if val in ROMAN_MAP:
            return ROMAN_MAP[val]

    m2 = re.match(r'^\s*([ivxlcdm]+)\b', text, re.I)
    if m2:
        val = m2.group(1).lower()
        if val in ROMAN_MAP:
            return ROMAN_MAP[val]
    return None


def _normalize_heading_str(s):
    if not s:
        return ""
    s = s.split('\t')[0]
    s = html.unescape(s)
    s = re.sub(r'[\u2014\u2013\-\:\_\/\.\,]+', ' ', s)
    s = re.sub(r'[\r\n\u2028]+', ' ', s)
    s = re.sub(r'[^\w\s]', '', s.lower())
    return re.sub(r'\s+', ' ', s).strip()


def _extract_doc_toc_entries_es(target_dir, book_name=None):
    raw_entries = []

    # 1. Check EPUB toc.ncx
    epub_dir = SCRIPTS_DIR.parent / "epub_input_files_Spanish"
    if not epub_dir.exists():
        epub_dir = SCRIPTS_DIR.parent / "epub_input_files"
    if epub_dir.exists():
        clean_name = re.sub(r'(_formatted|_normalized|_injected|\.idml)$', '', str(book_name or Path(target_dir).parent.stem), flags=re.I).strip()
        matched_epubs = list(epub_dir.glob(f"*{clean_name}*.epub"))
        if matched_epubs:
            try:
                with zipfile.ZipFile(matched_epubs[0], "r") as z:
                    toc_files = [n for n in z.namelist() if "toc" in n.lower() or "nav" in n.lower()]
                    for tf in toc_files:
                        toc_xml = z.read(tf).decode("utf-8", errors="ignore")
                        nav_labels = re.findall(r"<text>(.*?)</text>", toc_xml, re.IGNORECASE)
                        for l in nav_labels:
                            cl = l.strip()
                            if cl and not any(k in cl.lower() for k in [
                                "cubierta", "título", "titulo", "derechos de autor", "contenido",
                                "sobre la autoría", "sobre la autoria", "sobre el autor", "cover", "copyright", "title", "about the author"
                            ]):
                                raw_entries.append(cl)
                        break
            except Exception:
                pass

    # 2. Extract from document stories
    stories_dir = Path(target_dir) / "Stories"
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
                        txt = content_text(psr).strip()
                        if txt and not any(k in txt.lower() for k in ["contenido", "índice", "indice", "contents"]):
                            parts = re.split(r"(?=(?:CAPÍTULO|PARTE|LIBRO|ACTO|\d+\.\s+|[IVXLCDM]+\.\s+|PREFACIO|INTRODUCCIÓN|NOTA DEL AUTOR))", txt, flags=re.I)
                            for part in parts:
                                clean = " ".join(part.split()).strip()
                                if clean and len(clean) > 2 and clean not in raw_entries:
                                    raw_entries.append(clean)

    filtered_entries = [
        e for e in raw_entries
        if not any(k in e.lower() for k in ["contenido", "índice", "indice", "table of contents", "double 9 books"])
    ]
    norm_entries = set(_normalize_heading_str(e) for e in filtered_entries if _normalize_heading_str(e))
    chap_numbers = set()
    for e in filtered_entries:
        c = _extract_chap_number_es(e)
        if c is not None:
            chap_numbers.add(c)

    return filtered_entries, norm_entries, chap_numbers


def _clean_chapter_runon_es(text):
    cleaned = text.strip().replace("\r", " ").replace("\n", " ")

    # 1. Spanish Parte/Libro + Capítulo run-on
    m_parte_chap = re.match(
        r"^(PARTE\s+[^\n\r]+?)(CAP[ÍI]TULO\s+[IVXLCDM0-9]+.*)$",
        cleaned,
        re.I,
    )
    if m_parte_chap:
        parte_raw = m_parte_chap.group(1).strip()
        chap_raw = m_parte_chap.group(2).strip()
        _, chap_txt, _ = _clean_chapter_runon_es(chap_raw)
        return parte_raw, chap_txt, True

    # 2. English Part/Book + Chapter run-on
    m_part_chap = re.match(
        r"^((?:PART|BOOK)\s+[^\n\r]+?)(CHAPTER\s+[IVXLCDM0-9]+.*)$",
        cleaned,
        re.I,
    )
    if m_part_chap:
        part_raw = m_part_chap.group(1).strip()
        chap_raw = m_part_chap.group(2).strip()
        _, chap_txt, _ = _clean_chapter_runon_es(chap_raw)
        return part_raw, chap_txt, True

    # 3. Spanish CAPÍTULO [IVXLCDM0-9]+ with punctuation/dash separator
    m_chap_es = re.match(
        r"^(CAP[ÍI]TULO\s+[IVXLCDM0-9]+)\s*[\.\:\-\u2013\u2014]\s*(.+)$",
        cleaned,
        re.I,
    )
    if m_chap_es:
        num = m_chap_es.group(1).strip()
        title = m_chap_es.group(2).strip()
        return None, f"{num}\u2028{title}", True

    # 4. Spanish Ordinals: "Primer capítulo Dos mundos"
    m_ord = re.match(
        r"^((?:Primer|Segundo|Tercer|Cuarto|Quinto|Sexto|S[ée]ptimo|Octavo|Noveno|D[ée]cimo)\s+cap[íi]tulo)\s+([A-ZÁÉÍÓÚÑ].*)$",
        cleaned,
        re.I,
    )
    if m_ord:
        num = m_ord.group(1).strip()
        title = m_ord.group(2).strip()
        return None, f"{num}\u2028{title}", True

    # 5. English CHAPTER [IVXLCDM0-9]+ with punctuation
    m_chap_en = re.match(
        r"^(CHAPTER\s+[IVXLCDM0-9]+)\s*[\.\:\-\u2013\u2014]\s*(.+)$",
        cleaned,
        re.I,
    )
    if m_chap_en:
        num = m_chap_en.group(1).strip()
        title = m_chap_en.group(2).strip()
        return None, f"{num}\u2028{title}", True

    # 6. Chapter Num + Title with space only
    m_chap_sp = re.match(
        r"^(CAP[ÍI]TULO|CHAPTER\s+[IVXLCDM0-9]+)\s+([A-ZÁÉÍÓÚÑ\s]{3,}.*)$",
        cleaned,
        re.I,
    )
    if m_chap_sp:
        num = m_chap_sp.group(1).strip()
        title = m_chap_sp.group(2).strip()
        return None, f"{num}\u2028{title}", True

    return None, cleaned, False


def _load_epub_underlines_es(target_dir, book_name=None):
    epub_dir = SCRIPTS_DIR.parent / "epub_input_files_Spanish"
    if not epub_dir.exists():
        epub_dir = SCRIPTS_DIR.parent / "epub_input_files"
    if not epub_dir.exists():
        return set()

    clean_name = re.sub(r'(_formatted|_normalized|_injected|\.idml)$', '', str(book_name or Path(target_dir).parent.stem), flags=re.I).strip()
    target_epubs = list(epub_dir.glob(f"*{clean_name}*.epub")) or list(epub_dir.glob("*.epub"))
    valid_strings = set()

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


def update_styles_xml(target_dir, reference_dir):
    styles_path = Path(target_dir) / "Resources" / "Styles.xml"
    if not styles_path.exists():
        return {}

    needed = {
        "ParagraphStyle/body_text",
        "ParagraphStyle/chapter_name",
        "ParagraphStyle/Sub-heading",
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
    sync_fonts(target_dir, reference_dir)

    root = ET.parse(styles_path).getroot()
    for cs in list(root.iter()):
        if lname(cs.tag) == "CharacterStyle":
            self_id = cs.attrib.get("Self", "")
            props = next((c for c in cs if lname(c.tag) == "Properties"), None)
            if self_id == "CharacterStyle/boldtext":
                cs.set("FontStyle", "Bold")
                if "PointSize" in cs.attrib:
                    del cs.attrib["PointSize"]
                if props is not None:
                    for af in list(props):
                        if lname(af.tag) == "AppliedFont":
                            props.remove(af)
            elif self_id in ("CharacterStyle/italicalign", "CharacterStyle/italic"):
                cs.set("FontStyle", "Italic")
                if "PointSize" in cs.attrib:
                    del cs.attrib["PointSize"]
                if props is not None:
                    for af in list(props):
                        if lname(af.tag) == "AppliedFont":
                            props.remove(af)
            elif self_id == "CharacterStyle/underlinalign":
                cs.set("Underline", "true")
                if "PointSize" in cs.attrib:
                    del cs.attrib["PointSize"]
                if props is not None:
                    for af in list(props):
                        if lname(af.tag) == "AppliedFont":
                            props.remove(af)
            elif self_id == "CharacterStyle/upper":
                cs.set("Capitalization", "AllCaps")
                if "PointSize" in cs.attrib:
                    del cs.attrib["PointSize"]
                if props is not None:
                    for af in list(props):
                        if lname(af.tag) == "AppliedFont":
                            props.remove(af)
            elif self_id == "CharacterStyle/dropcap":
                cs.set("PointSize", "9.65")
                if props is not None:
                    for af in list(props):
                        if lname(af.tag) == "AppliedFont":
                            af.text = "Palatino Linotype"
        elif lname(cs.tag) == "ParagraphStyle":
            self_id = cs.attrib.get("Self", "")
            if self_id == "ParagraphStyle/chapter_name":
                cs.set("PointSize", "16")
                cs.set("FontStyle", "Bold")
                cs.set("Justification", "CenterAlign")
                cs.set("SpaceBefore", "3")
                cs.set("SpaceAfter", "30")
                cs.set("StartParagraph", "NextPage")
                cs.set("KeepAllLinesTogether", "true")
                cs.set("KeepLinesTogether", "true")
                cs.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/chapter_name01":
                cs.set("PointSize", "12")
                cs.set("FontStyle", "Bold")
                cs.set("StartParagraph", "NextPage")
                cs.set("KeepAllLinesTogether", "true")
                cs.set("KeepLinesTogether", "true")
                cs.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/Sub-heading":
                cs.set("PointSize", "16")
                cs.set("Justification", "CenterAlign")
                cs.set("SpaceAfter", "20")
                cs.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/after_chapter_name_heading":
                cs.set("PointSize", "16")
                cs.set("Justification", "CenterAlign")
                cs.set("SpaceAfter", "30")
                cs.set("KeepWithNext", "2")
                cs.set("StartParagraph", "Anywhere")
                if "ParagraphBreakType" in cs.attrib:
                    cs.attrib["ParagraphBreakType"] = "Anywhere"
            elif self_id in ("ParagraphStyle/body_text", "ParagraphStyle/Normal"):
                # Uniform word spacing (no stretched spaces); justify via letter
                # spacing + hyphenation (matches the English pipeline).
                cs.set("Justification", "LeftJustified")
                cs.set("MinimumWordSpacing", "80")
                cs.set("DesiredWordSpacing", "100")
                cs.set("MaximumWordSpacing", "120")
                cs.set("MinimumLetterSpacing", "0")
                cs.set("DesiredLetterSpacing", "0")
                cs.set("MaximumLetterSpacing", "0")
                cs.set("MinimumGlyphScaling", "100")
                cs.set("DesiredGlyphScaling", "100")
                cs.set("MaximumGlyphScaling", "100")
                cs.set("Hyphenation", "true")
            elif self_id in ("ParagraphStyle/block1", "ParagraphStyle/block", "ParagraphStyle/block2", "ParagraphStyle/verse", "ParagraphStyle/poem", "ParagraphStyle/quotes_normal"):
                cs.set("Justification", "LeftAlign")
                cs.set("LeftIndent", "39.68503937007875")
                cs.set("RightIndent", "39.68503937007875")
                cs.set("FirstLineIndent", "0")
        sanitize_styles_xml(root)
    write_xml(root, styles_path)
    return {"styles_updated": True}


def fix_table_overfit(target_dir, max_width=324.0):
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

                for cell in tbl.iter():
                    if lname(cell.tag) == "Cell":
                        cell.set("ClipContentToTextCell", "false")
                        if scaled:
                            cell.set("TextLeftInset", "2")
                            cell.set("TextRightInset", "2")
                            cell.set("TextTopInset", "2")
                            cell.set("TextBottomInset", "2")

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

                for row in tbl.iter():
                    if lname(row.tag) == "Row":
                        row.set("AutoGrow", "true")

                tables_fixed += 1
                changed = True

        if changed:
            write_xml(root, sp)

    return tables_fixed


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

    epub_underlines = _load_epub_underlines_es(target_dir, book_name=book_name)
    res = load_epub_heading_hierarchy(book_name or Path(target_dir).parent.stem)
    if len(res) == 4:
        epub_h1_set, epub_sub_set, epub_toc, epub_h1_meta = res
    else:
        epub_h1_set, epub_sub_set, epub_toc = res
        epub_h1_meta = {"chapter_map": {}, "same_chap_pairs": set()}
    epub_h1_map = epub_h1_meta.get("chapter_map", {})
    same_chap_pairs = epub_h1_meta.get("same_chap_pairs", set())
    toc_raw, toc_norms, toc_chaps = _extract_doc_toc_entries_es(target_dir, book_name=book_name)
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

        # 1. Universal pre-split for compound paragraphs containing both Table and text/heading
        for parent in list(root.iter()):
            children = list(parent)
            for idx, psr in enumerate(children):
                if lname(psr.tag) == "ParagraphStyleRange":
                    t_csrs = [c for c in psr if any(lname(e.tag) == "Table" for e in c.iter())]
                    if not t_csrs:
                        continue
                    # Clean all table cells inside table
                    for tc in t_csrs:
                        for tbl in tc.iter():
                            if lname(tbl.tag) == "Table":
                                _normalize_table_content(tbl, epub_fmt=epub_fmt)

                    pre_csrs = []
                    post_csrs = []
                    seen_tbl = False
                    for child in list(psr):
                        if child in t_csrs:
                            seen_tbl = True
                        elif not seen_tbl:
                            pre_csrs.append(child)
                        else:
                            post_csrs.append(child)

                    pre_text = "".join(c.text for oc in pre_csrs for c in oc.iter() if lname(c.tag) == "Content" and c.text).strip()
                    post_text = "".join(c.text for oc in post_csrs for c in oc.iter() if lname(c.tag) == "Content" and c.text).strip()

                    if pre_text or post_text:
                        for child in list(psr):
                            psr.remove(child)
                        ins_idx = list(parent).index(psr)
                        # Use the LIVE position of psr, not the stale enumerate() idx:
                        # earlier compound table paragraphs in the same parent insert/
                        # remove siblings, so the snapshot index no longer matches and
                        # the split block would land before preceding paragraphs.

                        if pre_text:
                            _pre_attrib = dict(psr.attrib)
                            if any(k in _pre_attrib.get("AppliedParagraphStyle", "").lower() for k in ("quote", "block", "verse", "poem", "extract", "epigraph")):
                                _pre_attrib["Justification"] = "LeftAlign"  # block/quote: ragged, never justified
                            pre_psr = ET.Element("ParagraphStyleRange", _pre_attrib)
                            for pc in pre_csrs:
                                pre_psr.append(pc)
                            last_csr = None
                            for c in reversed(list(pre_psr)):
                                if lname(c.tag) == "CharacterStyleRange":
                                    last_csr = c
                                    break
                            if last_csr is None or not any(lname(child.tag) == "Br" for child in last_csr):
                                br_c = ET.SubElement(pre_psr, "CharacterStyleRange", {
                                    "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                                })
                                ET.SubElement(br_c, "Br")
                            parent.insert(ins_idx, pre_psr)
                            ins_idx += 1

                        table_psr = ET.Element("ParagraphStyleRange", {
                            "AppliedParagraphStyle": "ParagraphStyle/body_text",
                            "Justification": "LeftAlign",
                            "FirstLineIndent": "0",
                            "SpaceBefore": "6",
                            "SpaceAfter": "6",
                        })
                        for tc in t_csrs:
                            table_psr.append(tc)
                        last_t_csr = None
                        for c in reversed(list(table_psr)):
                            if lname(c.tag) == "CharacterStyleRange":
                                last_t_csr = c
                                break
                        if last_t_csr is None or not any(lname(child.tag) == "Br" for child in last_t_csr):
                            br_c = ET.SubElement(table_psr, "CharacterStyleRange", {
                                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                            })
                            ET.SubElement(br_c, "Br")
                        parent.insert(ins_idx, table_psr)
                        ins_idx += 1

                        if post_text:
                            # Block/quote tail after an embedded table stays in its block
                            # style (e.g. quotes_normal) instead of dropping to body_text.
                            _orig_style = psr.attrib.get("AppliedParagraphStyle", "")
                            _is_block = any(k in _orig_style.lower() for k in ("quote", "block", "verse", "poem", "extract", "epigraph"))
                            if _is_block:
                                _post_attrib = dict(psr.attrib)
                                _post_attrib["Justification"] = "LeftAlign"  # block/quote tail: ragged
                            else:
                                _post_attrib = {
                                    "AppliedParagraphStyle": "ParagraphStyle/body_text",
                                    "FirstLineIndent": "18",
                                    "SpaceBefore": "1.5",
                                    "SpaceAfter": "3",
                                    "Justification": "LeftAlign" if " " in post_text else "LeftJustified",
                                }
                            post_psr = ET.Element("ParagraphStyleRange", _post_attrib)
                            for pc in post_csrs:
                                post_psr.append(pc)
                            last_p_csr = None
                            for c in reversed(list(post_psr)):
                                if lname(c.tag) == "CharacterStyleRange":
                                    last_p_csr = c
                                    break
                            if last_p_csr is None or not any(lname(child.tag) == "Br" for child in last_p_csr):
                                br_c = ET.SubElement(post_psr, "CharacterStyleRange", {
                                    "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                                })
                                ET.SubElement(br_c, "Br")
                            parent.insert(ins_idx, post_psr)

                        parent.remove(psr)

        # Rebuild parent_map and psrs list after pre-split
        parent_map = {}
        for p in root.iter():
            for child in p:
                parent_map[child] = p
        psrs = [e for e in root.iter() if lname(e.tag) == "ParagraphStyleRange"]

        in_preface = False
        in_footnotes = False
        last_h1_norm = None
        last_h1_text = None
        last_h1_num = None
        seen_body_since_h1 = False

        for psr in psrs:
            ptxt = content_text(psr).strip()
            pstyle = psr.attrib.get("AppliedParagraphStyle", "")
            has_table = any(lname(c.tag) == "Table" for c in psr.iter())

            # Check if this psr is nested inside a Table or Cell
            in_cell_or_table = False
            cur_node = parent_map.get(psr)
            while cur_node is not None:
                if lname(cur_node.tag) in ("Cell", "Table"):
                    in_cell_or_table = True
                    break
                cur_node = parent_map.get(cur_node)

            if has_table:
                # A block quote can embed its image Table INSIDE a single
                # CharacterStyleRange, with Content both before and after the table
                # (e.g. "...Aus--.<Table/>We shut him off, and sat down..."). The
                # pre/table/post classifier below splits by CSR, so with everything
                # in one CSR it cannot separate them and the image is appended after
                # the whole block. Pre-split any such CSR at its Table boundaries so
                # the table keeps its in-flow position between the surrounding text.
                for _csr in list(psr):
                    if lname(_csr.tag) != "CharacterStyleRange":
                        continue
                    _kids = list(_csr)
                    if not any(lname(_k.tag) == "Table" for _k in _kids):
                        continue
                    _non_tbl = [_k for _k in _kids if lname(_k.tag) not in ("Table", "Properties")]
                    if not _non_tbl:
                        continue  # table-only CSR: nothing to separate
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
                psr.set("FirstLineIndent", "0")
                psr.set("Justification", "LeftAlign")
                continue

            if in_cell_or_table:
                _cell_style = psr.attrib.get("AppliedParagraphStyle", "").lower()
                _cell_lines = _split_soft_lines(psr)
                _is_verse_cell = _is_true_verse(psr)
                if any(k in _cell_style for k in ["chapter", "sub-heading", "head"]):
                    psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                elif any(k in _cell_style for k in ["block", "quote", "verse", "poem"]) or _is_verse_cell:
                    # Block quote / poem inside a table cell keeps its block indent + ragged-left.
                    psr.set("LeftIndent", "39.68503937007875")
                    psr.set("RightIndent", "39.68503937007875")
                    psr.set("FirstLineIndent", "0")
                    psr.set("Justification", "LeftAlign")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                continue

            if any(k in pstyle.lower() for k in ["verso", "copyright", "doublenine", "main_page_title", "toc", "content_ch", "about_the_auther"]):
                continue
            if _is_blank_page_spacer(psr) or _is_page_break_spacer(psr):
                continue
            if any(k in ptxt.lower() for k in ["double 9 books", "cubierta", "títuloderechos", "iniciodelcontenido"]):
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

                # 2. Extract ONLY the clean placeholder tag: ###Insert ... ###
                m_ph = re.search(r"(###Insert\s+.*?###)", ptxt)
                ph_str = m_ph.group(1).strip() if m_ph else ptxt.strip()

                # 3. Clean all children of psr and build a single clean CSR with Br
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

            # PREFACE / PRÓLOGO / INTRODUCCIÓN
            is_preface = (
                not has_table
                and any(ptxt.lower().startswith(k) for k in [
                    "prefacio", "prólogo", "prologo", "introducción", "introduccion",
                    "nota del autor", "nota preliminar", "advertencia", "estudio preliminar",
                    "preface", "foreword", "introduction"
                ])
                and len(ptxt) < 60
            )
            if is_preface:
                in_preface = True
                in_footnotes = False
                parent = parent_map.get(psr)
                _apply_preface_page_break(psr, parent)
                clean_hd = ptxt.upper()
                _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
                continue

            # BACKMATTER / NOTAS
            is_backmatter = (
                not has_table
                and re.match(
                    r"^(NOTAS(\s+AL\s+PIE)?|AP[ÉE]NDICE|EP[ÍI]LOGO|GLOSARIO|[ÍI]NDICE|BIBLIOGRAF[ÍI]A|CONCLUSI[ÓO]N|FOOT-?NOTES?|NOTES?|APPENDIX|EPILOGUE|GLOSSARY|INDEX|BIBLIOGRAPHY)\b:?\.?$",
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
                clean_hd = re.sub(r"[:.]+$", "", ptxt).strip()
                _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
                continue

            # CHAPTER / SUBHEADINGS
            is_heading_cand = (
                not has_table
                and not in_cell_or_table
                and (
                    (
                        any(k in pstyle.lower() for k in ["chap", "head", "sub-heading"])
                        and not any(k in pstyle.lower() for k in ["toc", "verso", "copy", "main_page", "author", "caption"])
                    ) or (
                        re.match(r"^(cap[íi]tulo|libro|parte|acto|escena|secci[óo]n|chapter|book|part|act|scene)\b", ptxt, re.I)
                        and len(ptxt) < 120
                    ) or (
                        re.match(r"^(?:primer|segundo|tercer|cuarto|quinto|sexto|s[ée]ptimo|octavo|noveno|d[ée]cimo)\s+cap[íi]tulo\b", ptxt, re.I)
                        and len(ptxt) < 120
                    ) or (
                        re.match(r"^\d+\.\s+[A-ZÁÉÍÓÚÑ]", ptxt)
                        and len(ptxt) < 80
                    ) or (
                        re.match(r"^(?:[IVXLCDM]+\b\.?\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{2,})", ptxt)
                        and len(ptxt) < 80
                    )
                )
            )

            if is_heading_cand:
                book_part, chap_part, was_separated = split_runon_heading(ptxt, lang="es")
                effective_txt = chap_part if was_separated else ptxt
                norm_p = normalize_heading_str(effective_txt)
                norm_p_clean = re.sub(r'[\s\.\-_]+', '', norm_p)
                toc_clean_map = {re.sub(r'[\s\.\-_]+', '', t): t for t in toc_norms}
                epub_h1_clean_map = {re.sub(r'[\s\.\-_]+', '', h): h for h in epub_h1_set}
                c_num = extract_heading_number(effective_txt, lang="es")

                is_main = False
                if norm_p in epub_h1_set or norm_p_clean in epub_h1_clean_map:
                    is_main = True
                elif norm_p in epub_sub_set and norm_p not in epub_h1_set and norm_p_clean not in epub_h1_clean_map:
                    is_main = False
                elif len(toc_norms) > 1:
                    if norm_p in toc_norms or norm_p_clean in toc_clean_map:
                        is_main = True
                    elif c_num is not None and c_num in toc_chaps and (
                        is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt)
                    ):
                        is_main = True
                    elif any(norm_p.startswith(t) for t in toc_norms if len(t) > 6 and len(norm_p) > 6):
                        is_main = True
                    elif any(norm_p_clean.startswith(tc) for tc in toc_clean_map if len(tc) > 6 and len(norm_p_clean) > 6):
                        is_main = True
                else:
                    if is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt):
                        is_main = True

                # If original style was explicitly chapter_name and text is short, treat as main chapter
                if not is_main and any(k in pstyle.lower() for k in ["chapter_name", "chapter"]) and len(ptxt) < 60:
                    is_main = True

                if was_separated and book_part:
                    in_preface = False
                    in_footnotes = False
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

                    apply_paired_heading_format(psr, chap_part, font_name="Gill Sans MT", space_before="14", space_after="30", language="es")

                    last_h1_norm = normalize_heading_str(chap_part)
                    last_h1_text = chap_part
                    last_h1_num = c_num
                    seen_body_since_h1 = False
                    continue

                if is_main:
                    in_preface = False
                    in_footnotes = False
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
                        apply_paired_heading_format(psr, effective_txt, font_name="Gill Sans MT", space_before="14", space_after="30", language="es")
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
                            and not heading_text.lower().startswith("cap")
                            and norm_p not in toc_norms
                        ) else "ParagraphStyle/chapter_name"
                        space_aft = "20" if style_to_use == "ParagraphStyle/Sub-heading" else "30"
                        _format_clean_heading(psr, style_to_use, "Gill Sans MT", heading_text, space_after=space_aft)
                        psr.set("StartParagraph", "NextPage")

                        last_h1_norm = norm_p
                        last_h1_text = heading_text
                        last_h1_num = curr_h1_num
                        seen_body_since_h1 = False

                    chapters_separated += 1
                    changed = True
                    continue
                else:
                    parent = parent_map.get(psr)
                    _clean_subheading_page_break(psr, parent)
                    _format_clean_subheading(psr, "Gill Sans MT", ptxt, space_before="18", space_after="12", point_size=14)
                    changed = True
                    continue

            # PREFACE Body
            if in_preface and ptxt:
                psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                psr.set("FirstLineIndent", "18")
                psr.set("Justification", "LeftAlign" if "\u2028" in ptxt else "LeftJustified")
                psr.set("SpaceBefore", "1.5")
                psr.set("SpaceAfter", "3")
                psr.set("AppliedLanguage", "$ID/Spanish: Standard")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                body_styled += 1
                continue

            # FOOTNOTES / QUOTES
            is_fn = in_footnotes or "footnote" in pstyle.lower() or ptxt.startswith("{Nota ") or ptxt.startswith("[Nota")
            is_quote = any(k in pstyle.lower() for k in ["quote", "block", "verse", "poem"])
            _soft_lines = _split_soft_lines(psr)
            has_soft_break = _is_true_verse(psr)

            if is_fn and ptxt:
                psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
                psr.set("LeftIndent", "39.68503937007875")
                psr.set("RightIndent", "39.68503937007875")
                psr.set("FirstLineIndent", "0")
                psr.set("SpaceBefore", "1.5")
                psr.set("SpaceAfter", "3")
                psr.set("Justification", "LeftAlign" if has_soft_break else "LeftJustified")
                psr.set("AppliedLanguage", "$ID/Spanish: Standard")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                footnotes_formatted += 1
                continue
            elif is_quote or has_soft_break:
                psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
                psr.set("Justification", "LeftAlign")
                psr.set("LeftIndent", "39.68503937007875")
                psr.set("RightIndent", "39.68503937007875")
                psr.set("FirstLineIndent", "0")
                psr.set("SpaceBefore", "2")
                psr.set("SpaceAfter", "3")
                psr.set("AppliedLanguage", "$ID/Spanish: Standard")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                continue

            # If paragraph has chapter_name01 / chapter_name but is actually narrative body text (e.g. > 120 chars or full sentences without heading keywords)
            has_chap_kw = bool(re.match(r"^(?:cap[íi]tulo|chapter|parte|part|libro|book|acto|[íi]ndice|indice|index|prefacio|preface|pr[óo]logo|prologue|introducci[óo]n|introduction|conclusi[óo]n|conclusion|ep[íi]logo|epilogue|ap[ée]ndice|appendix|glosario|glossary|bibliograf[íi]a|bibliography|notas|notes|[IVXLCDM]+\b|\d+\b)\b", ptxt.strip(), re.I))
            is_mistaken_chap = (
                any(k in pstyle.lower() for k in ["chapter_name", "sub-heading"])
                and not has_chap_kw
                and (len(ptxt) > 120 or (len(ptxt) > 50 and "." in ptxt))
                and _normalize_heading_str(ptxt) not in toc_norms
                and not any(_normalize_heading_str(ptxt).startswith(t) for t in toc_norms if len(t) > 6)
            )

            # BODY TEXT
            if (
                is_mistaken_chap
                or (
                    any(k in pstyle.lower() for k in ["noindent", "body", "normal", "msonormal", "basic paragraph", "text", "style", "paragraph", "para"])
                    and not any(k in pstyle.lower() for k in ["chapter_name", "sub-heading", "heading", "toc", "verso", "copy", "author", "caption", "quote"])
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
                    psr.set("AppliedLanguage", "$ID/Spanish: Standard")
                    for csr in psr.iter():
                        if lname(csr.tag) == "CharacterStyleRange":
                            _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                            if csr.attrib.get("FontStyle") == "Bold" and "bold" not in csr.attrib.get("AppliedCharacterStyle", "").lower():
                                csr.set("FontStyle", "Regular")
                    body_styled += 1

            if len(ptxt) > 15 and not any(k in pstyle.lower() for k in ["head", "chap", "sub"]):
                seen_body_since_h1 = True

        # CharacterStyleRange cleanup (bold, italic, underline, runaway sub/sup, font family & size)
        for psr in root.iter():
            if lname(psr.tag) == "ParagraphStyleRange":
                pstyle = psr.attrib.get("AppliedParagraphStyle", "")
                is_body = any(k in pstyle.lower() for k in ["body_text", "noindent", "normal", "basic", "quotes_normal"])

                # Br-aware verse/block safety: ragged-left on verse or block/quote styles.
                _plines = _split_soft_lines(psr)
                _is_block_sty = any(k in pstyle.lower() for k in ("block", "quote", "verse", "poem"))
                _is_verse_p = _is_true_verse(psr)
                if _is_verse_p or _is_block_sty:
                    _eff_just = psr.attrib.get("Justification")
                    if _eff_just == "LeftJustified" or _eff_just is None:
                        psr.set("Justification", "LeftAlign")

                for csr in list(psr):
                    if lname(csr.tag) == "CharacterStyleRange":
                        csr.set("AppliedLanguage", "$ID/Spanish: Standard")
                        cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                        if cstyle in MERGE_MAP:
                            cstyle = MERGE_MAP[cstyle]
                            csr.set("AppliedCharacterStyle", cstyle)

                        # Clean runaway Subscript / Superscript
                        pos = csr.attrib.get("Position", "")
                        if pos in ("Subscript", "Superscript"):
                            has_table_inner = any(lname(c.tag) == "Table" for c in csr.iter())
                            raw_text = "".join(c.text for c in csr if lname(c.tag) == "Content" and c.text)
                            direct_text = raw_text.strip()
                            is_runaway = False
                            if has_table_inner or len(direct_text) > 5 or " " in raw_text or any(p in raw_text for p in [".", ",", ";", ":", "\u2028", "\r", "\n"]):
                                is_runaway = True
                            elif pos == "Subscript" and (not direct_text.isdigit() or len(direct_text) > 3):
                                is_runaway = True
                            elif pos == "Superscript" and not (direct_text.isdigit() or direct_text in ("*", "†", "‡", "§", "er", "o", "a", "os", "as")):
                                is_runaway = True

                            if is_runaway:
                                split_done = False
                                cnt_first = next((c for c in csr if lname(c.tag) == "Content" and c.text), None)
                                if cnt_first is not None and cnt_first.text:
                                    first_txt = cnt_first.text
                                    is_year = bool(re.match(r"^(18\d\d|19\d\d|20\d\d)", first_txt))
                                    if not is_year:
                                        m_sub = None
                                        if pos == "Subscript":
                                            m_sub = re.match(r"^(\d{1,3})(.*)$", first_txt, re.S)
                                        elif pos == "Superscript":
                                            m_sub = re.match(r"^(\d{1,3}|[\*†‡§]|er|o|a|os|as)(.*)$", first_txt, re.S)

                                        if m_sub and m_sub.group(1) and m_sub.group(2):
                                            token_part = m_sub.group(1)
                                            rest_part = m_sub.group(2)
                                            c_sub = ET.Element(csr.tag, attrib=dict(csr.attrib))
                                            c_sub.set("Position", pos)
                                            for child in csr:
                                                if lname(child.tag) == "Properties":
                                                    c_sub.append(copy.deepcopy(child))
                                            _ensure_font_prop(c_sub, "Palatino Linotype")
                                            sub_cnt = ET.SubElement(c_sub, "Content")
                                            sub_cnt.text = token_part

                                            cnt_first.text = rest_part
                                            del csr.attrib["Position"]
                                            if is_body:
                                                _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)

                                            idx = list(psr).index(csr)
                                            psr.insert(idx, c_sub)
                                            split_done = True

                                if not split_done:
                                    del csr.attrib["Position"]
                                    if is_body:
                                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                            else:
                                _ensure_font_prop(csr, "Palatino Linotype")

                        if "bold" in cstyle.lower() or csr.attrib.get("FontStyle") == "Bold":
                            csr.set("FontStyle", "Bold")
                            bold_fixed += 1
                        if "italic" in cstyle.lower() or csr.attrib.get("FontStyle") == "Italic":
                            csr.set("FontStyle", "Italic")
                            italic_fixed += 1

                        # Enforce uniform body font family & size
                        if is_body:
                            pos_now = csr.attrib.get("Position", "")
                            if pos_now not in ("Subscript", "Superscript"):
                                _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)

                        # Validate Underline
                        if cstyle == CANONICAL_CHAR_STYLES["underline"] or "underlin" in cstyle.lower():
                            c_text = "".join(c.text for c in csr.iter() if lname(c.tag) == "Content" and c.text).strip()
                            c_clean = c_text.lower().replace("\xa0", " ")
                            is_valid = False
                            if epub_underlines:
                                is_valid = any(c_clean == u or c_clean in u or u in c_clean for u in epub_underlines)
                            if not is_valid and re.search(r"\bfootnote\b|\bnota\b|\bref\b|\bsee\b|\bcf\b|\bpage\b|\bpág\b|\d{1,4}", c_clean):
                                is_valid = True
                            if not is_valid and len(c_clean) > 40:
                                csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                                if "Underline" in csr.attrib:
                                    del csr.attrib["Underline"]
                            else:
                                underline_fixed += 1

        write_xml(root, sp)

    return {
        "bold_fixed": bold_fixed,
        "italic_fixed": italic_fixed,
        "underline_fixed": underline_fixed,
        "chapters_separated": chapters_separated,
        "body_styled": body_styled,
        "footnotes_formatted": footnotes_formatted,
    }


def apply(target_dir, reference_dir, book_name=None):
    styles_report = update_styles_xml(target_dir, reference_dir)
    story_report = process_stories(target_dir, book_name=book_name)
    tables_fixed = fix_table_overfit(target_dir, max_width=324.0)
    return {
        "styles_xml": styles_report,
        "stories": story_report,
        "tables_fixed": tables_fixed,
    }

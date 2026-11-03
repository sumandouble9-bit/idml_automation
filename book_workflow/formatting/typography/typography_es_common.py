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

                            is_epub_it = bool(clean_c and clean_c in lower_italics)
                            is_epub_bd = bool(clean_c and clean_c in lower_bolds)

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
                                if c_csr.attrib.get("FontStyle") in ("Italic", "Bold"):
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


__all__ = [
    'CANONICAL_CHAR_STYLES',
    'MERGE_MAP',
    'ROMAN_MAP',
    'SPANISH_ORDINALS',
    'REF_MARKER_REGEX',
    '_normalize_table_content',
    '_is_page_break_spacer',
    '_is_blank_page_spacer',
    '_apply_heading_page_break',
    '_apply_preface_page_break',
    '_clean_subheading_page_break',
    '_split_soft_lines',
    '_is_true_verse',
    '_ensure_font_prop',
    '_format_clean_heading',
    '_format_clean_subheading',
    '_extract_chap_number_es',
    '_normalize_heading_str',
    '_extract_doc_toc_entries_es',
    '_clean_chapter_runon_es',
    '_load_epub_underlines_es',
]

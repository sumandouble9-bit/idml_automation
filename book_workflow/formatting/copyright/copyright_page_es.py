import copy
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.idml_utils import (
    content_text,
    copy_named_styles,
    find_main_story,
    lname,
    parse,
    sync_fonts,
    write_xml,
)


def _extract_copyright_data(root, book_name=None):
    from core.idml_utils import load_epub_copyright_info

    epub_info = load_epub_copyright_info(book_name, root)

    psrs = [e for e in root.iter() if lname(e.tag) == "ParagraphStyleRange"]
    title = epub_info.get("title", "")
    subtitle = epub_info.get("subtitle", "")
    author = epub_info.get("author", "")
    translation_credit = epub_info.get("translation_credit", "Translated from the English by Double9 Books Editorial Team")
    year = epub_info.get("year", "2026")
    isbn = epub_info.get("isbn", "")
    contents_idx = None

    for i, p in enumerate(psrs):
        txt = content_text(p).strip().replace("\u2028", " ")
        st = p.attrib.get("AppliedParagraphStyle", "")
        if any(k in txt.lower() for k in ["contenido", "índice", "indice", "contents"]) and len(txt) <= 25:
            contents_idx = i
            break
        if not txt:
            continue
        if not year or year == "2026":
            if "copyright" in txt.lower() or "derechos" in txt.lower() or "reservados" in txt.lower():
                m_yr = re.search(r"(?:copyright|©)\s*[©\u00a9]?\s*(\d{4})", txt, re.I)
                if m_yr:
                    year = m_yr.group(1)
        if not isbn:
            if "isbn" in txt.lower():
                m_isbn = re.search(r"isbn[:\s]*([0-9xX\-]+)", txt, re.I)
                if m_isbn:
                    isbn = f"ISBN: {m_isbn.group(1).strip()}"
        if not title:
            if "verso_title" in st.lower() or "copyhead" in st.lower():
                title = txt
        if not subtitle:
            if "copybody" in st.lower() or "subtitle" in st.lower():
                subtitle = txt
        if not author:
            if "verso_author" in st.lower() or "copy1" in st.lower():
                author = re.sub(r"^(?:por|by)\s*", "", txt, flags=re.I).strip()
        if not translation_credit:
            if "translated from the english" in txt.lower():
                translation_credit = txt

    # Fallback for title/author if not yet found
    if not title:
        for p in psrs[:5]:
            txt = content_text(p).strip()
            if txt and not any(k in txt.lower() for k in ["copyright", "derechos", "contenido", "índice"]):
                title = txt
                break
    if not author:
        for p in psrs[:7]:
            txt = content_text(p).strip()
            if re.match(r"^(?:por|by)\b", txt, re.I):
                author = re.sub(r"^(?:por|by)\s*", "", txt, flags=re.I).strip()
                break

    # Ensure master Spanish Print ISBN from isbn_manager is applied
    try:
        from core.isbn_manager import get_book_isbn_info
        lookup_cand = book_name or isbn
        meta = get_book_isbn_info(lookup_cand)
        if meta and meta.get("sp_print_isbn_formatted"):
            isbn = f"ISBN: {meta['sp_print_isbn_formatted']}"
    except Exception:
        pass

    if not isbn:
        isbn = "ISBN: 978-81-66130-48-9"

    if author:
        author = re.sub(r"^(?:por|by)\s+", "", author, flags=re.I).strip()

    return title, subtitle, author, year, isbn, translation_credit, contents_idx


def _make_csr(parent, text="", pt=None, font=None, bold=False, leading=None, br_count=1, caps=False, italic=False):
    csr = ET.SubElement(parent, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "AppliedLanguage": "$ID/Spanish: Standard",
    })
    if pt is not None:
        csr.set("PointSize", str(pt))
    if bold:
        csr.set("FontStyle", "Bold")
    elif italic:
        csr.set("FontStyle", "Italic")
    if caps:
        csr.set("Capitalization", "AllCaps")
    if leading is not None or font is not None:
        props = ET.SubElement(csr, "Properties")
        if leading is not None:
            l = ET.SubElement(props, "Leading", {"type": "unit"})
            l.text = str(leading)
        if font is not None:
            af = ET.SubElement(props, "AppliedFont", {"type": "string"})
            af.text = str(font)
    if text:
        cnt = ET.SubElement(csr, "Content")
        cnt.text = text
    for _ in range(br_count):
        ET.SubElement(csr, "Br")
    return csr


def _build_copyright_psrs(title, subtitle, author, year, isbn, translation_credit=""):
    # 1. Verso Title & Subtitle & Author (matching Screenshot 2 & Spanish Reference)
    p0 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/verso_title",
        "Justification": "CenterAlign",
    })
    
    # Split title lines if multi-line to preserve line breaks
    title_lines = [l.strip() for l in re.split(r"[\r\n\u2028]+", title) if l.strip()]
    if not title_lines:
        title_lines = [title]
    for tl in title_lines:
        _make_csr(p0, tl, pt=17, font="Ebrima", bold=True, leading=24.4, br_count=1, caps=True)

    if subtitle:
        sub_lines = [l.strip() for l in re.split(r"[\r\n\u2028]+", subtitle) if l.strip()]
        if not sub_lines:
            sub_lines = [subtitle]
        sub_pt = 10 if len(subtitle) > 40 else 12
        sub_ld = 12.0 if len(subtitle) > 40 else 14.0
        for sl in sub_lines:
            _make_csr(p0, sl, pt=sub_pt, font="Ebrima", bold=True, leading=sub_ld, br_count=1)

    _make_csr(p0, "", pt=1, leading=2.75, br_count=1)
    
    # Author strictly dynamic, NO "Por " prepended (matches Screenshot 2)
    clean_author = re.sub(r"^(?:por|by)\s+", "", author, flags=re.I).strip()
    _make_csr(p0, clean_author, pt=14, font="Ebrima", bold=True, leading=9.1, br_count=1)
    _make_csr(p0, "", pt=8, leading=10.0, br_count=1)

    # 2. Translation credit line (matches Screenshot 2 & Spanish Reference Story_u1eb.xml)
    p_trans = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
    })
    trans_text = translation_credit or "Translated from the English by Double9 Books Editorial Team"
    _make_csr(p_trans, trans_text, pt=11, bold=True, br_count=1)
    _make_csr(p_trans, "", pt=6, leading=8.0, br_count=1)

    # 3. Spanish Legal text block (matches Screenshot 2 & Spanish Reference)
    p1 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
    })
    csr1 = ET.SubElement(p1, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "AppliedLanguage": "$ID/Spanish: Standard",
    })
    is_long_layout = bool((subtitle and len(subtitle) > 40) or (len(title_lines) > 2))
    legal_parts = [
        (f"Copyright © {year}", 1 if is_long_layout else 2),
        ("Reservados todos los derechos.", 1),
        ("Ninguna parte de esta publicación puede ser reproducida,", 1),
        ("almacenado en un sistema de recuperación o transmitido en cualquier", 1),
        ("forma o por cualquier medio, electrónico, mecánico,", 1),
        ("fotocopia o cualquier otro medio, sin la autorización por escrito", 1),
        ("permiso del editor.", 1 if is_long_layout else 2),
        ("El autor/editor afirma el derecho moral a", 1),
        ("ser identificado como el autor/editor de esta obra.", 1 if is_long_layout else 2),
        (f"{isbn}", 1 if is_long_layout else 2),
    ]
    for text_val, brs in legal_parts:
        cnt = ET.SubElement(csr1, "Content")
        cnt.text = text_val
        for _ in range(brs):
            ET.SubElement(csr1, "Br")

    # 4. Publicado por
    p2 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
        "Hyphenation": "false",
    })
    _make_csr(p2, "Publicado por", pt=11, font="Palatino Linotype", bold=True, leading=14, br_count=1)

    # 5. Publisher Imprint Block: LeafBound + An Imprint of DOUBLE 9 BOOKS
    p3 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/doublenine_books",
        "Justification": "CenterAlign",
        "Hyphenation": "false",
        "SpaceBefore": "0",
        "SpaceAfter": "0",
    })
    csr3 = ET.SubElement(p3, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "PointSize": "18",
        "FontStyle": "Bold",
    })
    cnt3 = ET.SubElement(csr3, "Content")
    cnt3.text = "LeafBound"
    ET.SubElement(csr3, "Br")

    # An Imprint of DOUBLE 9 BOOKS (An Imprint of in italic, DOUBLE 9 BOOKS in bold/regular)
    p3_imprint = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
    })
    csr_imp_it = ET.SubElement(p3_imprint, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Italic",
    })
    cnt_imp_it = ET.SubElement(csr_imp_it, "Content")
    cnt_imp_it.text = "An Imprint of "

    csr_imp_b = ET.SubElement(p3_imprint, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Bold",
    })
    cnt_imp_b = ET.SubElement(csr_imp_b, "Content")
    cnt_imp_b.text = "DOUBLE 9 BOOKS"
    ET.SubElement(csr_imp_b, "Br")

    # 6. Spanish Address block (matching Screenshot 2 & Spanish Reference, NO Gutenberg notice)
    p4 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
    })
    csr4 = ET.SubElement(p4, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "AppliedLanguage": "$ID/Spanish: Standard",
    })
    address_parts = [
        ("2/13-B, Ansari Road", 1),
        ("Daryaganj, New Delhi - 110002", 1),
        ("info@double9books.com", 1),
        ("www.double9books.com", 1),
        ("Ph:011-40042856", 0),
    ]
    for text_val, brs in address_parts:
        cnt = ET.SubElement(csr4, "Content")
        cnt.text = text_val
        for _ in range(brs):
            ET.SubElement(csr4, "Br")

    return [p0, p_trans, p1, p2, p3, p3_imprint, p4]


def _update_path_point_array(tf, width, height):
    half_w = width / 2.0
    half_h = height / 2.0
    target_pts = [
        (-half_w, -half_h),
        (-half_w, half_h),
        (half_w, half_h),
        (half_w, -half_h),
    ]
    ppa = next((e for e in tf.iter() if lname(e.tag) == "PathPointArray"), None)
    if ppa is not None:
        pts = [c for c in ppa if lname(c.tag) == "PathPointType"]
        if len(pts) == 4:
            for pt, (x, y) in zip(pts, target_pts):
                pt.set("Anchor", f"{x:.12g} {y:.12g}")
                pt.set("LeftDirection", f"{x:.12g} {y:.12g}")
                pt.set("RightDirection", f"{x:.12g} {y:.12g}")
            return True
    return False


def apply(target_dir, reference_dir, book_name=None):
    target_story_path, target_root = find_main_story(target_dir)
    if target_root is None:
        raise RuntimeError("Could not find main story files.")

    ref_stories_dir = Path(reference_dir) / "Stories"
    ref_u2a6_path = ref_stories_dir / "Story_u2a6.xml"
    if not ref_u2a6_path.exists():
        for sp in ref_stories_dir.glob("*.xml"):
            txt = sp.read_text(encoding="utf-8", errors="ignore")
            if "verso_title" in txt or "copyright_text" in txt:
                ref_u2a6_path = sp
                break

    ref_root = parse(ref_u2a6_path)

    # 1. Extract dynamic metadata
    title, subtitle, author, year, isbn, translation_credit, contents_idx = _extract_copyright_data(target_root, book_name=book_name)

    t_story = Path(target_dir) / "Stories" / "Story_u_title_story.xml"
    if t_story.exists():
        try:
            t_root = parse(t_story)
            t_psrs = [e for e in t_root.iter() if lname(e.tag) == "ParagraphStyleRange"]
            if t_psrs:
                p0_csrs = [e for e in t_psrs[0].iter() if lname(e.tag) == "CharacterStyleRange"]
                if p0_csrs:
                    c0 = next((e for e in p0_csrs[0].iter() if lname(e.tag) == "Content"), None)
                    if c0 is not None and c0.text and c0.text.strip():
                        title = c0.text.strip()
                    if len(p0_csrs) >= 2:
                        c1 = next((e for e in p0_csrs[1].iter() if lname(e.tag) == "Content"), None)
                        if c1 is not None and c1.text and c1.text.strip():
                            subtitle = c1.text.strip()
            if len(t_psrs) > 3:
                p3_csrs = [e for e in t_psrs[3].iter() if lname(e.tag) == "CharacterStyleRange"]
                if p3_csrs:
                    ca = next((e for e in p3_csrs[0].iter() if lname(e.tag) == "Content"), None)
                    if ca is not None and ca.text and ca.text.strip():
                        author = ca.text.strip()
        except Exception:
            pass

    # 2. Build dedicated Story_u_copyright_story.xml
    new_story_root = copy.deepcopy(ref_root)
    target_dom = target_root.attrib.get("DOMVersion", "14.0")
    new_story_root.set("DOMVersion", target_dom)

    if "Self" in new_story_root.attrib:
        del new_story_root.attrib["Self"]

    story_elem = next(e for e in list(new_story_root) if lname(e.tag) == "Story")
    story_elem.set("Self", "u_copyright_story")
    story_elem.set("AppliedLanguage", "$ID/Spanish: Standard")

    for attr in list(story_elem.attrib.keys()):
        if attr.startswith("Ai"):
            del story_elem.attrib[attr]

    for child in list(story_elem):
        story_elem.remove(child)

    ET.SubElement(story_elem, "StoryPreference", {
        "OpticalMarginAlignment": "false",
        "OpticalMarginSize": "12",
        "FrameType": "TextFrameType",
        "StoryOrientation": "Horizontal",
        "StoryDirection": "LeftToRightDirection",
    })
    ET.SubElement(story_elem, "InCopyExportOption", {
        "IncludeGraphicProxies": "true",
        "IncludeAllResources": "false",
    })

    new_psrs = _build_copyright_psrs(title, subtitle, author, year, isbn, translation_credit=translation_credit)
    for p in new_psrs:
        story_elem.append(p)

    new_story_path = Path(target_dir) / "Stories" / "Story_u_copyright_story.xml"
    write_xml(new_story_root, new_story_path)

    # 3. Register in designmap.xml
    dmap_path = Path(target_dir) / "designmap.xml"
    if dmap_path.exists():
        dmap_root = parse(dmap_path)
        pkg_ns = "{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}"
        story_rel = "Stories/Story_u_copyright_story.xml"

        for child in list(dmap_root):
            if lname(child.tag) == "Story" and child.attrib.get("src") == story_rel:
                dmap_root.remove(child)

        new_el = ET.Element(f"{pkg_ns}Story", {"src": story_rel})
        last_story_idx = -1
        for idx, child in enumerate(list(dmap_root)):
            if lname(child.tag) in {"Story", "BackingStory"}:
                last_story_idx = idx
        if last_story_idx >= 0:
            dmap_root.insert(last_story_idx + 1, new_el)
        else:
            dmap_root.append(new_el)

        story_list = dmap_root.attrib.get("StoryList", "").split()
        if "u_copyright_story" not in story_list:
            idx_insert = story_list.index("u_title_story") + 1 if "u_title_story" in story_list else 0
            story_list.insert(idx_insert, "u_copyright_story")
            dmap_root.set("StoryList", " ".join(story_list))

        write_xml(dmap_root, dmap_path)

    # 4. Rewire Page 2 TextFrame on Spread 2
    spreads_dir = Path(target_dir) / "Spreads"
    spread2_path = None
    spread2_root = None

    for sp in spreads_dir.glob("*.xml"):
        r = parse(sp)
        pages = [p.attrib.get("Name") for p in r.iter() if lname(p.tag) == "Page"]
        if "2" in pages:
            spread2_path = sp
            spread2_root = r
            break

    if spread2_root is not None:
        p2_tf = None
        for tf in spread2_root.iter():
            if lname(tf.tag) == "TextFrame":
                p2_tf = tf
                break

        if p2_tf is not None:
            p2_tf.set("ParentStory", "u_copyright_story")
            p2_tf.set("PreviousTextFrame", "n")
            p2_tf.set("NextTextFrame", "n")
            p2_tf.set("ItemTransform", "1 0 0 1 -198 -9")
            _update_path_point_array(p2_tf, 324.0, 522.0)
            tfp = next((c for c in p2_tf if lname(c.tag) == "TextFramePreference"), None)
            if tfp is None:
                tfp = ET.SubElement(p2_tf, "TextFramePreference")
            tfp.set("VerticalJustification", "CenterAlign")

        # Unthread Page 3 text frame so it starts cleanly with Contents
        all_tfs = [e for e in spread2_root.iter() if lname(e.tag) == "TextFrame"]
        if len(all_tfs) >= 2:
            p3_tf = all_tfs[1]
            p3_tf.set("PreviousTextFrame", "n")

        write_xml(spread2_root, spread2_path)

    # 5. Clean old copyright paragraphs from main story
    psrs = [e for e in target_root.iter() if lname(e.tag) == "ParagraphStyleRange"]
    to_remove = []
    found_copyright = False

    for p in psrs:
        txt = content_text(p).strip()
        st = p.attrib.get("AppliedParagraphStyle", "")
        if any(k in txt.lower() for k in ["contenido", "índice", "indice", "contents"]) and len(txt) <= 25:
            break
        if "copyright" in txt.lower() or "derechos" in txt.lower() or "reservados" in txt.lower() or any(
            k in st.lower() for k in ["verso", "copy0", "copy1", "copyhead", "copybody", "doublenine"]
        ):
            found_copyright = True
            to_remove.append(p)
        elif found_copyright:
            if not txt or len(txt) < 80:
                to_remove.append(p)

    for p in to_remove:
        parent = None
        for cand in target_root.iter():
            if p in list(cand):
                parent = cand
                break
        if parent is not None:
            parent.remove(p)

    write_xml(target_root, target_story_path)

    styles_to_copy = {
        "ParagraphStyle/verso_title",
        "ParagraphStyle/verso_author",
        "ParagraphStyle/copyright_text",
        "ParagraphStyle/body_text",
        "ParagraphStyle/doublenine_books",
        "ParagraphStyle/about_the_autherh",
    }
    copy_named_styles(target_dir, reference_dir, styles_to_copy)
    sync_fonts(target_dir, reference_dir)

    return {
        "title": title,
        "subtitle": subtitle,
        "author": author,
        "year": year,
        "isbn": isbn,
        "new_story": "Story_u_copyright_story.xml",
    }

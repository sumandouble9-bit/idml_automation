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
    year = epub_info.get("year", "2025")
    isbn = epub_info.get("isbn", "")
    contents_idx = None

    for i, p in enumerate(psrs):
        txt = content_text(p).strip().replace("\u2028", " ")
        st = p.attrib.get("AppliedParagraphStyle", "")
        if "contents" in txt.lower() and len(txt) <= 25:
            contents_idx = i
            break
        if not txt:
            continue
        if not year or year == "2025":
            if "copyright" in txt.lower():
                m_yr = re.search(r"copyright\s*[©\u00a9]?\s*(\d{4})", txt, re.I)
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
                author = re.sub(r"^(?:by|por)\s*", "", txt, flags=re.I).strip()

    # Fallback for title/author if not yet found
    if not title:
        for p in psrs[:5]:
            txt = content_text(p).strip()
            if txt and "copyright" not in txt.lower() and "contents" not in txt.lower():
                title = txt
                break
    if not author:
        for p in psrs[:7]:
            txt = content_text(p).strip()
            if re.match(r"^by\b", txt, re.I):
                author = re.sub(r"^by\s*", "", txt, flags=re.I).strip()
                break

    # Ensure master Print ISBN from isbn_manager is applied
    try:
        from core.isbn_manager import get_book_isbn_info
        lookup_cand = book_name or isbn
        meta = get_book_isbn_info(lookup_cand)
        if meta and meta.get("sp_print_isbn_formatted"):
            isbn = f"ISBN: {meta['sp_print_isbn_formatted']}"
    except Exception:
        pass

    if not isbn:
        isbn = "ISBN: 978-93-70421-24-0"

    if author:
        author = re.sub(r"^(?:by|por)\s+", "", author, flags=re.I).strip()

    return title, subtitle, author, year, isbn, contents_idx


def _make_csr(parent, text="", pt=None, font=None, bold=False, leading=None, br_count=1, caps=False, italic=False):
    csr = ET.SubElement(parent, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
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


def _build_copyright_psrs(title, subtitle, author, year, isbn):
    # 1. Verso Title & Subtitle & Author (matching Reference Story_u2a6.xml & Screenshot 1)
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
    
    # Author strictly dynamic, NO "by " prepended (matches Screenshot 1)
    clean_author = re.sub(r"^(?:by|por)\s+", "", author, flags=re.I).strip()
    _make_csr(p0, clean_author, pt=14, font="Ebrima", bold=True, leading=9.1, br_count=1)
    _make_csr(p0, "", pt=13.25, leading=14.6, br_count=1)

    # 2. Legal text block (matching Reference Story_u2a6.xml & Screenshot 1)
    p1 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
    })
    csr1 = ET.SubElement(p1, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
    })
    is_long_layout = bool((subtitle and len(subtitle) > 40) or (len(title_lines) > 2))
    legal_parts = [
        (f"Copyright © {year}", 1 if is_long_layout else 2),
        ("All Rights reserved.", 1 if is_long_layout else 2),
        ("No part of this publication may be reproduced,", 1),
        ("stored in a retrieval system, or transmitted in any", 1),
        ("form or by any means, electronic, mechanical,", 1),
        ("photocopying or Otherwise, without the written", 1),
        ("permission of the publisher.", 1 if is_long_layout else 2),
        ("The author/editor asserts the moral right to", 1),
        ("be identified as the author/editor of this work.", 1 if is_long_layout else 2),
        (f"{isbn}", 1 if is_long_layout else 2),
    ]
    for text_val, brs in legal_parts:
        cnt = ET.SubElement(csr1, "Content")
        cnt.text = text_val
        for _ in range(brs):
            ET.SubElement(csr1, "Br")

    # 3. Published by
    p2 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
        "Hyphenation": "false",
    })
    _make_csr(p2, "Published by", pt=11, font="Palatino Linotype", bold=True, leading=14, br_count=1)

    # 4. DOUBLE 9 BOOKS
    p3 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/doublenine_books",
        "Justification": "CenterAlign",
        "Hyphenation": "false",
        "SpaceBefore": "0",
        "SpaceAfter": "0",
    })
    csr3 = ET.SubElement(p3, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
    })
    cnt3 = ET.SubElement(csr3, "Content")
    cnt3.text = "DOUBLE 9 BOOKS"
    ET.SubElement(csr3, "Br")

    # 5. Address block & Gutenberg notice (matching Screenshot 1)
    p4 = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/copyright_text",
        "Justification": "CenterAlign",
    })
    csr4 = ET.SubElement(p4, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
    })
    address_parts = [
        ("2/13-B, Ansari Road", 1),
        ("Daryaganj, New Delhi - 110002", 1),
        ("info@double9books.com", 1),
        ("www.double9books.com", 1),
        ("Ph:011-40042856", 3),
    ]
    for text_val, brs in address_parts:
        cnt = ET.SubElement(csr4, "Content")
        cnt.text = text_val
        for _ in range(brs):
            ET.SubElement(csr4, "Br")

    # Gutenberg public domain note with Project Gutenberg in italics
    cnt_g1 = ET.SubElement(csr4, "Content")
    cnt_g1.text = "This book is part of "

    csr_g_it = ET.SubElement(p4, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        "FontStyle": "Italic",
    })
    cnt_g_it = ET.SubElement(csr_g_it, "Content")
    cnt_g_it.text = "Project Gutenberg"

    csr_g_end = ET.SubElement(p4, "CharacterStyleRange", {
        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
    })
    cnt_g2 = ET.SubElement(csr_g_end, "Content")
    cnt_g2.text = " and is available at www.gutenberg.org"
    ET.SubElement(csr_g_end, "Br")
    cnt_g3 = ET.SubElement(csr_g_end, "Content")
    cnt_g3.text = "as this book is under public domain."

    return [p0, p1, p2, p3, p4]


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

    title, subtitle, author, year, isbn, contents_idx = _extract_copyright_data(target_root, book_name=book_name)

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
    all_psrs = [e for e in target_root.iter() if lname(e.tag) == "ParagraphStyleRange"]

    if contents_idx is None:
        contents_idx = min(4, len(all_psrs))

    contents_psr = all_psrs[contents_idx] if contents_idx < len(all_psrs) else None
    old_copyright_psrs = all_psrs[:contents_idx]

    # Build reference copyright paragraphs
    new_psrs = _build_copyright_psrs(title, subtitle, author, year, isbn)

    # 1. Create dedicated Story_u_copyright_story.xml cloned from reference Story_u2a6.xml
    target_dom = target_root.attrib.get("DOMVersion", "14.0")
    ref_u2a6 = None
    if reference_dir:
        stories_dir = Path(reference_dir) / "Stories"
        cand = stories_dir / "Story_u2a6.xml"
        if cand.exists():
            ref_u2a6 = cand
        else:
            for s in stories_dir.glob("Story_*.xml"):
                raw_txt = s.read_text(encoding="utf-8", errors="ignore")
                if "DOUBLE 9 BOOKS" in raw_txt:
                    ref_u2a6 = s
                    break

    if ref_u2a6 is not None:
        new_story_root = copy.deepcopy(parse(ref_u2a6))
        new_story_root.set("DOMVersion", target_dom)
        story_elem_c = next(e for e in list(new_story_root) if lname(e.tag) == "Story")
        story_elem_c.set("Self", "u_copyright_story")
        for attr in list(story_elem_c.attrib.keys()):
            if attr.startswith("Ai"):
                del story_elem_c.attrib[attr]
        # Remove old PSRs
        for c in list(story_elem_c):
            if lname(c.tag) == "ParagraphStyleRange":
                story_elem_c.remove(c)
        for psr in new_psrs:
            story_elem_c.append(psr)
    else:
        new_story_root = ET.Element("{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}Story", {
            "DOMVersion": target_dom,
        })
        story_elem_c = ET.SubElement(new_story_root, "Story", {
            "Self": "u_copyright_story",
            "AppliedTOCStyle": "n",
            "UserText": "true",
            "IsEndnoteStory": "false",
            "TrackChanges": "false",
            "StoryTitle": "$ID/",
            "AppliedNamedGrid": "n",
        })
        ET.SubElement(story_elem_c, "StoryPreference", {
            "OpticalMarginAlignment": "false",
            "OpticalMarginSize": "12",
            "FrameType": "TextFrameType",
            "StoryOrientation": "Horizontal",
            "StoryDirection": "LeftToRightDirection",
        })
        ET.SubElement(story_elem_c, "InCopyExportOption", {
            "IncludeGraphicProxies": "true",
            "IncludeAllResources": "false",
        })
        for psr in new_psrs:
            story_elem_c.append(psr)

    copyright_story_path = Path(target_dir) / "Stories" / "Story_u_copyright_story.xml"
    write_xml(new_story_root, copyright_story_path)

    # 2. Register u_copyright_story in designmap.xml using correct idPkg:Story element
    dm_path = Path(target_dir) / "designmap.xml"
    if dm_path.exists():
        dm_root = parse(dm_path)
        ns = "{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}"
        story_rel = "Stories/Story_u_copyright_story.xml"

        # Remove any existing ref
        for child in list(dm_root):
            if lname(child.tag) == "Story" and child.attrib.get("src") == story_rel:
                dm_root.remove(child)

        new_ref = ET.Element(f"{ns}Story", {"src": story_rel})
        last_story_idx = -1
        for idx, child in enumerate(list(dm_root)):
            if lname(child.tag) in {"Story", "BackingStory"}:
                last_story_idx = idx
        if last_story_idx >= 0:
            dm_root.insert(last_story_idx + 1, new_ref)
        else:
            dm_root.append(new_ref)

        story_list = dm_root.attrib.get("StoryList", "").split()
        if "u_copyright_story" not in story_list:
            idx_insert = story_list.index("u_title_story") + 1 if "u_title_story" in story_list else 0
            story_list.insert(idx_insert, "u_copyright_story")
            dm_root.set("StoryList", " ".join(story_list))

        write_xml(dm_root, dm_path)

    # 3. Update Spreads: Assign Page 2 TextFrame to u_copyright_story (standalone) and unthread Page 3
    spreads_dir = Path(target_dir) / "Spreads"
    for sp in spreads_dir.glob("*.xml"):
        sp_root = parse(sp)
        pages = [p.attrib.get("Name") for p in sp_root.findall(".//{*}Page")]
        if "2" in pages:
            changed_sp = False
            for tf in sp_root.findall(".//{*}TextFrame"):
                it = tf.attrib.get("ItemTransform", "").split()
                if len(it) == 6:
                    tx = float(it[4])
                    if tx < 0:
                        # Page 2 Copyright TextFrame: dedicated, unthreaded
                        tf.set("ParentStory", "u_copyright_story")
                        tf.set("PreviousTextFrame", "n")
                        tf.set("NextTextFrame", "n")
                        tf.set("ItemTransform", "1 0 0 1 -198 -9")
                        _update_path_point_array(tf, 324.0, 522.0)
                        tfp = next((c for c in tf if lname(c.tag) == "TextFramePreference"), None)
                        if tfp is None:
                            tfp = ET.SubElement(tf, "TextFramePreference")
                        tfp.set("VerticalJustification", "CenterAlign")
                        changed_sp = True
                    else:
                        # Page 3 TOC TextFrame: begins main story (unthreaded from Page 2)
                        tf.set("PreviousTextFrame", "n")
                        changed_sp = True

            if changed_sp:
                write_xml(sp_root, sp)
                break

    # 4. Remove all old copyright paragraphs from main story
    story_elem = next((e for e in target_root.iter() if lname(e.tag) == "Story" and "Self" in e.attrib), None)
    if story_elem is None:
        for cand in target_root.iter():
            if contents_psr in list(cand):
                story_elem = cand
                break
    if story_elem is None:
        story_elem = next(e for e in target_root.iter() if lname(e.tag) == "Story")

    for p in old_copyright_psrs:
        if p in list(story_elem):
            story_elem.remove(p)

    # 5. Format Contents heading (first paragraph of main story starting on Page 3)
    if contents_psr is not None:
        contents_psr.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
        contents_psr.set("Justification", "CenterAlign")
        contents_psr.set("SpaceBefore", "0")
        contents_psr.set("SpaceAfter", "15")
        if "ParagraphBreakType" in contents_psr.attrib:
            del contents_psr.attrib["ParagraphBreakType"]

        for child in list(contents_psr):
            contents_psr.remove(child)

        _make_csr(contents_psr, "Contents", pt=18, font="Times New Roman", bold=True, br_count=1)

    # Strip ParagraphBreakType only from front-matter / copyright paragraphs if present
    for p in old_copyright_psrs:
        for el in p.iter():
            if "ParagraphBreakType" in el.attrib:
                del el.attrib["ParagraphBreakType"]

    write_xml(target_root, target_story_path)

    # 6. Copy and configure styles
    styles_to_copy = {
        "ParagraphStyle/verso_title",
        "ParagraphStyle/verso_author",
        "ParagraphStyle/copyright_text",
        "ParagraphStyle/body_text",
        "ParagraphStyle/doublenine_books",
        "ParagraphStyle/about_the_autherh",
    }
    copied, added, missing = copy_named_styles(
        target_dir, reference_dir, styles_to_copy
    )

    styles_path = Path(target_dir) / "Resources" / "Styles.xml"
    if styles_path.exists():
        sroot = parse(styles_path)
        for ps in sroot.iter():
            name = ps.attrib.get("Self", "")
            if name == "ParagraphStyle/doublenine_books":
                ps.set("PointSize", "22")
                ps.set("FontStyle", "Black")
                ps.set("Justification", "CenterAlign")
                ps.set("SpaceBefore", "1")
                ps.set("SpaceAfter", "1")
                props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                if props is not None:
                    af = next((c for c in props if lname(c.tag) == "AppliedFont"), None)
                    if af is not None:
                        af.text = "Humnst777 BlkCn BT"
            elif name == "ParagraphStyle/copyright_text":
                ps.set("Justification", "CenterAlign")
                ps.set("PointSize", "12")
                ps.set("SpaceBefore", "0.5")
                ps.set("SpaceAfter", "0.5")
                props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                if props is not None:
                    ld = next((c for c in props if lname(c.tag) == "Leading"), None)
                    if ld is not None:
                        ld.text = "14"
            elif name == "ParagraphStyle/verso_title":
                ps.set("Justification", "CenterAlign")
                ps.set("PointSize", "16")
                ps.set("FontStyle", "Bold")
                ps.set("SpaceBefore", "1")
                ps.set("SpaceAfter", "1")
                props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                if props is not None:
                    af = next((c for c in props if lname(c.tag) == "AppliedFont"), None)
                    if af is not None:
                        af.text = "Ebrima"
                    ld = next((c for c in props if lname(c.tag) == "Leading"), None)
                    if ld is not None:
                        ld.text = "24.4"
            elif name == "ParagraphStyle/verso_author":
                ps.set("Justification", "CenterAlign")
                ps.set("PointSize", "14")
                ps.set("FontStyle", "Bold")
                ps.set("SpaceBefore", "3")
                ps.set("SpaceAfter", "1")
                props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                if props is not None:
                    af = next((c for c in props if lname(c.tag) == "AppliedFont"), None)
                    if af is not None:
                        af.text = "Ebrima"
                    ld = next((c for c in props if lname(c.tag) == "Leading"), None)
                    if ld is not None:
                        ld.text = "15"
        write_xml(sroot, styles_path)

    fonts_synced = sync_fonts(target_dir, reference_dir)

    return {
        "title": title,
        "subtitle": subtitle,
        "author": author,
        "year": year,
        "isbn": isbn,
        "copyright_paragraphs": len(new_psrs),
        "styles_copied": copied + added,
        "fonts_synced": fonts_synced,
    }

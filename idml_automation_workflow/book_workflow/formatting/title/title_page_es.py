"""
Spanish Title Page Module:
- Dedicated title page formatter for Spanish IDML books.
- Replicates Reference Title Page layout:
  1. Main Title (29 pt Helvetica Bold, Centered) + Subtitle (18/15 pt, Centered, if present)
  2. Clean spacer paragraph (PointSize=18)
  3. Separate "Por" credit (17 pt Minion Pro italic, author_name style, Centered)
  4. Author name (16 pt Times New Roman regular, main_page_title style, Centered)
- Centers TextFrame: Width 324 pt, Height 290 pt, ItemTransform="1 0 0 1 198 -9"
- Centers Publisher Logo Polygon at ItemTransform="1 0 0 1 198.5325489776247 220.0"
- Unthreads Page 2 text frame so Page 2 starts cleanly with Copyright
- Removes old front-matter title paragraphs from target's main story
"""

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
    load_epub_titlepage_extras,
    parse,
    sync_fonts,
    write_xml,
)


def _paragraphs(root):
    return [e for e in root.iter() if lname(e.tag) == "ParagraphStyleRange"]


def _is_publisher_imprint(txt: str) -> bool:
    """Detects historical publisher imprint lines, publishing cities, dates, or legal text."""
    if not txt:
        return True
    t_clean = txt.strip()
    if re.search(r"\b(?:cassell|company|limited|londres|parís|paris|nueva york|new york|melbourne|boston|chicago|madrid|barcelona|editorial|ediciones|imprenta|printed by|published by|publishing|publisher|press|impreso en)\b", t_clean, re.I):
        return True
    # 4-digit year like 1890, 1901 alone or with punctuation
    if re.fullmatch(r"[\d\s\.\,\;\:\-\–\—\(\)\[\]]{4,10}", t_clean):
        return True
    if any(k in t_clean.lower() for k in ["double 9 books", "derechos reservados", "all rights reserved", "isbn"]):
        return True
    return False


def _extract_title_parts(psrs):
    """
    Extracts (title, subtitle, by, author, epigraph, is_epigraph_bold, front_psrs) from front paragraphs.
    Front paragraphs end when verso/copyright is encountered.
    """
    front_psrs = []
    for psr in psrs[:12]:
        style = psr.attrib.get("AppliedParagraphStyle", "")
        txt = content_text(psr).strip()
        if (
            "copyright" in txt.lower()
            or "derechos de autor" in txt.lower()
            or "reservados" in txt.lower()
            or "copy0" in style.lower()
            or "verso" in style.lower()
            or "copyhead" in style.lower()
        ):
            break
        front_psrs.append(psr)

    if not front_psrs:
        front_psrs = psrs[:2]

    title = ""
    subtitle = ""
    by = "Por"
    author = ""
    epigraph = ""
    is_epigraph_bold = False

    non_quote_psrs = []
    for psr in front_psrs:
        style = psr.attrib.get("AppliedParagraphStyle", "").lower()
        txt = content_text(psr).strip()
        if not txt or _is_publisher_imprint(txt):
            continue
        # Detect explicit quotes or verse/poetry/epigraph paragraphs
        if any(k in style for k in ["quote", "epigraph", "block"]) or (
            re.search(r"[\u2013\u2014\-]\s*[A-Z]{3,}", txt) and not re.match(r"^(?:por|by)\b", txt, re.I)
        ):
            if not epigraph:
                epigraph = txt
            else:
                epigraph += "\u2028" + txt
            if any(c.attrib.get("FontStyle") == "Bold" for c in psr.iter()):
                is_epigraph_bold = True
        else:
            non_quote_psrs.append(psr)

    if non_quote_psrs:
        p0_text = content_text(non_quote_psrs[0]).strip()
        if len(non_quote_psrs) == 1:
            lines = [x.strip() for x in re.split(r"[\u2028\r\n]+", p0_text) if x.strip()]
            title = lines[0] if lines else ""
            for line in lines[1:]:
                if _is_publisher_imprint(line):
                    continue
                if re.match(r"^(?:por|by)\b", line, re.I):
                    by_part = re.sub(r"^(?:por|by)[:\s]*", "", line, flags=re.I).strip()
                    if by_part:
                        author = by_part
                elif not author:
                    author = line
                elif not epigraph and not _is_publisher_imprint(line):
                    epigraph = line
        else:
            title = p0_text
            for psr in non_quote_psrs[1:]:
                txt = content_text(psr).strip()
                if not txt or _is_publisher_imprint(txt):
                    continue
                if re.match(r"^(?:por|by)\b", txt, re.I) or "author" in psr.attrib.get("AppliedParagraphStyle", "").lower():
                    by_part = re.sub(r"^(?:por|by)[:\s]*", "", txt, flags=re.I).strip()
                    if by_part:
                        author = by_part
                    by = "Por"
                elif not author:
                    if not subtitle:
                        subtitle = txt
                    else:
                        author = txt
                else:
                    if not epigraph:
                        epigraph = txt
                    else:
                        epigraph += "\u2028" + txt

    return title, subtitle, by, author, epigraph, is_epigraph_bold, front_psrs


def find_reference_title_story(reference_dir):
    """Locate the reference title story (Story_u288.xml or via Spread 1)."""
    stories_dir = Path(reference_dir) / "Stories"
    ref_u288 = stories_dir / "Story_u288.xml"
    if ref_u288.exists():
        return ref_u288, parse(ref_u288)

    spreads_dir = Path(reference_dir) / "Spreads"
    for sp in spreads_dir.glob("*.xml"):
        root = parse(sp)
        pages = [p.attrib.get("Name") for p in root.iter() if lname(p.tag) == "Page"]
        if "1" in pages:
            for tf in root.iter():
                if lname(tf.tag) == "TextFrame":
                    sid = tf.attrib.get("ParentStory")
                    spath = stories_dir / f"Story_{sid}.xml"
                    if spath.exists():
                        return spath, parse(spath)

    raise RuntimeError("Could not locate reference title story.")


def _update_or_clone_polygon(sp_root, reference_dir):
    """
    Ensures Spread 1 has the publisher logo Polygon at
    ItemTransform="1 0 0 1 198.5325489776247 220.0"
    with correct path points matching reference.
    """
    poly = next((e for e in sp_root.iter() if lname(e.tag) == "Polygon"), None)

    ref_poly = None
    if reference_dir:
        ref_spreads = Path(reference_dir) / "Spreads"
        for rsp in ref_spreads.glob("*.xml"):
            rroot = parse(rsp)
            rpages = [p.attrib.get("Name") for p in rroot.iter() if lname(p.tag) == "Page"]
            if "1" in rpages:
                ref_poly = next((e for e in rroot.iter() if lname(e.tag) == "Polygon"), None)
                if ref_poly is not None:
                    break

    target_pts = [
        "-25.60902897762477 -28.34730737762474",
        "-25.60902897762477 17.412692622375296",
        "0.6668510998203487 17.41269262237529",
        "24.543931022375315 17.412692622375296",
        "24.543931022375315 -28.34730737762474",
    ]

    if poly is not None:
        poly.set("ItemTransform", "1 0 0 1 198.5325489776247 220.0")
        ppa = next((e for e in poly.iter() if lname(e.tag) == "PathPointArray"), None)
        if ppa is not None:
            pts = [c for c in ppa if lname(c.tag) == "PathPointType"]
            if len(pts) == len(target_pts):
                for pt, t in zip(pts, target_pts):
                    pt.set("Anchor", t)
                    pt.set("LeftDirection", t)
                    pt.set("RightDirection", t)

        img = next((e for e in poly.iter() if lname(e.tag) == "Image"), None)
        if img is not None:
            img.set(
                "ItemTransform",
                "0.046437925925926014 0 0 0.04237037037037037 -25.609028977624785 -28.347307377624723",
            )
        return "updated"

    elif ref_poly is not None:
        new_poly = copy.deepcopy(ref_poly)
        spread_elem = next((e for e in sp_root.iter() if lname(e.tag) == "Spread"), sp_root)
        spread_elem.append(new_poly)
        return "cloned"

    return "none"


def apply(target_dir, reference_dir):
    target_story_path, target_root = find_main_story(target_dir)
    if target_root is None:
        raise RuntimeError("Could not locate target main story.")

    ref_story_path, ref_story_root = find_reference_title_story(reference_dir)
    target_psrs = _paragraphs(target_root)

    (
        title,
        subtitle,
        by_text,
        author_name,
        epigraph_quote,
        is_epigraph_bold,
        old_front_psrs,
    ) = _extract_title_parts(target_psrs)

    if not epigraph_quote:
        book_name = Path(target_dir).parent.name
        epub_quote, is_bold = load_epub_titlepage_extras(book_name)
        if epub_quote:
            epigraph_quote = epub_quote
            is_epigraph_bold = is_bold

    if not title:
        raise RuntimeError("Target title text is empty.")

    # 1. Build dedicated title story cloned from reference Story_u288.xml
    new_story_root = copy.deepcopy(ref_story_root)
    target_dom = target_root.attrib.get("DOMVersion", "14.0")
    new_story_root.set("DOMVersion", target_dom)

    # Clean packaging root attributes
    if "Self" in new_story_root.attrib:
        del new_story_root.attrib["Self"]

    story_elem = next(e for e in list(new_story_root) if lname(e.tag) == "Story")
    story_elem.set("Self", "u_title_story")
    story_elem.set("AppliedLanguage", "$ID/Spanish: Standard")

    for attr in list(story_elem.attrib.keys()):
        if attr.startswith("Ai"):
            del story_elem.attrib[attr]

    story_psrs = [e for e in story_elem.iter() if lname(e.tag) == "ParagraphStyleRange"]
    if len(story_psrs) < 4:
        raise RuntimeError("Reference title story has fewer than 4 ParagraphStyleRanges.")

    # PSR 0: Title & Subtitle (main_page_title, PointSize=29)
    p0_csrs = [e for e in story_psrs[0].iter() if lname(e.tag) == "CharacterStyleRange"]
    if p0_csrs:
        t_content = next((e for e in p0_csrs[0].iter() if lname(e.tag) == "Content"), None)
        if t_content is not None:
            t_content.text = title

        if subtitle:
            if len(p0_csrs) >= 2:
                s_content = next((e for e in p0_csrs[1].iter() if lname(e.tag) == "Content"), None)
                if s_content is not None:
                    s_content.text = subtitle
                sub_props = next((e for e in p0_csrs[1].iter() if lname(e.tag) == "Properties"), None)
                if sub_props is None:
                    sub_props = ET.SubElement(p0_csrs[1], "Properties")
                sub_leading = next((e for e in sub_props.iter() if lname(e.tag) == "Leading"), None)
                if sub_leading is None:
                    sub_leading = ET.SubElement(sub_props, "Leading", {"type": "unit"})

                if len(subtitle) > 80:
                    p0_csrs[1].set("PointSize", "11")
                    sub_leading.text = "15"
                elif len(subtitle) > 35:
                    p0_csrs[1].set("PointSize", "13")
                    sub_leading.text = "18"
                else:
                    p0_csrs[1].set("PointSize", "16")
                    sub_leading.text = "22"
            if len(p0_csrs) >= 3:
                story_psrs[0].remove(p0_csrs[2])
        else:
            if len(p0_csrs) >= 3:
                story_psrs[0].remove(p0_csrs[1])

    # PSR 1: Spacer paragraph
    if (subtitle or len(title) > 30) and len(story_psrs) > 1:
        for child in list(story_psrs[1]):
            story_psrs[1].remove(child)
        sp_size = "10" if (subtitle and len(subtitle) > 40) else "16"
        sp_csr = ET.SubElement(story_psrs[1], "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            "PointSize": sp_size,
        })
        ET.SubElement(sp_csr, "Br")

    # PSR 2: "Por" (author_name style, Minion Pro Italic 17pt)
    if len(story_psrs) > 2:
        story_psrs[2].set("AppliedParagraphStyle", "ParagraphStyle/author_name")
        for child in list(story_psrs[2]):
            story_psrs[2].remove(child)
        by_csr = ET.SubElement(story_psrs[2], "CharacterStyleRange", {
            "AppliedCharacterStyle": "CharacterStyle/italic",
            "FontStyle": "Italic",
            "PointSize": "17",
            "AppliedLanguage": "$ID/Spanish: Standard",
        })
        props = ET.SubElement(by_csr, "Properties")
        ld = ET.SubElement(props, "Leading", {"type": "unit"})
        ld.text = "26.2"
        af = ET.SubElement(props, "AppliedFont", {"type": "string"})
        af.text = "Minion Pro"
        cnt = ET.SubElement(by_csr, "Content")
        cnt.text = "Por"
        ET.SubElement(by_csr, "Br")

    # PSR 3: Author Name (author_name style, Times New Roman 16pt)
    story_psrs[3].set("AppliedParagraphStyle", "ParagraphStyle/author_name")
    p3_csrs = [e for e in story_psrs[3].iter() if lname(e.tag) == "CharacterStyleRange"]
    if p3_csrs:
        a_content = next((e for e in p3_csrs[0].iter() if lname(e.tag) == "Content"), None)
        if a_content is not None:
            a_content.text = author_name

    # PSR 4: Epigraph / Quote / Verse (quotes_normal style, Palatino Linotype 10pt Italic)
    if epigraph_quote:
        q_psr = ET.SubElement(story_elem, "ParagraphStyleRange", {
            "AppliedParagraphStyle": "ParagraphStyle/quotes_normal",
            "Justification": "LeftAlign",
            "FirstLineIndent": "0",
            "LeftIndent": "18",
            "RightIndent": "18",
            "SpaceBefore": "24",
            "SpaceAfter": "6",
            "AppliedLanguage": "$ID/Spanish: Standard",
        })
        q_csr = ET.SubElement(q_psr, "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            "FontStyle": "BoldItalic" if is_epigraph_bold else "Italic",
            "PointSize": "10",
            "AppliedLanguage": "$ID/Spanish: Standard",
        })
        props = ET.SubElement(q_csr, "Properties")
        af = ET.SubElement(props, "AppliedFont", {"type": "string"})
        af.text = "Palatino Linotype"
        ld = ET.SubElement(props, "Leading", {"type": "unit"})
        ld.text = "13.5"
        cnt = ET.SubElement(q_csr, "Content")
        cnt.text = epigraph_quote
        ET.SubElement(q_csr, "Br")

    # Save new title story
    new_story_path = Path(target_dir) / "Stories" / "Story_u_title_story.xml"
    write_xml(new_story_root, new_story_path)

    # 2. Register Story_u_title_story.xml in designmap.xml
    dmap_path = Path(target_dir) / "designmap.xml"
    if dmap_path.exists():
        dmap_root = parse(dmap_path)
        pkg_ns = "{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}"
        story_rel = "Stories/Story_u_title_story.xml"
        existing = [e.attrib.get("src") for e in dmap_root.findall(".//{*}Story")]
        if story_rel not in existing:
            new_story_el = ET.Element(f"{pkg_ns}Story", {"src": story_rel})
            last_story_idx = -1
            for idx, child in enumerate(list(dmap_root)):
                if lname(child.tag) in {"Story", "BackingStory"}:
                    last_story_idx = idx
            if last_story_idx >= 0:
                dmap_root.insert(last_story_idx + 1, new_story_el)
            else:
                dmap_root.append(new_story_el)

        # Register u_title_story in Document StoryList attribute
        story_list = dmap_root.attrib.get("StoryList", "").split()
        if "u_title_story" not in story_list:
            story_list.insert(0, "u_title_story")
            dmap_root.set("StoryList", " ".join(story_list))

        write_xml(dmap_root, dmap_path)

    # 3. Locate Spread 1 and rewire Page 1 TextFrame
    spreads_dir = Path(target_dir) / "Spreads"
    spread1_path = None
    spread1_root = None

    for sp in spreads_dir.glob("*.xml"):
        root = parse(sp)
        pages = [p.attrib.get("Name") for p in root.iter() if lname(p.tag) == "Page"]
        if "1" in pages:
            spread1_path = sp
            spread1_root = root
            break

    polygon_status = "none"
    if spread1_root is not None:
        for tf in spread1_root.iter():
            if lname(tf.tag) == "TextFrame":
                tf.set("ParentStory", "u_title_story")
                tf.set("PreviousTextFrame", "n")
                tf.set("NextTextFrame", "n")

                tf.set("ItemTransform", "1 0 0 1 198 -30")
                half_w = 324.0 / 2.0
                half_h = 400.0 / 2.0  # 200.0 pt height

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
                break

        # Check Page 2 TextFrame on Spread 2 to unthread it from Page 1
        for sp in spreads_dir.glob("*.xml"):
            if sp == spread1_path:
                continue
            r = parse(sp)
            pages = [p.attrib.get("Name") for p in r.iter() if lname(p.tag) == "Page"]
            if "2" in pages:
                changed_sp2 = False
                for tf in r.iter():
                    if lname(tf.tag) == "TextFrame":
                        if tf.attrib.get("PreviousTextFrame") != "n":
                            tf.set("PreviousTextFrame", "n")
                            changed_sp2 = True
                        break
                if changed_sp2:
                    write_xml(r, sp)
                break

        polygon_status = _update_or_clone_polygon(spread1_root, reference_dir)
        write_xml(spread1_root, spread1_path)

    # 4. Remove old front-matter title paragraphs from target's main story
    for p in old_front_psrs:
        parent = None
        for cand in target_root.iter():
            if p in list(cand):
                parent = cand
                break
        if parent is not None:
            parent.remove(p)

    write_xml(target_root, target_story_path)

    # 5. Copy necessary styles and fonts from reference
    styles_to_copy = {
        "ParagraphStyle/main_page_title",
        "ParagraphStyle/author_name",
        "ParagraphStyle/quotes_normal",
        "CharacterStyle/italic",
    }
    copy_named_styles(target_dir, reference_dir, styles_to_copy)
    sync_fonts(target_dir, reference_dir)

    return {
        "title": title,
        "subtitle": subtitle,
        "by": "Por",
        "author": author_name,
        "epigraph": epigraph_quote,
        "polygon_status": polygon_status,
        "new_story": "Story_u_title_story.xml",
    }

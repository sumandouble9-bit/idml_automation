"""
Title Page Module:

- Task 2: Preserve formatting and positioning of the title page as per original/reference
- Task 9: Fix the title-page font size and font style according to reference layout
- Task 10: Preserve the title-page "by" credit styling separately from title and author text

Produces an exact replica of Reference Title Page 
- Decouples Page 1 into an independent, unthreaded story (Story_u_title_story.xml)
- Replicates the exact 4 ParagraphStyleRanges from Reference Story_u288.xml:
  1. Main Title (29 pt Helvetica Bold, Centered) + Subtitle (20 pt, Centered, if present) + spacer (20 pt)
  2. Exact 3-blank-return spacer paragraph (CSR size=27.77 pt br=2 + CSR size=0.1 pt br=1)
  3. Separate "by" credit (17 pt Minion Pro italic, author_name style, Centered)
  4. Author name (16 pt Times New Roman regular, main_page_title style, Centered)
- Centers TextFrame: Width 324 pt, Height 290 pt, ItemTransform="1 0 0 1 198 -9"
- Centers Publisher Logo Polygon at ItemTransform="1 0 0 1 198.5325489776247 225.34730737762473"
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
    by = "by"
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
            re.search(r"[\u2013\u2014\-]\s*[A-Z]{3,}", txt) and not re.match(r"^by\b", txt, re.I)
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
                if re.match(r"^by\b", line, re.I):
                    by_part = re.sub(r"^by[:\s]*", "", line, flags=re.I).strip()
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
                if re.match(r"^by\b", txt, re.I) or "author" in psr.attrib.get("AppliedParagraphStyle", "").lower():
                    by_part = re.sub(r"^by[:\s]*", "", txt, flags=re.I).strip()
                    if by_part:
                        author = by_part
                    by = "by"
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
    ItemTransform="1 0 0 1 198.5325489776247 225.34730737762473"
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
        # Clone reference polygon into spread
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

    # Target the inner Story element (child of packaging idPkg:Story)
    story_elem = next(e for e in list(new_story_root) if lname(e.tag) == "Story")
    story_elem.set("Self", "u_title_story")

    # Clean all InDesign CC 2026 AI attributes
    for attr in list(story_elem.attrib.keys()):
        if attr.startswith("Ai"):
            del story_elem.attrib[attr]

    story_psrs = [e for e in story_elem.iter() if lname(e.tag) == "ParagraphStyleRange"]
    if len(story_psrs) < 4:
        raise RuntimeError("Reference title story has fewer than 4 ParagraphStyleRanges.")

    # PSR 0: Title & Subtitle (main_page_title, PointSize=29)
    p0_csrs = [e for e in story_psrs[0].iter() if lname(e.tag) == "CharacterStyleRange"]
    if p0_csrs:
        # CSR 0: Title
        t_content = next((e for e in p0_csrs[0].iter() if lname(e.tag) == "Content"), None)
        if t_content is not None:
            t_content.text = title

        if subtitle:
            # CSR 1: Subtitle
            if len(p0_csrs) >= 2:
                s_content = next((e for e in p0_csrs[1].iter() if lname(e.tag) == "Content"), None)
                if s_content is not None:
                    s_content.text = subtitle
                # If subtitle is long, scale point size down
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
            # Remove trailing blank CSR in PSR 0 when subtitle is present
            if len(p0_csrs) >= 3:
                story_psrs[0].remove(p0_csrs[2])
        else:
            # If no subtitle, remove the subtitle CSR (CSR 1)
            if len(p0_csrs) >= 3:
                story_psrs[0].remove(p0_csrs[1])

    # PSR 1: Spacer paragraph
    # If subtitle is present or title is long, use 1 clean break to guarantee author is never overset/clipped
    if (subtitle or len(title) > 30) and len(story_psrs) > 1:
        for child in list(story_psrs[1]):
            story_psrs[1].remove(child)
        sp_size = "10" if (subtitle and len(subtitle) > 40) else "16"
        sp_csr = ET.SubElement(story_psrs[1], "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            "PointSize": sp_size,
        })
        ET.SubElement(sp_csr, "Br")

    # PSR 2: "by" (author_name style, Minion Pro Italic 17pt)
    if len(story_psrs) > 2:
        story_psrs[2].set("AppliedParagraphStyle", "ParagraphStyle/author_name")
        for child in list(story_psrs[2]):
            story_psrs[2].remove(child)
        by_csr = ET.SubElement(story_psrs[2], "CharacterStyleRange", {
            "AppliedCharacterStyle": "CharacterStyle/italic",
            "FontStyle": "Italic",
            "PointSize": "17",
        })
        props = ET.SubElement(by_csr, "Properties")
        ld = ET.SubElement(props, "Leading", {"type": "unit"})
        ld.text = "26.2"
        af = ET.SubElement(props, "AppliedFont", {"type": "string"})
        af.text = "Minion Pro"
        cnt = ET.SubElement(by_csr, "Content")
        cnt.text = "by"
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
        })
        q_csr = ET.SubElement(q_psr, "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            "FontStyle": "BoldItalic" if is_epigraph_bold else "Italic",
            "PointSize": "10",
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

    # 2. Register new story in designmap.xml
    dm_path = Path(target_dir) / "designmap.xml"
    if dm_path.exists():
        dm_root = parse(dm_path)
        existing = [e.attrib.get("src") for e in dm_root.findall(".//{*}Story")]
        if "Stories/Story_u_title_story.xml" not in existing:
            ns = "{http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging}"
            new_ref = ET.Element(f"{ns}Story", {"src": "Stories/Story_u_title_story.xml"})
            # Insert adjacent to existing Story elements
            last_story_idx = -1
            for idx, child in enumerate(list(dm_root)):
                if lname(child.tag) in {"Story", "BackingStory"}:
                    last_story_idx = idx
            if last_story_idx >= 0:
                dm_root.insert(last_story_idx + 1, new_ref)
            else:
                dm_root.append(new_ref)

        # Register u_title_story in Document StoryList attribute
        story_list = dm_root.attrib.get("StoryList", "").split()
        if "u_title_story" not in story_list:
            story_list.insert(0, "u_title_story")
            dm_root.set("StoryList", " ".join(story_list))

        write_xml(dm_root, dm_path)

    # 3. Update Spread 1: assign Page 1 TextFrame to u_title_story, unthread from Page 2
    spreads_dir = Path(target_dir) / "Spreads"
    spread_files = list(spreads_dir.glob("*.xml"))
    next_tf_to_unthread = None
    poly_status = "none"

    for sp in spread_files:
        sp_root = parse(sp)
        pages = [p.attrib.get("Name") for p in sp_root.findall(".//{*}Page")]
        if "1" in pages:
            # Page 1 TextFrame
            tf = next((e for e in sp_root.findall(".//{*}TextFrame")), None)
            if tf is not None:
                next_tf_to_unthread = tf.attrib.get("NextTextFrame")
                tf.set("ParentStory", "u_title_story")
                tf.set("PreviousTextFrame", "n")
                tf.set("NextTextFrame", "n")
                tf.set("ItemTransform", "1 0 0 1 198 -30")

                # Update path points to 324 x 400 (-200 to +200)
                ppa = next((e for e in tf.iter() if lname(e.tag) == "PathPointArray"), None)
                if ppa is not None:
                    tf_pts = [
                        "-162 -200",
                        "-162 200",
                        "162 200",
                        "162 -200",
                    ]
                    pts = [c for c in ppa if lname(c.tag) == "PathPointType"]
                    if len(pts) == 4:
                        for pt, t in zip(pts, tf_pts):
                            pt.set("Anchor", t)
                            pt.set("LeftDirection", t)
                            pt.set("RightDirection", t)

            # Update or clone publisher logo polygon
            poly_status = _update_or_clone_polygon(sp_root, reference_dir)
            write_xml(sp_root, sp)
            break

    # Unthread next text frame on Page 2 so main story begins on Page 2
    if next_tf_to_unthread and next_tf_to_unthread != "n":
        for sp in spread_files:
            sp_root = parse(sp)
            changed = False
            for tf2 in sp_root.findall(".//{*}TextFrame"):
                if tf2.attrib.get("Self") == next_tf_to_unthread:
                    tf2.set("PreviousTextFrame", "n")
                    changed = True
            if changed:
                write_xml(sp_root, sp)
                break

    # 4. Remove old front matter paragraphs from target's main story
    first_old = old_front_psrs[0]
    parent = None
    for candidate in target_root.iter():
        children = list(candidate)
        if first_old in children:
            parent = candidate
            break

    if parent is not None:
        for old in old_front_psrs:
            if old in list(parent):
                parent.remove(old)
        write_xml(target_root, target_story_path)

    # 5. Copy reference styles needed for title page
    styles_to_copy = {
        "ParagraphStyle/main_page_title",
        "ParagraphStyle/author_name",
        "ParagraphStyle/quotes_normal",
        "CharacterStyle/italic",
    }
    copied, added, missing = copy_named_styles(
        target_dir, reference_dir, styles_to_copy
    )

    # 6. Ensure Style attributes in Styles.xml
    styles_path = Path(target_dir) / "Resources" / "Styles.xml"
    if styles_path.exists():
        sroot = parse(styles_path)
        for ps in sroot.iter():
            name = ps.attrib.get("Self", "")
            if name == "ParagraphStyle/main_page_title":
                ps.set("Justification", "CenterAlign")
                ps.set("PointSize", "30")
                ps.set("FontStyle", "Bold")
                ps.set("SpaceBefore", "5.669291338582678")
            elif name == "ParagraphStyle/author_name":
                ps.set("Justification", "CenterAlign")
                ps.set("PointSize", "20")
                ps.set("SpaceBefore", "7.2")
            elif name in ("CharacterStyle/italic", "CharacterStyle/italicalign"):
                ps.set("FontStyle", "Italic")

        cstyle_names = {cs.attrib.get("Self") for cs in sroot.iter() if lname(cs.tag) == "CharacterStyle"}
        if "CharacterStyle/italic" not in cstyle_names:
            group = next((e for e in sroot.iter() if lname(e.tag) == "RootCharacterStyleGroup"), None)
            if group is not None:
                new_cs = ET.SubElement(group, "CharacterStyle", {
                    "Self": "CharacterStyle/italic",
                    "Name": "italic",
                    "FontStyle": "Italic",
                    "Imported": "false",
                })
                cs_props = ET.SubElement(new_cs, "Properties")
                based = ET.SubElement(cs_props, "BasedOn", {"type": "string"})
                based.text = "$ID/[No character style]"

        write_xml(sroot, styles_path)

    # 7. Synchronize fonts
    fonts_synced = sync_fonts(target_dir, reference_dir)

    # 8. Update MasterSpread footer stories and designmap Running Header with finalized title
    from pages.document_setup import (
        update_designmap_text_variables,
        update_master_footer_stories,
    )
    update_designmap_text_variables(target_dir)
    update_master_footer_stories(target_dir, title)

    return {
        "title": title,
        "subtitle": subtitle,
        "by": by_text,
        "author": author_name,
        "polygon_status": poly_status,
        "story_created": "Story_u_title_story.xml",
        "styles_copied": copied + added,
        "fonts_synced": fonts_synced,
    }

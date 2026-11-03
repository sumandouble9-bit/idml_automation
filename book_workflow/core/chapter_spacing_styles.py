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

try:
    from chapter_spacing_common import *
except ImportError:
    from .chapter_spacing_common import *


def update_styles_xml(styles_xml_content: bytes, space_before: str = REF_SPACE_BEFORE, space_after: str = REF_SPACE_AFTER) -> bytes:
    """Ensure Styles.xml has exact reference spacing and formatting for chapters and front matter."""
    root = ET.fromstring(styles_xml_content)
    
    chapter_style = None
    normal_style = None
    
    for p in root.iter():
        if _lname(p.tag) == "ParagraphStyle":
            name = p.attrib.get("Name", "")
            self_id = p.attrib.get("Self", "")
            
            # Chapter heading style
            if name == "chapter_name" or self_id == "ParagraphStyle/chapter_name":
                chapter_style = p
            elif name == "Normal" or self_id == "ParagraphStyle/Normal":
                normal_style = p
            
            # Ensure chapter_name and chapter_name01 have StartParagraph="NextPage"
            # while after_chapter_name_heading has StartParagraph="Anywhere"
            if ("after_chapter" in name.lower() or "after_chapter" in self_id.lower()):
                p.set("StartParagraph", "Anywhere")
            elif ("chapter_name" in name.lower() or "chapter_name" in self_id.lower()) and "master" not in self_id.lower():
                p.set("StartParagraph", "Anywhere")

            # Front matter: TOC heading style
            if name == "about_the_autherh" or self_id == "ParagraphStyle/about_the_autherh":
                p.set("Justification", "CenterAlign")
                p.set("SpaceBefore", "44")
                p.set("SpaceAfter", "50")
                p.set("Hyphenation", "false")
                
            # Front matter: TOC items style (maintain equal left and right space in TOC)
            elif name in ["toc_normaltext", "content_ch", "toc_bold", "part_contents_text"] or self_id in [
                "ParagraphStyle/toc_normaltext",
                "ParagraphStyle/content_ch",
                "ParagraphStyle/toc_bold",
                "ParagraphStyle/part_contents_text"
            ]:
                p.set("SpaceBefore", "0")
                p.set("SpaceAfter", "5")
                props = p.find("Properties")
                if props is None:
                    props = ET.SubElement(p, "Properties")
                tl = props.find("TabList")
                if tl is None:
                    tl = ET.SubElement(props, "TabList")
                tl.clear()
                tl.set("type", "list")
                li = ET.SubElement(tl, "ListItem", {"type": "record"})
                ET.SubElement(li, "Alignment", {"type": "enumeration"}).text = "RightAlign"
                ET.SubElement(li, "AlignmentCharacter", {"type": "string"}).text = "."
                ET.SubElement(li, "Leader", {"type": "string"}).text = "."
                ET.SubElement(li, "Position", {"type": "unit"}).text = "324"
                
            # Front matter: Title & Copyright styles
            elif name == "main_page_title" or self_id == "ParagraphStyle/main_page_title":
                p.set("Justification", "CenterAlign")
                p.set("Hyphenation", "false")
            elif name in ["verso_title", "verso_author"]:
                p.set("Justification", "CenterAlign")
                p.set("Hyphenation", "false")
            elif name == "doublenine_books" or self_id == "ParagraphStyle/doublenine_books":
                p.set("Justification", "CenterAlign")
                p.set("Hyphenation", "false")
                p.set("SpaceBefore", "0")
                p.set("SpaceAfter", "0")
            elif name in ["copyright_text"]:
                p.set("Justification", "CenterAlign")

    if chapter_style is not None:
        chapter_style.set("SpaceBefore", str(space_before))
        chapter_style.set("SpaceAfter", str(space_after))
        chapter_style.set("FontStyle", "Bold")
        chapter_style.set("StartParagraph", "Anywhere")
    else:
        # Create chapter_name style based on Sub-heading
        parent = root.find(".//RootParagraphStyleGroup") or root
        chapter_style = ET.SubElement(parent, "ParagraphStyle", {
            "Self": "ParagraphStyle/chapter_name",
            "Name": "chapter_name",
            "SpaceBefore": str(space_before),
            "SpaceAfter": str(space_after),
            "FontStyle": "Bold",
            "Justification": "CenterAlign",
            "PointSize": REF_POINT_SIZE,
            "StartParagraph": "NextPage",
        })
        props = ET.SubElement(chapter_style, "Properties")
        ET.SubElement(props, "BasedOn", {"type": "object"}).text = "ParagraphStyle/Sub-heading"
        ET.SubElement(props, "Leading", {"type": "enumeration"}).text = "Auto"
        ET.SubElement(props, "RuleAboveColor", {"type": "string"}).text = "Text Color"

    # Ensure ParagraphStyle/Normal exists for spacer paragraphs
    if normal_style is None:
        parent = root.find(".//RootParagraphStyleGroup") or root
        ET.SubElement(parent, "ParagraphStyle", {
            "Self": "ParagraphStyle/Normal",
            "Name": "Normal",
        })

    return ET.tostring(root, encoding="utf-8")


def update_spreads_geometry(files: dict) -> None:
    """
    Adjust TextFrame geometries on Page 1 (Title) and Page 2 (Copyright) to faithfully match
    the reference document '18049 Impressions Of A War Correspondent.indd':
      - Title page frame: top=124.72 pt (44 mm), bottom=402.52 pt (142 mm), left=36 pt, right=360 pt
      - Copyright page frame: top=71.0 pt (25.05 mm), bottom=515.0 pt (181.7 mm), left=36 pt, right=360 pt
    """
    for fname in sorted(files.keys()):
        if fname.startswith("Spreads/Spread_"):
            root = ET.fromstring(files[fname])
            changed = False
            pages = [p.attrib.get("Name", "") for p in root.iter() if _lname(p.tag) == "Page"]
            
            # Title Page (Page 1)
            if "1" in pages:
                for tf in root.iter():
                    if _lname(tf.tag) == "TextFrame":
                        story = tf.attrib.get("ParentStory", "")
                        st_name = f"Stories/Story_{story}.xml"
                        is_title = False
                        if st_name in files:
                            txt = files[st_name].decode("utf-8", errors="ignore")
                            if "main_page_title" in txt or "author_name" in txt:
                                is_title = True
                        if is_title or len(pages) == 1:
                            # Center X = 198, Center Y = (124.72 + 558.0)/2 = 341.36 -> ty = 341.36 - 306 = 35.36
                            # Top = 124.72 pt (44 mm reference top), Bottom = 558.0 pt (bottom margin line, half-height = 216.64 pt)
                            # Expands frame height to 433.28 pt so multi-line titles and author credits are fully displayed without truncation!
                            tf.set("ItemTransform", "1 0 0 1 198 35.36")
                            for prop in tf:
                                if _lname(prop.tag) == "Properties":
                                    for pg in prop:
                                        if _lname(pg.tag) == "PathGeometry":
                                            for pt_elem in pg.iter():
                                                if _lname(pt_elem.tag) == "PathPointType":
                                                    anch = pt_elem.attrib.get("Anchor", "")
                                                    parts = anch.split()
                                                    if len(parts) == 2:
                                                        x_val = -162 if float(parts[0]) < 0 else 162
                                                        y_val = -216.64 if float(parts[1]) < 0 else 216.64
                                                        new_val = f"{x_val} {y_val}"
                                                        pt_elem.set("Anchor", new_val)
                                                        pt_elem.set("LeftDirection", new_val)
                                                        pt_elem.set("RightDirection", new_val)
                            changed = True
                            break
                            
            # Copyright Page (Page 2)
            if "2" in pages:
                for tf in root.iter():
                    if _lname(tf.tag) == "TextFrame":
                        story = tf.attrib.get("ParentStory", "")
                        st_name = f"Stories/Story_{story}.xml"
                        if st_name in files:
                            txt = files[st_name].decode("utf-8", errors="ignore")
                            if "copyright" in txt.lower() or "verso" in txt.lower():
                                # Verso Center X = -198, Center Y = (36 + 558)/2 = 297.0 -> ty = 297.0 - 306 = -9.0
                                # Top = 36 pt, Bottom = 558 pt, Height = 522 pt (half-height = 261 pt)
                                tf.set("ItemTransform", "1 0 0 1 -198 -9")
                                for prop in tf:
                                    if _lname(prop.tag) == "Properties":
                                        for pg in prop:
                                            if _lname(pg.tag) == "PathGeometry":
                                                for pt_elem in pg.iter():
                                                    if _lname(pt_elem.tag) == "PathPointType":
                                                        anch = pt_elem.attrib.get("Anchor", "")
                                                        parts = anch.split()
                                                        if len(parts) == 2:
                                                            x_val = -162 if float(parts[0]) < 0 else 162
                                                            y_val = -261.0 if float(parts[1]) < 0 else 261.0
                                                            new_val = f"{x_val} {y_val}"
                                                            pt_elem.set("Anchor", new_val)
                                                            pt_elem.set("LeftDirection", new_val)
                                                            pt_elem.set("RightDirection", new_val)
                                tfp = next((c for c in tf if _lname(c.tag) == "TextFramePreference"), None)
                                if tfp is None:
                                    tfp = ET.SubElement(tf, "TextFramePreference")
                                tfp.set("VerticalJustification", "CenterAlign")
                                changed = True
                                break
                                
            if changed:
                files[fname] = ET.tostring(root, encoding="utf-8")


def format_title_story(story_xml_bytes: bytes, target_by_baseline: float = 374.0) -> bytes:
    """
    Format Title page story:
      - Strips empty spacer lines and redundant blank paragraphs.
      - Centers title and author text without hyphenation.
      - Anchors 'by' / 'Por' at baseline ~374 pt (132 mm) to replicate reference layout
        with a balanced ~180-190 pt gap below the book title.
    """
    root = ET.fromstring(story_xml_bytes)
    story_elem = root.find(".//Story") if root.tag.endswith("Story") else root.find("Story")
    if story_elem is None:
        story_elem = root
        
    children = list(story_elem)
    psrs = [c for c in children if _lname(c.tag) == "ParagraphStyleRange"]
    
    title_psrs = []
    by_psr = None
    author_psrs = []
    
    found_by = False
    for p in psrs:
        st = p.attrib.get("AppliedParagraphStyle", "")
        txt = "".join(e.text or "" for e in p.iter() if _lname(e.tag) == "Content").strip()
        
        if not found_by:
            if "author_name" in st and any(txt.lower() == k for k in ["by", "por"]):
                found_by = True
                by_psr = p
            elif txt:
                title_psrs.append(p)
        else:
            if txt:
                author_psrs.append(p)
                
    if not by_psr:
        for p in psrs:
            p.set("Justification", "CenterAlign")
            p.set("Hyphenation", "false")
        return ET.tostring(root, encoding="utf-8")
        
    # Clean CSRs inside title_psrs: remove empty trailing Br-only CSRs
    for tp in title_psrs:
        tp.set("Justification", "CenterAlign")
        tp.set("Hyphenation", "false")
        cleaned_csrs = []
        for csr in tp.findall("CharacterStyleRange"):
            c_txt = "".join(e.text or "" for e in csr.iter() if _lname(e.tag) == "Content").strip()
            brs = csr.findall("Br")
            if c_txt:
                cleaned_csrs.append(csr)
            elif not c_txt and brs and cleaned_csrs:
                # Omit empty spacer CSRs
                pass
        # Ensure last CSR has Br
        if cleaned_csrs:
            last = cleaned_csrs[-1]
            if not last.findall("Br"):
                ET.SubElement(last, "Br")
        # Replace CSRs
        for c in list(tp):
            if _lname(c.tag) == "CharacterStyleRange":
                tp.remove(c)
        for c in cleaned_csrs:
            tp.append(c)

    # Count title lines approximately: title frame top is 124.7 pt, first baseline is 145.8 pt.
    # Each title line is ~32 pt leading.
    lines = 0
    for tp in title_psrs:
        for csr in tp.findall("CharacterStyleRange"):
            txt = "".join(e.text or "" for e in csr.iter() if _lname(csr.tag) == "Content" or _lname(e.tag) == "Content").strip()
            if txt:
                pt = float(csr.attrib.get("PointSize", "29"))
                chars_per_line = max(15, int(324 / (pt * 0.55)))
                lines += max(1, (len(txt) + chars_per_line - 1) // chars_per_line)
                
    lines = max(1, min(lines, 4))
    estimated_last_baseline = 145.8 + (lines - 1) * 32.0
    
    # Calculate SpaceBefore so that by/por lands at target_by_baseline (~374 pt)
    # baseline = last_title_baseline + font_descent (~4) + SpaceBefore + font_ascent (~12)
    # SpaceBefore = target_by_baseline - estimated_last_baseline - 16
    calculated_sb = max(60.0, target_by_baseline - estimated_last_baseline - 16.0)
    
    by_psr.set("SpaceBefore", f"{calculated_sb:.1f}")
    by_psr.set("Justification", "CenterAlign")
    by_psr.set("Hyphenation", "false")
    
    for ap in author_psrs:
        ap.set("SpaceBefore", "0")
        ap.set("Justification", "CenterAlign")
        ap.set("Hyphenation", "false")
        
    # Rebuild story
    new_children = []
    for c in children:
        if _lname(c.tag) != "ParagraphStyleRange":
            new_children.append(c)
            
    for tp in title_psrs:
        new_children.append(tp)
    new_children.append(by_psr)
    for ap in author_psrs:
        new_children.append(ap)
        
    for c in list(story_elem):
        story_elem.remove(c)
    for c in new_children:
        story_elem.append(c)
        
    return ET.tostring(root, encoding="utf-8")


def process_frontmatter_stories(files: dict) -> None:
    """Format Title, Copyright, and Table of Contents stories to match reference alignment and spacing."""
    for fname in sorted(files.keys()):
        if fname.startswith("Stories/Story_"):
            content = files[fname]
            root = ET.fromstring(content)
            story_elem = root.find(".//Story") if root.tag.endswith("Story") else root.find("Story")
            if story_elem is None:
                story_elem = root
                
            children = list(story_elem)
            psrs = [c for c in children if _lname(c.tag) == "ParagraphStyleRange"]
            changed = False
            
            # Check for Title Story
            is_title_story = any("main_page_title" in p.attrib.get("AppliedParagraphStyle", "") for p in psrs)
            if is_title_story and len(psrs) <= 15:
                files[fname] = format_title_story(files[fname])
                continue

            # Check for Copyright Story
            is_copyright_story = any("verso_title" in p.attrib.get("AppliedParagraphStyle", "") or "copyright" in p.attrib.get("AppliedParagraphStyle", "").lower() for p in psrs)
            if is_copyright_story and len(psrs) <= 15:
                for p in psrs:
                    st = p.attrib.get("AppliedParagraphStyle", "")
                    p_txt = "".join(c.text or "" for c in p.iter() if _lname(c.tag) == "Content").strip()
                    if any(k in st.lower() for k in ["verso", "copyright", "doublenine", "body_text"]):
                        p.set("Justification", "CenterAlign")
                        p.set("Hyphenation", "false")

                    # User Requirement: Make 'Publicado por' / 'Published by' bold, copyright_text style, single Br (no extra space before LeafBound)
                    if any(k in p_txt.lower() for k in ["publicado por", "published by"]):
                        p.set("AppliedParagraphStyle", "ParagraphStyle/copyright_text")
                        p.set("Justification", "CenterAlign")
                        p.set("Hyphenation", "false")
                        for attr in ["FirstLineIndent", "SpaceBefore", "SpaceAfter", "KeepLinesTogether", "KeepFirstAndLastLines", "MinLinesAtStart", "MinLinesAtEnd"]:
                            if attr in p.attrib:
                                del p.attrib[attr]
                        for csr in p.findall("CharacterStyleRange"):
                            csr.set("FontStyle", "Bold")
                            csr.set("PointSize", "11")
                            props = csr.find("Properties")
                            if props is None:
                                props = ET.SubElement(csr, "Properties")
                            af = props.find("AppliedFont")
                            if af is None:
                                af = ET.SubElement(props, "AppliedFont", {"type": "string"})
                            af.text = "Palatino Linotype"
                            ld = props.find("Leading")
                            if ld is None:
                                ld = ET.SubElement(props, "Leading", {"type": "unit"})
                            ld.text = "14"
                            brs = csr.findall("Br")
                            if len(brs) > 1:
                                for extra_br in brs[1:]:
                                    csr.remove(extra_br)

                    # Ensure LeafBound / DOUBLE 9 BOOKS imprint has no excess space
                    if any(k in p_txt.lower() for k in ["leafbound", "doublenine_books"]):
                        p.set("Justification", "CenterAlign")
                        p.set("Hyphenation", "false")
                        for attr in ["SpaceBefore", "SpaceAfter"]:
                            if attr in p.attrib:
                                del p.attrib[attr]

                changed = True

            # Check for TOC heading (Contents / Contenido / Índice)
            if psrs:
                p0 = psrs[0]
                p0_style = p0.attrib.get("AppliedParagraphStyle", "")
                p0_text = "".join(c.text or "" for c in p0.iter() if _lname(c.tag) == "Content").strip()
                
                if "about_the_autherh" in p0_style and any(k in p0_text.lower() for k in ["content", "contenido", "indice", "table of contents"]):
                    p0.set("Justification", "CenterAlign")
                    p0.set("Hyphenation", "false")
                    p0.set("SpaceBefore", "44")
                    p0.set("SpaceAfter", "50")
                    
                    # Check if spacer already exists immediately before p0
                    idx = list(story_elem).index(p0)
                    has_spacer = False
                    if idx > 0:
                        prev = story_elem[idx - 1]
                        if _lname(prev.tag) == "ParagraphStyleRange":
                            prev_txt = "".join(prev.itertext()).strip()
                            if not prev_txt or prev_txt == LS:
                                has_spacer = True
                                
                    if not has_spacer:
                        spacer_psr = ET.Element("ParagraphStyleRange", {
                            "AppliedParagraphStyle": "ParagraphStyle/Normal"
                        })
                        csr = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                            "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"
                        })
                        cnt = ET.SubElement(csr, "Content")
                        cnt.text = LS
                        ET.SubElement(csr, "Br")
                        story_elem.insert(idx, spacer_psr)
                    changed = True

            if changed:
                files[fname] = ET.tostring(root, encoding="utf-8")


def update_spreads_master_pages(files: dict, first_content_page: int) -> None:
    """Ensure pages 1..(first_content_page - 1) have AppliedMaster='n' (None) and subsequent pages have A-Master."""
    if "designmap.xml" not in files:
        return
    try:
        dm = ET.fromstring(files["designmap.xml"])
        spread_srcs = [elem.attrib.get("src") for elem in dm.findall(f".//{{{IDPKG_NS}}}Spread")]
        page_index = 1
        for sf in spread_srcs:
            if sf in files:
                s_root = ET.fromstring(files[sf])
                pages = s_root.findall(".//Page")
                modified = False
                for p in pages:
                    if page_index < first_content_page:
                        if p.attrib.get("AppliedMaster") != "n":
                            p.set("AppliedMaster", "n")
                            modified = True
                    else:
                        if p.attrib.get("AppliedMaster") == "n":
                            p.set("AppliedMaster", "ub9")
                            modified = True
                    page_index += 1
                if modified:
                    files[sf] = ET.tostring(s_root, encoding="utf-8")
    except Exception:
        pass


__all__ = [
    'update_styles_xml',
    'update_spreads_geometry',
    'format_title_story',
    'process_frontmatter_stories',
    'update_spreads_master_pages',
]

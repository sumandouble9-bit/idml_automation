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

def _classify_frontmatter_blocks(psrs):
    """Walk the front-matter PSRs and split them into TOC, author and content blocks by heading markers."""
    toc_psrs = []
    author_psrs = []
    content_psrs = []
    mode = None
    
    for p in psrs:
        st = p.attrib.get("AppliedParagraphStyle", "")
        c_texts = [c.text for c in p.findall(".//Content") if c.text]
        c_txt = "".join(c_texts).strip()
        txt_low = c_txt.lower()
        
        is_toc_heading = ("contents" in txt_low or "contenido" in txt_low) and len(c_txt) < 30
        is_author_heading = ("about the author" in txt_low or "sobre la autor" in txt_low) and len(c_txt) < 40
        
        if is_toc_heading:
            mode = "TOC"
        elif is_author_heading:
            mode = "AUTHOR"
        elif mode == "TOC":
            is_toc_style = any(s in st.lower() for s in ["toc", "content_ch", "part_contents"]) or st.lower().endswith("/normal")
            if not is_toc_style and c_txt:
                mode = "CONTENT"
            elif any(s in st.lower() for s in ["chapter_name", "body_text", "quote", "heading", "title"]) and c_txt:
                mode = "CONTENT"
        elif mode == "AUTHOR":
            has_next_page = False
            if p.attrib.get("ParagraphBreakType") == "NextPage":
                has_next_page = True
            for csr in p.findall("CharacterStyleRange"):
                if csr.attrib.get("ParagraphBreakType") == "NextPage":
                    has_next_page = True
                    
            is_chap_heading = ("chapter_name" in st or "sub-heading" in st.lower())
            if not is_chap_heading and any(k in txt_low for k in ["chapter", "capítulo", "capitulo", "preface", "prefacio", "prologue", "prólogo", "part", "parte", "book", "libro", "apología", "arena y espuma", "espectros", "canto", "introduction", "introducción", "bendición"]):
                if "chapter" in st or "sub-heading" in st or "heading" in st or (len(c_txt) < 80 and not c_txt.startswith("Palatino")):
                    is_chap_heading = True
                    
            if is_chap_heading or has_next_page:
                mode = "CONTENT"
            elif len(author_psrs) >= 2 and c_txt:
                if is_toc_heading:
                    mode = "TOC"
                else:
                    mode = "CONTENT"
                
        if mode == "TOC":
            toc_psrs.append(p)
        elif mode == "AUTHOR":
            author_psrs.append(p)
        elif mode == "CONTENT":
            content_psrs.append(p)
            
    return toc_psrs, author_psrs, content_psrs


def _refine_author_psrs(author_psrs, content_psrs):
    """Split any author paragraph that embeds a dropcap/prologue or merged chapter text into content; return the author list."""
    # Split any author PSR that improperly contains an embedded dropcap/prologue or merged chapter text
    refined_author = []
    for p in author_psrs:
        c_txt = "".join(c.text for c in p.findall(".//Content") if c.text)
        csrs = list(p.findall("CharacterStyleRange"))
        dropcap_idx = -1
        for i, c in enumerate(csrs):
            if "dropcap" in c.attrib.get("AppliedCharacterStyle", ""):
                dropcap_idx = i
                break
        if dropcap_idx > 0:
            p_author = ET.Element(p.tag, dict(p.attrib))
            for c in csrs[:dropcap_idx]:
                p_author.append(c)
            refined_author.append(p_author)

            p_content = ET.Element(p.tag, dict(p.attrib))
            for c in csrs[dropcap_idx:]:
                p_content.append(c)
            content_psrs.insert(0, p_content)
        elif len(c_txt.strip()) > 2000 and re.search(r"(\.)\s*(1\.\s+[A-Z])", c_txt):
            m = re.search(r"(\.)\s*(1\.\s+[A-Z])", c_txt)
            split_pos = m.start(2)
            p_auth = ET.Element(p.tag, dict(p.attrib))
            p_cont = ET.Element(p.tag, dict(p.attrib))
            curr_len = 0
            for c in csrs:
                csr_txt = "".join(e.text for e in c.findall("Content") if e.text)
                if curr_len + len(csr_txt) <= split_pos:
                    p_auth.append(c)
                    curr_len += len(csr_txt)
                elif curr_len >= split_pos:
                    p_cont.append(c)
                    curr_len += len(csr_txt)
                else:
                    offset = split_pos - curr_len
                    c1 = ET.Element(c.tag, dict(c.attrib))
                    cnt1 = ET.SubElement(c1, "Content")
                    cnt1.text = csr_txt[:offset].rstrip()
                    p_auth.append(c1)
                    c2 = ET.Element(c.tag, dict(c.attrib))
                    cnt2 = ET.SubElement(c2, "Content")
                    cnt2.text = csr_txt[offset:].lstrip()
                    p_cont.append(c2)
                    curr_len += len(csr_txt)
            refined_author.append(p_auth)
            content_psrs.insert(0, p_cont)
        else:
            refined_author.append(p)
    author_psrs = refined_author
    return author_psrs


def _trim_block_spacers(toc_psrs, author_psrs, content_psrs):
    """Drop empty/spacer paragraphs from the edges of the TOC, author and content blocks (in place)."""
    # Clean empty spacer PSRs from all blocks
    while toc_psrs and is_empty_psr(toc_psrs[-1]):
        toc_psrs.pop()
    while toc_psrs and is_empty_psr(toc_psrs[0]):
        toc_psrs.pop(0)
        
    while author_psrs and is_empty_psr(author_psrs[-1]):
        author_psrs.pop()
    while author_psrs and is_empty_psr(author_psrs[0]):
        author_psrs.pop(0)

    # Clean leading empty/spacer PSRs before Chapter 1 in content_psrs
    while content_psrs and (
        is_empty_psr(content_psrs[0])
        or content_psrs[0].attrib.get("BlankPageSpacer") == "true"
        or content_psrs[0].attrib.get("BlankPageProtected") == "true"
    ):
        content_psrs.pop(0)

    # Format all chapters inside content_psrs so every chapter starts on a new page with identical top spacing


def _format_content_chapters(content_psrs):
    """Format each chapter heading in the content block for a fresh page with reference top spacing; return the rebuilt list."""
    new_content_psrs = []
    seen_first_chapter = False
    
    ci = 0
    while ci < len(content_psrs):
        c_p = content_psrs[ci]
        if _lname(c_p.tag) != "ParagraphStyleRange":
            new_content_psrs.append(c_p)
            ci += 1
            continue
            
        c_txt = _get_text(c_p)
        prev_p = new_content_psrs[-1] if (new_content_psrs and _lname(new_content_psrs[-1].tag) == "ParagraphStyleRange") else None
        
        if is_chapter_heading(c_p, prev_p):
            is_sub_heading_of_part = False
            if prev_p is not None:
                prev_txt = _get_text(prev_p)
                prev_st = prev_p.attrib.get("AppliedParagraphStyle", "").lower()
                if (
                    "chapter_name" in prev_st
                    or "sub-heading" in prev_st
                    or any(k in prev_st for k in ["heading", "title", "part"])
                    or re.match(r"^\s*(?:PART|PARTE|BOOK|LIBRO)\b", prev_txt, re.I)
                ):
                    is_sub_heading_of_part = True
                    
            c_p.set("AppliedParagraphStyle", "ParagraphStyle/chapter_name")
            c_p.set("StartParagraph", "Anywhere")
            c_p.set("SpaceBefore", str(REF_SPACE_BEFORE))
            c_p.set("SpaceAfter", str(REF_SPACE_AFTER))
            c_p.set("KeepLinesTogether", "true")
            c_p.set("KeepWithNext", "2")
            
            for csr in c_p.findall("CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib:
                    del csr.attrib["ParagraphBreakType"]
                    
            csrs = list(c_p.findall("CharacterStyleRange"))
            if csrs:
                last_csr = csrs[-1]
                if not any(_lname(k.tag) == "Br" for k in last_csr):
                    ET.SubElement(last_csr, "Br")
                    
            if is_sub_heading_of_part:
                c_p.set("AppliedParagraphStyle", "ParagraphStyle/after_chapter_name_heading")
                c_p.set("StartParagraph", "Anywhere")
                if "ParagraphBreakType" in c_p.attrib:
                    del c_p.attrib["ParagraphBreakType"]
                for csr in c_p.findall("CharacterStyleRange"):
                    if "ParagraphBreakType" in csr.attrib:
                        del csr.attrib["ParagraphBreakType"]
                c_p.set("SpaceBefore", "14")
                c_p.set("SpaceAfter", str(REF_SPACE_AFTER))
                c_p.set("KeepLinesTogether", "true")
                c_p.set("KeepWithNext", "2")
                c_p.set("Justification", "CenterAlign")
                c_p.set("FirstLineIndent", "0")
                new_content_psrs.append(c_p)
                ci += 1
                continue
                
            # If previous children are existing empty spacer PSRs, remove them
            while new_content_psrs and _lname(new_content_psrs[-1].tag) == "ParagraphStyleRange":
                last_psr = new_content_psrs[-1]
                if any(_lname(k.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for k in last_psr.iter()):
                    break
                last_txt = _get_text(last_psr)
                if not last_txt or last_txt == LS:
                    new_content_psrs.pop()
                else:
                    break
                    
            if not seen_first_chapter:
                # Chapter 1 is preceded by chap1_top_spacer (added at Block 5)
                seen_first_chapter = True
            else:
                sub_spacer = ET.Element("ParagraphStyleRange", {
                    "AppliedParagraphStyle": "ParagraphStyle/Normal",
                    "StartParagraph": "NextPage",
                    "ParagraphBreakType": "NextPage",
                    "BlankPageSpacer": "true",
                    "BlankPageProtected": "true",
                })
                csr_spacer = ET.SubElement(sub_spacer, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
                    "ParagraphBreakType": "NextPage"
                })
                cnt = ET.SubElement(csr_spacer, "Content")
                cnt.text = LS
                ET.SubElement(csr_spacer, "Br")
                new_content_psrs.append(sub_spacer)
                
            new_content_psrs.append(c_p)
            ci += 1
        else:
            new_content_psrs.append(c_p)
            ci += 1
            
    content_psrs = new_content_psrs
    return content_psrs


def _assemble_frontmatter(root, story_elem, non_psrs, author_psrs, toc_psrs, content_psrs):
    """Build the reordered front-matter (author, blanks, TOC, balancing spacers, content) and return (xml_bytes, first_content_page)."""
    # For author and toc: remove ParagraphBreakType and StartParagraph
    for block in [author_psrs, toc_psrs]:
        for p in block:
            if "ParagraphBreakType" in p.attrib:
                del p.attrib["ParagraphBreakType"]
            if "StartParagraph" in p.attrib:
                del p.attrib["StartParagraph"]
            for csr in p.findall("CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib:
                    del csr.attrib["ParagraphBreakType"]

    # For Chapter 1 (initial content heading): ensure StartParagraph="Anywhere" so it stays on Page 7
    for p in content_psrs[:3]:
        style = (p.attrib.get("AppliedParagraphStyle") or "").lower()
        if "chapter" in style or "heading" in style:
            p.set("StartParagraph", "Anywhere")
            if "ParagraphBreakType" in p.attrib:
                del p.attrib["ParagraphBreakType"]
            for csr in p.findall("CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib:
                    del csr.attrib["ParagraphBreakType"]
        else:
            break

    # 1. Format ABOUT THE AUTHOR heading (Page 3)
    author_heading = author_psrs[0]
    author_heading.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
    author_heading.set("Justification", "CenterAlign")
    author_heading.set("SpaceBefore", "44")
    author_heading.set("SpaceAfter", "15")
    author_heading.set("Hyphenation", "false")

    author_top_spacer = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/Normal",
        "BlankPageSpacer": "true",
        "BlankPageProtected": "true",
    })
    csr_at = ET.SubElement(author_top_spacer, "CharacterStyleRange", {"AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"})
    cnt_at = ET.SubElement(csr_at, "Content")
    cnt_at.text = LS
    ET.SubElement(csr_at, "Br")

    # 2. Blank page spacer after About the Author:
    # Paragraph A: Page 3 (About Author) breaks to Page 4.
    page3_break = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/Normal",
        "BlankPageSpacer": "true",
        "BlankPageProtected": "true",
    })
    csr_to_p4 = ET.SubElement(page3_break, "CharacterStyleRange", {
        "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
        "ParagraphBreakType": "NextPage"
    })
    ET.SubElement(csr_to_p4, "Br")

    # Paragraph B: On Page 4, a blank spacer sits and breaks to Page 5.
    page4_blank = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/Normal",
        "BlankPageSpacer": "true",
        "BlankPageProtected": "true",
    })
    csr_p4_cnt = ET.SubElement(page4_blank, "CharacterStyleRange", {
        "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
        "ParagraphBreakType": "NextPage"
    })
    cnt_p4 = ET.SubElement(csr_p4_cnt, "Content")
    cnt_p4.text = LS
    ET.SubElement(csr_p4_cnt, "Br")

    # 3. Format TOC heading (Page 5)
    toc_heading = toc_psrs[0]
    toc_heading.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
    toc_heading.set("Justification", "CenterAlign")
    toc_heading.set("SpaceBefore", "44")
    toc_heading.set("SpaceAfter", "50")
    toc_heading.set("Hyphenation", "false")

    toc_top_spacer = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/Normal",
        "BlankPageSpacer": "true",
        "BlankPageProtected": "true",
    })
    csr_tt = ET.SubElement(toc_top_spacer, "CharacterStyleRange", {"AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"})
    cnt_tt = ET.SubElement(csr_tt, "Content")
    cnt_tt.text = LS
    ET.SubElement(csr_tt, "Br")

    # 4. Count TOC items to calculate exact TOC pages (using only visible Content text)
    toc_line_count = 0
    for p in toc_psrs[1:]:
        c_texts = [c.text for c in p.findall(".//Content") if c.text]
        full_p_text = "".join(c_texts).strip()
        if not full_p_text:
            continue
        lines = [l for l in re.split(r"[\r\n\u2028]+", full_p_text) if l.strip()]
        for line in lines:
            toc_line_count += max(1, int(math.ceil(len(line) / 45.0)))
        
    # Page 5 vertical budget:
    # Text frame height = 522 pt.
    # TOC Heading: SpaceBefore=44, SpaceAfter=50, fontSize~20 -> ~114 pt.
    # Remaining vertical space on Page 5 = 408 pt.
    # Each TOC item line height + SpaceAfter=5 -> ~18 pt.
    # Page 5 capacity: 408 / 18 = 22.6 lines -> at most 22 lines.
    # Pages 6+: Full text frame without heading: 522 / 18 = 29 lines per page.
    if toc_line_count <= 22:
        toc_pages = 1
    elif toc_line_count <= (22 + 29):   # <= 51 lines
        toc_pages = 2
    elif toc_line_count <= (22 + 29 + 29): # <= 80 lines
        toc_pages = 3
    else:
        toc_pages = 1 + int(math.ceil((toc_line_count - 22) / 29.0))
        
    last_toc_page = 5 + toc_pages - 1

    # 5. Post-TOC balancing:
    post_toc_elements = []
    if last_toc_page % 2 == 1:
        # TOC ends on odd page (e.g. 1-page TOC on Page 5, or 3-page TOC on Page 7).
        # We leave the next even page blank so content starts on an ODD page (Page 7 or Page 9, Recto)!
        first_content_page = last_toc_page + 2
        
        # Paragraph 1: breaks from TOC page to even blank page (e.g. Page 5 to Page 6)
        toc_end_break = ET.Element("ParagraphStyleRange", {
            "AppliedParagraphStyle": "ParagraphStyle/Normal",
            "BlankPageSpacer": "true",
            "BlankPageProtected": "true",
        })
        csr_to_even = ET.SubElement(toc_end_break, "CharacterStyleRange", {
            "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
            "ParagraphBreakType": "NextPage"
        })
        ET.SubElement(csr_to_even, "Br")
        post_toc_elements.append(toc_end_break)

        # Paragraph 2: sits on even page (Page 6) and breaks to next odd page (Page 7)
        blank_even_psr = ET.Element("ParagraphStyleRange", {
            "AppliedParagraphStyle": "ParagraphStyle/Normal",
            "BlankPageSpacer": "true",
            "BlankPageProtected": "true",
        })
        csr_blank_cnt = ET.SubElement(blank_even_psr, "CharacterStyleRange", {
            "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
            "ParagraphBreakType": "NextPage"
        })
        cnt_b = ET.SubElement(csr_blank_cnt, "Content")
        cnt_b.text = LS
        ET.SubElement(csr_blank_cnt, "Br")
        post_toc_elements.append(blank_even_psr)
    else:
        # TOC ends on even page (e.g. 2-page TOC on Page 6).
        # It already matches odd number criteria for content: DO NOT leave blank page!
        # Content starts directly on the next page (Page 7, Recto, Odd)!
        first_content_page = last_toc_page + 1
        
        toc_end_break = ET.Element("ParagraphStyleRange", {
            "AppliedParagraphStyle": "ParagraphStyle/Normal",
            "BlankPageSpacer": "true",
            "BlankPageProtected": "true",
        })
        csr_to_odd = ET.SubElement(toc_end_break, "CharacterStyleRange", {
            "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
            "ParagraphBreakType": "NextPage"
        })
        ET.SubElement(csr_to_odd, "Br")
        post_toc_elements.append(toc_end_break)

    # 6. Chapter 1 top spacer on first content page (WITHOUT NextPage break)
    chap1_top_spacer = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/Normal",
        "BlankPageSpacer": "true",
        "BlankPageProtected": "true",
    })
    csr_c1 = ET.SubElement(chap1_top_spacer, "CharacterStyleRange", {"AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"})
    cnt_c1 = ET.SubElement(csr_c1, "Content")
    cnt_c1.text = LS
    ET.SubElement(csr_c1, "Br")

    # 7. Rebuild the story elements in order
    new_story_elements = []
    new_story_elements.extend(non_psrs)
    
    # Block 1: About the Author (Page 3)
    new_story_elements.append(author_top_spacer)
    new_story_elements.extend(author_psrs)
    
    # Block 2: Blank Page 4
    new_story_elements.append(page3_break)
    new_story_elements.append(page4_blank)
    
    # Block 3: TOC (Page 5..)
    new_story_elements.append(toc_top_spacer)
    new_story_elements.extend(toc_psrs)
    
    # Block 4: Post-TOC spacer (balances blank pages to next Recto)
    new_story_elements.extend(post_toc_elements)

    # Block 5: Chapter 1 Top Spacer
    new_story_elements.append(chap1_top_spacer)
    
    # Block 6: Main Content (Chapter 1 onwards)
    new_story_elements.extend(content_psrs)
    
    for c in list(story_elem):
        story_elem.remove(c)
    for c in new_story_elements:
        story_elem.append(c)
        
    return ET.tostring(root, encoding="utf-8"), first_content_page


def resequence_frontmatter_story(story_xml_bytes: bytes) -> tuple[bytes, int]:
    """
    Resequences front matter blocks inside the main continuous story to match reference book layout:
      - Block 1: ABOUT THE AUTHOR (lands on Page 3, Recto, Master None)
      - Block 2: Blank Page 4 spacer (Verso, Master None)
      - Block 3: TABLE OF CONTENTS (lands on Page 5, Recto, Master None)
      - Block 4: Post-TOC balancing spacer (balances blank pages so content starts on Recto)
      - Block 5: Chapter 1 Top Spacer
      - Block 6: Main Content (Chapter 1 onwards, Master A-Master)

    Returns:
      (resequenced_xml_bytes, first_content_page)
    """
    root = ET.fromstring(story_xml_bytes)
    story_elem = root.find(".//Story") if root.tag.endswith("Story") else root.find("Story")
    if story_elem is None:
        story_elem = root

    children = list(story_elem)
    non_psrs = [c for c in children if _lname(c.tag) != "ParagraphStyleRange"]
    psrs = [
        c for c in children
        if _lname(c.tag) == "ParagraphStyleRange"
        and c.attrib.get("BlankPageSpacer") != "true"
        and c.attrib.get("BlankPageProtected") != "true"
    ]

    toc_psrs, author_psrs, content_psrs = _classify_frontmatter_blocks(psrs)
    if not author_psrs or not toc_psrs:
        return story_xml_bytes, 7

    author_psrs = _refine_author_psrs(author_psrs, content_psrs)
    _trim_block_spacers(toc_psrs, author_psrs, content_psrs)
    content_psrs = _format_content_chapters(content_psrs)
    return _assemble_frontmatter(root, story_elem, non_psrs, author_psrs, toc_psrs, content_psrs)


__all__ = [
    'resequence_frontmatter_story',
]

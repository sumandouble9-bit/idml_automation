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


SHORT_HEADING_CHARS = 60
HEADING_STYLE_KEYS = ("heading", "title", "part", "after_chapter")
HEADING_NUMERAL_RE = re.compile(r"^\s*(?:PART|PARTE|BOOK|LIBRO|[IVXLCDM0-9]+)\b", re.I)


def _is_paired_heading(prev_p, c_txt):
    """True when the heading is the second line of a paired heading, i.e. it follows a heading-like paragraph.

    A numeral-led line only pairs with a SHORT previous paragraph: a long body paragraph before "II LIVIA AND JULIA"
    is just the end of the previous chapter, so that heading keeps its own page.
    """
    prev_st = prev_p.attrib.get("AppliedParagraphStyle", "").lower()
    if "chapter_name" in prev_st or "sub-heading" in prev_st or any(k in prev_st for k in HEADING_STYLE_KEYS):
        return True
    prev_txt = _get_text(prev_p)
    if len(prev_txt) > SHORT_HEADING_CHARS:
        return False
    return bool(HEADING_NUMERAL_RE.match(prev_txt) or HEADING_NUMERAL_RE.match(c_txt))


OBJECT_TAGS = ("Rectangle", "Polygon", "Oval", "Image", "Table")
NO_CHARACTER_STYLE = "CharacterStyle/$ID/[No character style]"


def _has_object(psr):
    """True when the paragraph holds an anchored object (image, frame, table)."""
    return any(_lname(k.tag) in OBJECT_TAGS for k in psr.iter())


def _previous_real_psr(psrs):
    """The last paragraph before the current one that carries an object or real text (spacers are skipped)."""
    for cand in reversed(psrs):
        if _lname(cand.tag) != "ParagraphStyleRange":
            continue
        text = _get_text(cand)
        if _has_object(cand) or (text and text != LS):
            return cand
    return None


def _strip_csr_breaks(psr):
    """Remove the character-level page-break attribute from every character range of the paragraph."""
    for csr in psr.findall("CharacterStyleRange"):
        csr.attrib.pop("ParagraphBreakType", None)


def _format_chapter_heading(c_p):
    """Give a chapter heading the reference style and spacing, and make sure its last range ends with a break."""
    c_p.set("AppliedParagraphStyle", "ParagraphStyle/chapter_name")
    c_p.set("StartParagraph", "Anywhere")
    c_p.set("SpaceBefore", str(REF_SPACE_BEFORE))
    c_p.set("SpaceAfter", str(REF_SPACE_AFTER))
    c_p.set("KeepLinesTogether", "true")
    c_p.set("KeepWithNext", "2")
    _strip_csr_breaks(c_p)
    csrs = list(c_p.findall("CharacterStyleRange"))
    if csrs and not any(_lname(k.tag) == "Br" for k in csrs[-1]):
        ET.SubElement(csrs[-1], "Br")


def _format_paired_heading(c_p):
    """Restyle a heading as the second line of a paired heading: same page, centred, small gap above."""
    c_p.set("AppliedParagraphStyle", "ParagraphStyle/after_chapter_name_heading")
    c_p.set("StartParagraph", "Anywhere")
    c_p.attrib.pop("ParagraphBreakType", None)
    _strip_csr_breaks(c_p)
    c_p.set("SpaceBefore", "14")
    c_p.set("SpaceAfter", str(REF_SPACE_AFTER))
    c_p.set("KeepLinesTogether", "true")
    c_p.set("KeepWithNext", "2")
    c_p.set("Justification", "CenterAlign")
    c_p.set("FirstLineIndent", "0")


def _drop_blank_psrs_after(psrs, anchor):
    """Pop the blank paragraphs that sit between `anchor` and the end of the list (an object paragraph stops it)."""
    while psrs and psrs[-1] is not anchor:
        cand = psrs[-1]
        if _lname(cand.tag) != "ParagraphStyleRange" or _has_object(cand):
            break
        if _get_text(cand).replace(LS, "").strip():
            break
        psrs.pop()


def _drop_trailing_spacers(psrs):
    """Pop the empty spacer paragraphs at the end of the list so a chapter heading starts on a clean page."""
    while psrs and _lname(psrs[-1].tag) == "ParagraphStyleRange":
        last = psrs[-1]
        if _has_object(last) or _get_text(last) not in ("", LS):
            break
        psrs.pop()


def _page_break_spacer():
    """An empty protected paragraph that starts a new page; it precedes every chapter after the first."""
    psr = ET.Element("ParagraphStyleRange", {
        "AppliedParagraphStyle": "ParagraphStyle/Normal",
        "StartParagraph": "NextPage",
        "ParagraphBreakType": "NextPage",
        "BlankPageSpacer": "true",
        "BlankPageProtected": "true",
    })
    csr = ET.SubElement(psr, "CharacterStyleRange", {
        "AppliedCharacterStyle": NO_CHARACTER_STYLE,
        "ParagraphBreakType": "NextPage",
    })
    ET.SubElement(csr, "Content").text = LS
    ET.SubElement(csr, "Br")
    return psr


def _format_content_chapters(content_psrs):
    """Format each chapter heading for a fresh page with reference top spacing; return the rebuilt list."""
    out, seen_first_chapter = [], False
    for c_p in content_psrs:
        is_psr = _lname(c_p.tag) == "ParagraphStyleRange"
        prev = _previous_real_psr(out) if is_psr else None
        if not is_psr or not is_chapter_heading(c_p, prev):
            out.append(c_p)
            continue
        c_txt = _get_text(c_p)
        _format_chapter_heading(c_p)
        if prev is not None and _is_paired_heading(prev, c_txt):
            _drop_blank_psrs_after(out, prev)
            _format_paired_heading(c_p)
            out.append(c_p)
            continue
        _drop_trailing_spacers(out)
        if seen_first_chapter:
            out.append(_page_break_spacer())
        seen_first_chapter = True
        out.append(c_p)
    return out


FIRST_TOC_PAGE = 5
FIRST_TOC_PAGE_LINES = 22       # first TOC page: 522 pt frame minus the heading (about 114 pt), at about 18 pt per line
OTHER_TOC_PAGE_LINES = 29       # later TOC pages: the full 522 pt frame at about 18 pt per line
CHARS_PER_TOC_LINE = 45.0


def _toc_line_count(toc_psrs):
    """Estimated TOC lines, counting only the visible Content text of the entries (the heading is skipped)."""
    total = 0
    for psr in toc_psrs[1:]:
        text = "".join(c.text for c in psr.findall(".//Content") if c.text).strip()
        for line in (l for l in re.split(r"[\r\n\u2028]+", text) if l.strip()):
            total += max(1, int(math.ceil(len(line) / CHARS_PER_TOC_LINE)))
    return total


def _toc_page_count(line_count):
    """Pages the estimated TOC lines fill: the first page is shorter because of the heading."""
    if line_count <= FIRST_TOC_PAGE_LINES:
        return 1
    return 1 + int(math.ceil((line_count - FIRST_TOC_PAGE_LINES) / float(OTHER_TOC_PAGE_LINES)))


def _estimate_first_content_page(toc_psrs):
    """First-guess page where chapters start, from the TOC text length.

    Only a first guess that pre-assigns the footer master in the XML; the real TOC length is decided by InDesign
    (NextOddPage start paragraphs) and the real-layout pass in frontmatter_flow corrects the masters.
    """
    last_toc_page = FIRST_TOC_PAGE + _toc_page_count(_toc_line_count(toc_psrs)) - 1
    return last_toc_page + 2 if last_toc_page % 2 == 1 else last_toc_page + 1


def _spacer_psr(start_paragraph=None):
    """A protected, empty spacer paragraph holding one line separator, optionally starting on a given page type."""
    attrs = {"AppliedParagraphStyle": "ParagraphStyle/Normal"}
    if start_paragraph:
        attrs["StartParagraph"] = start_paragraph
    attrs.update({"BlankPageSpacer": "true", "BlankPageProtected": "true"})
    psr = ET.Element("ParagraphStyleRange", attrs)
    csr = ET.SubElement(psr, "CharacterStyleRange", {"AppliedCharacterStyle": NO_CHARACTER_STYLE})
    ET.SubElement(csr, "Content").text = LS
    ET.SubElement(csr, "Br")
    return psr


def _strip_page_breaks(psr):
    """Remove every forced page-break attribute from a paragraph and its character ranges."""
    psr.attrib.pop("ParagraphBreakType", None)
    psr.attrib.pop("StartParagraph", None)
    _strip_csr_breaks(psr)


def _keep_first_chapter_on_page(content_psrs):
    """The leading chapter headings of the content start 'anywhere': the odd-page spacer before them owns the break."""
    for p in content_psrs[:3]:
        style = (p.attrib.get("AppliedParagraphStyle") or "").lower()
        if "chapter" not in style and "heading" not in style:
            break
        p.set("StartParagraph", "Anywhere")
        p.attrib.pop("ParagraphBreakType", None)
        _strip_csr_breaks(p)


def _format_front_heading(psr, space_after):
    """Centre a front-matter heading (About the Author, Contents) in the heading style."""
    psr.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
    psr.set("Justification", "CenterAlign")
    psr.set("SpaceBefore", "44")
    psr.set("SpaceAfter", space_after)
    psr.set("Hyphenation", "false")


def _assemble_frontmatter(root, story_elem, non_psrs, author_psrs, toc_psrs, content_psrs):
    """Build the reordered front matter (author, TOC, content) and return (xml_bytes, first_content_page).

    Page flow is decided by InDesign from the real layout: the TOC and the first content page start on the next odd page.
    """
    for p in author_psrs + toc_psrs:
        _strip_page_breaks(p)
    _keep_first_chapter_on_page(content_psrs)
    if author_psrs:
        _format_front_heading(author_psrs[0], "15")
    _format_front_heading(toc_psrs[0], "50")
    ordered = (non_psrs + [_spacer_psr()] + author_psrs + [_spacer_psr("NextOddPage")] + toc_psrs
               + [_spacer_psr("NextOddPage")] + content_psrs)
    for child in list(story_elem):
        story_elem.remove(child)
    story_elem.extend(ordered)
    return ET.tostring(root, encoding="utf-8"), _estimate_first_content_page(toc_psrs)


def resequence_frontmatter_story(story_xml_bytes: bytes) -> tuple[bytes, int]:
    """
    Resequences front matter blocks inside the main continuous story to match reference book layout:
      - Block 1: ABOUT THE AUTHOR (lands on Page 3, Recto, Master None)
      - Block 2: TABLE OF CONTENTS (NextOddPage: lands on Page 5, Recto; blank Page 4 is automatic)
      - Block 3: Chapter 1 Top Spacer (NextOddPage: first content page is always odd, wherever the TOC ends)
      - Block 4: Main Content (Chapter 1 onwards, Master A-Master)

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

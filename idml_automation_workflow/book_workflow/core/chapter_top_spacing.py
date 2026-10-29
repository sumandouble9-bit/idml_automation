"""
Dedicated Standalone Module: Chapter & Front Matter Layout Spacing
==================================================================
Ensures consistent, elegant vertical spacing and alignment across all book IDML
documents, reverse-engineered faithfully from the human-designed reference InDesign document:
    'indd files/18049 Impressions Of A War Correspondent.indd' (and '18041 Proserpina.indd')

Design & Formatting Specifications:
-----------------------------------
1. Chapter Headings:
   - SpaceBefore = "14.5" pt (from margin glue line)
   - SpaceAfter = "30" pt
   - FontStyle = "Bold"
   - InDesign suppresses SpaceBefore on the first paragraph of a text frame;
     therefore a canonical spacer paragraph with Unicode Forced Line Break (U+2028)
     and NextPage break is placed before each chapter heading.
   - StartParagraph="NextPage" is removed from Styles.xml to prevent double page breaks.

2. Title Page (Page 1):
   - TextFrame bounds: [124.72, 36.0, 476.0, 360.0] pt (44 mm top, generous height preventing overset)
   - Title centered, non-hyphenated.
   - Precise reference gap below title to 'by' / 'Por' credit (baseline ~374 pt / 132 mm, gap ~180-190 pt)
   - Author name baseline ~400 pt (141 mm)

3. Copyright Page (Page 2):
   - TextFrame bounds aligned to exact reference: [71.0, 36.0, 515.0, 360.0] pt (25.05 mm top)
   - Verso title, copyright text, and publisher centered, non-hyphenated.

4. Table of Contents (TOC, Page 3):
   - Contents heading centered, non-hyphenated.
   - SpaceBefore = "44" pt with a preceding top spacer paragraph to achieve reference baseline.
   - SpaceAfter = "50" pt preserving the exact reference gap between Contents and its items.
   - Spacing between TOC items preserved (SpaceBefore="0", SpaceAfter="5").

5. Functional Spacing:
   - Body text, paragraph styles, headers, and footers remain undisturbed.

Usage:
------
    # Run on default directory (auto-detects renamed_output_files or Output):
    python run_chapter_top_spacing.py --pdf

    # Run on a single IDML file:
    python run_chapter_top_spacing.py path/to/book.idml --output-dir path/to/output --pdf

    # Update in-place:
    python run_chapter_top_spacing.py path/to/folder/ --in-place --pdf
"""

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

# Packaging namespace required for Adobe InDesign IDML
IDPKG_NS = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
ET.register_namespace("idPkg", IDPKG_NS)

# Constants reverse-engineered from reference '18049 Impressions Of A War Correspondent.indd'
REF_SPACE_BEFORE = "14.5"               # 14.5 pt top gap for chapters
REF_SPACE_AFTER = "30"                  # 30 pt space after chapter heading
REF_POINT_SIZE = "16"
LS = "\u2028"                           # Unicode Forced Line Break (Line Separator)

# Regex patterns for detecting chapter heading candidates
_CHAPTER_PREFIX = (
    r"(?:CHAPTER|CAP[IÍ]TULO|PART|PARTE|SECTION|SECCI[OÓ]N|CANTO|ACTO|TOMO|VOLUME|VOLUMEN)"
)
_BOOK_PREFIX = (
    r"(?:BOOK|LIBRO)\s+(?:[IVXLCDM0-9]+|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|"
    r"SEVENTH|EIGHTH|NINTH|TENTH|ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|"
    r"PRIMERO|SEGUNDO|TERCERO|CUARTO|QUINTO|SEXTO|S[EÉ]PTIMO|OCTAVO|NOVENO|D[EÉ]CIMO|"
    r"UNO|DOS|TRES|CUATRO|CINCO|SEIS|SIETE|OCHO|NUEVE|DIEZ)\b"
)
CHAPTER_PREFIX_RE = re.compile(
    rf"^\s*(?:{_CHAPTER_PREFIX}\s+(?:[IVXLCDM0-9]+|[A-ZÁÉÍÓÚÑa-záéíóúñ]+)|{_BOOK_PREFIX})\b",
    re.I,
)
STANDALONE_HEADINGS_RE = re.compile(
    r"^\s*(?:PREFACE|PREFACIO|PROLOGUE|PR[OÓ]LOGO|EPILOGUE|EP[IÍ]LOGO|INTRODUCTION|"
    r"INTRODUCCI[OÓ]N|CONCLUSION|CONCLUSI[OÓ]N|NOTES|NOTAS|APPENDIX|AP[EÉ]NDICE|"
    r"GLOSSARY|GLOSARIO)\s*$",
    re.I,
)

TOC_STYLE_KEYS = ("toc", "content", "index")
HEADING_STYLE_KEYS = ("chapter", "sub-heading", "centre_align", "center1", "after_chapter")


def _lname(tag: str) -> str:
    """Extract local XML tag name without namespace."""
    return tag.rsplit("}", 1)[-1]


def _get_text(elem: ET.Element) -> str:
    """Extract all text inside Content elements of an XML element."""
    return "".join(c.text or "" for c in elem.iter() if _lname(c.tag) == "Content").strip()


def is_chapter_heading(psr: ET.Element, prev_psr: ET.Element = None) -> bool:
    """Determine if a ParagraphStyleRange is a chapter heading."""
    style = psr.attrib.get("AppliedParagraphStyle", "").lower()
    
    # Never touch Table of Contents or Index rows
    if any(k in style for k in TOC_STYLE_KEYS):
        return False
        
    # Running headers on master pages or spread items are skipped
    if "master_" in style or "header" in style or "footer" in style:
        return False
        
    txt = _get_text(psr)
    if not txt or "###Insert" in txt:
        return False
        
    # Table of contents rows typically end with page numbers (e.g. "... 15")
    if re.search(r"[\t\.\s]{2,}\d+$", txt):
        return False
        
    # Style is explicitly chapter_name (and not running header or after_chapter)
    if "chapter_name" in style and not "after_chapter" in style:
        return True
    if "chapter_name01" in style:
        return True

    # Heading text matches chapter/part prefix or standalone section heading
    if CHAPTER_PREFIX_RE.match(txt):
        return True
    if STANDALONE_HEADINGS_RE.match(txt):
        if any(k in style for k in HEADING_STYLE_KEYS):
            return True
            
    return False


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
            
            # Remove any StartParagraph on chapter-related paragraph styles so InDesign
            # does not force a second page break after the spacer paragraph
            if "StartParagraph" in p.attrib and ("chapter" in name.lower() or "chapter" in self_id.lower()):
                del p.attrib["StartParagraph"]

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
            "StartParagraph": "Anywhere",
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


def process_story(story_xml_content: bytes) -> tuple[bytes, bool, int]:
    """Inspect and insert chapter heading top spacers into a story XML."""
    root = ET.fromstring(story_xml_content)
    
    story_elem = root.find(".//Story") if root.tag.endswith("Story") else root.find("Story")
    if story_elem is None:
        story_elem = root
        
    children = list(story_elem)
    psrs = [c for c in children if _lname(c.tag) == "ParagraphStyleRange"]
    if not psrs:
        return story_xml_content, False, 0
        
    has_master = any("master_chapter_name" in c.attrib.get("AppliedParagraphStyle", "") for c in psrs)
    if has_master and len(psrs) < 10:
        return story_xml_content, False, 0
        
    all_toc = all(any(k in c.attrib.get("AppliedParagraphStyle", "").lower() for k in TOC_STYLE_KEYS) for c in psrs if _get_text(c))
    if all_toc and len(psrs) > 0:
        return story_xml_content, False, 0

    changed = False
    chapter_count = 0
    new_children = []
    has_seen_content = False
    
    i = 0
    while i < len(children):
        child = children[i]
        if _lname(child.tag) != "ParagraphStyleRange":
            new_children.append(child)
            i += 1
            continue
            
        psr = child
        txt = _get_text(psr)
        prev_psr = new_children[-1] if (new_children and _lname(new_children[-1].tag) == "ParagraphStyleRange") else None
        
        if is_chapter_heading(psr, prev_psr):
            # Check if this heading immediately follows another heading (e.g. PART I followed by CHAPTER I)
            is_sub_heading_of_part = False
            if prev_psr is not None:
                prev_txt = _get_text(prev_psr)
                prev_st = prev_psr.attrib.get("AppliedParagraphStyle", "").lower()
                if (
                    "chapter_name" in prev_st
                    or "sub-heading" in prev_st
                    or any(k in prev_st for k in ["heading", "title", "part"])
                    or re.match(r"^\s*(?:PART|PARTE|BOOK|LIBRO)\b", prev_txt, re.I)
                ):
                    is_sub_heading_of_part = True
                    
            # Normalize chapter heading attributes
            psr.set("AppliedParagraphStyle", "ParagraphStyle/chapter_name")
            psr.set("StartParagraph", "Anywhere")
            psr.set("SpaceBefore", str(space_before))
            psr.set("SpaceAfter", str(space_after))
            psr.set("KeepLinesTogether", "true")
            psr.set("KeepWithNext", "2")
            
            # Remove any ParagraphBreakType on CSRs of the heading itself
            for csr in psr.findall("CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib:
                    del csr.attrib["ParagraphBreakType"]
                    
            # Ensure trailing Br on heading
            csrs = list(psr.findall("CharacterStyleRange"))
            if csrs:
                last_csr = csrs[-1]
                if not any(_lname(k.tag) == "Br" for k in last_csr):
                    ET.SubElement(last_csr, "Br")
                    
            if is_sub_heading_of_part:
                new_children.append(psr)
                changed = True
                i += 1
                continue
                
            # If previous children are existing empty spacer PSRs, remove them to ensure idempotence
            while new_children and _lname(new_children[-1].tag) == "ParagraphStyleRange":
                last_psr = new_children[-1]
                if any(_lname(k.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for k in last_psr.iter()):
                    break
                last_txt = _get_text(last_psr)
                if not last_txt or last_txt == LS:
                    new_children.pop()
                else:
                    break
                    
            if not has_seen_content:
                # First chapter in story: top spacer without NextPage break
                spacer_psr = ET.Element("ParagraphStyleRange", {
                    "AppliedParagraphStyle": "ParagraphStyle/Normal",
                    "BlankPageSpacer": "true",
                    "BlankPageProtected": "true",
                })
                csr = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"
                })
                cnt = ET.SubElement(csr, "Content")
                cnt.text = LS
                ET.SubElement(csr, "Br")
                new_children.append(spacer_psr)
            else:
                # Subsequent chapters: spacer with NextPage break, then heading starts Anywhere (below spacer)
                spacer_psr = ET.Element("ParagraphStyleRange", {
                    "AppliedParagraphStyle": "ParagraphStyle/Normal",
                    "BlankPageSpacer": "true",
                    "BlankPageProtected": "true",
                })
                csr_break = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
                    "ParagraphBreakType": "NextPage"
                })
                ET.SubElement(csr_break, "Br")
                csr_spacer = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"
                })
                cnt = ET.SubElement(csr_spacer, "Content")
                cnt.text = LS
                ET.SubElement(csr_spacer, "Br")
                new_children.append(spacer_psr)

            new_children.append(psr)
            has_seen_content = True
            changed = True
            chapter_count += 1
            i += 1
        else:
            if txt:
                has_seen_content = True
            new_children.append(child)
            i += 1
            
    if changed:
        for c in list(story_elem):
            story_elem.remove(c)
        for c in new_children:
            story_elem.append(c)
        return ET.tostring(root, encoding="utf-8"), True, chapter_count
        
    return story_xml_content, False, 0


def is_empty_psr(psr) -> bool:
    """Check if a ParagraphStyleRange contains only whitespace, BOM, or line separators."""
    txt = "".join(psr.itertext())
    cleaned = re.sub(r"[\s\ufeff\u2028\u00a0\r\n]+", "", txt)
    return len(cleaned) == 0


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
            
    if not author_psrs or not toc_psrs:
        return story_xml_bytes, 7

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
                # Subsequent chapters: insert spacer with NextPage break + \u2028
                sub_spacer = ET.Element("ParagraphStyleRange", {
                    "AppliedParagraphStyle": "ParagraphStyle/Normal",
                    "BlankPageSpacer": "true",
                    "BlankPageProtected": "true",
                })
                csr_break = ET.SubElement(sub_spacer, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
                    "ParagraphBreakType": "NextPage"
                })
                ET.SubElement(csr_break, "Br")
                csr_spacer = ET.SubElement(sub_spacer, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"
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


def apply_chapter_top_spacing(
    idml_path: str | Path,
    output_path: str | Path = None,
    space_before: str = REF_SPACE_BEFORE,
    space_after: str = REF_SPACE_AFTER,
    sequence_pages: bool = True,
    export_pdf: bool = False,
    pdf_path: str | Path = None,
    app = None,
    verbose: bool = True
) -> dict:
    """
    Applies reference chapter heading top spacing, front matter sequencing, and layout formatting.
    
    Sequence enforced:
      - Page 1: Title Page (Master None)
      - Page 2: Copyright Page (Master None)
      - Page 3: About the Author (Master None)
      - Page 4: Blank Page (Master None)
      - Page 5: Table of Contents (Master None)
      - Post-TOC balancing blank page (if TOC ends on odd page)
      - Content starts on Recto page with A-Master and page numbering!
    
    Args:
        idml_path: Path to source IDML document.
        output_path: Path for formatted IDML document. If None, overwrites in-place.
        space_before: Chapter InDesign SpaceBefore value (default: 14.5 pt).
        space_after: Chapter InDesign SpaceAfter value (default: 30 pt).
        sequence_pages: Resequence front matter blocks and assign master spreads (default: True).
        export_pdf: Also export High Quality Print PDF via Adobe InDesign.
        pdf_path: Custom path for exported PDF.
        app: Existing InDesign application COM instance.
        verbose: Print progress information.
        
    Returns:
        Dictionary summarizing changes: {file, chapters_spaced, stories_updated, first_content_page, success}
    """
    src = Path(idml_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source IDML not found: {src}")
        
    dst = Path(output_path).resolve() if output_path else src
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = dst.with_suffix(".tmp_spacing.idml")
    
    if verbose:
        print(f"[ChapterTopSpacing] Processing: {src.name}")
        
    with zipfile.ZipFile(src, "r") as zin:
        files = {item.filename: zin.read(item.filename) for item in zin.infolist()}
        
    # 1. Update Styles.xml (Chapters + Front Matter)
    if "Resources/Styles.xml" in files:
        files["Resources/Styles.xml"] = update_styles_xml(
            files["Resources/Styles.xml"],
            space_before=space_before,
            space_after=space_after
        )
        
    # 2. Update Spreads Geometry (Page 1 Title and Page 2 Copyright)
    update_spreads_geometry(files)

    # 3. Process Front Matter Stories (Title, Copyright, TOC)
    process_frontmatter_stories(files)

    # 4. Resequence front matter story & master spreads
    first_content_page = 7
    resequenced_fname = None
    if sequence_pages:
        for fname in sorted(files.keys()):
            if fname.startswith("Stories/Story_"):
                txt = files[fname].decode("utf-8", errors="ignore").lower()
                if ("contents" in txt or "contenido" in txt) and ("about the author" in txt or "sobre la autor" in txt):
                    files[fname], first_content_page = resequence_frontmatter_story(files[fname])
                    resequenced_fname = fname
                    break
        update_spreads_master_pages(files, first_content_page)

    # 5. Process all other story files for chapter headings
    total_chapters = 0
    stories_updated = 0
    
    for fname in sorted(files.keys()):
        if fname.startswith("Stories/Story_"):
            if fname == resequenced_fname:
                continue
            new_content, changed, count = process_story(files[fname])
            if changed:
                files[fname] = new_content
                stories_updated += 1
                total_chapters += count
                
    # 6. Write repackaged IDML archive
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
        if "mimetype" in files:
            zout.writestr("mimetype", files["mimetype"], compress_type=zipfile.ZIP_STORED)
        for fname, data in files.items():
            if fname != "mimetype":
                zout.writestr(fname, data, compress_type=zipfile.ZIP_DEFLATED)
                
    if dst.exists():
        os.remove(dst)
    shutil.move(temp_zip, dst)
    
    # 7. Export High Quality Print PDF & synchronize TOC if requested
    pdf_exported = False
    if export_pdf:
        target_pdf = Path(pdf_path) if pdf_path else dst.with_suffix(".pdf")
        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        ok = export_idml_to_pdf(dst, target_pdf, app=app)
        if ok:
            pdf_exported = True
            # Synchronize TOC page numbers from PDF
            if sync_idml_toc_from_pdf is not None:
                try:
                    updated = sync_idml_toc_from_pdf(dst, target_pdf)
                    if updated > 0:
                        if verbose:
                            print(f"      [TOC] Synchronized {updated} TOC page numbers; re-exporting final PDF...")
                        export_idml_to_pdf(dst, target_pdf, app=app)
                except Exception as e:
                    if verbose:
                        print(f"      [TOC] Note: TOC sync skipped: {e}")
            if verbose:
                print(f"      [OK] Exported PDF: {target_pdf.name} ({target_pdf.stat().st_size} bytes)")
    
    if verbose:
        print(f"[ChapterTopSpacing] Done: {dst.name} (Content begins on Page {first_content_page})")
        
    return {
        "file": str(dst),
        "chapters_spaced": total_chapters,
        "stories_updated": stories_updated,
        "first_content_page": first_content_page,
        "pdf_exported": pdf_exported,
        "success": True
    }


def get_indesign_app():
    """Acquire InDesign application instance via COM with graceful recovery and restart support."""
    import win32com.client
    # 1. Try active running instance
    for name in ["InDesign.Application.2025", "InDesign.Application"]:
        try:
            app = win32com.client.GetActiveObject(name)
            if app:
                return app
        except Exception:
            pass
            
    # 2. Try Dispatch
    for name in ["InDesign.Application.2025", "InDesign.Application"]:
        try:
            app = win32com.client.Dispatch(name)
            if app:
                return app
        except Exception:
            pass
            
    # 3. Clean restart via convert_to_pdf
    scripts_dir = Path(__file__).resolve().parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        from convert_to_pdf import restart_indesign
        return restart_indesign(wait_seconds=3)
    except Exception:
        pass
        
    raise RuntimeError("Could not connect to or start Adobe InDesign. Please ensure Adobe InDesign is installed.")


def export_idml_to_pdf(idml_path: str | Path, pdf_path: str | Path, app=None) -> bool:
    """Export an IDML document to High Quality Print PDF using Adobe InDesign."""
    src = Path(idml_path).resolve().as_posix()
    dst = Path(pdf_path).resolve().as_posix()
    
    for attempt in range(2):
        try:
            if app is None:
                app = get_indesign_app()
            jsx = f"""
            try {{
                app.scriptPreferences.userInteractionLevel = 1699640946;
                var doc = app.open(new File("{src}"));

                // User Requirement: if content is not showing full content, increase text frame preserving other formatting
                var didGrow = false;
                for (var s = 0; s < doc.stories.length; s++) {{
                    var story = doc.stories[s];
                    story.recompose();
                    for (var f = 0; f < story.textContainers.length; f++) {{
                        var tf = story.textContainers[f];
                        if (tf.constructor.name === "TextFrame" && tf.overflows) {{
                            var page = tf.parentPage;
                            var maxB = page ? (doc.documentPreferences.pageHeight - page.marginPreferences.bottom) : (tf.geometricBounds[2] + 72);
                            var gb = tf.geometricBounds;
                            if (gb[2] < maxB) {{
                                tf.geometricBounds = [gb[0], gb[1], maxB, gb[3]];
                                story.recompose();
                                didGrow = true;
                            }}
                            var step = 0;
                            while (tf.overflows && step < 15) {{
                                var cgb = tf.geometricBounds;
                                tf.geometricBounds = [cgb[0], cgb[1], cgb[2] + 36, cgb[3]];
                                story.recompose();
                                didGrow = true;
                                step++;
                            }}
                        }}
                    }}
                }}
                if (didGrow) {{
                    try {{ doc.save(new File("{src}")); }} catch(eSave) {{}}
                }}

                var pdfPreset = app.pdfExportPresets.itemByName("[High Quality Print]");
                if (!pdfPreset.isValid) {{
                    pdfPreset = app.pdfExportPresets[0];
                }}
                try {{
                    app.pdfExportPreferences.properties = pdfPreset.properties;
                    app.pdfExportPreferences.useDocumentBleedWithPDF = true;
                    doc.exportFile(ExportFormat.PDF_TYPE, new File("{dst}"), false);
                }} catch(eBleed) {{
                    doc.exportFile(ExportFormat.PDF_TYPE, new File("{dst}"), false, pdfPreset);
                }}
                doc.close(SaveOptions.NO);
                "OK";
            }} catch(e) {{
                "ERR:" + e.message;
            }}
            """
            res = app.DoScript(jsx, 1246973031)
            if str(res) == "OK":
                return True
        except Exception:
            if attempt == 0:
                try:
                    scripts_dir = Path(__file__).resolve().parent.parent
                    if str(scripts_dir) not in sys.path:
                        sys.path.insert(0, str(scripts_dir))
                    from convert_to_pdf import restart_indesign
                    app = restart_indesign(wait_seconds=3)
                except Exception:
                    app = None
            else:
                return False
    return False


def process_path(
    target_path: str | Path,
    output_dir: str | Path = None,
    in_place: bool = False,
    space_before: str = REF_SPACE_BEFORE,
    space_after: str = REF_SPACE_AFTER,
    export_pdf: bool = False,
    verbose: bool = True
) -> list[dict]:
    """Process an IDML file or a directory of IDML files."""
    p = Path(target_path).resolve()
    results = []
    app = None
    if export_pdf:
        # Ensure Document fonts in target directory so InDesign embeds them without substitution
        target_dir = Path(output_dir) if output_dir else (p if p.is_dir() else p.parent)
        doc_fonts_dir = target_dir / "Document fonts"
        if not doc_fonts_dir.exists():
            fonts_candidates = [
                Path(__file__).resolve().parent.parent.parent / "Output" / "Document fonts",
                Path(__file__).resolve().parent.parent.parent / "Fonts",
            ]
            for fc in fonts_candidates:
                if fc.is_dir():
                    try:
                        shutil.copytree(fc, doc_fonts_dir)
                    except Exception:
                        pass
                    break
        try:
            app = get_indesign_app()
        except Exception as e:
            if verbose:
                print(f"[ChapterTopSpacing] Note: InDesign will be initialized on-demand: {e}")
            app = None
    
    if p.is_file() and p.suffix.lower() == ".idml":
        if output_dir:
            out_base = Path(output_dir)
            out = (out_base / "idml" / p.name) if export_pdf else (out_base / p.name)
            out_pdf = out_base / "pdf" / p.with_suffix(".pdf").name
        else:
            out = p if in_place else p.with_name(f"{p.stem}_spaced.idml")
            out_pdf = out.with_suffix(".pdf")
        res = apply_chapter_top_spacing(
            p, out,
            space_before=space_before,
            space_after=space_after,
            sequence_pages=True,
            export_pdf=export_pdf,
            pdf_path=out_pdf if export_pdf else None,
            app=app,
            verbose=verbose
        )
        results.append(res)
    elif p.is_dir():
        all_idmls = sorted(list(p.glob("*.idml")))
        if not in_place:
            idml_files = [f for f in all_idmls if not f.name.endswith("_spaced.idml")]
        else:
            idml_files = all_idmls
        if not idml_files:
            print(f"[ChapterTopSpacing] No target IDML files found in directory: {p}")
            return results
            
        print(f"[ChapterTopSpacing] Found {len(idml_files)} IDML file(s) in {p.name}")
        for idml_file in idml_files:
            if output_dir:
                out_base = Path(output_dir)
                out = (out_base / "idml" / idml_file.name) if export_pdf else (out_base / idml_file.name)
                out_pdf = out_base / "pdf" / idml_file.with_suffix(".pdf").name
            else:
                out = idml_file if in_place else idml_file.with_name(f"{idml_file.stem}_spaced.idml")
                out_pdf = out.with_suffix(".pdf")
            try:
                res = apply_chapter_top_spacing(
                    idml_file, out,
                    space_before=space_before,
                    space_after=space_after,
                    sequence_pages=True,
                    export_pdf=export_pdf,
                    pdf_path=out_pdf if export_pdf else None,
                    app=app,
                    verbose=verbose
                )
                results.append(res)
            except Exception as e:
                print(f"[ChapterTopSpacing] ERROR processing {idml_file.name}: {e}")
                results.append({"file": str(idml_file), "success": False, "error": str(e)})
    else:
        print(f"[ChapterTopSpacing] Invalid file or directory: {target_path}")
        
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Apply chapter heading and front matter top spacing to InDesign IDML documents (reference '18049 Impressions Of A War Correspondent.indd')."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to an IDML file or directory containing IDML files (default: auto-detected renamed_output_files or Output directory)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help="Output directory for processed IDML files. If omitted, files will be saved with '_spaced.idml' suffix unless --in-place is specified.",
    )
    parser.add_argument(
        "--in-place",
        "-i",
        action="store_true",
        help="Overwrite target IDML files in-place.",
    )
    parser.add_argument(
        "--space-before",
        default=REF_SPACE_BEFORE,
        help=f"Chapter heading SpaceBefore value in points (default: {REF_SPACE_BEFORE} pt)",
    )
    parser.add_argument(
        "--space-after",
        default=REF_SPACE_AFTER,
        help=f"Chapter heading SpaceAfter value in points (default: {REF_SPACE_AFTER} pt)",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also export High Quality Print PDF files using Adobe InDesign.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress detailed output.",
    )

    args = parser.parse_args()
    target = args.path
    if not target:
        for candidate in [
            "idml_automation_workflow/renamed_output_files",
            "renamed_output_files",
            "../idml_automation_workflow/renamed_output_files",
            "idml_automation_workflow/Output",
            "Output",
            "../Output",
            "../idml_automation_workflow/Output",
        ]:
            if Path(candidate).is_dir() and list(Path(candidate).glob("*.idml")):
                target = candidate
                break
        if not target:
            target = "idml_automation_workflow/renamed_output_files"

    if not args.output_dir and not args.in_place:
        default_out = Path(__file__).resolve().parent.parent.parent / "final_output_files" / "sequenced_output"
        args.output_dir = str(default_out)

    results = process_path(
        target,
        output_dir=args.output_dir,
        in_place=args.in_place,
        space_before=args.space_before,
        space_after=args.space_after,
        export_pdf=args.pdf,
        verbose=not args.quiet
    )

    success_count = sum(1 for r in results if r.get("success"))
    print(f"\n[ChapterTopSpacing] Finished processing {success_count}/{len(results)} file(s) successfully.")


if __name__ == "__main__":
    main()

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

try:
    from typography_es_common import *
    from typography_es_story_processor import process_stories
except ImportError:
    from .typography_es_common import *
    from .typography_es_story_processor import process_stories


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


def apply(target_dir, reference_dir, book_name=None):
    styles_report = update_styles_xml(target_dir, reference_dir)
    story_report = process_stories(target_dir, book_name=book_name)
    tables_fixed = fix_table_overfit(target_dir, max_width=324.0)
    return {
        "styles_xml": styles_report,
        "stories": story_report,
        "tables_fixed": tables_fixed,
    }

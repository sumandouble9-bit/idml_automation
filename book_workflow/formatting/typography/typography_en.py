import copy
import html
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
    find_main_story,
    lname,
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
    from .typography_common import *
except ImportError:
    from typography_common import *

try:
    from .typography_story_processor import process_stories
except ImportError:
    from typography_story_processor import process_stories


def update_styles_xml(target_dir, reference_dir):
    """Ensure canonical styles are defined correctly in Resources/Styles.xml."""
    styles_path = Path(target_dir) / "Resources" / "Styles.xml"
    if not styles_path.exists():
        return {}

    root = ET.parse(styles_path).getroot()

    # Copy key styles from reference
    needed = {
        "ParagraphStyle/body_text",
        "ParagraphStyle/chapter_name",
        "ParagraphStyle/Sub-heading",
        "ParagraphStyle/after_chapter_name_heading",
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

    # Re-parse to enforce canonical character style attributes
    root = ET.parse(styles_path).getroot()
    removed_styles = []

    for cs in list(root.iter()):
        if lname(cs.tag) == "CharacterStyle":
            self_id = cs.attrib.get("Self", "")

            # Enforce formatting on canonical styles
            if self_id == "CharacterStyle/boldtext":
                cs.set("FontStyle", "Bold")
            elif self_id in ("CharacterStyle/italicalign", "CharacterStyle/italic"):
                cs.set("FontStyle", "Italic")
            elif self_id == "CharacterStyle/underlinalign":
                cs.set("Underline", "true")
            elif self_id == "CharacterStyle/upper":
                cs.set("Capitalization", "AllCaps")

            # Remove merged duplicate styles from Styles.xml (keep CharacterStyle/italic for title page)
            elif self_id in MERGE_MAP and self_id != "CharacterStyle/italic":
                parent = next(
                    (p for p in root.iter() if cs in list(p)),
                    None,
                )
                if parent is not None:
                    parent.remove(cs)
                    removed_styles.append(self_id)

    # Books may reference ParagraphStyle/body_text without defining it; create it
    # (cloned from Normal) so every body paragraph gets uniform justified + hyphenated
    # formatting instead of falling back to [Basic Paragraph] defaults.
    _bt_exists = any(
        lname(_p.tag) == "ParagraphStyle" and _p.attrib.get("Self") == "ParagraphStyle/body_text"
        for _p in root.iter()
    )
    _normal_el = next(
        (_p for _p in root.iter()
         if lname(_p.tag) == "ParagraphStyle" and _p.attrib.get("Self") == "ParagraphStyle/Normal"),
        None,
    )
    if not _bt_exists and _normal_el is not None:
        _bt = copy.deepcopy(_normal_el)
        _bt.set("Self", "ParagraphStyle/body_text")
        _bt.set("Name", "body_text")
        _bt.set("NextStyle", "ParagraphStyle/body_text")
        for _par in root.iter():
            if _normal_el in list(_par):
                _par.append(_bt)
                break

    # Enforce heading style font sizes, body/normal Palatino Linotype 9.65pt, and LeftAlign on quotes/verse
    for ps in list(root.iter()):
        if lname(ps.tag) == "ParagraphStyle":
            self_id = ps.attrib.get("Self", "")
            if self_id in (
                "ParagraphStyle/body_text",
                "ParagraphStyle/Normal",
                "ParagraphStyle/$ID/[Basic Paragraph]",
                "ParagraphStyle/$ID/NormalParagraphStyle",
                "ParagraphStyle/$ID/[Normal Paragraph Style]",
                "ParagraphStyle/Normal (Web)",
                "ParagraphStyle/noindent",
                "ParagraphStyle/noindentj",
                "ParagraphStyle/noindent1",
                "ParagraphStyle/bodytext_noendent",
                "ParagraphStyle/bodytext_Noendent",
                "ParagraphStyle/copybody",
                "ParagraphStyle/centre_align",
                "ParagraphStyle/center",
                "ParagraphStyle/center1",
            ) or (
                any(k in self_id.lower() for k in ["body", "normal", "basic", "noindent"])
                and not any(k in self_id.lower() for k in ["quote", "chapter", "sub-heading", "heading", "toc", "author", "title", "caption"])
            ):
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                if self_id in ("ParagraphStyle/body_text", "ParagraphStyle/Normal"):
                    ps.set("Justification", "LeftJustified")
                    ps.set("FirstLineIndent", "18")
                    ps.set("SpaceBefore", "1.5")
                    ps.set("SpaceAfter", "3")
                    # Uniform word spacing (no stretched spaces); justify via character
                    # spacing + hyphenation. Applied to the BODY style only, so poems,
                    # quotes and centered text (other styles) are never affected.
                    ps.set("MinimumWordSpacing", "80")
                    ps.set("DesiredWordSpacing", "100")
                    ps.set("MaximumWordSpacing", "120")
                    ps.set("MinimumLetterSpacing", "-2")
                    ps.set("DesiredLetterSpacing", "0")
                    ps.set("MaximumLetterSpacing", "5")
                    ps.set("MinimumGlyphScaling", "100")
                    ps.set("DesiredGlyphScaling", "100")
                    ps.set("MaximumGlyphScaling", "100")
                    ps.set("Hyphenation", "true")
            elif self_id in ("ParagraphStyle/block1", "ParagraphStyle/block", "ParagraphStyle/block2", "ParagraphStyle/verse", "ParagraphStyle/poem", "ParagraphStyle/quotes_normal"):
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                # Block quote / poem: indented both sides (EPUB margin ~4em), ragged-left
                # so forced verse lines never stretch.
                ps.set("Justification", "LeftAlign")
                ps.set("LeftIndent", "39.68503937007875")
                ps.set("RightIndent", "39.68503937007875")
                ps.set("FirstLineIndent", "0")
            elif self_id == "ParagraphStyle/fig caption":
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9", leading="11")
                ps.set("Justification", "CenterAlign")
            elif self_id == "ParagraphStyle/chapter_name":
                ps.set("PointSize", "16")
                ps.set("Hyphenation", "false")
                ps.set("FontStyle", "Bold")
                ps.set("Justification", "CenterAlign")
                ps.set("SpaceBefore", "14.5")
                ps.set("SpaceAfter", "30")
                ps.set("StartParagraph", "NextPage")
                ps.set("KeepAllLinesTogether", "true")
                ps.set("KeepLinesTogether", "true")
                ps.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/Sub-heading":
                ps.set("PointSize", "16")
                ps.set("Hyphenation", "false")
                ps.set("Justification", "CenterAlign")
                ps.set("SpaceAfter", "20")
                ps.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/after_chapter_name_heading":
                ps.set("PointSize", "16")
                ps.set("Hyphenation", "false")
                ps.set("Justification", "CenterAlign")
                ps.set("SpaceAfter", "30")
                ps.set("KeepWithNext", "2")
                ps.set("StartParagraph", "Anywhere")
                if "ParagraphBreakType" in ps.attrib:
                    ps.attrib["ParagraphBreakType"] = "Anywhere"
            elif self_id == "ParagraphStyle/chapter_name01":
                ps.set("PointSize", "12")
                ps.set("Hyphenation", "false")
                ps.set("FontStyle", "Bold")
                ps.set("SpaceBefore", "14.5")
                ps.set("StartParagraph", "NextPage")
                ps.set("KeepAllLinesTogether", "true")
                ps.set("KeepLinesTogether", "true")
                ps.set("KeepWithNext", "2")
            elif self_id == "ParagraphStyle/quotes_normal":
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                ps.set("Justification", "LeftJustified")
                ps.set("LeftIndent", "39.68503937007875")
                ps.set("RightIndent", "39.68503937007875")
                ps.set("PointSize", "9.65")
                ps.set("AppliedLanguage", "$ID/English: USA")
            elif any(k in self_id.lower() for k in ["quote", "block", "verse", "poem"]):
                _enforce_paragraph_style_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                ps.set("Justification", "LeftAlign")
                ps.set("AppliedLanguage", "$ID/English: USA")

        sanitize_styles_xml(root)
    write_xml(root, styles_path)
    fonts_synced = sync_fonts(target_dir, reference_dir)

    return {
        "removed_duplicate_styles": removed_styles,
        "fonts_synced": fonts_synced,
    }


def fix_table_overfit(target_dir, max_width=324.0):
    """
    Scans all stories for <Table> elements.
    If total table width > max_width (324 pt body text width):
    - Proportionally scales each Column SingleColumnWidth so total width == max_width.
    - Sets Cell insets to 2pt to prevent overflow.
    - Scales down font size in cells (<= 8.5pt, leading 10pt) to preserve inside content.
    - Ensures Row AutoGrow is true so height adjusts cleanly.
    """
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

                # Adjust cells inside this table
                for cell in tbl.iter():
                    if lname(cell.tag) == "Cell":
                        cell.set("ClipContentToTextCell", "false")
                        if scaled:
                            cell.set("TextLeftInset", "2")
                            cell.set("TextRightInset", "2")
                            cell.set("TextTopInset", "2")
                            cell.set("TextBottomInset", "2")

                            # Adjust cell text point size and leading
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

                # Ensure rows auto grow
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

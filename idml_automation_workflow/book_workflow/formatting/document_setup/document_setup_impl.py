"""
Document Setup Module:
Implements Task 1: "Add book size, page marge, bleed margin"

Sets trim size to 5.5 x 8.5 in (396 x 612 pt),
Margins to Top 36 pt, Bottom 54 pt, Left 36 pt, Right 36 pt,
Bleed margins to 3mm (8.5039 pt) top, bottom, outside/right, 0 inside.
Resizes pages, text frames, and logo polygon frames in all spreads and master spreads to match.
"""

import copy
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.idml_utils import find_main_story, lname, parse, write_xml

# Standard 5.5 x 8.5 in dimensions in points
PAGE_WIDTH = 396.0
PAGE_HEIGHT = 612.0
MARGIN_TOP = 36.0
MARGIN_BOTTOM = 54.0
MARGIN_LEFT = 36.0
MARGIN_RIGHT = 36.0
COLUMNS_POSITIONS = "0 324"
BLEED_OFFSET = "8.503937007874017"


def apply_preferences(target_dir):
    pref_path = Path(target_dir) / "Resources" / "Preferences.xml"
    if not pref_path.exists():
        return False

    root = parse(pref_path)
    changed = False

    for e in root.iter():
        tag = lname(e.tag)
        if tag == "DocumentPreference":
            e.set("PageWidth", str(int(PAGE_WIDTH)))
            e.set("PageHeight", str(int(PAGE_HEIGHT)))
            e.set("DocumentBleedTopOffset", BLEED_OFFSET)
            e.set("DocumentBleedBottomOffset", BLEED_OFFSET)
            # Inner (spine) edge bleeds, fore-edge = 0 -> page 1 right-side 0, page 2 left-side 0.
            e.set("DocumentBleedInsideOrLeftOffset", BLEED_OFFSET)
            e.set("DocumentBleedOutsideOrRightOffset", "0")
            e.set("DocumentBleedUniformSize", "false")
            e.set("FacingPages", "true")
            changed = True
        elif tag == "MarginPreference":
            e.set("Top", str(int(MARGIN_TOP)))
            e.set("Bottom", str(int(MARGIN_BOTTOM)))
            e.set("Left", str(int(MARGIN_LEFT)))
            e.set("Right", str(int(MARGIN_RIGHT)))
            e.set("ColumnCount", "1")
            e.set("ColumnGutter", "12")
            e.set("ColumnDirection", "Horizontal")
            e.set("ColumnsPositions", COLUMNS_POSITIONS)
            changed = True
        elif tag == "TextDefault":
            e.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
            e.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
            if "FontStyle" in e.attrib:
                e.set("FontStyle", "Regular")
            if "PointSize" in e.attrib:
                e.set("PointSize", "9.65")
            if "RuleBelow" in e.attrib:
                e.set("RuleBelow", "false")
            changed = True

    if changed:
        write_xml(root, pref_path)
    return changed


def _update_path_point_array(tf, width, height):
    """Update rectangular text frame path points to width x height centered at 0,0."""
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


def apply_spreads_and_pages(target_dir):
    spreads_dir = Path(target_dir) / "Spreads"
    master_dir = Path(target_dir) / "MasterSpreads"

    spread_files = list(spreads_dir.glob("*.xml"))
    pages_updated = 0
    frames_updated = 0

    body_w = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT  # 324 pt
    body_h = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM  # 522 pt

    # Discover primary master spread ID
    master_id = None
    if master_dir.is_dir():
        for mf in sorted(master_dir.glob("*.xml")):
            try:
                mroot = parse(mf)
                for ms in mroot.iter():
                    if lname(ms.tag) == "MasterSpread" and ms.attrib.get("Self"):
                        master_id = ms.attrib.get("Self")
                        break
                if master_id:
                    break
            except Exception:
                pass

    # Determine body start page based on existence of About the Author page:
    # Page 1: Title, Page 2: Copyright, Page 3: TOC, Page 4: Blank after TOC,
    # Page 5: About Author, Page 6: Blank after About Author -> Body starts on Page 7.
    # If no About Author: Body starts on Page 5.
    has_author_page = False
    stories_dir = Path(target_dir) / "Stories"
    if stories_dir.is_dir():
        for sf in stories_dir.glob("*.xml"):
            try:
                st_txt = sf.read_text(encoding="utf-8", errors="ignore").lower()
                if "sobre la autor" in st_txt or "about the author" in st_txt:
                    has_author_page = True
                    break
            except Exception:
                pass
    body_start_page = 7 if has_author_page else 5

    for sp in spread_files:
        try:
            root = parse(sp)
        except Exception:
            continue

        changed = False
        pages = [p for p in root.iter() if lname(p.tag) == "Page"]

        # Ensure correct AppliedMaster on every page:
        # Frontmatter (pages < body_start_page): AppliedMaster="n" (no headers/footers)
        # Body/Content (pages >= body_start_page): AppliedMaster=master_id (enables running footer and page numbers)
        for p in pages:
            pname = p.attrib.get("Name", "")
            try:
                pnum = int(pname)
            except ValueError:
                pnum = 0
            if 1 <= pnum < body_start_page:
                if p.attrib.get("AppliedMaster") != "n":
                    p.set("AppliedMaster", "n")
                    changed = True
                    pages_updated += 1
            elif pnum >= body_start_page and master_id:
                if p.attrib.get("AppliedMaster") != master_id:
                    p.set("AppliedMaster", master_id)
                    changed = True
                    pages_updated += 1

        is_p1 = any(p.attrib.get("Name") == "1" for p in pages)
        is_p2 = any(p.attrib.get("Name") == "2" for p in pages)
        if not (is_p1 or is_p2):
            if changed:
                write_xml(root, sp)
            continue

        frames = [f for f in root.iter() if lname(f.tag) == "TextFrame"]
        for tf in frames:
            it = tf.attrib.get("ItemTransform", "").split()
            if len(it) == 6:
                tx = float(it[4])
                is_verso = tx < 0

                if is_p1 and len(pages) == 1:
                    # Title frame on page 1: 324 x 400 pt, centered at X=198, Y=-30
                    _update_path_point_array(tf, body_w, 400.0)
                    tf.set("ItemTransform", f"1 0 0 1 {PAGE_WIDTH/2.0:.12g} -30")
                    frames_updated += 1
                    changed = True
                elif is_p2 and is_verso:
                    # Page 2 Copyright TextFrame: full verso margin box (324 x 522 pt) covering the page
                    _update_path_point_array(tf, body_w, body_h)
                    tf.set("ItemTransform", "1 0 0 1 -198 -9")
                    frames_updated += 1
                    changed = True

        # Adjust Polygon (Publisher Logo) on Page 1 if present
        if len(pages) == 1 and pages[0].attrib.get("Name") == "1":
            for poly in root.iter():
                if lname(poly.tag) == "Polygon":
                    poly.set("ItemTransform", "1 0 0 1 198.5325489776247 220.0")
                    ppa = next((e for e in poly.iter() if lname(e.tag) == "PathPointArray"), None)
                    if ppa is not None:
                        target_pts = [
                            "-25.60902897762477 -28.34730737762474",
                            "-25.60902897762477 17.412692622375296",
                            "0.6668510998203487 17.41269262237529",
                            "24.543931022375315 17.412692622375296",
                            "24.543931022375315 -28.34730737762474",
                        ]
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
                    changed = True

        if changed:
            write_xml(root, sp)

    return pages_updated, frames_updated


def clean_header_title(raw_title):
    """Clean and truncate raw title cleanly at subtitle/word boundary for running footers."""
    clean = re.sub(r"[\u2028\r\n]+", " ", raw_title).strip()
    clean = clean.split(":")[0].strip()
    for sep in [" FOR AMERICAN", " A Journey Around", "A Journey Around", "VOL.", "Vol.", "Volume"]:
        if sep in clean:
            clean = clean.split(sep)[0].strip()
    if len(clean) > 38:
        clean = clean[:38].rsplit(" ", 1)[0].strip()
    return clean


def extract_book_title(target_dir):
    """Extract clean primary book title for running footers and variables."""
    # 1. Try Title Page story if already generated
    t_story = Path(target_dir) / "Stories" / "Story_u_title_story.xml"
    if t_story.exists():
        try:
            root = parse(t_story)
            ps0 = next((p for p in root.iter() if lname(p.tag) == "ParagraphStyleRange"), None)
            if ps0 is not None:
                txt = "".join(c.text or "" for c in ps0.iter() if lname(c.tag) == "Content").strip()
                if txt:
                    return clean_header_title(txt)
        except Exception:
            pass

    # 2. Try main story front paragraphs
    mpath, mroot = find_main_story(target_dir)
    if mroot is not None:
        for p in list(mroot.iter())[:10]:
            if lname(p.tag) == "ParagraphStyleRange":
                txt = "".join(c.text or "" for c in p.iter() if lname(c.tag) == "Content").strip()
                if txt and len(txt) > 3 and not any(k in txt.lower() for k in ["copyright", "contents", "isbn", "double 9", "all rights"]):
                    clean = re.sub(r"[\u2028\r\n]+.*$", "", txt).strip()
                    if clean:
                        return clean_header_title(clean)

    return "Book Title"


def update_designmap_text_variables(target_dir):
    """Ensure Running Header text variable maps to main_page_title (matching Reference)."""
    dm_path = Path(target_dir) / "designmap.xml"
    if not dm_path.exists():
        return False
    try:
        root = parse(dm_path)
        changed = False
        for tv in root.iter():
            if lname(tv.tag) == "TextVariable" and tv.attrib.get("Name") == "Running Header":
                tv.set("VariableType", "MatchParagraphStyleType")
                pref = next((c for c in tv if "MatchParagraphStylePreference" in lname(c.tag)), None)
                if pref is None:
                    pref = ET.SubElement(tv, "MatchParagraphStylePreference")
                pref.set("TextBefore", "")
                pref.set("TextAfter", "")
                pref.set("AppliedParagraphStyle", "ParagraphStyle/main_page_title")
                pref.set("SearchStrategy", "FirstOnPage")
                pref.set("ChangeCase", "None")
                pref.set("DeleteEndPunctuation", "false")
                changed = True
        if changed:
            write_xml(root, dm_path)
        return changed
    except Exception:
        return False


def update_master_footer_stories(target_dir, book_title=None):
    """
    Populates MasterSpread footer stories with exact reference formatting:
    - Verso: Page Number | Book Title (Running Header)
    - Recto: Book Title (Running Header) | Page Number
    - Pre-populates ResultText with book_title and sets font to Bell MT 9pt.
    """
    if not book_title:
        book_title = extract_book_title(target_dir)

    clean_title = clean_header_title(book_title)

    master_dir = Path(target_dir) / "MasterSpreads"
    stories_dir = Path(target_dir) / "Stories"
    updated_stories = 0

    for mf in master_dir.glob("*.xml"):
        try:
            mroot = parse(mf)
        except Exception:
            continue

        for tf in mroot.iter():
            if lname(tf.tag) == "TextFrame":
                parent_story = tf.attrib.get("ParentStory")
                if not parent_story:
                    continue
                story_file = stories_dir / f"Story_{parent_story}.xml"

                it = tf.attrib.get("ItemTransform", "").split()
                is_verso = True
                if len(it) == 6:
                    tx = float(it[4])
                    is_verso = tx < 100.0

                ns_pkg = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
                ET.register_namespace("idPkg", ns_pkg)
                pkg_story = ET.Element(f"{{{ns_pkg}}}Story", {"DOMVersion": "14.0"})
                story_elem = ET.SubElement(pkg_story, "Story", {
                    "Self": parent_story,
                    "AppliedTOCStyle": "n",
                    "UserText": "true",
                    "IsEndnoteStory": "false",
                    "TrackChanges": "false",
                    "StoryTitle": "$ID/",
                    "AppliedNamedGrid": "n",
                })
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
                psr = ET.SubElement(story_elem, "ParagraphStyleRange", {
                    "AppliedParagraphStyle": "ParagraphStyle/master_chapter_name",
                    "Justification": "CenterAlign",
                })

                if is_verso:
                    # Verso: Page Number | Book Title
                    # 1. Page Number
                    csr1 = ET.SubElement(psr, "CharacterStyleRange", {
                        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                        "PointSize": "9",
                        "BaselineShift": "-1",
                    })
                    p1 = ET.SubElement(csr1, "Properties")
                    ET.SubElement(p1, "Leading", {"type": "enumeration"}).text = "Auto"
                    ET.SubElement(p1, "AppliedFont", {"type": "string"}).text = "Bell MT"
                    c1 = ET.SubElement(csr1, "Content")
                    c1.append(ET.ProcessingInstruction("ACE", "18"))

                    # 2. Separator
                    csr2 = ET.SubElement(psr, "CharacterStyleRange", {
                        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                        "PointSize": "9",
                    })
                    p2 = ET.SubElement(csr2, "Properties")
                    ET.SubElement(p2, "Leading", {"type": "enumeration"}).text = "Auto"
                    ET.SubElement(p2, "AppliedFont", {"type": "string"}).text = "Bell MT"
                    ET.SubElement(csr2, "Content").text = "\u2002|\u2002"

                    # 3. Running Header (Title)
                    csr3 = ET.SubElement(psr, "CharacterStyleRange", {
                        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                        "PointSize": "9",
                        "PageNumberType": "TextVariable",
                        "BaselineShift": "-1",
                    })
                    p3 = ET.SubElement(csr3, "Properties")
                    ET.SubElement(p3, "Leading", {"type": "enumeration"}).text = "Auto"
                    ET.SubElement(p3, "AppliedFont", {"type": "string"}).text = "Bell MT"
                    ET.SubElement(csr3, "TextVariableInstance", {
                        "Self": f"u_var_{parent_story}",
                        "Name": "Running Header",
                        "ResultText": clean_title,
                        "AssociatedTextVariable": "dTextVariablenRunning Header",
                    })
                else:
                    # Recto: Book Title | Page Number
                    # 1. Running Header (Title)
                    csr1 = ET.SubElement(psr, "CharacterStyleRange", {
                        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                        "PointSize": "9",
                        "PageNumberType": "TextVariable",
                        "BaselineShift": "-1",
                    })
                    p1 = ET.SubElement(csr1, "Properties")
                    ET.SubElement(p1, "Leading", {"type": "enumeration"}).text = "Auto"
                    ET.SubElement(p1, "AppliedFont", {"type": "string"}).text = "Bell MT"
                    ET.SubElement(csr1, "TextVariableInstance", {
                        "Self": f"u_var_{parent_story}",
                        "Name": "Running Header",
                        "ResultText": clean_title,
                        "AssociatedTextVariable": "dTextVariablenRunning Header",
                    })

                    # 2. Separator
                    csr2 = ET.SubElement(psr, "CharacterStyleRange", {
                        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                        "PointSize": "9",
                    })
                    p2 = ET.SubElement(csr2, "Properties")
                    ET.SubElement(p2, "Leading", {"type": "enumeration"}).text = "Auto"
                    ET.SubElement(p2, "AppliedFont", {"type": "string"}).text = "Bell MT"
                    ET.SubElement(csr2, "Content").text = "\u2002|\u2002"

                    # 3. Page Number
                    csr3 = ET.SubElement(psr, "CharacterStyleRange", {
                        "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                        "PointSize": "9",
                        "BaselineShift": "-1",
                    })
                    p3 = ET.SubElement(csr3, "Properties")
                    ET.SubElement(p3, "Leading", {"type": "enumeration"}).text = "Auto"
                    ET.SubElement(p3, "AppliedFont", {"type": "string"}).text = "Bell MT"
                    c3 = ET.SubElement(csr3, "Content")
                    c3.append(ET.ProcessingInstruction("ACE", "18"))

                write_xml(pkg_story, story_file)
                updated_stories += 1

    return updated_stories


def apply_master_spreads(target_dir):
    """
    Applies exact reference geometry to MasterSpreads:
    - Left page (Verso) and Right page (Recto) bounds and margins.
    - Running footers / page number text frames:
      - Verso: tx = -72.58647148672986, ty = 267.16 pt
      - Recto: tx = 323.41352851327014, ty = 267.16 pt
      - Path points: width = 324.75 pt, height = 9.58 pt
    - Running footer story content and text variable configuration.
    """
    master_dir = Path(target_dir) / "MasterSpreads"
    master_files = list(master_dir.glob("*.xml"))
    pages_updated = 0
    frames_updated = 0

    footer_target_pts = [
        "-287.7885285132702 -12.0",
        "-287.7885285132702 12.0",
        "36.96147148672994 12.0",
        "36.96147148672994 -12.0",
    ]

    for mf in master_files:
        try:
            root = parse(mf)
        except Exception:
            continue

        changed = False
        pages = [p for p in root.iter() if lname(p.tag) == "Page"]

        for idx, page in enumerate(pages):
            is_left = (idx == 0) if len(pages) > 1 else False

            mp = next((e for e in page if lname(e.tag) == "MarginPreference"), None)
            if mp is None:
                mp = ET.Element(page.tag.replace("Page", "MarginPreference"))
                page.insert(0, mp)
            mp.set("Top", "36")
            mp.set("Bottom", "54")
            mp.set("Left", "36")
            mp.set("Right", "36")
            mp.set("ColumnCount", "1")
            mp.set("ColumnGutter", "12")
            mp.set("ColumnDirection", "Horizontal")
            mp.set("ColumnsPositions", COLUMNS_POSITIONS)

            if is_left:
                page.set("ItemTransform", "1 0 0 1 -595.275590551 -420.94488188900004")
                page.set("GeometricBounds", "114.94488188900009 199.27559055100002 726.944881889 595.275590551")
            else:
                page.set("ItemTransform", "1 0 0 1 0 -420.94488188900004")
                page.set("GeometricBounds", "114.94488188900009 0 726.944881889 396")
            pages_updated += 1
            changed = True

        frames = [f for f in root.iter() if lname(f.tag) == "TextFrame"]
        for tf in frames:
            it = tf.attrib.get("ItemTransform", "").split()
            if len(it) == 6:
                tx = float(it[4])
                is_verso = tx < 100.0

                if is_verso:
                    tf.set("ItemTransform", "1 0 0 1 -72.58647148672986 267.15999999999997")
                else:
                    tf.set("ItemTransform", "1 0 0 1 323.41352851327014 267.15999999999997")

                ppa = next((e for e in tf.iter() if lname(e.tag) == "PathPointArray"), None)
                if ppa is not None:
                    pts = [c for c in ppa if lname(c.tag) == "PathPointType"]
                    if len(pts) == 4:
                        for pt, t in zip(pts, footer_target_pts):
                            pt.set("Anchor", t)
                            pt.set("LeftDirection", t)
                            pt.set("RightDirection", t)

                tf_pref = next((e for e in tf.iter() if lname(e.tag) == "TextFramePreference"), None)
                if tf_pref is not None:
                    tf_pref.set("TextColumnFixedWidth", "324.7500000000001")
                    tf_pref.set("VerticalJustification", "CenterAlign")

                frames_updated += 1
                changed = True

        if changed:
            write_xml(root, mf)

    # Update TextVariables and Footer stories with book title
    update_designmap_text_variables(target_dir)
    update_master_footer_stories(target_dir)

    return pages_updated, frames_updated


def apply(target_dir, reference_dir=None):
    # Step 1: Run XML/regex normalization from the new logic
    try:
        from .normalize_document_setup import normalize_extracted_dir
        norm_result = normalize_extracted_dir(target_dir, reference_dir)
    except Exception as e:
        norm_result = {"error": str(e)}

    pref_ok = apply_preferences(target_dir)
    pages_up, frames_up = apply_spreads_and_pages(target_dir)
    mpages_up, mframes_up = apply_master_spreads(target_dir)
    return {
        "preferences_applied": pref_ok,
        "normalization_step1": norm_result,
        "page_width": PAGE_WIDTH,
        "page_height": PAGE_HEIGHT,
        "margins": {
            "top": MARGIN_TOP,
            "bottom": MARGIN_BOTTOM,
            "left": MARGIN_LEFT,
            "right": MARGIN_RIGHT,
        },
        "bleed": BLEED_OFFSET,
        "pages_updated": pages_up + mpages_up,
        "frames_updated": frames_up + mframes_up,
    }

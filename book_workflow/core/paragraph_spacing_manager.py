"""Paragraph Spacing Manager.

Enforces standard normal paragraph spacing across all body and block/quote styles:
- SpaceBefore: 1.5 pt
- SpaceAfter: 3.0 pt

Normalizes baseline-to-baseline distance to standard 16.50 pt (net blank gap: 6.85 pt)
by updating paragraph style definitions in Resources/Styles.xml and trimming redundant
trailing <Br /> line breaks on body/block paragraphs, while preserving all existing
elements, paragraph structure, alignment, indents, and front-matter layout.
"""

import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


def _lname(tag: str) -> str:
    """Return local XML tag name without namespace."""
    return tag.rsplit("}", 1)[-1]


# Styles that represent standard prose / body text and block quotes
TARGET_STYLE_KEYWORDS = (
    "body_text",
    "normal",
    "copybody",
    "noindent",
    "noindentj",
    "noindent1",
    "bodytext_noendent",
    "bodytext_noendent",
    "block",
    "quote",
    "verse",
    "poem",
    "extract",
)

# Styles to explicitly exclude (headings, front-matter titles, captions, etc.)
EXCLUDED_STYLE_KEYWORDS = (
    "chapter",
    "sub-heading",
    "heading",
    "head",
    "title",
    "toc",
    "author",
    "caption",
    "verso",
    "copyright",
    "index",
    "folio",
    "running",
    "doublenine",
    "about_the_auth",
)

DEFAULT_SPACE_BEFORE = "1.5"
DEFAULT_SPACE_AFTER = "3"


def is_target_paragraph_style(style_name: str) -> bool:
    """Return True if style_name is a body or block/quote style."""
    s_lower = style_name.lower().replace("paragraphstyle/", "")
    if any(ex in s_lower for ex in EXCLUDED_STYLE_KEYWORDS):
        return False
    return any(k in s_lower for k in TARGET_STYLE_KEYWORDS)


def get_normal_spacing(styles_root: ET.Element) -> Tuple[str, str]:
    """Detect standard body text spacing from the document, falling back to defaults."""
    sb = None
    sa = None
    for ps in styles_root.iter():
        if _lname(ps.tag) != "ParagraphStyle":
            continue
        sid = ps.attrib.get("Self", ps.attrib.get("Name", ""))
        s_lower = sid.lower().replace("paragraphstyle/", "")
        if s_lower in ("body_text", "normal"):
            ps_sb = ps.attrib.get("SpaceBefore")
            ps_sa = ps.attrib.get("SpaceAfter")
            if ps_sb is not None and ps_sb != "None":
                sb = ps_sb
            if ps_sa is not None and ps_sa != "None":
                sa = ps_sa
            if sb and sa:
                break
    return (sb or DEFAULT_SPACE_BEFORE, sa or DEFAULT_SPACE_AFTER)


def apply_spacing_to_styles(styles_root: ET.Element, space_before: str, space_after: str) -> int:
    """Update SpaceBefore and SpaceAfter on all target styles in Styles.xml."""
    updated = 0
    for ps in styles_root.iter():
        if _lname(ps.tag) != "ParagraphStyle":
            continue
        sid = ps.attrib.get("Self", ps.attrib.get("Name", ""))
        if is_target_paragraph_style(sid):
            changed = False
            if ps.attrib.get("SpaceBefore") != space_before:
                ps.set("SpaceBefore", space_before)
                changed = True
            if ps.attrib.get("SpaceAfter") != space_after:
                ps.set("SpaceAfter", space_after)
                changed = True
            if changed:
                updated += 1
    return updated


def normalize_trailing_breaks(psr: ET.Element) -> int:
    """If a body or block paragraph ends with multiple trailing <Br /> line breaks,

    trims extra breaks so exactly one closing <Br /> remains. This ensures the
    inter-paragraph distance matches the standard normal 16.50 pt (6.85 pt gap)
    without merging paragraphs or altering front-matter spacers.
    """
    style = psr.attrib.get("AppliedParagraphStyle", "")
    if not is_target_paragraph_style(style):
        return 0

    txt = "".join(c.text or "" for c in psr.iter() if _lname(c.tag) == "Content").strip()
    if not txt:
        # Never touch empty paragraphs or spacers
        return 0

    # Collect Content and Br elements in document order
    nodes = []
    for elem in psr.iter():
        t = _lname(elem.tag)
        if t == "Content":
            nodes.append(("Content", elem, (elem.text or "").strip()))
        elif t == "Br":
            nodes.append(("Br", elem, ""))

    trailing_brs = []
    for kind, elem, text in reversed(nodes):
        if kind == "Br":
            trailing_brs.append(elem)
        elif kind == "Content" and text:
            break

    # If there are 2 or more trailing Brs at the end, remove the extra ones (keep 1)
    removed = 0
    if len(trailing_brs) > 1:
        for br_to_remove in trailing_brs[:-1]:
            for parent in psr.iter():
                if br_to_remove in list(parent):
                    try:
                        parent.remove(br_to_remove)
                        removed += 1
                        break
                    except ValueError:
                        pass
    return removed


def apply_spacing_to_stories(story_root: ET.Element, space_before: str, space_after: str) -> Tuple[int, int]:
    """Update inline SpaceBefore/SpaceAfter overrides and trim redundant trailing breaks.

    Returns:
        (overrides_updated, trailing_breaks_trimmed)
    """
    overrides_updated = 0
    breaks_trimmed = 0

    for psr in story_root.findall(".//ParagraphStyleRange"):
        style = psr.attrib.get("AppliedParagraphStyle", "")
        if is_target_paragraph_style(style):
            changed = False
            if "SpaceBefore" in psr.attrib and psr.attrib["SpaceBefore"] != space_before:
                psr.set("SpaceBefore", space_before)
                changed = True
            if "SpaceAfter" in psr.attrib and psr.attrib["SpaceAfter"] != space_after:
                psr.set("SpaceAfter", space_after)
                changed = True
            if changed:
                overrides_updated += 1

            # Trim redundant trailing Brs on content paragraphs
            b_rem = normalize_trailing_breaks(psr)
            if b_rem > 0:
                breaks_trimmed += b_rem

    return overrides_updated, breaks_trimmed


def apply_normal_paragraph_spacing(idml_path: Union[str, Path]) -> Dict[str, Union[int, str]]:
    """Apply standard normal paragraph spacing to an IDML file."""
    idml_path = Path(idml_path)
    if not idml_path.exists():
        raise FileNotFoundError(f"IDML not found: {idml_path}")

    styles_updated = 0
    total_overrides = 0
    total_breaks_trimmed = 0
    temp_dir = Path(tempfile.mkdtemp(prefix="idml_para_spc_"))

    try:
        with zipfile.ZipFile(idml_path, "r") as zin:
            zin.extractall(temp_dir)

        # 1. Update Styles.xml
        styles_file = temp_dir / "Resources" / "Styles.xml"
        sb, sa = DEFAULT_SPACE_BEFORE, DEFAULT_SPACE_AFTER
        if styles_file.exists():
            s_tree = ET.parse(styles_file)
            s_root = s_tree.getroot()
            sb, sa = get_normal_spacing(s_root)
            styles_updated = apply_spacing_to_styles(s_root, sb, sa)
            if styles_updated > 0:
                s_tree.write(styles_file, encoding="utf-8", xml_declaration=True)

        # 2. Update Stories (pure attribute updates and redundant break trimming)
        stories_dir = temp_dir / "Stories"
        if stories_dir.exists():
            for sf in stories_dir.glob("Story_*.xml"):
                st_tree = ET.parse(sf)
                st_root = st_tree.getroot()
                ov, br = apply_spacing_to_stories(st_root, sb, sa)
                if ov > 0 or br > 0:
                    st_tree.write(sf, encoding="utf-8", xml_declaration=True)
                    total_overrides += ov
                    total_breaks_trimmed += br

        # 3. Re-pack IDML if any changes made
        if styles_updated > 0 or total_overrides > 0 or total_breaks_trimmed > 0:
            temp_zip = temp_dir.parent / f"{idml_path.stem}_spc_fixed.zip"
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                mimetype_file = temp_dir / "mimetype"
                if mimetype_file.exists():
                    zout.write(mimetype_file, "mimetype", compress_type=zipfile.ZIP_STORED)

                for root, _, files in os.walk(temp_dir):
                    for file in files:
                        full_p = Path(root) / file
                        arcname = full_p.relative_to(temp_dir).as_posix()
                        if arcname == "mimetype":
                            continue
                        zout.write(full_p, arcname)

            shutil.move(str(temp_zip), str(idml_path))

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return {
        "styles_updated": styles_updated,
        "story_overrides_updated": total_overrides,
        "breaks_trimmed": total_breaks_trimmed,
        "space_before": sb,
        "space_after": sa,
    }


def normalize_paragraph_spacing_batch(targets: Union[str, Path, List[Union[str, Path]]]) -> List[Tuple[Path, dict]]:
    """Apply standard normal paragraph spacing to multiple IDML files."""
    files: List[Path] = []
    if isinstance(targets, (str, Path)):
        p = Path(targets)
        if p.is_dir():
            files = sorted(p.glob("*.idml"))
        elif p.is_file() and p.suffix.lower() == ".idml":
            files = [p]
    else:
        for t in targets:
            tp = Path(t)
            if tp.is_file() and tp.suffix.lower() == ".idml":
                files.append(tp)
            elif tp.is_dir():
                files.extend(sorted(tp.glob("*.idml")))

    results = []
    for f in files:
        stats = apply_normal_paragraph_spacing(f)
        results.append((f, stats))
    return results

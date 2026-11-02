import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _ln(tag):
    """Extracts local tag name by stripping XML namespace."""
    return tag.rsplit("}", 1)[-1]


def format_styles(root):
    """Normalizes paragraph styles for chapters to ensure proper page breaks and 14.5pt top spacing."""
    changed = False
    for ps in root.iter():
        if _ln(ps.tag) != "ParagraphStyle":
            continue
        name = (ps.attrib.get("Name", "") or "").lower()
        self_id = (ps.attrib.get("Self", "") or "").lower()
        if "after_chapter_name_heading" in self_id or "after_chapter_name_heading" in name:
            if ps.attrib.get("StartParagraph") != "Anywhere":
                ps.set("StartParagraph", "Anywhere")
                changed = True
            if ps.attrib.get("SpaceBefore") != "14":
                ps.set("SpaceBefore", "14")
                changed = True
            if ps.attrib.get("SpaceAfter") != "30":
                ps.set("SpaceAfter", "30")
                changed = True
            if ps.attrib.get("Justification") != "CenterAlign":
                ps.set("Justification", "CenterAlign")
                changed = True
            if ps.attrib.get("FirstLineIndent") != "0":
                ps.set("FirstLineIndent", "0")
                changed = True
        elif ("chapter_name" in self_id or "chapter_name" in name) and "master" not in self_id and "after" not in self_id:
            if ps.attrib.get("StartParagraph") != "NextPage":
                ps.set("StartParagraph", "NextPage")
                changed = True
            if ps.attrib.get("SpaceBefore") != "14.5":
                ps.set("SpaceBefore", "14.5")
                changed = True
            if ps.attrib.get("SpaceAfter") != "30":
                ps.set("SpaceAfter", "30")
                changed = True
            if ps.attrib.get("RuleAbove") != "true":
                ps.set("RuleAbove", "true")
                ps.set("RuleAboveLineWeight", "0")
                ps.set("RuleAboveOffset", "14.5")
                ps.set("KeepRuleAboveInFrame", "true")
                changed = True
            if ps.attrib.get("Justification") != "CenterAlign":
                ps.set("Justification", "CenterAlign")
                changed = True
            if ps.attrib.get("FirstLineIndent") != "0":
                ps.set("FirstLineIndent", "0")
                changed = True
    return changed


def _strip_trailing_break(psr):
    """Removes any ParagraphBreakType=NextPage so nothing forces a page break AFTER this paragraph."""
    changed = False
    if "ParagraphBreakType" in psr.attrib:
        del psr.attrib["ParagraphBreakType"]
        changed = True
    for c in psr.findall("CharacterStyleRange"):
        if "ParagraphBreakType" in c.attrib:
            del c.attrib["ParagraphBreakType"]
            changed = True
    return changed


def _preceding_has_content(psr):
    """True unless psr is an empty, break-carrying spacer that lost its BlankPageSpacer marker during injection."""
    if any(_ln(c.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for c in psr.iter()):
        return True
    txt = "".join(psr.itertext()).strip("\ufeff\u2028\u00a0 \t\r\n")
    if txt:
        return True
    breaks = (
        psr.attrib.get("StartParagraph") == "NextPage"
        or psr.attrib.get("ParagraphBreakType") == "NextPage"
        or any(c.attrib.get("ParagraphBreakType") == "NextPage" for c in psr.findall("CharacterStyleRange"))
    )
    return not breaks


def format_stories(root):
    """Ensures chapter headings start on a fresh page without creating double blank pages,
    while preserving paired headings on the same page and 14.5pt top gap."""
    changed = False
    parent_map = {c: p for p in root.iter() for c in p}

    # Identify all chapter headings in this story
    chapter_psrs = []
    for psr in list(root.iter()):
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        style = (psr.attrib.get("AppliedParagraphStyle", "") or "").lower()
        if "chapter_name" in style or style.endswith("/master_chapter_name") or "after_chapter" in style or "sub-heading" in style:
            chapter_psrs.append(psr)

    for i, psr in enumerate(chapter_psrs):
        parent = parent_map.get(psr)
        if parent is None:
            continue
        kids = list(parent)
        if psr not in kids:
            continue
        idx = kids.index(psr)

        # Check if this heading immediately follows another heading (paired / double H1 heading)
        is_paired = False
        prev_idx = idx - 1
        while prev_idx >= 0:
            prev_elem = kids[prev_idx]
            if _ln(prev_elem.tag) == "ParagraphStyleRange":
                p_st = (prev_elem.attrib.get("AppliedParagraphStyle", "") or "").lower()
                p_tx = "".join(prev_elem.itertext()).strip()
                if "chapter_name" in p_st or "sub-heading" in p_st or "after_chapter" in p_st:
                    is_paired = True
                    break
                elif p_tx:
                    break
            prev_idx -= 1

        if is_paired:
            # Second heading in a paired heading: stays on the SAME PAGE directly below
            if psr.attrib.get("AppliedParagraphStyle") != "ParagraphStyle/after_chapter_name_heading":
                psr.set("AppliedParagraphStyle", "ParagraphStyle/after_chapter_name_heading")
                changed = True
            if psr.attrib.get("StartParagraph") != "Anywhere":
                psr.set("StartParagraph", "Anywhere")
                changed = True
            if "ParagraphBreakType" in psr.attrib:
                del psr.attrib["ParagraphBreakType"]
                changed = True
            for csr in psr.findall("CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib:
                    del csr.attrib["ParagraphBreakType"]
                    changed = True
            if psr.attrib.get("SpaceBefore") != "14":
                psr.set("SpaceBefore", "14")
                changed = True
            if psr.attrib.get("SpaceAfter") != "30":
                psr.set("SpaceAfter", "30")
                changed = True
            if psr.attrib.get("Justification") != "CenterAlign":
                psr.set("Justification", "CenterAlign")
                changed = True
            if psr.attrib.get("FirstLineIndent") != "0":
                psr.set("FirstLineIndent", "0")
                changed = True
            continue

        # Main chapter heading: must have 14.5 gap
        if psr.attrib.get("SpaceBefore") != "14.5":
            psr.set("SpaceBefore", "14.5")
            changed = True
        if psr.attrib.get("SpaceAfter") != "30":
            psr.set("SpaceAfter", "30")
            changed = True
        if psr.attrib.get("Justification") != "CenterAlign":
            psr.set("Justification", "CenterAlign")
            changed = True
        if psr.attrib.get("FirstLineIndent") != "0":
            psr.set("FirstLineIndent", "0")
            changed = True

        # Check preceding element
        prev_child = kids[idx - 1] if idx > 0 else None
        prev_is_spacer = False
        if prev_child is not None and _ln(prev_child.tag) == "ParagraphStyleRange":
            if prev_child.attrib.get("BlankPageSpacer") == "true" or prev_child.attrib.get("BlankPageProtected") == "true":
                prev_is_spacer = True
            elif i > 0 and not _preceding_has_content(prev_child):
                prev_is_spacer = True

        if prev_is_spacer:
            # One break-before on the spacer moves the chapter to a fresh page; the heading
            # and its body then flow together, so no trailing page breaks are kept on either.
            if i == 0:
                if prev_child.attrib.get("StartParagraph") not in (None, "Anywhere"):
                    prev_child.set("StartParagraph", "Anywhere")
                    changed = True
            else:
                if prev_child.attrib.get("StartParagraph") != "NextPage":
                    prev_child.set("StartParagraph", "NextPage")
                    changed = True
            if _strip_trailing_break(prev_child):
                changed = True
            if psr.attrib.get("StartParagraph") != "Anywhere":
                psr.set("StartParagraph", "Anywhere")
                changed = True
            if _strip_trailing_break(psr):
                changed = True
        else:
            # No spacer: the heading itself carries the single break-before, with no trailing break.
            if i == 0:
                if psr.attrib.get("StartParagraph") != "Anywhere":
                    psr.set("StartParagraph", "Anywhere")
                    changed = True
            else:
                if psr.attrib.get("StartParagraph") != "NextPage":
                    psr.set("StartParagraph", "NextPage")
                    changed = True
            if _strip_trailing_break(psr):
                changed = True

    for psr in root.iter():
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        csrs = [c for c in psr if _ln(c.tag) == "CharacterStyleRange"]
        if len(csrs) >= 2:
            c1, c2 = csrs[0], csrs[1]
            br1 = any(_ln(x.tag) == "Br" for x in c1)
            br2 = any(_ln(x.tag) == "Br" for x in c2)
            pbt1 = c1.attrib.get("ParagraphBreakType") == "NextPage"
            txt1 = "".join(c1.itertext()).strip()
            txt2 = "".join(c2.itertext())
            if br1 and br2 and pbt1 and not txt1 and ("\u2028" in txt2 or not txt2.strip()):
                psr.remove(c1)
                psr.set("StartParagraph", "NextPage")
                if "ParagraphBreakType" in psr.attrib:
                    del psr.attrib["ParagraphBreakType"]
                changed = True
    return changed


_fix_styles = format_styles
_fix_stories = format_stories


def apply_to_idml(idml_path):
    """Applies chapter break formatting to an IDML file in-place."""
    idml_path = str(idml_path)
    tmpd = tempfile.mkdtemp(prefix="idml_chbreak_")
    try:
        with zipfile.ZipFile(idml_path, "r") as z:
            names = z.namelist()
            z.extractall(tmpd)
        any_changed = False

        styles_fp = os.path.join(tmpd, "Resources", "Styles.xml")
        if os.path.isfile(styles_fp):
            try:
                tree = ET.parse(styles_fp)
                if format_styles(tree.getroot()):
                    tree.write(styles_fp, xml_declaration=True, encoding="UTF-8")
                    any_changed = True
            except ET.ParseError:
                pass

        stories_dir = os.path.join(tmpd, "Stories")
        if os.path.isdir(stories_dir):
            for fn in os.listdir(stories_dir):
                if not fn.lower().endswith(".xml"):
                    continue
                fp = os.path.join(stories_dir, fn)
                try:
                    tree = ET.parse(fp)
                except ET.ParseError:
                    continue
                if format_stories(tree.getroot()):
                    tree.write(fp, xml_declaration=True, encoding="UTF-8")
                    any_changed = True

        if any_changed:
            tmp_zip = os.path.join(tmpd, "repacked.idml")
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
                first = "mimetype"
                if first in names:
                    zout.write(os.path.join(tmpd, first), first, compress_type=zipfile.ZIP_STORED)
                for nm in names:
                    if nm == first:
                        continue
                    fp = os.path.join(tmpd, nm)
                    if os.path.isfile(fp):
                        zout.write(fp, nm, compress_type=zipfile.ZIP_DEFLATED)
            shutil.move(tmp_zip, idml_path)
        return any_changed
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


fix_chapter_breaks = apply_to_idml

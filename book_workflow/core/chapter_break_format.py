import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _ln(tag):
    """Extracts local tag name by stripping XML namespace."""
    return tag.rsplit("}", 1)[-1]


def format_styles(root):
    """Normalizes paragraph styles for chapters to ensure proper page breaks."""
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
        elif ("chapter_name" in self_id or "chapter_name" in name) and "master" not in self_id and "after" not in self_id:
            if ps.attrib.get("StartParagraph") != "NextPage":
                ps.set("StartParagraph", "NextPage")
                changed = True
    return changed


def format_stories(root):
    """Ensures chapter headings start on a fresh page without creating double blank pages."""
    changed = False
    parent_map = {c: p for p in root.iter() for c in p}

    # Identify all chapter headings in this story
    chapter_psrs = []
    for psr in list(root.iter()):
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        style = (psr.attrib.get("AppliedParagraphStyle", "") or "").lower()
        if ("chapter_name" in style or style.endswith("/master_chapter_name")) and "after" not in style:
            chapter_psrs.append(psr)

    for i, psr in enumerate(chapter_psrs):
        # The very first chapter heading in the story (e.g. Chapter 1 on recto page 7)
        # stays on Page 7 with StartParagraph="Anywhere"
        if i == 0:
            if psr.attrib.get("StartParagraph") != "Anywhere":
                psr.set("StartParagraph", "Anywhere")
                changed = True
        else:
            # All subsequent chapter headings (Chapters 2+) must strictly start on NextPage
            if psr.attrib.get("StartParagraph") != "NextPage":
                psr.set("StartParagraph", "NextPage")
                changed = True

        # Remove redundant preceding empty spacer paragraphs that would cause double blank pages
        parent = parent_map.get(psr)
        if parent is not None:
            kids = list(parent)
            if psr in kids:
                idx = kids.index(psr)
                if idx > 0:
                    prev = kids[idx - 1]
                    prev_txt = "".join(prev.itertext()).strip()
                    is_spacer = prev.attrib.get("BlankPageSpacer") == "true" or prev_txt in ("", "\u2028")
                    if is_spacer and not any(_ln(c.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for c in prev.iter()):
                        parent.remove(prev)
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

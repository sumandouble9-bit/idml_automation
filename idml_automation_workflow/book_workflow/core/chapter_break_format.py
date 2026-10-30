# -*- coding: utf-8 -*-
"""Chapter break formatting module to ensure clean page breaks and prevent blank pages."""
import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _ln(tag):
    """Extracts local tag name by stripping XML namespace."""
    return tag.rsplit("}", 1)[-1]


def format_styles(root):
    """Normalizes paragraph styles for chapters to avoid conflicting page breaks."""
    changed = False
    for ps in root.iter():
        if _ln(ps.tag) != "ParagraphStyle":
            continue
        name = (ps.attrib.get("Name", "") or "").lower()
        self_id = (ps.attrib.get("Self", "") or "").lower()
        if "chapter" in name or "chapter" in self_id:
            if ps.attrib.get("StartParagraph") not in (None, "Anywhere"):
                ps.set("StartParagraph", "Anywhere")
                changed = True
    return changed


def format_stories(root):
    """Ensures chapter headings are preceded by a clean spacer paragraph so they start on a fresh page."""
    changed = False
    parent_map = {c: p for p in root.iter() for c in p}

    for psr in list(root.iter()):
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        style = (psr.attrib.get("AppliedParagraphStyle", "") or "").lower()
        if "chapter_name" in style or style.endswith("/master_chapter_name"):
            parent = parent_map.get(psr)
            if parent is not None:
                kids = list(parent)
                if psr in kids:
                    idx = kids.index(psr)
                    if idx > 0:
                        prev = kids[idx - 1]
                        has_rect = any(_ln(c.tag) == "Rectangle" for c in prev.iter())
                        prev_txt = "".join(prev.itertext()).strip()
                        if has_rect or (prev_txt and prev_txt != "\u2028"):
                            for csr in prev.iter():
                                if _ln(csr.tag) == "CharacterStyleRange":
                                    for c in list(csr):
                                        if _ln(c.tag) == "Content" and c.text and "\u2028" in c.text:
                                            c.text = c.text.replace("\u2028", "").strip()
                                            if not c.text:
                                                csr.remove(c)
                                            changed = True
                            if prev.attrib.get("StartParagraph") == "NextPage":
                                del prev.attrib["StartParagraph"]
                                changed = True

                            spacer = ET.Element("ParagraphStyleRange", {
                                "AppliedParagraphStyle": "ParagraphStyle/Normal",
                                "StartParagraph": "NextPage",
                                "BlankPageSpacer": "true",
                                "BlankPageProtected": "true",
                            })
                            csr = ET.SubElement(spacer, "CharacterStyleRange", {
                                "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"
                            })
                            cnt = ET.SubElement(csr, "Content")
                            cnt.text = "\u2028"
                            ET.SubElement(csr, "Br")
                            parent.insert(idx, spacer)
                            parent_map[spacer] = parent
                            changed = True

            if psr.attrib.get("StartParagraph") not in (None, "Anywhere"):
                psr.set("StartParagraph", "Anywhere")
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

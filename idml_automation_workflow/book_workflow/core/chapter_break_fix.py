# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET

def _ln(tag):
    return tag.rsplit("}", 1)[-1]


def _fix_styles(root):
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


def _fix_stories(root):
    changed = False
    for psr in root.iter():
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        style = (psr.attrib.get("AppliedParagraphStyle", "") or "").lower()
        if "chapter_name" in style or style.endswith("/master_chapter_name"):
            if psr.attrib.get("StartParagraph") not in (None, "Anywhere"):
                psr.set("StartParagraph", "Anywhere")
                changed = True
    return changed


def apply_to_idml(idml_path):
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
                if _fix_styles(tree.getroot()):
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
                if _fix_stories(tree.getroot()):
                    tree.write(fp, xml_declaration=True, encoding="UTF-8")
                    any_changed = True

        if any_changed:
            tmp_zip = idml_path + ".tmp"
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
                first = "mimetype"
                if first in names:
                    zout.write(os.path.join(tmpd, first), first, compress_type=zipfile.ZIP_STORED)
                for nm in names:
                    if nm == first:
                        continue
                    fp = os.path.join(tmpd, nm)
                    if os.path.isfile(fp):
                        zout.write(fp, nm)
            shutil.move(tmp_zip, idml_path)
        return any_changed
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


# Removes the duplicate forced page break that leaves a blank page before every
# chapter. The chapter-top spacer paragraph already carries StartParagraph=NextPage
# (it starts the new page and supplies the 14.5pt top gap); the chapter heading,
# however, inherits StartParagraph=NextPage from its paragraph STYLE, so it breaks
# a SECOND time - the spacer lands alone on an otherwise empty page. This forces
# every chapter style and heading paragraph to StartParagraph=Anywhere, leaving the
# single break on the spacer, so the heading follows the spacer on the same page.

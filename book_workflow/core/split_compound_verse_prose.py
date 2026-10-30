import copy
import re
import zipfile
import tempfile
import shutil
import os
from pathlib import Path
import xml.etree.ElementTree as ET


def _lname(tag: str) -> str:
    """Strips XML namespace, returning the local tag name."""
    return tag.rsplit("}", 1)[-1]


_SKIP_STYLES = (
    "chapter", "head", "toc", "title", "author", "caption",
    "verso", "copyright", "index", "folio", "running",
    "doublenine", "about_the_auth"
)


def _split_single_psr_at_br(psr: ET.Element):
    """Splits one compound ParagraphStyleRange at <Br /> boundaries into
    individual ParagraphStyleRange elements (one per paragraph)."""
    paragraphs = []
    current_csrs = []

    for csr in list(psr):
        if _lname(csr.tag) != "CharacterStyleRange":
            current_csrs.append(csr)
            continue

        sub_items = []
        for child in list(csr):
            if _lname(child.tag) == "Br":
                new_csr = copy.deepcopy(csr)
                for c in list(new_csr):
                    new_csr.remove(c)
                for item in sub_items:
                    new_csr.append(item)
                new_csr.append(child)
                current_csrs.append(new_csr)
                paragraphs.append(current_csrs)
                current_csrs = []
                sub_items = []
            else:
                sub_items.append(child)

        if sub_items:
            new_csr = copy.deepcopy(csr)
            for c in list(new_csr):
                new_csr.remove(c)
            for item in sub_items:
                new_csr.append(item)
            current_csrs.append(new_csr)

    if current_csrs:
        paragraphs.append(current_csrs)

    out_psrs = []
    orig_attrib = dict(psr.attrib)

    for p_csrs in paragraphs:
        p_txt = "".join(
            c.text or ""
            for node in p_csrs
            for c in node.iter()
            if _lname(c.tag) == "Content"
        ).strip()

        new_psr = ET.Element(psr.tag, dict(orig_attrib))
        for c in p_csrs:
            new_psr.append(c)

        has_soft_break = "\u2028" in p_txt
        has_long_word = any(len(w) >= 25 for w in re.findall(r'[A-Za-z0-9]{25,}', p_txt))
        if has_soft_break:
            new_psr.set("Justification", "LeftAlign")
            new_psr.set("FirstLineIndent", "0")
        elif has_long_word:
            new_psr.set("Justification", "LeftAlign")
            new_psr.set("FirstLineIndent", "0")
            new_psr.set("Hyphenation", "false")
            for csr in new_psr.iter():
                if _lname(csr.tag) == "CharacterStyleRange":
                    csr.set("Tracking", "-20")
        else:
            new_psr.set("Justification", "LeftJustified")
            new_psr.set("FirstLineIndent", "18")
            new_psr.set("SpaceBefore", "1.5")
            new_psr.set("SpaceAfter", "3")

        out_psrs.append(new_psr)

    return out_psrs


def split_compound_verse_and_prose(story_root: ET.Element) -> bool:
    """Scans story XML and splits compound ParagraphStyleRanges containing both
    soft-break verse lines and regular body prose. Returns True if modified."""
    parent_map = {c: p for p in story_root.iter() for c in p}
    changed = False

    for psr in list(story_root.iter()):
        if _lname(psr.tag) != "ParagraphStyleRange":
            continue

        style = psr.attrib.get("AppliedParagraphStyle", "").lower()
        if any(skip in style for skip in _SKIP_STYLES):
            continue

        brs = [c for c in psr.iter() if _lname(c.tag) == "Br"]
        if len(brs) <= 1:
            continue

        txt = "".join(c.text or "" for c in psr.iter() if _lname(c.tag) == "Content")
        has_soft_break = "\u2028" in txt
        has_long_word = any(len(w) >= 25 for w in re.findall(r'[A-Za-z0-9]{25,}', txt))
        if not has_soft_break and not has_long_word:
            continue

        parent = parent_map.get(psr)
        if parent is None:
            continue

        try:
            idx = list(parent).index(psr)
        except ValueError:
            continue

        parent.remove(psr)
        new_psrs = _split_single_psr_at_br(psr)
        for offset, n_psr in enumerate(new_psrs):
            parent.insert(idx + offset, n_psr)
            parent_map[n_psr] = parent

        changed = True

    return changed


def process_idml(idml_path: Path) -> bool:
    """Processes an IDML archive in-place, splitting any compound mixed
    verse/prose ranges in its stories."""
    idml_path = Path(idml_path)
    if not idml_path.exists():
        return False

    with zipfile.ZipFile(str(idml_path), "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}

    modified = False
    for n in names:
        if n.startswith("Stories/") and n.endswith(".xml"):
            try:
                root = ET.fromstring(data[n])
            except Exception:
                continue

            if split_compound_verse_and_prose(root):
                data[n] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                modified = True

    if modified:
        tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".idml")
        os.close(tmp_fd)
        with zipfile.ZipFile(tmp_path_str, "w", zipfile.ZIP_DEFLATED) as zout:
            for n in names:
                zout.writestr(n, data[n])
        shutil.move(tmp_path_str, str(idml_path))

    return modified

import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

_RUN = re.compile("\u2028(?:[ \t\u00a0\r\n]*\u2028)+")


def _lname(tag):
    return tag.rsplit("}", 1)[-1]
# local tag name without the XML namespace.


def collapse_soft_breaks(story_root):
    changed = False
    for c in story_root.iter():
        if _lname(c.tag) == "Content" and c.text and "\u2028" in c.text:
            new = _RUN.sub("\u2028", c.text)
            if new != c.text:
                c.text = new
                changed = True
    return changed
# collapses any run of 2+ consecutive soft line breaks (a blank line between stanzas)
# down to a single soft break, so stanza/paragraph gaps are one line, not several.


def apply_collapse(idml_path):
    idml_path = Path(idml_path)
    with zipfile.ZipFile(str(idml_path), "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}
    hits = 0
    for n in names:
        if n.startswith("Stories/") and n.endswith(".xml"):
            try:
                root = ET.fromstring(data[n])
            except Exception:
                continue
            if collapse_soft_breaks(root):
                data[n] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                hits += 1
    if hits:
        tmp = idml_path.with_suffix(".collapse.tmp")
        with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED) as zout:
            for n in names:
                zout.writestr(n, data[n])
        tmp.replace(idml_path)
    return hits
# file-level entry point: collapses multi soft-break runs across every story in place.

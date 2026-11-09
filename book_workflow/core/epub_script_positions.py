import html
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS = {"Superscript": "sup", "Subscript": "sub"}
MARKER_PATTERN = re.compile(r"^\[[^\]\s]{1,6}\]$")
TAG_PATTERN = re.compile(r"<[^>]+>")
NO_STYLE = "CharacterStyle/$ID/[No character style]"


def _lname(tag):
    """Local tag name without the XML namespace."""
    return tag.rsplit("}", 1)[-1]


def _clean(text):
    """Text with entities decoded and all whitespace removed, so EPUB and IDML runs compare equal."""
    return re.sub(r"[\s  ]+", "", html.unescape(text or ""))


def epub_script_texts(epub_path):
    """For each position ("Superscript", "Subscript"), the set of texts the EPUB really sets that way."""
    found = {position: set() for position in SCRIPTS}
    with zipfile.ZipFile(str(epub_path), "r") as zf:
        for name in zf.namelist():
            if name.lower().endswith((".xhtml", ".html", ".htm")):
                doc = zf.read(name).decode("utf-8", "ignore")
                for position, tag in SCRIPTS.items():
                    pattern = r"<%s\b[^>]*>(.*?)</%s>" % (tag, tag)
                    found[position].update(_clean(TAG_PATTERN.sub("", m)) for m in re.findall(pattern, doc, re.I | re.S))
    for texts in found.values():
        texts.discard("")
    return found


def _run_text(csr):
    """Visible text of one CharacterStyleRange."""
    return "".join(c.text or "" for c in csr.iter() if _lname(c.tag) == "Content")


def _script_of(csr):
    """The script position a run carries, by attribute or by character style name, else None."""
    position = csr.attrib.get("Position")
    if position in SCRIPTS:
        return position
    style = csr.attrib.get("AppliedCharacterStyle", "").lower()
    return next((p for p in SCRIPTS if style.endswith(p.lower())), None)


def _is_genuine(text, position, texts):
    """True when a script run is a footnote marker or text the EPUB sets the same way (without padding spaces)."""
    clean = _clean(text)
    if not clean or (position == "Superscript" and MARKER_PATTERN.match(clean)):
        return True
    return clean in texts[position] and text == text.strip()


def _clear_script(csr):
    """Remove the script position and script character style from a run."""
    csr.attrib.pop("Position", None)
    if _script_of(csr):
        csr.set("AppliedCharacterStyle", NO_STYLE)


def clear_false_positions(story_root, texts):
    """Clear superscript/subscript runs the EPUB does not set that way; return True when anything changed."""
    changed = False
    for csr in story_root.iter():
        if _lname(csr.tag) != "CharacterStyleRange":
            continue
        position = _script_of(csr)
        if position and not _is_genuine(_run_text(csr), position, texts):
            _clear_script(csr)
            changed = True
    return changed


def clear_extracted(extracted_dir, epub_path):
    """Clear false superscripts/subscripts in every story of an unpacked IDML; return stories changed."""
    stories = Path(extracted_dir) / "Stories"
    if not epub_path or not stories.is_dir():
        return 0
    texts = epub_script_texts(epub_path)
    hits = 0
    for story_file in stories.glob("Story_*.xml"):
        tree = ET.parse(story_file)
        if clear_false_positions(tree.getroot(), texts):
            tree.write(story_file, encoding="utf-8", xml_declaration=True)
            hits += 1
    return hits

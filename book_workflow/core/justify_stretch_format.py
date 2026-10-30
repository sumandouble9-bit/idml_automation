import re
import xml.etree.ElementTree as ET

_SKIP_STYLES = (
    "chapter", "head", "toc", "title", "author", "caption",
    "verso", "copyright", "index", "folio", "running",
    "doublenine", "about_the_auth"
)
_JUSTIFIED = ("LeftJustified", "FullyJustified", "RightJustified", "CenterJustified")


def _lname(tag):
    """Strips the XML namespace, returning just the local tag name."""
    return tag.rsplit("}", 1)[-1]


def format_justify_stretch(sroot):
    """Adjusts justification and tracking on soft line breaks and unbroken long words.

    Runs after the main justification pass. A paragraph holding a soft line break
    or an unbroken long word is formatted to LeftAlign with zero indent and negative tracking.
    Continuous body prose blocks without soft breaks remain justified.
    """
    changed = False
    for psr in sroot.iter():
        if _lname(psr.tag) != "ParagraphStyleRange":
            continue
        sl = psr.attrib.get("AppliedParagraphStyle", "").lower()
        if any(k in sl for k in _SKIP_STYLES):
            continue
        txt = "".join(c.text or "" for c in psr.iter() if _lname(c.tag) == "Content")
        if not txt.strip():
            continue
        cur = psr.attrib.get("Justification")
        if cur in ("CenterAlign", "RightAlign"):
            continue
        has_ls = "\u2028" in txt
        has_long_word = any(len(w) >= 25 for w in re.findall(r'[A-Za-z0-9]{25,}', txt))
        br = sum(1 for e in psr.iter() if _lname(e.tag) == "Br")
        if (has_ls or has_long_word) and br <= 1:
            if cur != "LeftAlign":
                psr.set("Justification", "LeftAlign")
                changed = True
            if has_long_word:
                psr.set("FirstLineIndent", "0")
                psr.set("Hyphenation", "false")
                for csr in psr.iter():
                    if _lname(csr.tag) == "CharacterStyleRange":
                        csr.set("Tracking", "-20")
                changed = True
        elif any(k in sl for k in ("quote", "block", "epigraph")) and br <= 1 and len(txt.strip()) > 120:
            if cur not in _JUSTIFIED:
                psr.set("Justification", "LeftJustified")
                changed = True
    return changed


fix_justify_stretch = format_justify_stretch

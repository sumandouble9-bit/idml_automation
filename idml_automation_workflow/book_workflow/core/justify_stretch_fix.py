import xml.etree.ElementTree as ET

_SKIP_STYLES = ("chapter", "head", "toc", "title", "author", "caption",
                "verso", "copyright", "index", "folio", "running",
                "doublenine", "about_the_auth")
_JUSTIFIED = ("LeftJustified", "FullyJustified", "RightJustified", "CenterJustified")


def _lname(tag):
    return tag.rsplit("}", 1)[-1]
# strips the XML namespace, returning just the local tag name.


def fix_justify_stretch(sroot):
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
        br = sum(1 for e in psr.iter() if _lname(e.tag) == "Br")
        if has_ls:
            if cur != "LeftAlign":
                psr.set("Justification", "LeftAlign")
                changed = True
        elif any(k in sl for k in ("quote", "block", "epigraph")) and br <= 1 and len(txt.strip()) > 120:
            if cur not in _JUSTIFIED:
                psr.set("Justification", "LeftJustified")
                changed = True
    return changed
# Runs after the main justification pass so it has the final say, without touching it.
# A paragraph holding a soft line break (\u2028) is forced to LeftAlign, because the
# visual line before each soft break is justified by InDesign and stretches when short
# (covers inherited justification and long pre-break segments the main pass misses).
# A long block/quote of continuous prose with no soft break is justified instead, so a
# block justified in the EPUB stays justified in the IDML. Headings, TOC, captions,
# front matter and centred/right paragraphs are never touched, and ordinary body
# paragraphs without a soft break keep whatever the main pass already set.

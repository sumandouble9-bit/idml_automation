"""Normalize chapter / book headings in an IDML story tree.

- Split "NUMBER <sep> TITLE" headings (e.g. "CHAPTER I\u2014M. MYRIEL",
  "BOOK FIRST\u2014A JUST MAN", "CAP\u00cdTULO XIV. Title") into two lines
  "NUMBER<U+2028>TITLE" with the separator removed.
- Center them and promote misclassified headings (body_text etc.) to chapter_name.

NEVER touches the Table of Contents (toc / content / index styles) or page-number
TOC rows. Language-agnostic (English + Spanish). Pure XML, no InDesign.
"""
import re
import xml.etree.ElementTree as ET

LS = "\u2028"  # forced line break inside a paragraph (NOT a paragraph break)

_PREFIX = r"(?:BOOK|PART|CHAPTER|SECTION|CANTO|VOLUME|CAP\u00cdTULO|CAPITULO|PARTE|LIBRO|SECCI\u00d3N|SECCION|ACTO|TOMO)"
_DASH_RE = re.compile(r"^(" + _PREFIX + r"\b[^\u2014\u2013]*?)\s*[\u2014\u2013]\s*(\S.*)$", re.I)
_DOT_RE = re.compile(r"^(" + _PREFIX + r"\s+[IVXLCDM0-9]+)\s*[.:]\s+(\S.*)$", re.I)
_START_RE = re.compile(r"^\s*" + _PREFIX + r"\s+(?:[IVXLCDM0-9]+|[A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1][A-Z\u00c1\u00c9\u00cd\u00d3\u00da\u00d1.]+)\b", re.I)
_HEAD_STYLE_KEYS = ("chapter", "sub-heading", "master_chapter", "after_chapter")
# A heading like "IROBINSON WITH HIS PARENTS" / "VTHE SHIPWRECK": a STRICT roman
# numeral stuck directly to an uppercase title with no separator. The strict
# pattern stops at the real numeral ("XLI" in "XLIDELIVERANCE", not "XLID").
_ROMAN_ATTACHED = re.compile(
    r"^(M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
    r"([A-ZÁÉÍÓÚÑ].*\s.*)$")
# TOC / front-matter list styles that must never be altered.
_SKIP_STYLE_KEYS = ("toc", "content", "index")


def _lname(tag):
    return tag.rsplit("}", 1)[-1]


def _split_heading_text(txt):
    t = re.sub(r"\s+", " ", txt.replace(LS, " ")).strip()
    m = _DASH_RE.match(t) or _DOT_RE.match(t)
    if not m:
        return None
    a, b = m.group(1).strip(), m.group(2).strip()
    if not a or not b:
        return None
    return a + LS + b


def _rewrite_content(psr, new_text):
    # Put the two-line text in the first Content; keep every <Br> (the trailing
    # <Br> is the PARAGRAPH break in IDML - removing it merges paragraphs).
    contents = [c for c in psr.iter() if _lname(c.tag) == "Content"]
    if not contents:
        return False
    contents[0].text = new_text
    for c in contents[1:]:
        c.text = ""
    return True


def _ensure_trailing_br(psr):
    """Guarantee the heading paragraph ends with a <Br/> (the IDML paragraph
    terminator). Headings that lack it merge into the following paragraph."""
    csrs = [c for c in psr if _lname(c.tag) == "CharacterStyleRange"]
    if not csrs:
        return False
    last = csrs[-1]
    kids = list(last)
    if kids and _lname(kids[-1].tag) == "Br":
        return False
    ET.SubElement(last, "Br")
    return True


def normalize_headings(sroot):
    """Fix chapter/book headings under story root `sroot`. TOC untouched.
    Returns True if anything changed."""
    changed = False
    psrs = [p for p in sroot.iter() if _lname(p.tag) == "ParagraphStyleRange"]

    def _style_l(p):
        return p.attrib.get("AppliedParagraphStyle", "").lower()

    def _is_toc(p):
        return any(k in _style_l(p) for k in _SKIP_STYLE_KEYS)

    def _txt(p):
        return "".join(c.text or "" for c in p.iter() if _lname(c.tag) == "Content").strip()

    # The "roman stuck to title" split (e.g. "IROBINSON..." -> "I" / "ROBINSON")
    # must ONLY fire when the book genuinely numbers its chapters with leading
    # romans. A book whose chapter titles are plain WORDS that merely begin with
    # roman-numeral letters must NOT be split: "LIBRE" starts with LI (=51),
    # "INSTINTO" starts with I (=1). Counting matches alone cannot tell the two
    # apart. Real chapter numbers form an ASCENDING sequence (I, II, III, ...);
    # coincidental word prefixes are a scatter of unrelated values.
    def _rom2int(r):
        vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
        tot = 0
        prev = 0
        for ch in reversed(r):
            v = vals.get(ch, 0)
            tot += -v if v < prev else v
            prev = max(prev, v)
        return tot

    _rom_seq = []
    for p in psrs:
        if not any(k in _style_l(p) for k in _HEAD_STYLE_KEYS):
            continue
        if any(k in _style_l(p) for k in _SKIP_STYLE_KEYS):
            continue
        t = _txt(p)
        rom = None
        if LS in t:                     # already-split form "III<LS>TITLE": read the
            head0 = t.split(LS, 1)[0].strip()   # numeral BEFORE the break. (Running
            if re.fullmatch(r"[IVXLCDM]{1,4}", head0):  # _ROMAN_ATTACHED across the
                rom = head0             # break mis-parses "III" as "II"+"I...".)
        else:
            mr = _ROMAN_ATTACHED.match(t)   # unsplit form: "IIIROBINSON..." -> "III"
            if mr and mr.group(1):
                rom = mr.group(1)
        if rom:
            _rom_seq.append(_rom2int(rom))

    # A genuinely roman-numbered book numbers its chapters I, II, III, ... so its
    # leading romans contain the consecutive run 1, 2, 3. No ordinary word can
    # start with "II" or "III", so the values 2 and 3 cannot appear by accident
    # from a word prefix ("CHAPTER" -> C=100, "LIBRE" -> LI=51, "DRAMA" -> D=500,
    # "INSTINTO" -> I=1). Requiring 1-2-3 present makes a false positive
    # essentially impossible, and is robust to noise from titles that merely
    # begin with roman letters (VICTORY=5, ISLAND=1).
    _romset = set(_rom_seq)
    _run = 0
    while (_run + 1) in _romset:
        _run += 1
    _do_roman = _run >= 3

    for i, psr in enumerate(psrs):
        style = psr.attrib.get("AppliedParagraphStyle", "")
        style_l = style.lower()
        if any(k in style_l for k in _SKIP_STYLE_KEYS):   # never touch the TOC
            continue
        # A heading sitting next to a TOC entry IS a TOC section header - skip it,
        # so the Table of Contents is never modified.
        if (i + 1 < len(psrs) and _is_toc(psrs[i + 1])) or (i > 0 and _is_toc(psrs[i - 1])):
            continue
        txt = "".join(c.text or "" for c in psr.iter() if _lname(c.tag) == "Content").strip()
        if not txt or "###Insert" in txt:
            continue
        if any(_lname(e.tag) == "Rectangle" for e in psr.iter()):
            continue
        # TOC rows also look like "CHAPTER I .... 41": a trailing page number or
        # dot leaders mean it is a contents entry, not a heading -> skip.
        if re.search(r"(\.\s*){3,}", txt) or re.search(r"\s\d{1,4}\s*$", txt):
            continue
        is_head_style = any(k in style_l for k in _HEAD_STYLE_KEYS)
        if not (is_head_style or (_START_RE.match(txt) and len(txt) < 110)):
            continue
        # REPAIR a prior bad roman-shear: an earlier run split a plain word whose
        # first letters are roman ("CHAPTER"->"C"/"HAPTER", "LIBRE"->"LI"/"BRE",
        # "INSTINTO"->"I"/"NSTINTO"). When the book is NOT roman-numbered
        # (_do_roman False) and the part before the break is a BARE numeral (no
        # space), rejoin it. A genuine split ("CHAPTER I" / "M. MYRIEL") has a
        # space before the break, and a truly roman-numbered book keeps _do_roman
        # True, so both are left untouched.
        if (LS in txt) and (not _do_roman) and re.fullmatch(r"[IVXLCDM]{1,4}", txt.split(LS, 1)[0].strip()):
            txt = txt.replace(LS, "")
            if _rewrite_content(psr, txt):
                changed = True
        new = _split_heading_text(txt)
        if (not new) and is_head_style and _do_roman and (" " not in txt):
            # heading-style only, roman-numbered book only: split a roman numeral
            # stuck to the title ("IROBINSON..." -> "I" / "ROBINSON...").
            mr = _ROMAN_ATTACHED.match(txt.strip())
            if mr and mr.group(1) and mr.group(2):
                new = mr.group(1).strip() + LS + mr.group(2).strip()
        if new and new != txt and _rewrite_content(psr, new):
            changed = True
        if _ensure_trailing_br(psr):
            changed = True
        if not is_head_style and _START_RE.match(txt):
            psr.set("AppliedParagraphStyle", "ParagraphStyle/chapter_name")
            changed = True
        if psr.attrib.get("Justification") != "CenterAlign":
            psr.set("Justification", "CenterAlign")
            changed = True
        # Zero indents so BOTH lines of the split heading center cleanly
        # (a leftover FirstLineIndent/LeftIndent shifts the second line).
        for _attr in ("FirstLineIndent", "LeftIndent", "RightIndent"):
            if psr.attrib.get(_attr) not in (None, "0"):
                psr.set(_attr, "0")
                changed = True
    return changed

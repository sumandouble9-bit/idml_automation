import copy
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def lname(tag):
    return tag.rsplit("}", 1)[-1]


def _is_true_verse_txt(txt):
    """Genuine verse: 3+ line-separator lines, (almost) all short, none long.
    Prose with a single break is NOT verse and must stay justified."""
    lines = [l.strip() for l in txt.split("\u2028") if l.strip()]
    if len(lines) < 2:
        return False
    short = [l for l in lines if len(l) < 60]
    long_ = [l for l in lines if len(l) > 80]
    # Verse = every forced line is short (none fills the measure). Catches even a
    # two-line couplet; a prose paragraph with one break has a long body segment.
    return not long_ and len(short) == len(lines)


def _soft_break_would_stretch(txt):
    """True when a paragraph has a soft line break ( ) AND at least one of
    its forced lines (except the last) is short enough that justifying it would
    visibly stretch the words. A   paragraph whose every segment already
    fills the line stays justified."""
    if " " not in txt:
        return False
    segs = txt.split(" ")
    return any(len(s.strip()) < 55 for s in segs[:-1])





def _psr_lines(psr):
    """Visual lines of a paragraph, split on <Br> ELEMENTS and   chars."""
    lines, cur = [], ""
    for e in psr.iter():
        t = lname(e.tag)
        if t == "Content" and e.text:
            cur += e.text
        elif t == "Br":
            lines.append(cur); cur = ""
    if cur:
        lines.append(cur)
    out = []
    for seg in lines:
        out.extend(seg.split(" "))
    return [l.strip() for l in out if l.strip()]


def _is_verse_psr(psr):
    """Pure verse only: 2+ forced lines, every line short (<60), none long (>80).
    Kept deliberately narrow so ordinary justified body text (including a
    chapter-opening epigraph line) is never turned ragged."""
    lines = _psr_lines(psr)
    if len(lines) < 2:
        return False
    long_ = [l for l in lines if len(l) > 80]
    short = [l for l in lines if len(l) < 60]
    return not long_ and len(short) == len(lines)


_SEPARATORS = ("*", "**", "***", "* * *", "*  *  *", "* * * * *", "⁂", "---", "— —")


def _has_graphic(el):
    """True if the element contains an anchored image/page item (empty-text but not blank)."""
    for d in el.iter():
        if lname(d.tag) in ("Rectangle", "Image", "EPS", "PDF", "Polygon",
                             "Oval", "GraphicLine", "Group", "PICT", "WMF", "ImportedPage"):
            return True
    return False


_HEADING_HINTS = ("chapter_name", "after_chapter_name_heading", "sub-heading", "master_chapter")


def _prev_is_heading(psr, parent_map):
    """True if the nearest preceding non-blank paragraph is itself a heading, i.e. this
    heading is a continuation (same EPUB h1 id) that must stay on the same page."""
    parent = parent_map.get(psr)
    if parent is None:
        return False
    try:
        idx = list(parent).index(psr)
    except ValueError:
        return False
    k = idx - 1
    while k >= 0:
        prev = list(parent)[k]
        if lname(prev.tag) != "ParagraphStyleRange":
            k -= 1
            continue
        txt = "".join(c.text or "" for c in prev.iter() if lname(c.tag) == "Content").strip()
        if not txt and not _has_graphic(prev):
            k -= 1
            continue
        sty = (prev.get("AppliedParagraphStyle") or "").lower()
        return any(h in sty for h in _HEADING_HINTS)
    return False


def _is_first_chapter_heading(psr, parent_map):
    """True if this chapter heading is Chapter 1 (the initial content chapter),
    meaning no body text has appeared after the front matter/TOC before this heading."""
    parent = parent_map.get(psr) if parent_map else None
    if parent is None:
        return False
    try:
        idx = list(parent).index(psr)
    except ValueError:
        return False
    k = idx - 1
    while k >= 0:
        prev = list(parent)[k]
        k -= 1
        if lname(prev.tag) != "ParagraphStyleRange":
            continue
        if _is_blank_page_spacer(prev):
            continue
        txt = "".join(c.text or "" for c in prev.iter() if lname(c.tag) == "Content").strip()
        if not txt and not _has_graphic(prev):
            continue
        sty = (prev.get("AppliedParagraphStyle") or "").lower()
        if any(h in sty for h in _HEADING_HINTS) or "chapter" in sty:
            continue
        if any(t in sty for t in ("toc", "content", "about", "author")):
            return True
        if "body" in sty or "quote" in sty or len(txt) > 40:
            return False
    return True


def _has_preceding_page_spacer(psr, parent_map):
    """True if this heading is preceded by an intentional page spacer (e.g. BlankPageSpacer with NextPage / \u2028)."""
    parent = parent_map.get(psr) if parent_map else None
    if parent is None:
        return False
    try:
        idx = list(parent).index(psr)
    except ValueError:
        return False
    k = idx - 1
    while k >= 0:
        prev = list(parent)[k]
        if lname(prev.tag) != "ParagraphStyleRange":
            k -= 1
            continue
        if _is_blank_page_spacer(prev):
            return True
        txt = "".join(c.text or "" for c in prev.iter() if lname(c.tag) == "Content").strip()
        if txt or _has_graphic(prev):
            return False
        k -= 1
    return False


def _ensure_csr_font(csr, font_name="Palatino Linotype", point_size="9.65", leading="12"):
    """Sets font family, point size, and leading on a CharacterStyleRange."""
    csr.set("PointSize", str(point_size))
    props = next((c for c in csr if lname(c.tag) == "Properties"), None)
    if props is None:
        props = ET.Element(csr.tag.replace("CharacterStyleRange", "Properties"))
        csr.insert(0, props)
    af = next((c for c in props if lname(c.tag) == "AppliedFont"), None)
    if af is None:
        af = ET.Element(props.tag.replace("Properties", "AppliedFont"), {"type": "string"})
        props.append(af)
    af.text = font_name
    ld = next((c for c in props if lname(c.tag) == "Leading"), None)
    if ld is None:
        ld = ET.Element(props.tag.replace("Properties", "Leading"), {"type": "unit"})
        props.append(ld)
    ld.text = str(leading)


def _ensure_pstyle_font(ps, font_name="Palatino Linotype", point_size="9.65", leading="12"):
    """Sets font family, point size, and leading on a ParagraphStyle definition in Styles.xml."""
    ps.set("PointSize", str(point_size))
    props = next((c for c in ps if lname(c.tag) == "Properties"), None)
    if props is None:
        props = ET.Element(ps.tag.replace("ParagraphStyle", "Properties"))
        ps.insert(0, props)
    af = next((c for c in props if lname(c.tag) == "AppliedFont"), None)
    if af is None:
        af = ET.Element(props.tag.replace("Properties", "AppliedFont"), {"type": "string"})
        props.append(af)
    af.text = font_name
    ld = next((c for c in props if lname(c.tag) == "Leading"), None)
    if ld is None:
        ld = ET.Element(props.tag.replace("Properties", "Leading"), {"type": "unit"})
        props.append(ld)
    ld.text = str(leading)


CHAP_KW_PATTERN = re.compile(
    r"\b(?:chapter|book|part|act|scene|section|cap[íi]tulo|parte|libro|acto|secci[óo]n|"
    r"index|[íi]ndice|indice|preface|prefacio|foreword|prologue|pr[óo]logo|introduction|introducci[óo]n|"
    r"conclusion|conclusi[óo]n|epilogue|ep[íi]logo|appendix|ap[ée]ndice|glossary|glosario|"
    r"bibliography|bibliograf[íi]a|notes?|notas?|advertisement|notice|dedication)\b",
    re.I,
)


def _is_blank_page_spacer(elem):
    """Detects intentional blank-page spacers (e.g. after TOC on p4, after About Author on p6)."""
    if elem is None:
        return False
    for k in ("BlankPageSpacer", "BlankPageProtected"):
        if elem.attrib.get(k) == "true":
            return True
    pbt = elem.attrib.get("ParagraphBreakType", "")
    sp = elem.attrib.get("StartParagraph", "")
    pts = elem.attrib.get("PointSize", "")
    ld = elem.attrib.get("Leading", "")
    txt = "".join(c.text or "" for c in elem.iter() if lname(c.tag) == "Content").strip()
    if not txt and (pbt == "NextPage" or sp == "NextPage") and (pts == "0.1" or ld == "0.1"):
        return True
    for c in elem.iter():
        if any(c.attrib.get(k) == "true" for k in ("BlankPageSpacer", "BlankPageProtected")):
            return True
        c_pbt = c.attrib.get("ParagraphBreakType", "")
        c_sp = c.attrib.get("StartParagraph", "")
        c_pts = c.attrib.get("PointSize", "")
        c_ld = c.attrib.get("Leading", "")
        if (c_pbt == "NextPage" or c_sp == "NextPage") and (c_pts == "0.1" or c_ld == "0.1"):
            return True
    return False


def _split_grouped_chapters(story_root):
    """Splits multiple chapter headings combined into a single ParagraphStyleRange
    into separate ParagraphStyleRange elements, each with StartParagraph='NextPage'."""
    changed = False
    parent_map = {}
    for p in story_root.iter():
        for ch in p:
            parent_map[ch] = p

    for psr in list(story_root.iter()):
        if lname(psr.tag) != "ParagraphStyleRange":
            continue
        style = psr.attrib.get("AppliedParagraphStyle", "")
        if "chapter" not in style.lower():
            continue

        parent = parent_map.get(psr)
        if parent is None:
            continue

        all_children = list(psr)
        segments = []
        cur_segment = []
        for csr in all_children:
            if lname(csr.tag) != "CharacterStyleRange":
                cur_segment.append(csr)
                continue
            csr_children = list(csr)
            cur_csr_children = []
            for child in csr_children:
                cur_csr_children.append(child)
                if lname(child.tag) == "Br":
                    new_csr = copy.deepcopy(csr)
                    for c in list(new_csr):
                        new_csr.remove(c)
                    for c in cur_csr_children:
                        new_csr.append(c)
                    cur_segment.append(new_csr)
                    segments.append(cur_segment)
                    cur_segment = []
                    cur_csr_children = []
            if cur_csr_children:
                new_csr = copy.deepcopy(csr)
                for c in list(new_csr):
                    new_csr.remove(c)
                for c in cur_csr_children:
                    new_csr.append(c)
                cur_segment.append(new_csr)
        if cur_segment:
            segments.append(cur_segment)

        non_empty_segments = []
        for seg in segments:
            seg_txt = "".join(
                c.text or ""
                for elem in seg
                for c in elem.iter()
                if lname(c.tag) == "Content"
            ).strip()
            if seg_txt:
                non_empty_segments.append((seg, seg_txt))

        if len(non_empty_segments) > 1:
            try:
                idx = list(parent).index(psr)
                parent.remove(psr)
                for i, (seg, seg_txt) in enumerate(non_empty_segments):
                    new_psr = copy.deepcopy(psr)
                    for c in list(new_psr):
                        new_psr.remove(c)

                    # Any segment after the first in a run-on heading introduces the same chapter
                    # and must remain on the SAME page below the first heading
                    is_paired = (i > 0)

                    if is_paired:
                        new_psr.set("AppliedParagraphStyle", "ParagraphStyle/after_chapter_name_heading")
                        if "StartParagraph" in new_psr.attrib:
                            del new_psr.attrib["StartParagraph"]
                        if "ParagraphBreakType" in new_psr.attrib:
                            del new_psr.attrib["ParagraphBreakType"]
                        new_psr.set("StartParagraph", "Anywhere")
                        new_psr.set("ParagraphBreakType", "Anywhere")
                        new_psr.set("SpaceBefore", "14")
                        new_psr.set("SpaceAfter", "30")
                    else:
                        is_part = bool(re.match(r"^(?:parte|part|libro|book)\b", seg_txt, re.I))
                        st_name = "ParagraphStyle/Sub-heading" if is_part else "ParagraphStyle/chapter_name"
                        new_psr.set("AppliedParagraphStyle", st_name)
                        new_psr.set("StartParagraph", "NextPage")
                        new_psr.set("SpaceBefore", "3")
                        new_psr.set("SpaceAfter", "14" if is_part else "30")

                    new_psr.set("KeepAllLinesTogether", "true")
                    new_psr.set("KeepLinesTogether", "true")
                    new_psr.set("KeepWithNext", "2")
                    new_psr.set("Justification", "CenterAlign")
                    new_psr.set("FirstLineIndent", "0")
                    for elem in seg:
                        new_psr.append(elem)
                    last_csr = next((c for c in reversed(list(new_psr)) if lname(c.tag) == "CharacterStyleRange"), None)
                    if last_csr is not None and not any(lname(c.tag) == "Br" for c in last_csr):
                        ET.SubElement(last_csr, "Br")
                    parent.insert(idx, new_psr)
                    idx += 1
                changed = True
            except ValueError:
                pass
    return changed


__all__ = [
    'lname',
    '_is_true_verse_txt',
    '_soft_break_would_stretch',
    '_psr_lines',
    '_is_verse_psr',
    '_has_graphic',
    '_prev_is_heading',
    '_is_first_chapter_heading',
    '_has_preceding_page_spacer',
    '_ensure_csr_font',
    '_ensure_pstyle_font',
    '_is_blank_page_spacer',
    '_split_grouped_chapters',
    '_SEPARATORS',
    '_HEADING_HINTS',
    'CHAP_KW_PATTERN',
]

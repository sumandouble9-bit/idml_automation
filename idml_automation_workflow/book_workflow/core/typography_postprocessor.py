"""
Typography Post-Processor for IDML Automation Workflow:
Ensures 100% uniform typography across all IDML files and stages:
1. Enforces Palatino Linotype 9.65pt (12pt leading) on body text and all fallback/default styles:
   - ParagraphStyle/body_text
   - ParagraphStyle/Normal
   - ParagraphStyle/$ID/[Basic Paragraph]
   - ParagraphStyle/$ID/NormalParagraphStyle
   - ParagraphStyle/$ID/[Normal Paragraph Style]
2. Restores any body story paragraphs that were reset to 'Normal' (e.g. during image injection)
   back to 'ParagraphStyle/body_text' with Palatino Linotype 9.65pt.
3. Enforces clean running footer formatting with en-space pipe separator (\u2002|\u2002) so page numbers
   and book titles never collide (e.g. '41Following the Equator' -> '41 | Following the Equator').
4. Ensures Resources/Styles.xml and Resources/Fonts.xml contain canonical definitions.
"""

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

                    # Check if this segment should be paired on the SAME page as preceding heading
                    is_paired = False
                    if i > 0:
                        prev_seg_txt = non_empty_segments[i - 1][1]
                        is_prev_part = bool(re.match(r"^(?:parte|part|libro|book)\b", prev_seg_txt, re.I))
                        is_curr_chap = bool(re.match(r"^(?:cap[íi]tulo|chapter)\b", seg_txt, re.I))
                        is_prev_chap = bool(re.match(r"^(?:cap[íi]tulo|chapter)\b", prev_seg_txt, re.I))
                        if is_prev_part and is_curr_chap:
                            is_paired = True
                        elif is_prev_chap and not is_curr_chap and not is_prev_part:
                            is_paired = True

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


def postprocess_idml(idml_path: Path) -> dict:
    """Post-processes an IDML package to ensure typography and footer consistency."""
    idml_path = Path(idml_path)
    if not idml_path.exists():
        return {"status": "error", "error": f"File not found: {idml_path}"}

    stats = {
        "styles_updated": 0,
        "body_paras_restored": 0,
        "footers_repaired": 0,
    }

    with tempfile.TemporaryDirectory(prefix="idml_typo_") as tmp_dir:
        tmp_dir = Path(tmp_dir)

        with zipfile.ZipFile(idml_path, "r") as z:
            z.extractall(tmp_dir)

        # -------------------------------------------------------------
        # 1. Enforce canonical fonts in Resources/Styles.xml
        # -------------------------------------------------------------
        styles_xml = tmp_dir / "Resources" / "Styles.xml"
        if styles_xml.exists():
            sroot = ET.parse(styles_xml).getroot()
            for ps in sroot.iter():
                if lname(ps.tag) == "ParagraphStyle":
                    sid = ps.attrib.get("Self", "")
                    if sid in (
                        "ParagraphStyle/body_text",
                        "ParagraphStyle/Normal",
                        "ParagraphStyle/$ID/[Basic Paragraph]",
                        "ParagraphStyle/$ID/NormalParagraphStyle",
                        "ParagraphStyle/$ID/[Normal Paragraph Style]",
                        "ParagraphStyle/Normal (Web)",
                        "ParagraphStyle/noindent",
                        "ParagraphStyle/noindentj",
                        "ParagraphStyle/noindent1",
                        "ParagraphStyle/bodytext_noendent",
                        "ParagraphStyle/bodytext_Noendent",
                        "ParagraphStyle/copybody",
                        "ParagraphStyle/centre_align",
                        "ParagraphStyle/center",
                        "ParagraphStyle/center1",
                    ) or (
                        any(k in sid.lower() for k in ["body", "normal", "basic", "noindent"])
                        and not any(k in sid.lower() for k in [
                            "quote", "chapter", "sub-heading", "heading", "toc", "author", "title", "caption", "copy"
                        ])
                    ):
                        _ensure_pstyle_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                        ps.set("KeepLinesTogether", "true")
                        ps.set("KeepFirstAndLastLines", "true")
                        ps.set("MinLinesAtStart", "2")
                        ps.set("MinLinesAtEnd", "2")
                        if sid in ("ParagraphStyle/body_text", "ParagraphStyle/Normal"):
                            ps.set("Justification", "LeftJustified")
                            ps.set("FirstLineIndent", "18")
                            ps.set("SpaceBefore", "1.5")
                            ps.set("SpaceAfter", "3")
                            ps.set("MinimumWordSpacing", "80")
                            ps.set("DesiredWordSpacing", "100")
                            ps.set("MaximumWordSpacing", "120")
                            ps.set("MinimumLetterSpacing", "0")
                            ps.set("DesiredLetterSpacing", "0")
                            ps.set("MaximumLetterSpacing", "0")
                            ps.set("Hyphenation", "true")
                        stats["styles_updated"] += 1
                    elif sid == "ParagraphStyle/fig caption":
                        _ensure_pstyle_font(ps, "Palatino Linotype", point_size="9", leading="11")
                        ps.set("Justification", "CenterAlign")
                        stats["styles_updated"] += 1
                    elif sid == "ParagraphStyle/chapter_name":
                        _ensure_pstyle_font(ps, "Gill Sans MT", point_size="16", leading="20")
                        ps.set("Hyphenation", "false")
                        ps.set("FontStyle", "Bold")
                        ps.set("Justification", "CenterAlign")
                        ps.set("StartParagraph", "NextPage")
                        ps.set("KeepAllLinesTogether", "true")
                        ps.set("KeepLinesTogether", "true")
                        ps.set("KeepWithNext", "2")
                        ps.set("RuleAbove", "true")
                        ps.set("RuleAboveLineWeight", "0")
                        ps.set("RuleAboveOffset", "14.5")
                        ps.set("KeepRuleAboveInFrame", "true")
                        props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                        if props is not None:
                            rac = next((c for c in props if lname(c.tag) == "RuleAboveColor"), None)
                            if rac is None:
                                rac = ET.SubElement(props, ps.tag.replace("ParagraphStyle", "RuleAboveColor"), {"type": "string"})
                                rac.text = "Text Color"
                    elif sid == "ParagraphStyle/after_chapter_name_heading":
                        _ensure_pstyle_font(ps, "Gill Sans MT", point_size="16", leading="20")
                        ps.set("FontStyle", "Bold")
                        ps.set("Justification", "CenterAlign")
                        ps.set("StartParagraph", "Anywhere")
                        ps.set("ParagraphBreakType", "Anywhere")
                        ps.set("FirstLineIndent", "0")
                        ps.set("SpaceBefore", "14")
                        ps.set("SpaceAfter", "30")
                        ps.set("KeepWithNext", "2")
                        ps.set("KeepAllLinesTogether", "true")
                        ps.set("KeepLinesTogether", "true")
                    elif sid == "ParagraphStyle/Sub-heading":
                        _ensure_pstyle_font(ps, "Gill Sans MT", point_size="14", leading="18")
                        ps.set("Hyphenation", "false")
                        ps.set("FontStyle", "Bold")
                        ps.set("Justification", "CenterAlign")
                        ps.set("SpaceBefore", "18")
                        ps.set("SpaceAfter", "12")
                        ps.set("KeepWithNext", "2")
                        ps.set("KeepLinesTogether", "true")
                        if "ParagraphBreakType" in ps.attrib:
                            del ps.attrib["ParagraphBreakType"]
                    elif sid == "ParagraphStyle/quotes_normal":
                        _ensure_pstyle_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                        ps.set("Justification", "LeftAlign")
                        ps.set("KeepLinesTogether", "true")
                        ps.set("KeepFirstAndLastLines", "true")
                        ps.set("MinLinesAtStart", "2")
                        ps.set("MinLinesAtEnd", "2")

                elif lname(ps.tag) == "CharacterStyle":
                    sid = ps.attrib.get("Self", "")
                    props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                    if sid == "CharacterStyle/boldtext":
                        ps.set("FontStyle", "Bold")
                        if "PointSize" in ps.attrib:
                            del ps.attrib["PointSize"]
                        if props is not None:
                            for af in list(props):
                                if lname(af.tag) == "AppliedFont":
                                    props.remove(af)
                    elif sid in ("CharacterStyle/italicalign", "CharacterStyle/italic"):
                        ps.set("FontStyle", "Italic")
                        if "PointSize" in ps.attrib:
                            del ps.attrib["PointSize"]
                        if props is not None:
                            for af in list(props):
                                if lname(af.tag) == "AppliedFont":
                                    props.remove(af)
                    elif sid == "CharacterStyle/underlinalign":
                        ps.set("Underline", "true")
                        if "PointSize" in ps.attrib:
                            del ps.attrib["PointSize"]
                        if props is not None:
                            for af in list(props):
                                if lname(af.tag) == "AppliedFont":
                                    props.remove(af)
                    elif sid == "CharacterStyle/dropcap":
                        ps.set("PointSize", "9.65")
                        if props is not None:
                            for af in list(props):
                                if lname(af.tag) == "AppliedFont":
                                    af.text = "Palatino Linotype"
            ET.ElementTree(sroot).write(styles_xml, encoding="utf-8", xml_declaration=True)

        pref_xml = tmp_dir / "Resources" / "Preferences.xml"
        if pref_xml.exists():
            proot = ET.parse(pref_xml).getroot()
            pref_changed = False
            for td in proot.iter():
                if lname(td.tag) == "TextDefault":
                    td.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                    td.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                    if "FontStyle" in td.attrib:
                        td.set("FontStyle", "Regular")
                    if "PointSize" in td.attrib:
                        td.set("PointSize", "9.65")
                    if "RuleBelow" in td.attrib:
                        td.set("RuleBelow", "false")
                    pref_changed = True
            if pref_changed:
                ET.ElementTree(proot).write(pref_xml, encoding="utf-8", xml_declaration=True)

        # -------------------------------------------------------------
        # 2. Check and repair Stories
        # -------------------------------------------------------------
        stories_dir = tmp_dir / "Stories"
        toc_norms = set()
        if stories_dir.is_dir():
            for sf in stories_dir.glob("*.xml"):
                try:
                    r = ET.parse(sf).getroot()
                except Exception:
                    continue
                for psr in r.iter():
                    if lname(psr.tag) == "ParagraphStyleRange":
                        st = psr.attrib.get("AppliedParagraphStyle", "")
                        if any(k in st.lower() for k in ["toc", "content_ch", "tochead", "tocch"]):
                            hl = [h for h in psr.iter() if lname(h.tag) == "HyperlinkTextSource"]
                            if hl:
                                for h in hl:
                                    t = "".join(c.text or "" for c in h.iter() if lname(c.tag) == "Content").strip()
                                    if t:
                                        for part in re.split(r"\t\d*", t):
                                            part = part.strip()
                                            if part:
                                                s = re.sub(r"[\r\n\u2028]+", " ", part)
                                                s = re.sub(r"[^\w\s]", "", s.lower())
                                                s = re.sub(r"\s+", " ", s).strip()
                                                if s and not any(k in s for k in ["table of contents", "contents", "double 9 books"]):
                                                    toc_norms.add(s)
                            else:
                                txt = "".join(c.text or "" for c in psr.iter() if lname(c.tag) == "Content").strip()
                                if txt:
                                    for line in re.split(r"[\r\n\u2028]+", txt):
                                        line = line.strip()
                                        if line:
                                            for part in re.split(r"\t\d*", line):
                                                part = part.strip()
                                                if part:
                                                    s = re.sub(r"[\r\n\u2028]+", " ", part)
                                                    s = re.sub(r"[^\w\s]", "", s.lower())
                                                    s = re.sub(r"\s+", " ", s).strip()
                                                    if s and not any(k in s for k in ["table of contents", "contents", "double 9 books"]):
                                                         toc_norms.add(s)
            toc_clean_norms = {re.sub(r"[\s\.\-_]+", "", t) for t in toc_norms}

        if stories_dir.is_dir():
            for sf in stories_dir.glob("*.xml"):
                raw_text = sf.read_text(encoding="utf-8")
                # Handle MasterSpread footers via raw string to preserve <?ACE 18?> ProcessingInstruction
                if "<?ACE 18?>" in raw_text and "<TextVariableInstance" in raw_text:
                    if "\u2002|\u2002" not in raw_text and "\u2003" not in raw_text and " | " not in raw_text:
                        sep = '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]"><Properties><Leading type="enumeration">Auto</Leading><AppliedFont type="string">Bell MT</AppliedFont></Properties><Content>\u2002|\u2002</Content></CharacterStyleRange>'
                        if raw_text.find("<?ACE 18?>") < raw_text.find("<TextVariableInstance"):
                            # Verso: Page Number then Title -> insert separator after Page Number CSR
                            idx = raw_text.find("<?ACE 18?></Content>")
                            if idx != -1:
                                end_csr = raw_text.find("</CharacterStyleRange>", idx)
                                if end_csr != -1:
                                    end_pos = end_csr + len("</CharacterStyleRange>")
                                    raw_text = raw_text[:end_pos] + "\n\t\t\t" + sep + raw_text[end_pos:]
                                    sf.write_text(raw_text, encoding="utf-8")
                                    stats["footers_repaired"] += 1
                        else:
                            # Recto: Title then Page Number -> insert separator after Title CSR
                            idx = raw_text.find("<TextVariableInstance")
                            if idx != -1:
                                end_csr = raw_text.find("</CharacterStyleRange>", idx)
                                if end_csr != -1:
                                    end_pos = end_csr + len("</CharacterStyleRange>")
                                    raw_text = raw_text[:end_pos] + "\n\t\t\t" + sep + raw_text[end_pos:]
                                    sf.write_text(raw_text, encoding="utf-8")
                                    stats["footers_repaired"] += 1
                    continue

                try:
                    sroot = ET.parse(sf).getroot()
                except Exception:
                    continue

                story_changed = False
                try:
                    from core.chapter_heading_format import normalize_headings as _norm_head
                except Exception:
                    try:
                        from chapter_heading_format import normalize_headings as _norm_head
                    except Exception:
                        _norm_head = None
                if _norm_head is not None and _norm_head(sroot):
                    story_changed = True
                try:
                    from core.caption_dedup import dedup_captions as _dedup_caps
                except Exception:
                    try:
                        from caption_dedup import dedup_captions as _dedup_caps
                    except Exception:
                        _dedup_caps = None
                if _dedup_caps is not None and _dedup_caps(sroot):
                    story_changed = True
                if _split_grouped_chapters(sroot):
                    story_changed = True
                try:
                    from core.split_compound_verse_prose import split_compound_verse_and_prose as _scvp
                except Exception:
                    try:
                        from split_compound_verse_prose import split_compound_verse_and_prose as _scvp
                    except Exception:
                        _scvp = None
                if _scvp is not None and _scvp(sroot):
                    story_changed = True

                parent_map = {}
                for p in sroot.iter():
                    for child in p:
                        parent_map[child] = p

                for psr in sroot.iter():
                    if lname(psr.tag) != "ParagraphStyleRange":
                        continue

                    style = psr.attrib.get("AppliedParagraphStyle", "")
                    txt = "".join(c.text or "" for c in psr.iter() if lname(c.tag) == "Content").strip()
                    rects = [e for e in psr.iter() if lname(e.tag) == "Rectangle"]
                    has_soft_break = "\u2028" in txt

                    # If this is a placeholder paragraph: ensure exactly one closing Br and Normal style
                    if "###Insert" in txt:
                        if "ParagraphBreakType" in psr.attrib:
                            del psr.attrib["ParagraphBreakType"]
                            story_changed = True
                        if "StartParagraph" in psr.attrib:
                            del psr.attrib["StartParagraph"]
                            story_changed = True
                        psr.set("AppliedParagraphStyle", "ParagraphStyle/Normal")
                        psr.set("Justification", "CenterAlign")
                        for csr in psr.iter():
                            if lname(csr.tag) == "CharacterStyleRange":
                                for br in list(csr):
                                    if lname(br.tag) == "Br":
                                        csr.remove(br)
                                        story_changed = True
                        last_csr = list(psr)[-1] if list(psr) else None
                        if last_csr is not None and not any(lname(c.tag) == "Br" for c in psr.iter()):
                            ET.SubElement(last_csr, "Br")
                            story_changed = True
                        continue

                    # A. Ensure captions use correct font
                    if "caption" in style.lower():
                        for csr in psr.iter():
                            if lname(csr.tag) == "CharacterStyleRange":
                                for p in csr:
                                    if lname(p.tag) == "Properties":
                                        for af in p:
                                            if lname(af.tag) == "AppliedFont":
                                                af.text = "Palatino Linotype"
                                                story_changed = True
                        continue

                    # A2. Subheading page-break cleanup (Keep on SAME PAGE as chapter text)
                    if "sub-heading" in style.lower() or style == "ParagraphStyle/Sub-heading":
                        norm_txt = re.sub(r"[^\w\s]", "", txt.lower())
                        norm_txt = re.sub(r"\s+", " ", norm_txt).strip()
                        is_in_toc = (norm_txt in toc_norms) or any(norm_txt.startswith(t) for t in toc_norms if len(t) > 6 and len(norm_txt) > 6)
                        if is_in_toc:
                            continue

                        if "ParagraphBreakType" in psr.attrib:
                            del psr.attrib["ParagraphBreakType"]
                            story_changed = True
                        for c in psr.iter():
                            if "ParagraphBreakType" in c.attrib:
                                del c.attrib["ParagraphBreakType"]
                                story_changed = True
                        psr.set("SpaceBefore", "18")
                        psr.set("SpaceAfter", "12")
                        psr.set("KeepWithNext", "2")
                        psr.set("KeepLinesTogether", "true")
                        parent = parent_map.get(psr)
                        if parent is not None:
                            try:
                                idx = list(parent).index(psr)
                                while idx > 0:
                                    prev_child = list(parent)[idx - 1]
                                    if lname(prev_child.tag) == "ParagraphStyleRange":
                                        if _is_blank_page_spacer(prev_child):
                                            break
                                        has_nb = any(c.attrib.get("ParagraphBreakType") == "NextPage" for c in prev_child.iter())
                                        prev_txt = "".join(c.text or "" for c in prev_child.iter() if lname(c.tag) == "Content").strip()
                                        if has_nb and not prev_txt and not _has_graphic(prev_child):
                                            parent.remove(prev_child)
                                            idx -= 1
                                            story_changed = True
                                        else:
                                            break
                                    else:
                                        break
                            except ValueError:
                                pass
                        for csr in psr.iter():
                            if lname(csr.tag) == "CharacterStyleRange":
                                _ensure_csr_font(csr, "Gill Sans MT", point_size="14", leading="18")
                                csr.set("FontStyle", "Bold")
                                story_changed = True
                        continue

                    # A3. Chapter heading blank page cleanup (eliminate blank pages between chapters)
                    if "chapter_name" in style.lower():
                        parent = parent_map.get(psr)
                        if parent is not None:
                            try:
                                idx = list(parent).index(psr)
                                while idx > 0:
                                    prev_child = list(parent)[idx - 1]
                                    if lname(prev_child.tag) == "ParagraphStyleRange":
                                        if _is_blank_page_spacer(prev_child):
                                            break
                                        prev_txt = "".join(c.text or "" for c in prev_child.iter() if lname(c.tag) == "Content").replace("\u2028", "").replace("\ufeff", "").strip()
                                        if not prev_txt and not _has_graphic(prev_child):
                                            parent.remove(prev_child)
                                            idx -= 1
                                            story_changed = True
                                        else:
                                            break
                                    else:
                                        break
                                if idx > 0:
                                    prev_child = list(parent)[idx - 1]
                                    if not _is_blank_page_spacer(prev_child):
                                        if prev_child.attrib.get("ParagraphBreakType") == "NextPage":
                                            del prev_child.attrib["ParagraphBreakType"]
                                            story_changed = True
                                        for c in prev_child.iter():
                                            if c.attrib.get("ParagraphBreakType") == "NextPage":
                                                del c.attrib["ParagraphBreakType"]
                                                story_changed = True
                            except ValueError:
                                pass

                    # Check if paragraph was mistakenly styled as chapter_name / chapter_name01
                    if any(k in style.lower() for k in ["chapter", "sub-heading"]):
                        norm_t = re.sub(r"[^\w\s]", "", txt.lower()).strip()
                        norm_clean = re.sub(r"[\s\.\-_]+", "", norm_t)
                        has_chap_kw = bool(CHAP_KW_PATTERN.search(txt)) or bool(re.match(r"^(?:[IVXLCDM]+\b|\d+\b)\.?\s*", txt.strip(), re.I))
                        is_known_heading = has_chap_kw or (norm_clean in toc_clean_norms) or (norm_t in toc_norms)

                        if not is_known_heading and (len(txt) > 150 or (len(txt) > 60 and "." in txt and not any(k in txt.lower() for k in ["part", "book", "chap", "vol"]))):
                            psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                            psr.set("Justification", "LeftAlign" if _is_true_verse_txt(txt) else "LeftJustified")
                            psr.set("FirstLineIndent", "18")
                            psr.set("SpaceBefore", "1.5")
                            psr.set("SpaceAfter", "3")
                            psr.set("KeepLinesTogether", "true")
                            psr.set("KeepFirstAndLastLines", "true")
                            psr.set("MinLinesAtStart", "2")
                            psr.set("MinLinesAtEnd", "2")
                            if "StartParagraph" in psr.attrib:
                                del psr.attrib["StartParagraph"]
                            if "ParagraphBreakType" in psr.attrib:
                                del psr.attrib["ParagraphBreakType"]
                            style = "ParagraphStyle/body_text"
                            stats["body_paras_restored"] += 1
                            story_changed = True
                        elif "chapter" in style.lower() and "after" not in style.lower():
                            psr.set("KeepAllLinesTogether", "true")
                            psr.set("KeepLinesTogether", "true")
                            psr.set("KeepWithNext", "2")
                            psr.set("Justification", "CenterAlign")
                            psr.set("FirstLineIndent", "0")
                        elif "after" in style.lower():
                            if "StartParagraph" in psr.attrib:
                                del psr.attrib["StartParagraph"]
                            if "ParagraphBreakType" in psr.attrib:
                                del psr.attrib["ParagraphBreakType"]
                            psr.set("StartParagraph", "Anywhere")
                            psr.set("ParagraphBreakType", "Anywhere")
                            psr.set("KeepAllLinesTogether", "true")
                            psr.set("KeepLinesTogether", "true")
                            psr.set("KeepWithNext", "2")
                            psr.set("Justification", "CenterAlign")
                            psr.set("FirstLineIndent", "0")
                        elif "sub-heading" in style.lower():
                            psr.set("KeepWithNext", "2")
                            psr.set("KeepLinesTogether", "true")
                            psr.set("Justification", "CenterAlign")
                            psr.set("FirstLineIndent", "0")

                    if style in ("ParagraphStyle/chapter_name", "ParagraphStyle/chapter_name01"):
                        parent = parent_map.get(psr)
                        _prev_prot = False
                        if parent is not None:
                            _kids = list(parent)
                            if psr in _kids:
                                _ix = _kids.index(psr)
                                if _ix > 0 and _kids[_ix - 1].attrib.get("BlankPageProtected") == "true":
                                    _prev_prot = True
                        if _is_first_chapter_heading(psr, parent_map):
                            psr.set("StartParagraph", "Anywhere")
                            psr.set("SpaceBefore", "14.5")
                            psr.set("SpaceAfter", "30")
                            story_changed = True
                        elif _has_preceding_page_spacer(psr, parent_map):
                            psr.set("StartParagraph", "Anywhere")
                            psr.set("SpaceBefore", "14.5")
                            psr.set("SpaceAfter", "30")
                            story_changed = True
                        elif _prev_prot:
                            if psr.attrib.get("StartParagraph") != "Anywhere":
                                psr.set("StartParagraph", "Anywhere")
                                story_changed = True
                        elif psr.attrib.get("StartParagraph") != "NextPage" and not _prev_is_heading(psr, parent_map):
                            psr.set("StartParagraph", "NextPage")
                            story_changed = True
                        else:
                            psr.set("StartParagraph", "Anywhere")
                            story_changed = True

                    # B. Standardize all body paragraphs
                    is_body_like = (
                        style in (
                            "ParagraphStyle/body_text",
                            "ParagraphStyle/Normal",
                            "ParagraphStyle/$ID/[Basic Paragraph]",
                            "ParagraphStyle/noindent",
                            "ParagraphStyle/noindentj",
                            "ParagraphStyle/noindent1",
                            "ParagraphStyle/bodytext_noendent",
                            "ParagraphStyle/bodytext_Noendent",
                            "ParagraphStyle/copybody",
                            "ParagraphStyle/centre_align",
                            "ParagraphStyle/center",
                            "ParagraphStyle/center1",
                        )
                        or any(k in style.lower() for k in ["body", "normal", "basic", "noindent"])
                    )
                    is_heading_or_front = any(k in style.lower() for k in [
                        "chapter", "sub-heading", "heading", "toc", "author", "title", "caption", "copyright", "verso", "doublenine", "about_the_auther"
                    ]) or any(k in txt.lower() for k in [
                        "double 9 books", "all rights reserved", "isbn", "published by", "about the author"
                    ])

                    if is_body_like and not is_heading_or_front and txt and not rects and txt != "\u2028" and "\ufeff" not in txt:
                        if style in ("ParagraphStyle/Normal", "ParagraphStyle/$ID/[Basic Paragraph]", "ParagraphStyle/copybody"):
                            psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                            psr.set("Justification", "LeftAlign" if _is_true_verse_txt(txt) else "LeftJustified")
                            psr.set("FirstLineIndent", "18")
                            psr.set("SpaceBefore", "1.5")
                            psr.set("SpaceAfter", "3")
                            stats["body_paras_restored"] += 1

                        _sl = style.lower()
                        _cur_just = psr.attrib.get("Justification")
                        if txt.strip() in _SEPARATORS:
                            # Stanza / section separators ("*", "* * *") are centered.
                            if _cur_just != "CenterAlign":
                                psr.set("Justification", "CenterAlign")
                                story_changed = True
                        elif any(_k in _sl for _k in ("quote", "verse", "block", "poem", "epigraph")):
                            # Block / quote / verse styles are ALWAYS ragged-left (quotes_normal
                            # contains "normal", so it would otherwise be justified).
                            if _cur_just not in ("CenterAlign", "RightAlign"):
                                psr.set("Justification", "LeftAlign")
                                story_changed = True
                        elif _is_verse_psr(psr) or _soft_break_would_stretch(txt):
                            # Verse, or any paragraph holding a soft line break ( ):
                            # these stretch badly when justified (unlike <Br> paragraph
                            # breaks). Keep centered if already centered, else ragged-left.
                            if _cur_just not in ("CenterAlign", "RightAlign"):
                                psr.set("Justification", "LeftAlign")
                                story_changed = True
                        elif "cent" not in _sl and _cur_just not in ("CenterAlign", "RightAlign"):
                            psr.set("Justification", "LeftJustified")
                            story_changed = True
                        psr.set("KeepLinesTogether", "true")
                        psr.set("KeepFirstAndLastLines", "true")
                        psr.set("MinLinesAtStart", "2")
                        psr.set("MinLinesAtEnd", "2")
                        if "PointSize" in psr.attrib:
                            del psr.attrib["PointSize"]
                        if "Leading" in psr.attrib:
                            del psr.attrib["Leading"]

                        for csr in psr.iter():
                            if lname(csr.tag) == "CharacterStyleRange":
                                cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                                is_bold = "bold" in cstyle.lower()
                                is_italic = "italic" in cstyle.lower()
                                if not is_bold and not is_italic:
                                    csr.set("FontStyle", "Regular")

                                # Clean runaway Subscript / Superscript overrides
                                pos = csr.attrib.get("Position", "")
                                if pos in ("Subscript", "Superscript"):
                                    raw_text = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")
                                    c_txt = raw_text.strip()
                                    is_runaway = False
                                    if not c_txt:
                                        is_runaway = True
                                    elif pos == "Superscript":
                                        is_note = bool(re.match(r"^\[?\d{1,5}[a-z]?\]?$", c_txt)) or c_txt.lower() in ("*", "†", "‡", "§", "#", "st", "nd", "rd", "th", "d", "e", "er", "re", "°")
                                        if not is_note:
                                            is_runaway = True
                                    elif pos == "Subscript":
                                        is_sub = bool(re.match(r"^\d{1,3}$", c_txt)) or c_txt.lower() in ("ab", "x1", "x2", "t1", "t2")
                                        if not is_sub:
                                            is_runaway = True

                                    if is_runaway:
                                        del csr.attrib["Position"]
                                        pos = ""
                                        stats["runaway_sub_sup_cleaned"] = stats.get("runaway_sub_sup_cleaned", 0) + 1
                                        story_changed = True

                                # Fix rogue language tags
                                if csr.attrib.get("AppliedLanguage") in ("$ID/Arabic", "$ID/Hebrew"):
                                    del csr.attrib["AppliedLanguage"]
                                    story_changed = True

                                # Ensure body text font and 9.65pt size on all body text
                                _ensure_csr_font(csr, "Palatino Linotype", point_size="9.65", leading="12")

                                # Strip rogue underline from body text paragraphs
                                if csr.attrib.get("Underline") == "true":
                                    c_txt = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")
                                    c_clean = c_txt.replace("\xa0", " ").strip().lower()
                                    if len(c_clean) > 30 or re.search(r"[.?!]\s+[a-z]", c_clean) or not re.match(
                                        r"^(?:footnote(?:\s*\d+)?|\d{1,4}|chapter(?:\s+[ivxlcdm0-9]+)?|chapters(?:\s+[ivxlcdm0-9]+)?|[ivxlcdm]{2,}|[-–—]\d+|p\.\s*\d+)$",
                                        c_clean,
                                        re.I,
                                    ):
                                        del csr.attrib["Underline"]
                                        if "underlin" in cstyle.lower():
                                            csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                                    else:
                                        if "Position" in csr.attrib:
                                            del csr.attrib["Position"]
                        story_changed = True

                    elif style in ("ParagraphStyle/quotes_normal",):
                        for csr in psr.iter():
                            if lname(csr.tag) == "CharacterStyleRange":
                                _ensure_csr_font(csr, "Palatino Linotype", point_size="9.65", leading="12")
                        story_changed = True

                    # C. Rogue font cleanup: clear old fonts from regular text
                    if not is_heading_or_front and "author" not in style.lower():
                        for csr in psr.iter():
                            if lname(csr.tag) == "CharacterStyleRange":
                                for p in csr:
                                    if lname(p.tag) == "Properties":
                                        for af in p:
                                            if lname(af.tag) == "AppliedFont" and af.text in ("Times New Roman", "Minion Pro", "Baskerville Old Face"):
                                                af.text = "Palatino Linotype"
                                                story_changed = True

                try:
                    from core.justify_stretch_format import fix_justify_stretch as _fjs
                except Exception:
                    try:
                        from justify_stretch_format import fix_justify_stretch as _fjs
                    except Exception:
                        _fjs = None
                if _fjs is not None and _fjs(sroot):
                    story_changed = True
                if story_changed:
                    ET.ElementTree(sroot).write(sf, encoding="utf-8", xml_declaration=True)

        # -------------------------------------------------------------
        # 3. Re-pack IDML cleanly
        # -------------------------------------------------------------
        tmp_out = idml_path.with_suffix(".tmp.idml")
        with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as z_out:
            for p in sorted(tmp_dir.rglob("*")):
                if p.is_file():
                    z_out.write(p, p.relative_to(tmp_dir).as_posix())
        tmp_out.replace(idml_path)

    try:
        from core.epub_class_format import apply_epub_classes as _aec
    except Exception:
        try:
            from epub_class_format import apply_epub_classes as _aec
        except Exception:
            _aec = None
    if _aec is not None:
        try:
            _aec(idml_path)
        except Exception:
            pass

    try:
        from core.collapse_soft_breaks import apply_collapse as _acsb
    except Exception:
        try:
            from collapse_soft_breaks import apply_collapse as _acsb
        except Exception:
            _acsb = None
    if _acsb is not None:
        try:
            _acsb(idml_path)
        except Exception:
            pass

    stats["status"] = "ok"
    return stats

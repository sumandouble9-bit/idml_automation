import copy
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from typography_postprocessor_es_helpers import *
except ImportError:
    from .typography_postprocessor_es_helpers import *


def enforce_styles_xml_es(tmp_dir, stats):
    """Enforce canonical fonts and paragraph/character-style attributes in Resources/Styles.xml (Spanish)."""
    styles_xml = tmp_dir / "Resources" / "Styles.xml"
    if styles_xml.exists():
        sroot = ET.parse(styles_xml).getroot()
        for ps in sroot.iter():
            if lname(ps.tag) == "ParagraphStyle":
                sid = ps.attrib.get("Self", "")
                ps.set("SingleWordJustification", "AlignLeft")
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
                    stats["styles_updated"] += 1
                elif sid == "ParagraphStyle/chapter_name":
                    _ensure_pstyle_font(ps, "Gill Sans MT", point_size="16", leading="20")
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
                    ps.set("Justification", "LeftJustified")
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
                elif "hyperlink" in sid.lower():
                    ps.set("Underline", "false")
                    ps.set("FillColor", "Swatch/Black")
                    if props is not None:
                        for c in list(props):
                            if lname(c.tag) in ("UnderlineColor", "UnderlineType"):
                                props.remove(c)

        # Ensure dedicated superscript and subscript CharacterStyles exist
        has_sup = any(c.attrib.get("Self") == "CharacterStyle/superscript" for c in sroot.iter() if lname(c.tag) == "CharacterStyle")
        if not has_sup:
            ET.SubElement(sroot, "CharacterStyle", {
                "Self": "CharacterStyle/superscript",
                "Name": "superscript",
                "Position": "Superscript",
                "FillColor": "Swatch/Black",
                "Underline": "false"
            })
        has_sub = any(c.attrib.get("Self") == "CharacterStyle/subscript" for c in sroot.iter() if lname(c.tag) == "CharacterStyle")
        if not has_sub:
            ET.SubElement(sroot, "CharacterStyle", {
                "Self": "CharacterStyle/subscript",
                "Name": "subscript",
                "Position": "Subscript",
                "FillColor": "Swatch/Black",
                "Underline": "false"
            })

        ET.ElementTree(sroot).write(styles_xml, encoding="utf-8", xml_declaration=True)


def collect_toc_norms_es(tmp_dir):
    """Collect normalized TOC entry strings from the Spanish stories; return (toc_norms, toc_clean_norms)."""
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
                                            if s and not any(k in s for k in ["table of contents", "contents", "índice", "indice", "double 9 books"]):
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
                                                if s and not any(k in s for k in ["table of contents", "contents", "índice", "indice", "double 9 books"]):
                                                    toc_norms.add(s)
        toc_clean_norms = {re.sub(r"[\s\.\-_]+", "", t) for t in toc_norms}
    return toc_norms, toc_clean_norms


def restyle_psr_es(psr, parent_map, toc_norms, toc_clean_norms, stats):
    """Restyle one Spanish body/heading ParagraphStyleRange; return True if changed."""
    changed = False
    style = psr.attrib.get("AppliedParagraphStyle", "")
    txt = "".join(c.text or "" for c in psr.iter() if lname(c.tag) == "Content").strip()
    has_table = any(lname(c.tag) == "Table" for c in psr.iter())
    has_soft_break = "\u2028" in txt

    # Check if paragraph was mistakenly styled as chapter_name / chapter_name01
    if any(k in style.lower() for k in ["chapter", "sub-heading"]):
        norm_txt = re.sub(r"[^\w\s]", "", txt.lower())
        norm_txt = re.sub(r"\s+", " ", norm_txt).strip()
        norm_clean = re.sub(r"[\s\.\-_]+", "", norm_txt)
        has_chap_kw = bool(CHAP_KW_PATTERN.search(txt)) or bool(re.match(r"^(?:[IVXLCDM]+\b|\d+\b)\.?\s*", txt.strip(), re.I))
        is_known_heading = has_chap_kw or (norm_clean in toc_clean_norms) or (norm_txt in toc_norms)

        if not is_known_heading and (len(txt) > 150 or (len(txt) > 60 and "." in txt and not any(k in txt.lower() for k in ["parte", "part", "cap", "vol"]))):
            psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
            psr.set("Justification", "LeftAlign" if _is_true_verse_txt(txt) else "LeftJustified")
            psr.set("FirstLineIndent", "18")
            psr.set("SpaceBefore", "1.5")
            psr.set("SpaceAfter", "3")
            has_tbl = any(lname(c.tag) == "Table" for c in psr.iter())
            if not has_tbl:
                psr.set("KeepLinesTogether", "true")
            else:
                if "KeepLinesTogether" in psr.attrib:
                    del psr.attrib["KeepLinesTogether"]
                psr.set("FirstLineIndent", "0")
                psr.set("KeepFirstAndLastLines", "true")
                psr.set("MinLinesAtStart", "2")
                psr.set("MinLinesAtEnd", "2")
                if "StartParagraph" in psr.attrib:
                    del psr.attrib["StartParagraph"]
                if "ParagraphBreakType" in psr.attrib:
                    del psr.attrib["ParagraphBreakType"]
                style = "ParagraphStyle/body_text"
                stats["body_paras_restored"] += 1
                changed = True
        elif "chapter" in style.lower() and "after" not in style.lower():
            _par = parent_map.get(psr)
            _prev_prot = False
            if _par is not None:
                _kids = list(_par)
                if psr in _kids:
                    _ix = _kids.index(psr)
                    if _ix > 0 and _kids[_ix - 1].attrib.get("BlankPageProtected") == "true":
                        _prev_prot = True
            psr.set("KeepAllLinesTogether", "true")
            psr.set("KeepLinesTogether", "true")
            psr.set("KeepWithNext", "2")
            psr.set("Justification", "CenterAlign")
            psr.set("FirstLineIndent", "0")
            parent = parent_map.get(psr)
            if _is_first_chapter_heading(psr, parent_map):
                psr.set("StartParagraph", "Anywhere")
                psr.set("SpaceBefore", "14.5")
                psr.set("SpaceAfter", "30")
                changed = True
            elif _has_preceding_page_spacer(psr, parent_map):
                psr.set("StartParagraph", "Anywhere")
                psr.set("SpaceBefore", "14.5")
                psr.set("SpaceAfter", "30")
                changed = True
            elif _prev_prot:
                if psr.attrib.get("StartParagraph") != "Anywhere":
                    psr.set("StartParagraph", "Anywhere")
                    changed = True
            elif not _prev_is_heading(psr, parent_map):
                psr.set("StartParagraph", "NextPage")
                changed = True
            else:
                psr.set("StartParagraph", "Anywhere")
                changed = True
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

    if has_soft_break and not has_table and "chapter" not in style.lower():
        psr.set("Justification", "LeftAlign")
        changed = True

    is_body = (
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
        "double 9 books", "reservados todos los derechos", "isbn", "sobre la autoría"
    ]) or ("publicado por" in txt.lower() and ("double 9" in txt.lower() or "derechos" in txt.lower() or len(txt) < 50))

    if is_body and not is_heading_or_front and txt and not has_table and txt != "\u2028" and "\ufeff" not in txt:
        _orig_just = psr.attrib.get("Justification")
        _sl = style.lower()
        _is_cent = (
            _orig_just == "CenterAlign"
            or any(k in _sl for k in ("center", "centre"))
            or txt.strip() in _SEPARATORS
        )
        _is_rt = (
            _orig_just == "RightAlign"
            or any(k in _sl for k in ("right", "signature", "signed"))
        )
        _has_soft = " " in txt or _is_verse_psr(psr) or _is_true_verse_txt(txt) or _soft_break_would_stretch(txt)

        if style in ("ParagraphStyle/Normal", "ParagraphStyle/$ID/[Basic Paragraph]", "ParagraphStyle/copybody"):
            psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
            stats["body_paras_restored"] += 1

        if _is_cent:
            if _orig_just != "CenterAlign":
                psr.set("Justification", "CenterAlign")
                changed = True
            psr.set("FirstLineIndent", "0")
        elif _is_rt:
            if _orig_just != "RightAlign":
                psr.set("Justification", "RightAlign")
                changed = True
            psr.set("FirstLineIndent", "0")
        elif _has_soft or any(_k in _sl for _k in ("quote", "verse", "block", "poem", "epigraph")):
            if _orig_just != "LeftAlign":
                psr.set("Justification", "LeftAlign")
                changed = True
            psr.set("FirstLineIndent", "0")
        else:
            if _orig_just != "LeftJustified":
                psr.set("Justification", "LeftJustified")
                changed = True
            psr.set("FirstLineIndent", "18")

        psr.set("SpaceBefore", "1.5")
        psr.set("SpaceAfter", "3")
        psr.set("KeepLinesTogether", "true")
        psr.set("KeepFirstAndLastLines", "true")
        psr.set("MinLinesAtStart", "2")
        psr.set("MinLinesAtEnd", "2")

        for csr in list(psr):
            if lname(csr.tag) == "CharacterStyleRange":
                # 1. Clean runaway Subscript / Superscript
                pos = csr.attrib.get("Position", "")
                if pos in ("Subscript", "Superscript"):
                    raw_text = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")
                    c_txt = raw_text.strip()
                    is_runaway = False
                    if not c_txt:
                        is_runaway = True
                    elif pos == "Superscript":
                        is_note = bool(re.match(r"^\[?\d{1,5}[a-z]?\]?$", c_txt)) or c_txt.lower() in ("*", "†", "‡", "§", "#", "st", "nd", "rd", "th", "d", "e", "er", "re", "o", "a", "os", "as", "°")
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
                        changed = True

                if csr.attrib.get("AppliedLanguage") in ("$ID/Arabic", "$ID/Hebrew"):
                    del csr.attrib["AppliedLanguage"]
                    changed = True

                # Strip hyperlink styling: remove link, force Black color, remove underline
                # Preserve any legitimate Superscript / Subscript marker!
                cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                if "hyperlink" in cstyle.lower():
                    if pos == "Superscript":
                        csr.set("AppliedCharacterStyle", "CharacterStyle/superscript")
                        cstyle = "CharacterStyle/superscript"
                    elif pos == "Subscript":
                        csr.set("AppliedCharacterStyle", "CharacterStyle/subscript")
                        cstyle = "CharacterStyle/subscript"
                    else:
                        csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                        cstyle = r"CharacterStyle/$ID/[No character style]"
                    if "Underline" in csr.attrib:
                        del csr.attrib["Underline"]
                    if "FillColor" in csr.attrib:
                        del csr.attrib["FillColor"]
                    changed = True
                elif pos == "Superscript" and cstyle in ("", r"CharacterStyle/$ID/[No character style]"):
                    csr.set("AppliedCharacterStyle", "CharacterStyle/superscript")
                    cstyle = "CharacterStyle/superscript"
                    changed = True
                elif pos == "Subscript" and cstyle in ("", r"CharacterStyle/$ID/[No character style]"):
                    csr.set("AppliedCharacterStyle", "CharacterStyle/subscript")
                    cstyle = "CharacterStyle/subscript"
                    changed = True

                # Unwrap HyperlinkTextSource so text is not an active link
                for child in list(csr):
                    if lname(child.tag) == "HyperlinkTextSource":
                        idx = list(csr).index(child)
                        csr.remove(child)
                        for sub in list(child):
                            csr.insert(idx, sub)
                            idx += 1
                        changed = True

                # 2. Enforce Palatino Linotype 9.65pt on body text
                if pos not in ("Superscript", "Subscript"):
                    _ensure_csr_font(csr, "Palatino Linotype", point_size="9.65", leading="12")
                    changed = True

                # 3. Validate underline
                if csr.attrib.get("Underline") == "true":
                    c_txt = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")
                    c_clean = c_txt.replace("\xa0", " ").strip().lower()
                    if len(c_clean) > 30 or re.search(r"[.?!]\s+[a-z]", c_clean):
                        del csr.attrib["Underline"]
                        cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                        if "underlin" in cstyle.lower():
                            csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                        changed = True

    elif style in ("ParagraphStyle/quotes_normal",):
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                _ensure_csr_font(csr, "Palatino Linotype", point_size="9.65", leading="12")
                changed = True

    # Clear rogue non-Palatino fonts from regular text
    if not is_heading_or_front and not has_table and "author" not in style.lower():
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                props = next((p for p in csr if lname(p.tag) == "Properties"), None)
                if props is not None:
                    for af in list(props):
                        if lname(af.tag) == "AppliedFont" and af.text in ("Times New Roman", "Minion Pro", "Baskerville Old Face"):
                            af.text = "Palatino Linotype"
                            changed = True
    return changed


def process_story_file_es(sf, toc_norms, toc_clean_norms, stats):
    """Repair footers and restyle every paragraph in one Spanish story XML file, writing it back if changed."""
    raw_text = sf.read_text(encoding="utf-8")
    # Handle MasterSpread footers via raw string
    if "<?ACE 18?>" in raw_text and "<TextVariableInstance" in raw_text:
        if "\u2002|\u2002" not in raw_text and "\u2003" not in raw_text and " | " not in raw_text:
            sep = '<CharacterStyleRange AppliedCharacterStyle="CharacterStyle/$ID/[No character style]"><Properties><Leading type="enumeration">Auto</Leading><AppliedFont type="string">Bell MT</AppliedFont></Properties><Content>\u2002|\u2002</Content></CharacterStyleRange>'
            if raw_text.find("<?ACE 18?>") < raw_text.find("<TextVariableInstance"):
                idx = raw_text.find("<?ACE 18?></Content>")
                if idx != -1:
                    end_csr = raw_text.find("</CharacterStyleRange>", idx)
                    if end_csr != -1:
                        end_pos = end_csr + len("</CharacterStyleRange>")
                        raw_text = raw_text[:end_pos] + "\n\t\t\t" + sep + raw_text[end_pos:]
                        sf.write_text(raw_text, encoding="utf-8")
                        stats["footers_repaired"] += 1
            else:
                idx = raw_text.find("<TextVariableInstance")
                if idx != -1:
                    end_csr = raw_text.find("</CharacterStyleRange>", idx)
                    if end_csr != -1:
                        end_pos = end_csr + len("</CharacterStyleRange>")
                        raw_text = raw_text[:end_pos] + "\n\t\t\t" + sep + raw_text[end_pos:]
                        sf.write_text(raw_text, encoding="utf-8")
                        stats["footers_repaired"] += 1
        return

    try:
        sroot = ET.parse(sf).getroot()
    except Exception:
        return

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
    for _pp in sroot.iter():
        for _cc in _pp:
            parent_map[_cc] = _pp
    for psr in sroot.iter():
        if lname(psr.tag) != "ParagraphStyleRange":
            continue
        if restyle_psr_es(psr, parent_map, toc_norms, toc_clean_norms, stats):
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


__all__ = ['enforce_styles_xml_es', 'collect_toc_norms_es', 'restyle_psr_es', 'process_story_file_es']

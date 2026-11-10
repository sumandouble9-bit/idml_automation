import copy
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from typography_postprocessor_helpers import *
except ImportError:
    from .typography_postprocessor_helpers import *


try:
    from typography_postprocessor_styles import *
except ImportError:
    from .typography_postprocessor_styles import *


def restyle_psr(psr, parent_map, toc_norms, toc_clean_norms, stats):
    """Restyle one body/heading ParagraphStyleRange (fonts, justification, markers, hyperlinks); return True if changed."""
    changed = False
    style = psr.attrib.get("AppliedParagraphStyle", "")
    txt = "".join(c.text or "" for c in psr.iter() if lname(c.tag) == "Content").strip()
    rects = [e for e in psr.iter() if lname(e.tag) == "Rectangle"]
    has_soft_break = "\u2028" in txt

    # If this is a placeholder paragraph: ensure exactly one closing Br and Normal style
    if "###Insert" in txt:
        if "ParagraphBreakType" in psr.attrib:
            del psr.attrib["ParagraphBreakType"]
            changed = True
        if "StartParagraph" in psr.attrib:
            del psr.attrib["StartParagraph"]
            changed = True
        psr.set("AppliedParagraphStyle", "ParagraphStyle/Normal")
        psr.set("Justification", "CenterAlign")
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                for br in list(csr):
                    if lname(br.tag) == "Br":
                        csr.remove(br)
                        changed = True
        last_csr = list(psr)[-1] if list(psr) else None
        if last_csr is not None and not any(lname(c.tag) == "Br" for c in psr.iter()):
            ET.SubElement(last_csr, "Br")
            changed = True
        return changed

    # A. Ensure captions use correct font
    if "caption" in style.lower():
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                for p in csr:
                    if lname(p.tag) == "Properties":
                        for af in p:
                            if lname(af.tag) == "AppliedFont":
                                af.text = "Palatino Linotype"
                                changed = True
        return changed

    # A2. Subheading page-break cleanup (Keep on SAME PAGE as chapter text)
    if "sub-heading" in style.lower() or style == "ParagraphStyle/Sub-heading":
        norm_txt = re.sub(r"[^\w\s]", "", txt.lower())
        norm_txt = re.sub(r"\s+", " ", norm_txt).strip()
        is_in_toc = (norm_txt in toc_norms) or any(norm_txt.startswith(t) for t in toc_norms if len(t) > 6 and len(norm_txt) > 6)
        if is_in_toc:
            return changed

        if "ParagraphBreakType" in psr.attrib:
            del psr.attrib["ParagraphBreakType"]
            changed = True
        for c in psr.iter():
            if "ParagraphBreakType" in c.attrib:
                del c.attrib["ParagraphBreakType"]
                changed = True
        psr.set("SpaceBefore", "18")
        psr.set("SpaceAfter", "12")
        psr.set("KeepWithNext", "2")
        has_tbl = any(lname(c.tag) == "Table" for c in psr.iter())
        if not has_tbl:
            psr.set("KeepLinesTogether", "true")
        else:
            if "KeepLinesTogether" in psr.attrib:
                del psr.attrib["KeepLinesTogether"]
            psr.set("FirstLineIndent", "0")
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
                            changed = True
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
                changed = True
        return changed

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
                            changed = True
                        else:
                            break
                    else:
                        break
                if idx > 0:
                    prev_child = list(parent)[idx - 1]
                    if not _is_blank_page_spacer(prev_child):
                        if prev_child.attrib.get("ParagraphBreakType") == "NextPage":
                            del prev_child.attrib["ParagraphBreakType"]
                            changed = True
                        for c in prev_child.iter():
                            if c.attrib.get("ParagraphBreakType") == "NextPage":
                                del c.attrib["ParagraphBreakType"]
                                changed = True
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
            changed = True
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
        elif psr.attrib.get("StartParagraph") != "NextPage" and not _prev_is_heading(psr, parent_map):
            psr.set("StartParagraph", "NextPage")
            changed = True
        else:
            psr.set("StartParagraph", "Anywhere")
            changed = True

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
        "double 9 books", "all rights reserved", "isbn", "about the author"
    ]) or ("published by" in txt.lower() and ("double 9" in txt.lower() or "copyright" in txt.lower() or len(txt) < 50))

    if is_body_like and not is_heading_or_front and txt and not rects and txt != "\u2028" and "\ufeff" not in txt:
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
        _has_soft = (
            "\u2028" in txt
            or "\n" in txt
            or "\r" in txt
            or "index" in _sl
            or any("\u2028" in (c.text or "") for c in psr.iter() if lname(c.tag) == "Content")
            or _is_verse_psr(psr)
            or _is_true_verse_txt(txt)
            or _soft_break_would_stretch(txt)
        )

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
        elif re.match(r"^\s*\[\d{1,4}[a-z]?\]", txt or ""):
            if _orig_just != "LeftJustified":
                psr.set("Justification", "LeftJustified")
                changed = True
            psr.set("FirstLineIndent", "0")
        elif _has_soft or any(_k in _sl for _k in ("quote", "verse", "block", "poem", "epigraph")):
            if _orig_just != "LeftAlign":
                psr.set("Justification", "LeftAlign")
                changed = True
            psr.set("SingleWordJustification", "AlignLeft")
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
        if "PointSize" in psr.attrib:
            del psr.attrib["PointSize"]
        if "Leading" in psr.attrib:
            del psr.attrib["Leading"]

        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                is_bold = "bold" in cstyle.lower()
                is_italic = "italic" in cstyle.lower()
                # Emphasis the EPUB enricher applied (CharacterStyle/italic,
                # CharacterStyle/boldtext) is EPUB-verified and kept at any length;
                # only stray long italics/bolds from other styles are flattened.
                is_epub_emph = cstyle in ("CharacterStyle/italic", "CharacterStyle/boldtext")
                raw_c_txt = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content").strip()
                if is_italic and len(raw_c_txt) > 80 and not is_epub_emph:
                    csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                    csr.set("FontStyle", "Regular")
                    cstyle = r"CharacterStyle/$ID/[No character style]"
                    changed = True
                elif is_bold and len(raw_c_txt) > 80 and not is_epub_emph:
                    csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                    csr.set("FontStyle", "Regular")
                    cstyle = r"CharacterStyle/$ID/[No character style]"
                    changed = True
                elif not is_bold and not is_italic:
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
                        changed = True

                # Fix rogue language tags
                if csr.attrib.get("AppliedLanguage") in ("$ID/Arabic", "$ID/Hebrew"):
                    del csr.attrib["AppliedLanguage"]
                    changed = True

                # Strip hyperlink styling: remove link, force Black color, remove underline
                # Preserve any legitimate Superscript / Subscript marker!
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

                # Ensure body text font and 9.65pt size on all body text
                _ensure_csr_font(csr, "Palatino Linotype", point_size="9.65", leading="12")

                # Strip rogue underline from body text paragraphs
                if csr.attrib.get("Underline") == "true":
                    c_txt = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")
                    c_clean = c_txt.replace("\xa0", " ").strip().lower()
                    pos_check = csr.attrib.get("Position", "")
                    is_fn_marker = bool(re.match(r"^\[?\d{1,5}[a-z]?\]?$", c_clean)) or pos_check in ("Superscript", "Subscript")
                    if is_fn_marker or len(c_clean) > 30 or re.search(r"[.?!]\s+[a-z]", c_clean) or not re.match(
                        r"^(?:chapter(?:\s+[ivxlcdm0-9]+)?|chapters(?:\s+[ivxlcdm0-9]+)?|[ivxlcdm]{2,})$",
                        c_clean,
                        re.I,
                    ):
                        del csr.attrib["Underline"]
                        if "FillColor" in csr.attrib:
                            del csr.attrib["FillColor"]
                        if "underlin" in cstyle.lower():
                            csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                    else:
                        if "Position" in csr.attrib:
                            del csr.attrib["Position"]
        changed = True

    elif style in ("ParagraphStyle/quotes_normal",):
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                _ensure_csr_font(csr, "Palatino Linotype", point_size="9.65", leading="12")
        changed = True

    # C. Rogue font cleanup: clear old fonts from regular text
    if not is_heading_or_front and "author" not in style.lower():
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                for p in csr:
                    if lname(p.tag) == "Properties":
                        for af in p:
                            if lname(af.tag) == "AppliedFont" and af.text in ("Times New Roman", "Minion Pro", "Baskerville Old Face"):
                                af.text = "Palatino Linotype"
                                changed = True
    return changed


def process_story_file(sf, toc_norms, toc_clean_norms, stats):
    """Repair footers and restyle every paragraph in one story XML file, writing it back if changed."""
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
    for p in sroot.iter():
        for child in p:
            parent_map[child] = p
    for psr in sroot.iter():
        if lname(psr.tag) != "ParagraphStyleRange":
            continue
        if restyle_psr(psr, parent_map, toc_norms, toc_clean_norms, stats):
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


__all__ = ['restyle_psr', 'process_story_file']

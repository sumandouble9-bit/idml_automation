"""Character-run level transforms for one ParagraphStyleRange: CSR unpacking, footnote/chem markers, and emphasis styles."""

import copy
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.idml_utils import lname

try:
    from .typography_common import MERGE_MAP, CHEM_REGEX, REF_MARKER_REGEX, _tokenize_chem, _normalize_table_content
except ImportError:
    from typography_common import MERGE_MAP, CHEM_REGEX, REF_MARKER_REGEX, _tokenize_chem, _normalize_table_content


def split_table_and_text(psr, parent_map, epub_fmt):
    """Split a paragraph holding both a Table and body text into separate table/text PSRs; True if it was split."""
    for _csr in list(psr):
        if lname(_csr.tag) != "CharacterStyleRange":
            continue
        _kids = list(_csr)
        if not any(lname(_k.tag) == "Table" for _k in _kids):
            continue
        _non_tbl = [_k for _k in _kids if lname(_k.tag) not in ("Table", "Properties")]
        if not _non_tbl:
            continue
        _csr_attrib = dict(_csr.attrib)
        _props = [_k for _k in _kids if lname(_k.tag) == "Properties"]
        _segments, _cur = [], []
        for _k in _kids:
            if lname(_k.tag) == "Properties":
                continue
            if lname(_k.tag) == "Table":
                if _cur:
                    _segments.append(("content", _cur)); _cur = []
                _segments.append(("table", _k))
            else:
                _cur.append(_k)
        if _cur:
            _segments.append(("content", _cur))
        _at = list(psr).index(_csr)
        psr.remove(_csr)
        for _stype, _payload in _segments:
            _ncsr = ET.Element("CharacterStyleRange", _csr_attrib)
            for _pr in _props:
                _ncsr.append(copy.deepcopy(_pr))
            if _stype == "content":
                for _node in _payload:
                    _ncsr.append(_node)
            else:
                _ncsr.append(_payload)
            psr.insert(_at, _ncsr); _at += 1
    segs = []
    for _c in list(psr):
        if lname(_c.tag) != "CharacterStyleRange":
            continue
        if any(lname(_s.tag) == "Table" for _s in _c.iter()):
            for _tbl in _c.iter():
                if lname(_tbl.tag) == "Table":
                    _normalize_table_content(_tbl, epub_fmt=epub_fmt)
            segs.append(["table", [_c]])
        elif segs and segs[-1][0] == "content":
            segs[-1][1].append(_c)
        else:
            segs.append(["content", [_c]])

    def _seg_text(_csrs):
        return "".join(
            _cc.text or ""
            for _csr in _csrs
            for _cc in _csr.iter()
            if lname(_cc.tag) == "Content"
        ).strip()

    parent = parent_map.get(psr)
    _has_content = any(s[0] == "content" and _seg_text(s[1]) for s in segs)
    _has_table = any(s[0] == "table" for s in segs)
    if parent is None or not (_has_content and _has_table):
        return False

    _orig_style = psr.attrib.get("AppliedParagraphStyle", "")
    _is_block = any(k in _orig_style.lower() for k in ("quote", "block", "verse", "poem", "extract", "epigraph"))
    idx = list(parent).index(psr)
    for child in list(psr):
        psr.remove(child)
    ins_idx = idx
    _seen_table = False
    for _stype, _csrs in segs:
        if _stype == "table":
            seg_psr = ET.Element("ParagraphStyleRange", {
                "AppliedParagraphStyle": "ParagraphStyle/body_text",
                "Justification": "LeftAlign",
                "FirstLineIndent": "0",
                "SpaceBefore": "6",
                "SpaceAfter": "6",
            })
            _seen_table = True
        else:
            _txt = _seg_text(_csrs)
            if not _txt:
                continue
            if (not _seen_table) or _is_block:
                seg_attrib = dict(psr.attrib)
                if _is_block:
                    seg_attrib["Justification"] = "LeftAlign"
            else:
                seg_attrib = {
                    "AppliedParagraphStyle": "ParagraphStyle/body_text",
                    "FirstLineIndent": "18",
                    "SpaceBefore": "1.5",
                    "SpaceAfter": "3",
                    "Justification": "LeftAlign" if " " in _txt else "LeftJustified",
                }
            seg_psr = ET.Element("ParagraphStyleRange", seg_attrib)
        for _c in _csrs:
            seg_psr.append(_c)
        _last = None
        for _c in reversed(list(seg_psr)):
            if lname(_c.tag) == "CharacterStyleRange":
                _last = _c
                break
        if _last is None or not any(lname(_ch.tag) == "Br" for _ch in _last):
            _brc = ET.SubElement(seg_psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
            })
            ET.SubElement(_brc, "Br")
        parent.insert(ins_idx, seg_psr)
        parent_map[seg_psr] = parent
        ins_idx += 1
    parent.remove(psr)
    return True


def unpack_multichild_csrs(psr):
    """Split any CSR with several non-Properties children so each holds at most one; return whether changed."""
    changed = False
    for csr in list(psr):
        if lname(csr.tag) == "CharacterStyleRange":
            non_prop_children = [c for c in list(csr) if lname(c.tag) != "Properties"]
            if len(non_prop_children) > 1:
                prop_child = next((c for c in list(csr) if lname(c.tag) == "Properties"), None)
                idx = list(psr).index(csr)
                psr.remove(csr)
                for offset, child in enumerate(non_prop_children):
                    new_csr = ET.Element(csr.tag, attrib=dict(csr.attrib))
                    if prop_child is not None:
                        new_csr.append(copy.deepcopy(prop_child))
                    new_csr.append(child)
                    psr.insert(idx + offset, new_csr)
                changed = True
    return changed


ENTRY_MARKER_START = re.compile(r"^\s*\[\d{1,4}[a-z]?\]")


def _ends_line(csr):
    """True when the run finishes with a line break, so the next run starts a new footnote entry."""
    kids = list(csr)
    return bool(kids) and lname(kids[-1].tag) == "Br"


def _plain_marker(csr):
    """Strip superscript/subscript position and character style from a run; return True when it changed."""
    changed = csr.attrib.pop("Position", None) is not None
    style = csr.attrib.get("AppliedCharacterStyle", "").lower()
    if style.endswith("superscript") or style.endswith("subscript"):
        csr.set("AppliedCharacterStyle", "CharacterStyle/$ID/[No character style]")
        changed = True
    return changed


def unsuperscript_entry_marker(psr):
    """Make every footnote entry's leading [n] marker plain text (not superscript); return changed.

    One paragraph can hold many entries separated by line breaks, so each run that starts a line is checked.
    """
    changed = False
    at_line_start = True
    for csr in psr:
        if lname(csr.tag) != "CharacterStyleRange":
            continue
        text = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")
        if text.strip():
            if at_line_start and ENTRY_MARKER_START.match(text) and _plain_marker(csr):
                changed = True
            at_line_start = False
        if _ends_line(csr):
            at_line_start = True
    return changed


def merge_and_split_ref_markers(psr, in_footnotes, is_fn_style, stats):
    """Merge bracket-split footnote markers, then split markers into their own superscript CSRs; return changed."""
    changed = False

    # 1. Merge adjacent CSRs that split brackets (e.g. '[' and '14]')
    csrs_list = [c for c in list(psr) if lname(c.tag) == "CharacterStyleRange"]
    for i in range(len(csrs_list) - 1):
        c1, c2 = csrs_list[i], csrs_list[i + 1]
        t1 = "".join(e.text or "" for e in c1.iter() if lname(e.tag) == "Content")
        t2 = "".join(e.text or "" for e in c2.iter() if lname(e.tag) == "Content")
        if re.search(r"\[\d*$", t1) and re.match(r"^\d*\]", t2):
            cnt1 = next((e for e in c1.iter() if lname(e.tag) == "Content"), None)
            cnt2 = next((e for e in c2.iter() if lname(e.tag) == "Content"), None)
            if cnt1 is not None and cnt2 is not None:
                cnt1.text = (cnt1.text or "") + (cnt2.text or "")
                cnt2.text = ""
                changed = True

    # 2. Split CSRs containing footnote/reference markers (in body text only, not footnote entries)
    if not (in_footnotes or is_fn_style):
        for csr in list(psr):
            if lname(csr.tag) != "CharacterStyleRange":
                continue
            cnt_elem = next((e for e in csr.iter() if lname(e.tag) == "Content"), None)
            if cnt_elem is None or not cnt_elem.text:
                continue
            txt = cnt_elem.text

            if REF_MARKER_REGEX.search(txt):
                parts = REF_MARKER_REGEX.split(txt)
                if len(parts) > 1:
                    idx = list(psr).index(csr)
                    psr.remove(csr)
                    offset = 0
                    for part in parts:
                        if not part:
                            continue
                        new_csr = copy.deepcopy(csr)
                        new_cnt = next((e for e in new_csr.iter() if lname(e.tag) == "Content"), None)
                        if new_cnt is not None:
                            new_cnt.text = part
                        if REF_MARKER_REGEX.match(part):
                            new_csr.set("Position", "Superscript")
                            stats["super_fixed"] += 1
                        else:
                            if "Position" in new_csr.attrib:
                                del new_csr.attrib["Position"]
                        psr.insert(idx + offset, new_csr)
                        offset += 1
                    changed = True
    return changed


def handle_chem_and_subscript(psr, stats):
    """Subscript chemical-formula digits and clean leaked subscripts across the paragraph's CSRs; return changed."""
    changed = False
    txt = ""

    # 1. Chemical formulas with digits (e.g. K2O, H2O, C5N4, CO2, P2O5)
    for csr in list(psr):
        if lname(csr.tag) != "CharacterStyleRange":
            continue
        cnt_elem = next((e for e in csr.iter() if lname(e.tag) == "Content"), None)
        if cnt_elem is None or not cnt_elem.text:
            continue
        txt = cnt_elem.text

        if CHEM_REGEX.search(txt) and not REF_MARKER_REGEX.search(txt):
            tokens = _tokenize_chem(txt)
            if any(is_sub for _, is_sub in tokens):
                idx = list(psr).index(csr)
                psr.remove(csr)
                offset = 0
                for part, is_sub in tokens:
                    if not part:
                        continue
                    c_tok = copy.deepcopy(csr)
                    t_cnt = next((e for e in c_tok.iter() if lname(e.tag) == "Content"), None)
                    if t_cnt is not None:
                        t_cnt.text = part
                    if is_sub:
                        c_tok.set("Position", "Subscript")
                        stats["sub_fixed"] += 1
                    else:
                        if "Position" in c_tok.attrib:
                            del c_tok.attrib["Position"]
                    psr.insert(idx + offset, c_tok)
                    offset += 1
                changed = True

    # 2. Leaked subscripts in input starting with digits or variable indices
    for csr in list(psr):
        if lname(csr.tag) != "CharacterStyleRange":
            continue
        pos = csr.attrib.get("Position", "")
        cstyle = csr.attrib.get("AppliedCharacterStyle", "")
        if pos == "Subscript" or "subscript" in cstyle.lower():
            cnt_elem = next((e for e in csr.iter() if lname(e.tag) == "Content"), None)
            if cnt_elem is None or not cnt_elem.text:
                continue
            is_year = bool(re.match(r"^(18\d\d|19\d\d|20\d\d)", txt.strip()))
            if not is_year and len(txt.strip()) <= 3 and (re.match(r"^\d+$", txt.strip()) or txt.strip() in ("ab", "t1", "t2", "t3", "x1", "x2")):
                csr.set("Position", "Subscript")
            elif not is_year and re.match(r"^(\d{1,3})(.*)$", txt, re.S):
                m = re.match(r"^(\d{1,3})(.*)$", txt, re.S)
                sub_part, rest_part = m.group(1), m.group(2)
                idx = list(psr).index(csr)
                psr.remove(csr)
                offset = 0
                if sub_part:
                    c_sub = copy.deepcopy(csr)
                    c_cnt = next((e for e in c_sub.iter() if lname(e.tag) == "Content"), None)
                    if c_cnt is not None:
                        c_cnt.text = sub_part
                    c_sub.set("Position", "Subscript")
                    stats["sub_fixed"] += 1
                    psr.insert(idx + offset, c_sub)
                    offset += 1
                if rest_part:
                    c_rest = copy.deepcopy(csr)
                    c_cnt = next((e for e in c_rest.iter() if lname(e.tag) == "Content"), None)
                    if c_cnt is not None:
                        c_cnt.text = rest_part
                    if "Position" in c_rest.attrib:
                        del c_rest.attrib["Position"]
                    psr.insert(idx + offset, c_rest)
                    offset += 1
                changed = True
            else:
                if "Position" in csr.attrib:
                    del csr.attrib["Position"]
                changed = True
    return changed


def apply_char_styles(psr, epub_fmt, lower_italics, lower_bolds, epub_underlines, stats):
    """Apply bold/italic/underline/caps/superscript/subscript character styling to each CSR; return changed."""
    changed = False
    for csr in list(psr):
        if lname(csr.tag) != "CharacterStyleRange":
            continue

        cstyle = csr.attrib.get("AppliedCharacterStyle", "")
        ctxt = "".join(e.text or "" for e in csr.iter() if lname(e.tag) == "Content")

        # Remap merged styles (bold, italic, allcaps)
        if cstyle in MERGE_MAP and not any(k in cstyle.lower() for k in ["underlin", "/u"]):
            canonical = MERGE_MAP[cstyle]
            csr.set("AppliedCharacterStyle", canonical)
            cstyle = canonical
            changed = True

        # Apply bold only if legitimate (EPUB match or short heading/lead-in)
        is_bold_cand = "bold" in cstyle.lower() or csr.attrib.get("FontStyle") == "Bold"
        if is_bold_cand:
            c_clean = ctxt.replace("\xa0", " ").strip().lower()
            if epub_fmt and len(c_clean) > 60 and c_clean not in lower_bolds:
                csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                csr.set("FontStyle", "Regular")
                cstyle = r"CharacterStyle/$ID/[No character style]"
            else:
                csr.set("FontStyle", "Bold")
                stats["bold_fixed"] += 1
            changed = True

        # Apply italic only if legitimate (EPUB match or short phrase)
        is_it_cand = "italic" in cstyle.lower() or csr.attrib.get("FontStyle") == "Italic"
        if is_it_cand:
            c_clean = ctxt.replace("\xa0", " ").strip().lower()
            if epub_fmt and len(c_clean) > 60 and c_clean not in lower_italics:
                csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                csr.set("FontStyle", "Regular")
                cstyle = r"CharacterStyle/$ID/[No character style]"
            else:
                csr.set("FontStyle", "Italic")
                stats["italic_fixed"] += 1
            changed = True

        # Task 8, 15, 17: Underline Handling & Leaked Underline Cleanup
        is_legit_u = False
        is_u_style = any(k in cstyle.lower() for k in ["underlin", "/u"])
        has_u_attr = csr.attrib.get("Underline") == "true"

        pos_curr = csr.attrib.get("Position", "")
        is_note_marker = bool(re.match(r"^\[?\d{1,5}[a-z]?\]?$", ctxt.strip())) or pos_curr in ("Superscript", "Subscript")
        if is_note_marker:
            is_legit_u = False
            is_u_style = False
            if "Underline" in csr.attrib:
                del csr.attrib["Underline"]
            if "FillColor" in csr.attrib:
                del csr.attrib["FillColor"]
            changed = True
        elif is_u_style or has_u_attr:
            c_clean = ctxt.replace("\xa0", " ").strip().lower()
            if c_clean:
                if epub_underlines:
                    if c_clean in epub_underlines or any(
                        c_clean == u or (len(c_clean) >= 2 and c_clean in u.split())
                        for u in epub_underlines
                    ):
                        is_legit_u = True
                elif (
                    is_u_style
                    and len(c_clean) <= 30
                    and not re.search(r"[.?!]\s+[a-z]", c_clean)
                ):
                    if re.match(
                        r"^(?:chapter(?:\s+[ivxlcdm0-9]+)?|chapters(?:\s+[ivxlcdm0-9]+)?|[ivxlcdm]{2,})$",
                        c_clean,
                        re.I,
                    ):
                        is_legit_u = True

            if is_legit_u:
                csr.set("Underline", "true")
                csr.set("AppliedCharacterStyle", "CharacterStyle/underlinalign")
                cstyle = "CharacterStyle/underlinalign"
                if "Position" in csr.attrib:
                    del csr.attrib["Position"]
                stats["underline_fixed"] += 1
                changed = True
            else:
                # Strip leaked/runaway underline
                if "Underline" in csr.attrib:
                    del csr.attrib["Underline"]
                    changed = True
                if is_u_style:
                    # Reset style: retain italic/bold if applicable, else [No character style]
                    if csr.attrib.get("FontStyle") == "Italic" or "italic" in cstyle.lower():
                        csr.set("AppliedCharacterStyle", "CharacterStyle/italicalign")
                        cstyle = "CharacterStyle/italicalign"
                    elif csr.attrib.get("FontStyle") == "Bold" or "bold" in cstyle.lower():
                        csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                        cstyle = "CharacterStyle/boldtext"
                    else:
                        csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                        cstyle = r"CharacterStyle/$ID/[No character style]"
                    changed = True

        # Apply all caps
        if "upper" in cstyle.lower() or csr.attrib.get("Capitalization") == "AllCaps":
            csr.set("Capitalization", "AllCaps")
            stats["caps_fixed"] += 1
            changed = True

        # Task 13: Superscript markers (e.g. [1], [215], 1, 2)
        is_true_super = (
            not is_legit_u
            and (
                bool(REF_MARKER_REGEX.match(ctxt.strip()))
                or (re.match(r"^(\d{1,3}|\*|†|‡)$", ctxt.strip()) and (csr.attrib.get("Position") == "Superscript" or "superscript" in cstyle.lower()))
                or ("superscript" in cstyle.lower() and len(ctxt.strip()) <= 4)
            )
        )
        if is_true_super:
            csr.set("Position", "Superscript")
            stats["super_fixed"] += 1
            changed = True
        elif csr.attrib.get("Position") == "Superscript":
            # Strip corrupted superscript from regular body text
            del csr.attrib["Position"]
            changed = True

        # Task 14: Subscript markers
        is_true_sub = (
            len(ctxt.strip()) <= 4
            and (re.match(r"^\d+$", ctxt.strip()) or ctxt.strip() in ("ab", "t1", "t2", "t3", "x1", "x2"))
            and (csr.attrib.get("Position") == "Subscript" or "subscript" in cstyle.lower())
        )
        if is_true_sub:
            csr.set("Position", "Subscript")
            stats["sub_fixed"] += 1
            changed = True
        elif csr.attrib.get("Position") == "Subscript":
            del csr.attrib["Position"]
            changed = True

        # Fix corrupted Arabic language tag
        if csr.attrib.get("AppliedLanguage") == "$ID/Arabic":
            csr.set("AppliedLanguage", "$ID/English: USA")
            changed = True
    return changed

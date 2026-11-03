import copy
import html
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.idml_utils import (
    content_text,
    copy_named_styles,
    lname,
    parse,
    sync_fonts,
    write_xml,
    get_epub_dir,
    load_epub_heading_hierarchy,
)
from core.heading_classifier import (
    normalize_heading_str,
    is_part_or_book_heading,
    is_chapter_heading,
    is_frontmatter_or_backmatter,
    extract_heading_number,
    split_runon_heading,
    should_pair_headings,
    apply_paired_heading_format,
    sanitize_styles_xml,
)

try:
    from typography_es_common import *
except ImportError:
    from .typography_es_common import *


def presplit_compound_tables(root, epub_fmt):
    """Split compound paragraphs holding a Table plus surrounding text into separate pre/table/post PSRs."""
    for parent in list(root.iter()):
        children = list(parent)
        for idx, psr in enumerate(children):
            if lname(psr.tag) == "ParagraphStyleRange":
                t_csrs = [c for c in psr if any(lname(e.tag) == "Table" for e in c.iter())]
                if not t_csrs:
                    continue
                # Clean all table cells inside table
                for tc in t_csrs:
                    for tbl in tc.iter():
                        if lname(tbl.tag) == "Table":
                            _normalize_table_content(tbl, epub_fmt=epub_fmt)

                pre_csrs = []
                post_csrs = []
                seen_tbl = False
                for child in list(psr):
                    if child in t_csrs:
                        seen_tbl = True
                    elif not seen_tbl:
                        pre_csrs.append(child)
                    else:
                        post_csrs.append(child)

                pre_text = "".join(c.text for oc in pre_csrs for c in oc.iter() if lname(c.tag) == "Content" and c.text).strip()
                post_text = "".join(c.text for oc in post_csrs for c in oc.iter() if lname(c.tag) == "Content" and c.text).strip()

                if pre_text or post_text:
                    for child in list(psr):
                        psr.remove(child)
                    ins_idx = list(parent).index(psr)
                    # Use the LIVE position of psr, not the stale enumerate() idx:
                    # earlier compound table paragraphs in the same parent insert/
                    # remove siblings, so the snapshot index no longer matches and
                    # the split block would land before preceding paragraphs.

                    if pre_text:
                        _pre_attrib = dict(psr.attrib)
                        if any(k in _pre_attrib.get("AppliedParagraphStyle", "").lower() for k in ("quote", "block", "verse", "poem", "extract", "epigraph")):
                            _pre_attrib["Justification"] = "LeftAlign"  # block/quote: ragged, never justified
                        pre_psr = ET.Element("ParagraphStyleRange", _pre_attrib)
                        for pc in pre_csrs:
                            pre_psr.append(pc)
                        last_csr = None
                        for c in reversed(list(pre_psr)):
                            if lname(c.tag) == "CharacterStyleRange":
                                last_csr = c
                                break
                        if last_csr is None or not any(lname(child.tag) == "Br" for child in last_csr):
                            br_c = ET.SubElement(pre_psr, "CharacterStyleRange", {
                                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                            })
                            ET.SubElement(br_c, "Br")
                        parent.insert(ins_idx, pre_psr)
                        ins_idx += 1

                    table_psr = ET.Element("ParagraphStyleRange", {
                        "AppliedParagraphStyle": "ParagraphStyle/body_text",
                        "Justification": "LeftAlign",
                        "FirstLineIndent": "0",
                        "SpaceBefore": "6",
                        "SpaceAfter": "6",
                    })
                    for tc in t_csrs:
                        table_psr.append(tc)
                    last_t_csr = None
                    for c in reversed(list(table_psr)):
                        if lname(c.tag) == "CharacterStyleRange":
                            last_t_csr = c
                            break
                    if last_t_csr is None or not any(lname(child.tag) == "Br" for child in last_t_csr):
                        br_c = ET.SubElement(table_psr, "CharacterStyleRange", {
                            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                        })
                        ET.SubElement(br_c, "Br")
                    parent.insert(ins_idx, table_psr)
                    ins_idx += 1

                    if post_text:
                        # Block/quote tail after an embedded table stays in its block
                        # style (e.g. quotes_normal) instead of dropping to body_text.
                        _orig_style = psr.attrib.get("AppliedParagraphStyle", "")
                        _is_block = any(k in _orig_style.lower() for k in ("quote", "block", "verse", "poem", "extract", "epigraph"))
                        if _is_block:
                            _post_attrib = dict(psr.attrib)
                            _post_attrib["Justification"] = "LeftAlign"  # block/quote tail: ragged
                        else:
                            _post_attrib = {
                                "AppliedParagraphStyle": "ParagraphStyle/body_text",
                                "FirstLineIndent": "18",
                                "SpaceBefore": "1.5",
                                "SpaceAfter": "3",
                                "Justification": "LeftAlign" if " " in post_text else "LeftJustified",
                            }
                        post_psr = ET.Element("ParagraphStyleRange", _post_attrib)
                        for pc in post_csrs:
                            post_psr.append(pc)
                        last_p_csr = None
                        for c in reversed(list(post_psr)):
                            if lname(c.tag) == "CharacterStyleRange":
                                last_p_csr = c
                                break
                        if last_p_csr is None or not any(lname(child.tag) == "Br" for child in last_p_csr):
                            br_c = ET.SubElement(post_psr, "CharacterStyleRange", {
                                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                            })
                            ET.SubElement(br_c, "Br")
                        parent.insert(ins_idx, post_psr)

                    parent.remove(psr)


def split_table_csrs(psr, epub_fmt):
    """Pre-split CSRs that embed a Table so the table keeps its in-flow position, then left-align the paragraph."""
    for _csr in list(psr):
        if lname(_csr.tag) != "CharacterStyleRange":
            continue
        _kids = list(_csr)
        if not any(lname(_k.tag) == "Table" for _k in _kids):
            continue
        _non_tbl = [_k for _k in _kids if lname(_k.tag) not in ("Table", "Properties")]
        if not _non_tbl:
            continue  # table-only CSR: nothing to separate
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
    psr.set("FirstLineIndent", "0")
    psr.set("Justification", "LeftAlign")


def cleanup_character_styles(root, epub_underlines, stats):
    """Post-pass over every CSR: merge styles, fix runaway sub/superscript, enforce body font, validate underline."""
    # CharacterStyleRange cleanup (bold, italic, underline, runaway sub/sup, font family & size)
    for psr in root.iter():
        if lname(psr.tag) == "ParagraphStyleRange":
            pstyle = psr.attrib.get("AppliedParagraphStyle", "")
            is_body = any(k in pstyle.lower() for k in ["body_text", "noindent", "normal", "basic", "quotes_normal"])

            # Br-aware verse/block safety: ragged-left on verse or block/quote styles.
            _plines = _split_soft_lines(psr)
            _is_block_sty = any(k in pstyle.lower() for k in ("block", "quote", "verse", "poem"))
            _is_verse_p = _is_true_verse(psr)
            if _is_verse_p or _is_block_sty:
                _eff_just = psr.attrib.get("Justification")
                if _eff_just == "LeftJustified" or _eff_just is None:
                    psr.set("Justification", "LeftAlign")

            for csr in list(psr):
                if lname(csr.tag) == "CharacterStyleRange":
                    csr.set("AppliedLanguage", "$ID/Spanish: Standard")
                    cstyle = csr.attrib.get("AppliedCharacterStyle", "")
                    if cstyle in MERGE_MAP:
                        cstyle = MERGE_MAP[cstyle]
                        csr.set("AppliedCharacterStyle", cstyle)

                    # Clean runaway Subscript / Superscript
                    pos = csr.attrib.get("Position", "")
                    if pos in ("Subscript", "Superscript"):
                        has_table_inner = any(lname(c.tag) == "Table" for c in csr.iter())
                        raw_text = "".join(c.text for c in csr if lname(c.tag) == "Content" and c.text)
                        direct_text = raw_text.strip()
                        is_runaway = False
                        if has_table_inner or len(direct_text) > 5 or " " in raw_text or any(p in raw_text for p in [".", ",", ";", ":", "\u2028", "\r", "\n"]):
                            is_runaway = True
                        elif pos == "Subscript" and (not direct_text.isdigit() or len(direct_text) > 3):
                            is_runaway = True
                        elif pos == "Superscript" and not (direct_text.isdigit() or direct_text in ("*", "†", "‡", "§", "er", "o", "a", "os", "as")):
                            is_runaway = True

                        if is_runaway:
                            split_done = False
                            cnt_first = next((c for c in csr if lname(c.tag) == "Content" and c.text), None)
                            if cnt_first is not None and cnt_first.text:
                                first_txt = cnt_first.text
                                is_year = bool(re.match(r"^(18\d\d|19\d\d|20\d\d)", first_txt))
                                if not is_year:
                                    m_sub = None
                                    if pos == "Subscript":
                                        m_sub = re.match(r"^(\d{1,3})(.*)$", first_txt, re.S)
                                    elif pos == "Superscript":
                                        m_sub = re.match(r"^(\d{1,3}|[\*†‡§]|er|o|a|os|as)(.*)$", first_txt, re.S)

                                    if m_sub and m_sub.group(1) and m_sub.group(2):
                                        token_part = m_sub.group(1)
                                        rest_part = m_sub.group(2)
                                        c_sub = ET.Element(csr.tag, attrib=dict(csr.attrib))
                                        c_sub.set("Position", pos)
                                        for child in csr:
                                            if lname(child.tag) == "Properties":
                                                c_sub.append(copy.deepcopy(child))
                                        _ensure_font_prop(c_sub, "Palatino Linotype")
                                        sub_cnt = ET.SubElement(c_sub, "Content")
                                        sub_cnt.text = token_part

                                        cnt_first.text = rest_part
                                        del csr.attrib["Position"]
                                        if is_body:
                                            _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)

                                        idx = list(psr).index(csr)
                                        psr.insert(idx, c_sub)
                                        split_done = True

                            if not split_done:
                                del csr.attrib["Position"]
                                if is_body:
                                    _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                        else:
                            _ensure_font_prop(csr, "Palatino Linotype")

                    if "bold" in cstyle.lower() or csr.attrib.get("FontStyle") == "Bold":
                        csr.set("FontStyle", "Bold")
                        stats["bold_fixed"] += 1
                    if "italic" in cstyle.lower() or csr.attrib.get("FontStyle") == "Italic":
                        csr.set("FontStyle", "Italic")
                        stats["italic_fixed"] += 1

                    # Enforce uniform body font family & size
                    if is_body:
                        pos_now = csr.attrib.get("Position", "")
                        if pos_now not in ("Subscript", "Superscript"):
                            _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)

                    # Validate Underline
                    if cstyle == CANONICAL_CHAR_STYLES["underline"] or "underlin" in cstyle.lower():
                        c_text = "".join(c.text for c in csr.iter() if lname(c.tag) == "Content" and c.text).strip()
                        c_clean = c_text.lower().replace("\xa0", " ")
                        is_valid = False
                        if epub_underlines:
                            is_valid = any(c_clean == u or c_clean in u or u in c_clean for u in epub_underlines)
                        if not is_valid and re.search(r"\bfootnote\b|\bnota\b|\bref\b|\bsee\b|\bcf\b|\bpage\b|\bpág\b|\d{1,4}", c_clean):
                            is_valid = True
                        if not is_valid and len(c_clean) > 40:
                            csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                            if "Underline" in csr.attrib:
                                del csr.attrib["Underline"]
                        else:
                            stats["underline_fixed"] += 1


__all__ = [
    'presplit_compound_tables',
    'split_table_csrs',
    'cleanup_character_styles',
]

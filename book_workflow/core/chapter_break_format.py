import copy
import io
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _ln(tag):
    """Extracts local tag name by stripping XML namespace."""
    return tag.rsplit("}", 1)[-1]


def format_styles(root):
    """Normalizes paragraph styles for chapters to ensure proper page breaks and 14.5pt top spacing."""
    changed = False
    for ps in root.iter():
        if _ln(ps.tag) != "ParagraphStyle":
            continue
        name = (ps.attrib.get("Name", "") or "").lower()
        self_id = (ps.attrib.get("Self", "") or "").lower()
        if name == "body_text" or self_id == "paragraphstyle/body_text":
            # Injection drops the justified body style back to left; re-assert EPUB justification
            # (prose paragraphs that must stay ragged carry their own LeftAlign override).
            if ps.attrib.get("Justification") != "LeftJustified":
                ps.set("Justification", "LeftJustified")
                changed = True
        if "after_chapter_name_heading" in self_id or "after_chapter_name_heading" in name:
            if ps.attrib.get("StartParagraph") != "Anywhere":
                ps.set("StartParagraph", "Anywhere")
                changed = True
            if ps.attrib.get("SpaceBefore") != "14":
                ps.set("SpaceBefore", "14")
                changed = True
            if ps.attrib.get("SpaceAfter") != "30":
                ps.set("SpaceAfter", "30")
                changed = True
            if ps.attrib.get("Justification") != "CenterAlign":
                ps.set("Justification", "CenterAlign")
                changed = True
            if ps.attrib.get("FirstLineIndent") != "0":
                ps.set("FirstLineIndent", "0")
                changed = True
        elif ("chapter_name" in self_id or "chapter_name" in name) and "master" not in self_id and "after" not in self_id:
            if ps.attrib.get("StartParagraph") != "NextPage":
                ps.set("StartParagraph", "NextPage")
                changed = True
            if ps.attrib.get("SpaceBefore") != "14.5":
                ps.set("SpaceBefore", "14.5")
                changed = True
            if ps.attrib.get("SpaceAfter") != "30":
                ps.set("SpaceAfter", "30")
                changed = True
            if ps.attrib.get("RuleAbove") != "true":
                ps.set("RuleAbove", "true")
                ps.set("RuleAboveLineWeight", "0")
                ps.set("RuleAboveOffset", "14.5")
                ps.set("KeepRuleAboveInFrame", "true")
                changed = True
            if ps.attrib.get("Justification") != "CenterAlign":
                ps.set("Justification", "CenterAlign")
                changed = True
            if ps.attrib.get("FirstLineIndent") != "0":
                ps.set("FirstLineIndent", "0")
                changed = True
    return changed


def _strip_trailing_break(psr):
    """Removes any ParagraphBreakType=NextPage so nothing forces a page break AFTER this paragraph."""
    changed = False
    if "ParagraphBreakType" in psr.attrib:
        del psr.attrib["ParagraphBreakType"]
        changed = True
    for c in psr.findall("CharacterStyleRange"):
        if "ParagraphBreakType" in c.attrib:
            del c.attrib["ParagraphBreakType"]
            changed = True
    return changed


def _preceding_has_content(psr):
    """True unless psr is an empty, break-carrying spacer that lost its BlankPageSpacer marker during injection."""
    if any(_ln(c.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for c in psr.iter()):
        return True
    txt = "".join(psr.itertext()).strip("\ufeff\u2028\u00a0 \t\r\n")
    if txt:
        return True
    breaks = (
        psr.attrib.get("StartParagraph") == "NextPage"
        or psr.attrib.get("ParagraphBreakType") == "NextPage"
        or any(c.attrib.get("ParagraphBreakType") == "NextPage" for c in psr.findall("CharacterStyleRange"))
    )
    return not breaks


def format_stories(root):
    """Ensures chapter headings start on a fresh page without creating double blank pages,
    while preserving paired headings on the same page and 14.5pt top gap."""
    changed = False
    parent_map = {c: p for p in root.iter() for c in p}

    # Identify all chapter headings in this story
    chapter_psrs = []
    for psr in list(root.iter()):
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        style = (psr.attrib.get("AppliedParagraphStyle", "") or "").lower()
        if "chapter_name" in style or style.endswith("/master_chapter_name") or "after_chapter" in style or "sub-heading" in style:
            chapter_psrs.append(psr)

    for i, psr in enumerate(chapter_psrs):
        parent = parent_map.get(psr)
        if parent is None:
            continue
        kids = list(parent)
        if psr not in kids:
            continue
        idx = kids.index(psr)

        # Check if this heading immediately follows another heading (paired / double H1 heading)
        is_paired = False
        prev_idx = idx - 1
        while prev_idx >= 0:
            prev_elem = kids[prev_idx]
            if _ln(prev_elem.tag) == "ParagraphStyleRange":
                p_st = (prev_elem.attrib.get("AppliedParagraphStyle", "") or "").lower()
                p_tx = "".join(prev_elem.itertext()).strip()
                if (
                    "chapter_name" in p_st
                    or "sub-heading" in p_st
                    or "after_chapter" in p_st
                    or any(k in p_st for k in ["heading", "title", "part"])
                    or re.match(r"^\s*(?:PART|PARTE|BOOK|LIBRO|[IVXLCDM0-9]+)\b", p_tx, re.I)
                    or re.match(r"^\s*(?:PART|PARTE|BOOK|LIBRO|[IVXLCDM0-9]+)\b", "".join(psr.itertext()).strip(), re.I)
                ):
                    is_paired = True
                    break
                elif p_tx:
                    break
            prev_idx -= 1

        if is_paired:
            # Remove any trailing break on the preceding heading
            if _strip_trailing_break(kids[prev_idx]):
                changed = True
            # Clear breaks on any intervening empty elements
            for k in range(prev_idx + 1, idx):
                kid = kids[k]
                if _ln(kid.tag) == "ParagraphStyleRange":
                    if not "".join(kid.itertext()).replace("\ufeff", "").replace("\u2028", "").strip():
                        if "StartParagraph" in kid.attrib and kid.attrib["StartParagraph"] != "Anywhere":
                            kid.set("StartParagraph", "Anywhere")
                            changed = True
                        if _strip_trailing_break(kid):
                            changed = True
            # Second heading in a paired heading: stays on the SAME PAGE directly below
            if psr.attrib.get("AppliedParagraphStyle") != "ParagraphStyle/after_chapter_name_heading":
                psr.set("AppliedParagraphStyle", "ParagraphStyle/after_chapter_name_heading")
                changed = True
            if psr.attrib.get("StartParagraph") != "Anywhere":
                psr.set("StartParagraph", "Anywhere")
                changed = True
            if "ParagraphBreakType" in psr.attrib:
                del psr.attrib["ParagraphBreakType"]
                changed = True
            for csr in psr.findall("CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib:
                    del csr.attrib["ParagraphBreakType"]
                    changed = True
            if psr.attrib.get("SpaceBefore") != "14":
                psr.set("SpaceBefore", "14")
                changed = True
            if psr.attrib.get("SpaceAfter") != "30":
                psr.set("SpaceAfter", "30")
                changed = True
            if psr.attrib.get("Justification") != "CenterAlign":
                psr.set("Justification", "CenterAlign")
                changed = True
            if psr.attrib.get("FirstLineIndent") != "0":
                psr.set("FirstLineIndent", "0")
                changed = True
            continue

        # A standalone sub-heading (an in-text h2, not a true chapter_name) must stay on the
        # same page as the surrounding prose and never force a page break.
        style_l = (psr.attrib.get("AppliedParagraphStyle", "") or "").lower()
        if "sub-heading" in style_l and "chapter_name" not in style_l and "master_chapter" not in style_l:
            if psr.attrib.get("StartParagraph") not in (None, "Anywhere"):
                psr.set("StartParagraph", "Anywhere")
                changed = True
            if _strip_trailing_break(psr):
                changed = True
            prev_child = kids[idx - 1] if idx > 0 else None
            if (prev_child is not None and _ln(prev_child.tag) == "ParagraphStyleRange"
                    and not _preceding_has_content(prev_child)):
                if prev_child.attrib.get("StartParagraph") == "NextPage":
                    prev_child.set("StartParagraph", "Anywhere")
                    changed = True
                if _strip_trailing_break(prev_child):
                    changed = True
            continue

        # Main chapter heading: must have 14.5 gap
        if psr.attrib.get("SpaceBefore") != "14.5":
            psr.set("SpaceBefore", "14.5")
            changed = True
        if psr.attrib.get("SpaceAfter") != "30":
            psr.set("SpaceAfter", "30")
            changed = True
        if psr.attrib.get("Justification") != "CenterAlign":
            psr.set("Justification", "CenterAlign")
            changed = True
        if psr.attrib.get("FirstLineIndent") != "0":
            psr.set("FirstLineIndent", "0")
            changed = True

        # Check preceding element
        prev_child = kids[idx - 1] if idx > 0 else None
        prev_is_spacer = False
        if prev_child is not None and _ln(prev_child.tag) == "ParagraphStyleRange":
            if prev_child.attrib.get("BlankPageSpacer") == "true" or prev_child.attrib.get("BlankPageProtected") == "true":
                prev_is_spacer = True
            elif i > 0 and not _preceding_has_content(prev_child):
                prev_is_spacer = True

        if prev_is_spacer:
            # One break-before on the spacer moves the chapter to a fresh page; the heading
            # and its body then flow together, so no trailing page breaks are kept on either.
            if i == 0:
                # NextOddPage is the front-matter flow (first content page is always odd): never reset it.
                if prev_child.attrib.get("StartParagraph") not in (None, "Anywhere", "NextOddPage"):
                    prev_child.set("StartParagraph", "Anywhere")
                    changed = True
            else:
                if prev_child.attrib.get("StartParagraph") != "NextPage":
                    prev_child.set("StartParagraph", "NextPage")
                    changed = True
            if _strip_trailing_break(prev_child):
                changed = True
            if psr.attrib.get("StartParagraph") != "Anywhere":
                psr.set("StartParagraph", "Anywhere")
                changed = True
            if _strip_trailing_break(psr):
                changed = True
        else:
            # No spacer: the heading itself carries the single break-before, with no trailing break.
            if i == 0:
                if psr.attrib.get("StartParagraph") != "Anywhere":
                    psr.set("StartParagraph", "Anywhere")
                    changed = True
            else:
                if psr.attrib.get("StartParagraph") != "NextPage":
                    psr.set("StartParagraph", "NextPage")
                    changed = True
            if _strip_trailing_break(psr):
                changed = True

    for psr in root.iter():
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        csrs = [c for c in psr if _ln(c.tag) == "CharacterStyleRange"]
        if len(csrs) >= 2:
            c1, c2 = csrs[0], csrs[1]
            br1 = any(_ln(x.tag) == "Br" for x in c1)
            br2 = any(_ln(x.tag) == "Br" for x in c2)
            pbt1 = c1.attrib.get("ParagraphBreakType") == "NextPage"
            txt1 = "".join(c1.itertext()).strip()
            txt2 = "".join(c2.itertext())
            if br1 and br2 and pbt1 and not txt1 and ("\u2028" in txt2 or not txt2.strip()):
                psr.remove(c1)
                psr.set("StartParagraph", "NextPage")
                if "ParagraphBreakType" in psr.attrib:
                    del psr.attrib["ParagraphBreakType"]
                changed = True
    return changed


def _direct_text_excluding_tables(psr):
    """Returns the paragraph's own text, not counting any text inside nested tables."""
    out = []
    for csr in psr:
        if _ln(csr.tag) != "CharacterStyleRange":
            continue
        for ch in csr:
            if _ln(ch.tag) == "Content":
                out.append(ch.text or "")
    return "".join(out)


def _strip_leading_blank_lines(psr):
    """Removes blank lines (leading Br / empty Content) at the very start of a paragraph,
    which a table above often leaves behind as an oversized gap. Stops at the first real
    content and never touches a Properties element."""
    changed = False
    for csr in psr:
        if _ln(csr.tag) != "CharacterStyleRange":
            continue
        for child in list(csr):
            tag = _ln(child.tag)
            if tag == "Properties":
                continue
            if tag == "Br" or (tag == "Content" and not (child.text or "").strip()):
                csr.remove(child)
                changed = True
                continue
            return changed
        if any(_ln(c.tag) == "Table" for c in csr):
            break
    return changed


def collapse_table_trailing_gap(root):
    """Collapses the oversized gap a table leaves above the following paragraph.

    A table-only paragraph and the paragraph after it often carry extra blank lines (the
    paragraph-return under the table, plus leading Br runs at the start of the next
    paragraph) that push the following prose far below the table. Those blank lines are
    removed so the gap after a table matches a normal inter-paragraph gap. Paragraphs that
    carry their own prose alongside a table are left untouched."""
    changed = False
    parent_map = {c: p for p in root.iter() for c in p}
    for psr in list(root.iter()):
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        has_table = any(
            _ln(t.tag) == "Table"
            for csr in psr if _ln(csr.tag) == "CharacterStyleRange"
            for t in csr
        )
        if not has_table or _direct_text_excluding_tables(psr).strip():
            continue
        if psr.attrib.get("SpaceAfter") not in ("0",):
            psr.set("SpaceAfter", "0")
            changed = True
        parent = parent_map.get(psr)
        if parent is None:
            continue
        sibs = list(parent)
        idx = sibs.index(psr)
        for k in range(idx + 1, len(sibs)):
            nxt = sibs[k]
            if _ln(nxt.tag) == "ParagraphStyleRange":
                if _strip_leading_blank_lines(nxt):
                    changed = True
                break
    return changed


def _split_br_prose_psr(psr):
    """Splits a body_text paragraph that collapsed several sentence-paragraphs into one PSR
    (separated by forced line breaks) back into separate paragraphs, so each justifies on its
    own with a ragged last line. Returns the list of new PSRs, or None when not applicable."""
    style = (psr.attrib.get("AppliedParagraphStyle", "") or "").lower()
    if "body_text" not in style:
        return None
    if any(_ln(x.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for x in psr.iter()):
        return None
    csrs = [c for c in psr if _ln(c.tag) == "CharacterStyleRange"]
    if not csrs:
        return None
    segments = []
    cur = []
    for csr in csrs:
        run = []
        for ch in csr:
            if _ln(ch.tag) == "Properties":
                continue
            if _ln(ch.tag) == "Br":
                cur.append((csr, run))
                segments.append(cur)
                cur, run = [], []
            else:
                run.append(ch)
        if run:
            cur.append((csr, run))
    if cur:
        segments.append(cur)
    seg_texts = []
    for seg in segments:
        t = "".join(c.text or "" for _, r in seg for c in r if _ln(c.tag) == "Content").strip()
        seg_texts.append(t)
    non_empty = [t for t in seg_texts if t]
    if len(non_empty) < 2:
        return None
    end_sent = sum(1 for t in non_empty if t.endswith((".", "!", "?", "»", "”", '"')))
    avg_len = sum(len(t) for t in non_empty) / len(non_empty)
    if end_sent / len(non_empty) < 0.6 or avg_len < 40:
        return None
    new_psrs = []
    for seg, t in zip(segments, seg_texts):
        if not t:
            continue
        npsr = ET.Element(psr.tag, dict(psr.attrib))
        if npsr.attrib.get("Justification") == "LeftAlign":
            del npsr.attrib["Justification"]
        for csr, run in seg:
            ncsr = ET.Element(csr.tag, dict(csr.attrib))
            props = csr.find("Properties")
            if props is not None:
                ncsr.append(copy.deepcopy(props))
            for ch in run:
                ncsr.append(copy.deepcopy(ch))
            npsr.append(ncsr)
        last = [c for c in npsr if _ln(c.tag) == "CharacterStyleRange"]
        if last:
            ET.SubElement(last[-1], "Br")
        new_psrs.append(npsr)
    return new_psrs if len(new_psrs) >= 2 else None


def split_br_prose_paragraphs(root):
    """Splits Br-collapsed prose paragraphs across every story container so justified body text
    no longer stretches forced-break lines (a Spanish-source artifact)."""
    changed = False
    for parent in list(root.iter()):
        kids = list(parent)
        if not any(_ln(c.tag) == "ParagraphStyleRange" for c in kids):
            continue
        rebuilt = []
        local_changed = False
        for c in kids:
            if _ln(c.tag) == "ParagraphStyleRange":
                res = _split_br_prose_psr(c)
                if res:
                    rebuilt.extend(res)
                    local_changed = True
                    continue
            rebuilt.append(c)
        if local_changed:
            for c in list(parent):
                parent.remove(c)
            for c in rebuilt:
                parent.append(c)
            changed = True
    return changed


def fix_apostrophe_glyphs(root):
    """Restores apostrophes that the source stored as single angle quotes (U+2039/U+203A)
    between letters (e.g. Elizabeth›s -> Elizabeth’s). Paired ‹ › guillemets
    around a phrase are left untouched because at least one side borders a non-letter."""
    changed = False
    for c in root.iter():
        if _ln(c.tag) != "Content" or not c.text:
            continue
        new = re.sub(r"(?<=[^\W\d_])[‹›](?=[^\W\d_])", "’", c.text)
        if new != c.text:
            c.text = new
            changed = True
    return changed


def _content_text(psr):
    return "".join(c.text or "" for c in psr.iter() if _ln(c.tag) == "Content")


def _norm_alnum(s):
    return re.sub(r"[^0-9a-z]", "", s.lower())


def remove_duplicate_above_captions(root):
    """Removes a caption that was left ABOVE an image when the same caption is also placed
    BELOW it (the EPUB caption injection adds the lower one; the stray upper one must go)."""
    changed = False
    for parent in list(root.iter()):
        kids = list(parent)
        for i, el in enumerate(kids):
            if _ln(el.tag) != "ParagraphStyleRange":
                continue
            if not any(_ln(x.tag) in ("Rectangle", "Image") for x in el.iter()):
                continue
            after = None
            for j in range(i + 1, min(len(kids), i + 3)):
                if _ln(kids[j].tag) == "ParagraphStyleRange" and _content_text(kids[j]).strip():
                    after = kids[j]
                    break
            before = None
            for j in range(i - 1, max(-1, i - 3), -1):
                if _ln(kids[j].tag) == "ParagraphStyleRange":
                    if any(_ln(x.tag) in ("Rectangle", "Image", "Table") for x in kids[j].iter()):
                        break
                    if _content_text(kids[j]).strip():
                        before = kids[j]
                        break
            if after is None or before is None:
                continue
            at, bt = _norm_alnum(_content_text(after)), _norm_alnum(_content_text(before))
            if at and bt and at == bt and len(at) > 8:
                parent.remove(before)
                changed = True
    return changed


_fix_styles = format_styles
_fix_stories = format_stories


def restore_footer_page_number(stories_dir):
    """ElementTree drops the <?ACE 18?> auto-page-number marker on every rewrite. Re-insert it
    into the master running-foot stories (those carrying the Running Header variable) so page
    numbers reappear on the content pages that use that master."""
    changed = False
    for fn in os.listdir(stories_dir):
        if not fn.lower().endswith(".xml"):
            continue
        fp = os.path.join(stories_dir, fn)
        try:
            txt = io.open(fp, encoding="utf-8").read()
        except Exception:
            continue
        if 'Name="Running Header"' not in txt or "<?ACE 18?>" in txt:
            continue
        m = re.search(r"(<Content>)([^<]*\|[^<]*)(</Content>)", txt)
        if not m:
            continue
        # On a recto foot the running-header title sits BEFORE the folio content,
        # so the page number must follow the separator ("Title | 37"); on a verso
        # the title follows, so the number leads ("38 | Title").
        title_pos = txt.find("TextVariableInstance")
        if 0 <= title_pos < m.start():
            new = m.group(1) + m.group(2) + "<?ACE 18?>" + m.group(3)
        else:
            new = m.group(1) + "<?ACE 18?>" + m.group(2) + m.group(3)
        txt = txt[:m.start()] + new + txt[m.end():]
        io.open(fp, "w", encoding="utf-8").write(txt)
        changed = True
    return changed


def apply_to_idml(idml_path):
    """Applies chapter break formatting to an IDML file in-place."""
    idml_path = str(idml_path)
    tmpd = tempfile.mkdtemp(prefix="idml_chbreak_")
    try:
        with zipfile.ZipFile(idml_path, "r") as z:
            names = z.namelist()
            z.extractall(tmpd)
        any_changed = False

        styles_fp = os.path.join(tmpd, "Resources", "Styles.xml")
        if os.path.isfile(styles_fp):
            try:
                tree = ET.parse(styles_fp)
                if format_styles(tree.getroot()):
                    tree.write(styles_fp, xml_declaration=True, encoding="UTF-8")
                    any_changed = True
            except ET.ParseError:
                pass

        stories_dir = os.path.join(tmpd, "Stories")
        if os.path.isdir(stories_dir):
            for fn in os.listdir(stories_dir):
                if not fn.lower().endswith(".xml"):
                    continue
                fp = os.path.join(stories_dir, fn)
                try:
                    tree = ET.parse(fp)
                except ET.ParseError:
                    continue
                root = tree.getroot()
                story_changed = format_stories(root)
                if fix_apostrophe_glyphs(root):
                    story_changed = True
                if remove_duplicate_above_captions(root):
                    story_changed = True
                if split_br_prose_paragraphs(root):
                    story_changed = True
                if collapse_table_trailing_gap(root):
                    story_changed = True
                if story_changed:
                    tree.write(fp, xml_declaration=True, encoding="UTF-8")
                    any_changed = True
            if restore_footer_page_number(stories_dir):
                any_changed = True

        if any_changed:
            tmp_zip = os.path.join(tmpd, "repacked.idml")
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
                first = "mimetype"
                if first in names:
                    zout.write(os.path.join(tmpd, first), first, compress_type=zipfile.ZIP_STORED)
                for nm in names:
                    if nm == first:
                        continue
                    fp = os.path.join(tmpd, nm)
                    if os.path.isfile(fp):
                        zout.write(fp, nm, compress_type=zipfile.ZIP_DEFLATED)
            shutil.move(tmp_zip, idml_path)
        return any_changed
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


fix_chapter_breaks = apply_to_idml

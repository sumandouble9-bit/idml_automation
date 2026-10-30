import re
import xml.etree.ElementTree as ET
from collections import defaultdict

MIN_BLOCK = 5


def _lname(tag):
    return tag.rsplit("}", 1)[-1]


def _norm(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("\u2028", " ").replace("\ufeff", "")
    return re.sub(r"\s+", " ", s).strip().lower().rstrip(".;:, ")


def _is_caption(p):
    return "caption" in p.attrib.get("AppliedParagraphStyle", "").lower()


def _is_image(p):
    return any(_lname(e.tag) == "Rectangle" for e in p.iter())


def _ctext(p):
    return _norm("".join(c.text or "" for c in p.iter() if _lname(c.tag) == "Content"))


def _sig(p):
    return (p.attrib.get("AppliedParagraphStyle", ""), _ctext(p), _is_image(p))


def _remove(parent, elems):
    changed = False
    for p in elems:
        par = parent.get(p)
        if par is not None:
            try:
                par.remove(p); changed = True
            except ValueError:
                pass
    return changed


FIG_START = re.compile(r"^\s*fig(?:ure|ura|s)?\.?\s*\d", re.I)


def _first_br(psr):
    """Return (br_element, its_CharacterStyleRange) for the FIRST <Br> in psr."""
    for csr in psr:
        if _lname(csr.tag) != "CharacterStyleRange":
            continue
        for e in list(csr):
            if _lname(e.tag) == "Br":
                return e, csr
    return None, None


def _text_after(psr, br):
    seen = False
    out = []
    for csr in psr:
        if _lname(csr.tag) != "CharacterStyleRange":
            continue
        for e in list(csr):
            if e is br:
                seen = True
                continue
            if seen and _lname(e.tag) == "Content":
                out.append(e.text or "")
    return "".join(out)


def _fix_caption_overflow(sroot):
    """A caption paragraph shaped as `caption <Br> OVERFLOW` is wrong: the caption
    must stand alone below its image. Two kinds of overflow:
      * another "Fig N ..." caption (a stray/duplicate belonging to a different
        figure that already has its own caption) -> DELETE the overflow.
      * a long run of body prose that got merged into the caption -> SPLIT it off
        into its own justified body_text paragraph (so it is no longer ragged).
    Only the part AFTER the first <Br> is touched; the caption line is kept.
    """
    changed = False
    psrs = [p for p in sroot.iter() if _lname(p.tag) == "ParagraphStyleRange"]
    parent = {c: p for p in sroot.iter() for c in p}
    for psr in psrs:
        if not _is_caption(psr):
            continue
        br, br_csr = _first_br(psr)
        if br is None:
            continue
        after = re.sub(r"\s+", " ", _text_after(psr, br)).strip()
        if len(after) < 40:                      # short -> genuine 2-line caption
            continue
        # Collect the elements that live AFTER the first <Br>: the tail of br_csr
        # plus every following CharacterStyleRange.
        kids = list(br_csr)
        bi = kids.index(br)
        tail_in_csr = kids[bi + 1:]
        following_csrs = []
        hit = False
        for csr in psr:
            if csr is br_csr:
                hit = True
                continue
            if hit and _lname(csr.tag) == "CharacterStyleRange":
                following_csrs.append(csr)

        if FIG_START.match(after):
            # Overflow is another figure caption -> delete it; keep caption + <Br>.
            for e in tail_in_csr:
                br_csr.remove(e)
            for csr in following_csrs:
                psr.remove(csr)
            changed = True
            continue

        if len(after) >= 150:
            # Overflow is body prose -> move it into a new justified paragraph.
            ppar = parent.get(psr)
            if ppar is None:
                continue
            new = ET.Element(psr.tag)
            new.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
            new.set("Justification", "LeftJustified")
            if tail_in_csr:
                ncsr = ET.SubElement(new, br_csr.tag)
                for k, v in br_csr.attrib.items():
                    ncsr.set(k, v)
                for e in tail_in_csr:
                    br_csr.remove(e)
                    ncsr.append(e)
            for csr in following_csrs:
                psr.remove(csr)
                new.append(csr)
            # Guarantee both paragraphs end with a <Br> terminator.
            def _ends_with_br(p):
                cs = [c for c in p if _lname(c.tag) == "CharacterStyleRange"]
                if not cs:
                    return False
                k = list(cs[-1])
                return bool(k) and _lname(k[-1].tag) == "Br"
            if not _ends_with_br(new):
                cs = [c for c in new if _lname(c.tag) == "CharacterStyleRange"]
                if cs:
                    ET.SubElement(cs[-1], "Br")
            idx = list(ppar).index(psr)
            ppar.insert(idx + 1, new)
            changed = True
    return changed


def dedup_captions(sroot):
    changed = False
    changed = _fix_caption_overflow(sroot) or changed
    # ---- pass 1: whole duplicated blocks, anchored on a repeated caption ----
    psrs = [p for p in sroot.iter() if _lname(p.tag) == "ParagraphStyleRange"]
    parent = {c: p for p in sroot.iter() for c in p}
    n = len(psrs)
    sigs = [_sig(p) for p in psrs]
    cap_pos = defaultdict(list)
    for i, p in enumerate(psrs):
        if _is_caption(p):
            t = sigs[i][1]
            if len(t) >= 6:
                cap_pos[t].append(i)
    removed = set()
    for t, pos in cap_pos.items():
        if len(pos) < 2:
            continue
        i = pos[0]
        for j in pos[1:]:
            if psrs[j] in removed or psrs[i] in removed:
                continue
            b = 0
            while i + b < j and j + b < n and psrs[j + b] not in removed and sigs[i + b] == sigs[j + b]:
                b += 1
            a = 0
            while i - a - 1 >= 0 and j - a - 1 >= i + b and psrs[j - a - 1] not in removed and sigs[i - a - 1] == sigs[j - a - 1]:
                a += 1
            if a + b >= MIN_BLOCK:
                for k in range(j - a, j + b):
                    removed.add(psrs[k])
    if removed:
        changed = _remove(parent, removed) or changed

    # ---- pass 2: adjacent duplicated figure / stray top caption ----
    psrs = [p for p in sroot.iter() if _lname(p.tag) == "ParagraphStyleRange"]
    parent = {c: p for p in sroot.iter() for c in p}
    n = len(psrs)
    to_remove = set()
    for i in range(n):
        pi = psrs[i]
        if pi in to_remove or not _is_caption(pi):
            continue
        ti = _ctext(pi)
        if len(ti) < 6:
            continue
        for j in range(i + 1, min(i + 6, n)):
            pj = psrs[j]
            if pj in to_remove or not _is_caption(pj) or _ctext(pj) != ti:
                continue
            img_i = i > 0 and _is_image(psrs[i - 1])
            img_j = j > 0 and _is_image(psrs[j - 1])
            if img_i and img_j:
                to_remove.add(pj); to_remove.add(psrs[j - 1])
            elif img_j and not img_i:
                to_remove.add(pi)
            else:
                to_remove.add(pj)
            break
    if to_remove:
        changed = _remove(parent, to_remove) or changed
    return changed

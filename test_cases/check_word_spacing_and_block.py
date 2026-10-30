import re
import zipfile

# Styles / content that are NOT body prose and are never audited.
SKIP_STYLE = ("chapter", "head", "toc", "title", "verso", "copyright", "caption",
              "author", "folio", "running", "page", "index", "content", "fig ",
              "quote", "block", "verse", "poem", "epigraph", "foot", "note",
              "centre", "center", "subtitle", "doublenine", "master")
SKIP_CONTENT = re.compile(
    r"^(chapter|cap[íi]tulo|parte|part|libro|book|act[oe]?|canto|secci[oó]n|"
    r"section|appendix|ap[eé]ndice|preface|prefacio|introduction|introducci[oó]n|"
    r"note|nota)\b", re.I)
SKIP_FOOTNOTE = re.compile(r"^(\[\s*(\d{1,3}|[a-zA-Z])\s*\]|\{\s*nota|\[\s*nota|\[\s*note)", re.I)
CAPTION = re.compile(r"^(fig(ure|ura|s)?\.?\s|plate|table|tabla|cuadro|l[áa]m(ina)?|il?ustraci[oó]n|image|imagen)\b", re.I)

# A body paragraph long enough to wrap past two lines; shorter ones render the
# same whether ragged or justified, so they are exempt.
WRAP_MIN_CHARS = 150

# Body word-spacing ceiling (percent). InDesign default max is 133; above this
# justified lines stretch the gaps between words visibly.
WS_MAX = 133.0


def _styles(idml):
    with zipfile.ZipFile(idml) as z:
        return z.read("Resources/Styles.xml").decode("utf-8", "replace")


def _stories(idml):
    out = {}
    with zipfile.ZipFile(idml) as z:
        for n in z.namelist():
            if n.startswith("Stories/") and n.endswith(".xml"):
                out[n] = z.read(n).decode("utf-8", "replace")
    return out


def _style_table(styles_xml):
    tbl = {}
    for m in re.finditer(r'<ParagraphStyle\b[^>]*Self="(ParagraphStyle/[^"]+)"[^>]*>', styles_xml):
        end = styles_xml.find("</ParagraphStyle>", m.start())
        blk_full = styles_xml[m.start():end]
        head = blk_full[:blk_full.find(">") + 1]
        mj = re.search(r'Justification="([^"]+)"', head)
        mw = re.search(r'MaximumWordSpacing="([^"]+)"', head)
        based = re.search(r'<BasedOn[^>]*>([^<]+)</BasedOn>', blk_full)
        tbl[m.group(1)] = {"Justification": mj.group(1) if mj else None,
                           "MaximumWordSpacing": mw.group(1) if mw else None,
                           "BasedOn": based.group(1).strip() if based else None}
    return tbl


def _eff_attr(tbl, style_id, attr, _depth=0):
    """Effective attribute value, resolving the BasedOn inheritance chain
    (InDesign drops an attribute when it equals the parent's value)."""
    if not style_id or _depth > 10:
        return None
    sdef = tbl.get(style_id)
    if sdef is None:
        return None
    if sdef.get(attr) is not None:
        return sdef[attr]
    return _eff_attr(tbl, sdef.get("BasedOn"), attr, _depth + 1)


def _eff_just(tbl, style_id):
    return _eff_attr(tbl, style_id, "Justification")


def _plain_text(psr_xml):
    txt = "".join(re.findall(r"<Content>(.*?)</Content>", psr_xml, re.S))
    txt = re.sub(r"<[^>]+>", "", txt)
    return txt.replace(" ", " ").strip()


JUSTIFIED = ("LeftJustified", "FullyJustified", "RightJustified", "CenterJustified")


def check(injected_idml):
    reasons = []
    tbl = _style_table(_styles(injected_idml))

    # Word spacing: the body style's max word spacing must stay tight so justified
    # lines do not stretch the gaps between words.
    if "ParagraphStyle/body_text" in tbl:
        maxws = _eff_attr(tbl, "ParagraphStyle/body_text", "MaximumWordSpacing")
        if maxws is not None and float(maxws) > WS_MAX + 0.01:
            reasons.append("WORD_SPACING: body_text MaximumWordSpacing=%s (too loose; keep <=%g so words do not stretch)"
                           % (maxws, WS_MAX))

    for _n, xml in _stories(injected_idml).items():
        for m in re.finditer(r"<ParagraphStyleRange\b([^>]*)>(.*?)</ParagraphStyleRange>", xml, re.S):
            head, body_xml = m.group(1), m.group(2)
            if "<Table" in body_xml:
                continue
            msty = re.search(r'AppliedParagraphStyle="([^"]+)"', head)
            sfull = msty.group(1) if msty else ""
            sname = sfull.lower()
            if any(k in sname for k in SKIP_STYLE):
                continue
            text = _plain_text(body_xml)
            if len(text) <= WRAP_MIN_CHARS:          # too short to wrap -> exempt
                continue
            if SKIP_CONTENT.match(text) or SKIP_FOOTNOTE.match(text):
                continue
            if CAPTION.match(text):                  # figure / plate / table captions
                continue
            if " " in body_xml or body_xml.count("<Br") >= 2:
                # forced line breaks (soft  , or 2+ <Br> beyond the trailing
                # paragraph mark) = verse / list / structured content. It renders as
                # separate lines regardless of justification, so never flag it.
                continue

            # Verse / poetry: 3+ forced lines, (almost) all short. Such paragraphs
            # are legitimately ragged, so they are not a justification violation.
            raw = "".join(re.findall(r"<Content>(.*?)</Content>", body_xml, re.S))
            raw = re.sub(r"<[^>]+>", " ", raw)  # treat <Br> as a line break too
            segs = [s.strip() for s in raw.split(" ") if s.strip()]
            if len(segs) >= 3 and sum(1 for s in segs if len(s) < 55) >= len(segs) - 1:
                continue

            just = re.search(r'Justification="([^"]+)"', head)
            just = just.group(1) if just else _eff_just(tbl, sfull)
            # Only ragged-LEFT body prose is a violation. CenterAlign / RightAlign are
            # deliberate alignment choices (verse, captions, headings), not violations.
            if just == "LeftAlign":
                reasons.append("BODY_ALIGN: body paragraph not justified '%s' (must be justified)" % text[:34])

    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r); out.append(r)
    return out


if __name__ == "__main__":
    import sys
    rs = check(sys.argv[1])
    if rs:
        print("FAIL (%d):" % len(rs))
        for r in rs[:40]:
            print("  -", r)
        sys.exit(1)
    print("PASS: body paragraphs justified + word spacing tight")

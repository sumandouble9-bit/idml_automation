import os, re, zipfile

PH = re.compile(r"###Insert\s+(image\d+)", re.I)


def _read_stories(idml_path):
    out = {}
    with zipfile.ZipFile(idml_path) as z:
        for n in z.namelist():
            if n.startswith("Stories/") and n.endswith(".xml"):
                out[n] = z.read(n).decode("utf-8", "replace")
    return out


def source_pairs(source_idml):
    """Return list of frozenset pairs from source-IDML table rows."""
    pairs = []
    for _, xml in _read_stories(source_idml).items():
        for tm in re.finditer(r"<Table\b.*?</Table>", xml, re.S):
            tbl = tm.group(0)
            # placeholders per row: each <Cell ...>...</Cell> is one cell; a
            # 1-row 2-col image table yields 2 cells each with a placeholder.
            cells = re.findall(r"<Cell\b.*?</Cell>", tbl, re.S)
            names = []
            for c in cells:
                m = PH.search(c)
                if m:
                    names.append(m.group(1).lower())
            for i in range(len(names) - 1):
                pairs.append(frozenset((names[i], names[i + 1])))
    return pairs


def _table_span_of_image(xml, imgname):
    """(start, end) char span of the <Table>...</Table> enclosing the image whose
    link URI ends with imgname.jpg, else None. Side-by-side images are placed in
    CELLS of one borderless row-table, so a pair is correct iff both images fall
    inside the SAME table span (stacked/overlapping pairs are not in one table)."""
    uri = "/%s.jpg" % imgname
    i = xml.find(uri)
    if i < 0:
        return None
    topen = xml.rfind("<Table ", 0, i)
    if topen < 0:
        return None
    tclose = xml.find("</Table>", topen)
    if tclose < 0 or tclose < i:
        return None
    return (topen, tclose)


def check(source_idml, injected_idml):
    """Return (ok, details). ok=False if any source pair is NOT in one table."""
    pairs = source_pairs(source_idml)
    if not pairs:
        return True, "no side-by-side pairs in source"
    stories = _read_stories(injected_idml)
    problems = []
    for pr in pairs:
        a, b = sorted(pr)
        found_together = False
        for _, xml in stories.items():
            if ("/%s.jpg" % a) in xml and ("/%s.jpg" % b) in xml:
                ta = _table_span_of_image(xml, a)
                tb = _table_span_of_image(xml, b)
                if ta is not None and ta == tb:
                    found_together = True
                    break
        if not found_together:
            problems.append("%s|%s" % (a, b))
    ok = not problems
    detail = "pairs=%d ok=%s not_side_by_side=%s" % (len(pairs), ok, ",".join(problems) or "none")
    return ok, detail


if __name__ == "__main__":
    import sys
    src, inj = sys.argv[1], sys.argv[2]
    ok, det = check(src, inj)
    print(("PASS" if ok else "FAIL") + ": SIDEBYSIDE " + det)
    sys.exit(0 if ok else 1)

import re as _re
import zipfile as _zip


def check(idml_path):
    """Verify paired continuation headings are NOT force-broken: the
    'after_chapter_name_heading' style and its paragraphs must not start a new page
    (same EPUB chapter id => headings share one page)."""
    bad = []
    try:
        with _zip.ZipFile(idml_path) as z:
            st = z.read("Resources/Styles.xml").decode("utf-8", "replace")
            m = _re.search(r'<ParagraphStyle\b[^>]*Self="ParagraphStyle/after_chapter_name_heading"[^>]*>', st)
            if m and _re.search(r'StartParagraph="NextPage"', m.group(0)):
                bad.append("style=NextPage")
            npar = 0
            for n in z.namelist():
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                x = z.read(n).decode("utf-8", "replace")
                for mm in _re.finditer(r"<ParagraphStyleRange\b([^>]*)>", x):
                    tag = mm.group(1)
                    if 'AppliedParagraphStyle="ParagraphStyle/after_chapter_name_heading"' in tag \
                       and _re.search(r'StartParagraph="NextPage"', tag):
                        npar += 1
            if npar:
                bad.append("%d paragraph(s)=NextPage" % npar)
    except Exception as e:
        return ["HEADING_PAIR_CHECK_ERROR=%s" % e]
    if bad:
        return ["HEADING_PAIR_BROKEN=%s" % ",".join(bad)]
    return []

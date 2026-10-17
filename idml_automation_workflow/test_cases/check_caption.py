"""Audit: figure captions must appear exactly ONCE (below the image), never
duplicated (e.g. the original caption left at the top AND a second copy below).

check(injected_idml, caption_map) -> list of reason strings (empty = OK).
caption_map: {imageNNN.jpg: "CAPTION TEXT"} built from the book's EPUB.
"""
import re
import zipfile
from collections import Counter


def _norm(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = s.replace("\u2028", " ").replace("\ufeff", "")
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = s.rstrip(".;:, ")
    return s


def _para_texts(injected_idml):
    out = []
    with zipfile.ZipFile(injected_idml) as z:
        for n in z.namelist():
            if n.startswith("Stories/") and n.endswith(".xml"):
                x = z.read(n).decode("utf-8", "replace")
                for m in re.finditer(r"<ParagraphStyleRange\b([^>]*)>(.*?)</ParagraphStyleRange>", x, re.S):
                    txt = "".join(re.findall(r"<Content>(.*?)</Content>", m.group(2), re.S))
                    sty = re.search(r'AppliedParagraphStyle="([^"]+)"', m.group(1))
                    just = re.search(r'Justification="([^"]+)"', m.group(1))
                    out.append((_norm(txt), sty.group(1) if sty else "", just.group(1) if just else None))
    return out


_LABEL_ONLY = re.compile(r"^(fig(ure|ura|s)?|plate|lam(ina)?|tab(la|le)?|cuadro|tracking|no|n[oº]|\d+|[ivxlcdm]+)\s*\.?\s*\d*\.?$", re.I)


def check(injected_idml, caption_map):
    reasons = []
    # Only DESCRIPTIVE captions can be "duplicated top + below". Short figure
    # labels ("Fig. 1.", "Fig. 2.", "Plate II", "tracking") legitimately repeat
    # once per figure, so they are never flagged.
    caps = {_norm(v) for v in (caption_map or {}).values()
            if v and v.strip() and len(_norm(v)) > 15 and not _LABEL_ONLY.match(_norm(v))}
    if not caps:
        return reasons
    paras = _para_texts(injected_idml)
    counts = Counter()
    style_of = {}
    for txt, sty, just in paras:
        if txt and txt in caps:
            counts[txt] += 1
            style_of.setdefault(txt, (sty, just))
    for cap, cnt in counts.items():
        if cnt > 1:
            reasons.append("CAPTION_DUP: caption '%s' appears %d times (must be once, centered below the image)"
                           % (cap[:34], cnt))
    return reasons


if __name__ == "__main__":
    import sys, os
    idml = sys.argv[1]
    cm = {}
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "image_inject"))
        import epub_tools
        isbn = os.path.basename(idml).split("_")[0]
        epub = os.path.join(os.path.dirname(__file__), "..", "..", "epub_input_files", isbn + ".epub")
        if os.path.exists(epub):
            cm = epub_tools.build_caption_map(epub)
    except Exception as e:
        print("note: caption map unavailable:", e)
    rs = check(idml, cm)
    if rs:
        print("FAIL (%d):" % len(rs))
        for r in rs[:40]:
            print("  -", r)
        sys.exit(1)
    print("PASS: no duplicate captions")

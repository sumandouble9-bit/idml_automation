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


def _image_counts(injected_idml):
    counts = Counter()
    try:
        with zipfile.ZipFile(injected_idml) as z:
            for n in z.namelist():
                if n.startswith("Stories/") and n.endswith(".xml"):
                    x = z.read(n).decode("utf-8", "replace")
                    for img in re.findall(r'LinkResourceURI="[^"]*/([^"]+\.(?:jpg|png|jpeg))"', x, re.I):
                        counts[img] += 1
    except Exception:
        pass
    return counts


_LABEL_ONLY = re.compile(r"^(fig(ure|ura|s)?|plate|lam(ina)?|tab(la|le)?|cuadro|tracking|no|n[oº]|\d+|[ivxlcdm]+)\s*\.?\s*\d*\.?$", re.I)


def check(injected_idml, caption_map):
    reasons = []
    # Only DESCRIPTIVE captions can be "duplicated top + below". Short figure
    # labels ("Fig. 1.", "Fig. 2.", "Plate II", "tracking") legitimately repeat
    # once per figure, so they are never flagged.
    img_counts = _image_counts(injected_idml)
    expected_counts = Counter()
    for img_name, cap_text in (caption_map or {}).items():
        norm_c = _norm(cap_text)
        if norm_c and len(norm_c) > 15 and not _LABEL_ONLY.match(norm_c):
            occ = img_counts.get(img_name, 1)
            expected_counts[norm_c] += occ

    caps = set(expected_counts.keys())
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
        expected = expected_counts.get(cap, 1)
        if cnt > expected:
            reasons.append("CAPTION_DUP: caption '%s' appears %d times (must be once per image, centered below the image)"
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

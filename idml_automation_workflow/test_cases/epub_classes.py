import re, html, zipfile

KEYLEN = 60


def _key(text):
    return re.sub(r"[^a-zA-Z0-9]", "", html.unescape(text or "")).lower()[:KEYLEN]


def _strip_tags(s):
    return html.unescape(re.sub(r"(?is)<[^>]+>", "", s)).strip()


def extract(epub_path):
    """Return normalized-prefix-key sets per alignment role, derived dynamically
    from the book's own CSS + XHTML: {"center": set, "block": set, "right": set}."""
    center_cls, block_cls, right_cls = set(), set(), set()
    out = {"center": set(), "block": set(), "right": set()}
    try:
        z = zipfile.ZipFile(epub_path, "r")
    except Exception:
        return out

    css = ""
    for n in z.namelist():
        if n.lower().endswith(".css"):
            try:
                css += z.read(n).decode("utf-8", "ignore")
            except Exception:
                pass
    for m in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", css):
        cls, body = m.group(1), m.group(2)
        if re.search(r"text-align\s*:\s*center", body):
            center_cls.add(cls)
        if re.search(r"text-align\s*:\s*right", body):
            right_cls.add(cls)

    for n in z.namelist():
        if not n.lower().endswith((".xhtml", ".html", ".htm")):
            continue
        try:
            d = z.read(n).decode("utf-8", "ignore")
        except Exception:
            continue
        for tag, attrs, inner in re.findall(r"(?is)<(p|div|blockquote)\b([^>]*)>(.*?)</\1>", d):
            cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1]
            classes = set(cls.split())
            if re.search(r"(?is)<(p|div|table|blockquote)", inner):
                continue  # skip container elements; only key leaf text blocks
            key = _key(_strip_tags(inner))
            if len(key) < 4:
                continue
            if tag == "blockquote" or any("block" in c.lower() or "quote" in c.lower() for c in classes):
                out["block"].add(key)
            if (classes & center_cls) or any("center" in c for c in classes):
                out["center"].add(key)
            if (classes & right_cls) or "right" in classes:
                out["right"].add(key)
    return out


if __name__ == "__main__":
    import sys
    r = extract(sys.argv[1])
    for k in ("center", "block", "right"):
        print("%-7s : %d" % (k, len(r[k])))

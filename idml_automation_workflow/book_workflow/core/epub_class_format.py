import re
import html
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

EM_PT = 12.0
_SKIP_STYLES = ("toc", "index", "chapter", "head", "title", "author",
                "caption", "verso", "copyright", "folio", "running", "doublenine")
_BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "blockquote", "li")


def _lname(tag):
    return tag.rsplit("}", 1)[-1]
# local tag name without the XML namespace.


def _norm_key(text):
    t = html.unescape(text or "")
    t = re.sub(r"[\s\u00ad\u200b\ufeff\u2028\xa0]+", " ", t).strip().lower()
    return re.sub(r"[^a-z0-9\u00c0-\u017f]", "", t)[:60]
# punctuation/whitespace-insensitive key, matching epub_style_enricher.norm_key.


def _em(decl, prop):
    m = re.search(prop + r"\s*:\s*(-?\d*\.?\d+)\s*em", decl, re.I)
    return float(m.group(1)) if m else None
# reads an em-valued CSS property from a declaration block, or None.


def _format_from_decl(decl):
    fmt = {}
    ma = re.search(r"text-align\s*:\s*(center|right|justify|left)", decl, re.I)
    if ma:
        fmt["align"] = ma.group(1).lower()
    ml = _em(decl, "margin-left")
    if ml is None:
        ml = _em(decl, "padding-left")
    if ml and ml > 0:
        fmt["li"] = round(ml * EM_PT)
    mr = _em(decl, "margin-right")
    if mr is None:
        mr = _em(decl, "padding-right")
    if mr and mr > 0:
        fmt["ri"] = round(mr * EM_PT)
    return fmt
# turns one CSS declaration block into an IDML formatting dict (align + block indents).


def build_class_format(epub_path):
    class_fmt = {}
    key_fmt = {}
    try:
        with zipfile.ZipFile(str(epub_path), "r") as zf:
            for n in zf.namelist():
                if n.lower().endswith(".css"):
                    css = zf.read(n).decode("utf-8", "ignore")
                    for m in re.finditer(r"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}", css):
                        f = _format_from_decl(m.group(2))
                        if f:
                            class_fmt[m.group(1).lower()] = f
            for n in zf.namelist():
                if not n.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                doc = zf.read(n).decode("utf-8", "ignore")
                for tag in _BLOCK_TAGS:
                    for m in re.finditer(r"<" + tag + r"\b([^>]*)>(.*?)</" + tag + r">", doc, re.I | re.S):
                        attrs, inner = m.group(1), m.group(2)
                        fmt = {}
                        mc = re.search(r'class=["\']([^"\']+)["\']', attrs)
                        if mc:
                            for c in mc.group(1).split():
                                fmt.update(class_fmt.get(c.lower(), {}))
                        ms = re.search(r'style=["\']([^"\']+)["\']', attrs)
                        if ms:
                            fmt.update(_format_from_decl(ms.group(1)))
                        if fmt:
                            k = _norm_key(re.sub(r"<[^>]+>", " ", inner))
                            if len(k) >= 2:
                                key_fmt[k] = fmt
    except Exception:
        pass
    return key_fmt
# builds norm_key -> {align, li, ri} for every EPUB block carrying alignment/indent CSS.


def apply_class_format(story_root, key_fmt):
    changed = False
    for psr in story_root.iter():
        if _lname(psr.tag) != "ParagraphStyleRange":
            continue
        sl = psr.attrib.get("AppliedParagraphStyle", "").lower()
        if any(k in sl for k in _SKIP_STYLES):
            continue
        txt = "".join(c.text or "" for c in psr.iter() if _lname(c.tag) == "Content")
        if not txt.strip():
            continue
        fmt = key_fmt.get(_norm_key(txt))
        if not fmt:
            continue
        align = fmt.get("align")
        if align == "center":
            if psr.attrib.get("Justification") != "CenterAlign":
                psr.set("Justification", "CenterAlign")
                changed = True
            for a in ("FirstLineIndent", "LeftIndent", "RightIndent"):
                if psr.attrib.get(a) not in (None, "0"):
                    psr.set(a, "0")
                    changed = True
            continue
        if align == "right" and psr.attrib.get("Justification") != "RightAlign":
            psr.set("Justification", "RightAlign")
            changed = True
        _is_block = any(k in sl for k in ("quote", "block", "epigraph", "verse", "poem", "extract"))
        if _is_block:
            if "li" in fmt and psr.attrib.get("LeftIndent") != str(fmt["li"]):
                psr.set("LeftIndent", str(fmt["li"]))
                changed = True
            if "ri" in fmt and psr.attrib.get("RightIndent") != str(fmt["ri"]):
                psr.set("RightIndent", str(fmt["ri"]))
                changed = True
            if ("li" in fmt or "ri" in fmt) and "\u2028" not in txt and psr.attrib.get("Justification") != "LeftJustified":
                psr.set("Justification", "LeftJustified")
                changed = True
        else:
            if "li" in fmt and psr.attrib.get("LeftIndent") == str(fmt["li"]):
                psr.set("LeftIndent", "0")
                changed = True
            if "ri" in fmt and psr.attrib.get("RightIndent") == str(fmt["ri"]):
                psr.set("RightIndent", "0")
                changed = True
    return changed
# applies ONLY class formatting (never text): centre/right alignment and block
# left/right indents from the EPUB. Justify/left alignment is left alone so ordinary
# body paragraphs (which already work) are untouched; headings/TOC/front matter skipped.


def apply_epub_classes(idml_path):
    idml_path = Path(idml_path)
    stem = re.sub(r"(_injected|_normalized|_formatted|_FINAL)$", "", idml_path.stem, flags=re.I)
    epub = None
    p = idml_path.resolve()
    for _ in range(6):
        p = p.parent
        for sub in ("epub_input_files", "epub_input_files_Spanish"):
            cand = p / sub / (stem + ".epub")
            if cand.exists():
                epub = cand
                break
        if epub:
            break
    if epub is None:
        return 0
    key_fmt = build_class_format(epub)
    if not key_fmt:
        return 0
    with zipfile.ZipFile(str(idml_path), "r") as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}
    hits = 0
    for n in names:
        if n.startswith("Stories/") and n.endswith(".xml"):
            try:
                root = ET.fromstring(data[n])
            except Exception:
                continue
            if apply_class_format(root, key_fmt):
                data[n] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                hits += 1
    if hits:
        tmp = idml_path.with_suffix(".classfmt.tmp")
        with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED) as zout:
            for n in names:
                zout.writestr(n, data[n])
        tmp.replace(idml_path)
    return hits
# file-level entry point: finds the book EPUB, builds the class-format map, and projects
# alignment + indents onto matching paragraphs across every story, repackaging in place.

import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

try:
    from core.epub_class_format import build_class_format, _norm_key, _lname, _SKIP_STYLES
except Exception:
    from epub_class_format import build_class_format, _norm_key, _lname, _SKIP_STYLES


def apply_center_only(story_root, key_fmt):
    center_keys = set(k for k, v in key_fmt.items() if v.get("align") == "center")
    if not center_keys:
        return False
    changed = False
    for psr in story_root.iter():
        if _lname(psr.tag) != "ParagraphStyleRange":
            continue
        sl = psr.attrib.get("AppliedParagraphStyle", "").lower()
        if any(k in sl for k in _SKIP_STYLES):
            continue
        full = "".join(c.text or "" for c in psr.iter() if _lname(c.tag) == "Content")
        if not full.strip():
            continue
        lines = [full]
        for c in psr.iter():
            if _lname(c.tag) == "Content" and c.text:
                lines.extend(c.text.split("\u2028"))
        is_center = False
        fmt = None
        for ln in lines:
            nk = _norm_key(ln)
            if len(nk) >= 6 and nk in key_fmt:
                f = key_fmt[nk]
                if f.get("align") == "center":
                    is_center = True
                    break
                if fmt is None:
                    fmt = f
        if is_center:
            if psr.attrib.get("Justification") != "CenterAlign":
                psr.set("Justification", "CenterAlign")
                changed = True
            if psr.attrib.get("FirstLineIndent") not in (None, "0"):
                psr.set("FirstLineIndent", "0")
                changed = True
            continue
        if fmt is None:
            continue
        is_block = any(k in sl for k in ("quote", "block", "epigraph", "verse", "poem", "extract"))
        if is_block and ("li" in fmt or "ri" in fmt):
            if "li" in fmt and psr.attrib.get("LeftIndent") != str(fmt["li"]):
                psr.set("LeftIndent", str(fmt["li"]))
                changed = True
            if "ri" in fmt and psr.attrib.get("RightIndent") != str(fmt["ri"]):
                psr.set("RightIndent", str(fmt["ri"]))
                changed = True
            if "\u2028" not in full and psr.attrib.get("Justification") != "LeftJustified":
                psr.set("Justification", "LeftJustified")
                changed = True
    return changed


def apply_center(idml_path):
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
            if apply_center_only(root, key_fmt):
                data[n] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                hits += 1
    if hits:
        tmp = idml_path.with_suffix(".center.tmp")
        with zipfile.ZipFile(str(tmp), "w", zipfile.ZIP_DEFLATED) as zout:
            for n in names:
                zout.writestr(n, data[n])
        tmp.replace(idml_path)
    return hits
# Centres ONLY the paragraphs the EPUB centres (text-align:center classes/inline),
# via paragraph-level CenterAlign (never justified, so no word-space stretch) and a
# zeroed first-line indent. It changes nothing else - no left/right indents, no text -
# and skips heading/TOC/front-matter styles. Wired into the Spanish postprocessor,
# which the EN epub_class_format pass does not cover, so Spanish poems/verses centred
# in the EPUB are centred in the IDML/PDF too.

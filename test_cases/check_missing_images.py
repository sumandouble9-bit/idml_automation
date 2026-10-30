import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import re as _re
import zipfile as _zip

JS = 1246973031
_INS_RE = _re.compile(r"###\s*Insert\s+(.+?)\s+here\s*###", _re.I | _re.S)
_IMG_EXT = (".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff", ".bmp", ".webp")
_SKIP = ("logo", "leaf-bound")


def expected_image_names(source_idml):
    """Image basenames the source IDML expects, from its ###Insert X here### placeholders."""
    names = set()
    if not (source_idml and _os.path.exists(source_idml)):
        return names
    try:
        with _zip.ZipFile(source_idml) as z:
            for n in z.namelist():
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                text = _re.sub(r"<[^>]+>", "", z.read(n).decode("utf-8", "replace"))
                for m in _INS_RE.findall(text):
                    b = _re.sub(r"\s+", "", m).lower()
                    if b.endswith(_IMG_EXT) and not any(s in b for s in _SKIP):
                        names.add(b)
    except Exception:
        pass
    return names


_JS_LINKS = ('var out=[];var d=app.activeDocument;'
             'for(var i=0;i<d.links.length;i++){try{out.push(d.links[i].name);}catch(e){}}'
             'out.join("\u0001");')


def placed_image_names(app):
    """Basenames (lowercase) of every image actually placed/linked in the open document."""
    try:
        raw = str(app.DoScript(_JS_LINKS, JS) or "")
    except Exception:
        raw = ""
    return set(_os.path.basename(x).lower() for x in raw.split("\u0001") if x)


def check(app, expected=None):
    """Flag expected images dropped during injection (placeholder consumed, no placed link)."""
    if not expected:
        return []
    placed = placed_image_names(app)
    missing = sorted(n for n in expected if n not in placed)
    if missing:
        return ["MISSING_IMAGES=%d:%s" % (len(missing), ",".join(missing[:15]))]
    return []

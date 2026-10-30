import re as _re
import zipfile as _zip

_BLEED = "8.5"  # 3mm nominal; values compared with tolerance


def _vals(idml_path):
    with _zip.ZipFile(idml_path) as z:
        x = z.read("Resources/Preferences.xml").decode("utf-8", "replace")
    out = {}
    for k in ("DocumentBleedTopOffset", "DocumentBleedBottomOffset",
              "DocumentBleedInsideOrLeftOffset", "DocumentBleedOutsideOrRightOffset"):
        m = _re.search(k + r'="([^"]+)"', x)
        out[k] = float(m.group(1)) if m else None
    return out


def check(idml_path):
    """Verify bleed is on the inner (spine) edge + top/bottom, 0 on the fore-edge
    (page 1 right-side 0, page 2 left-side 0)."""
    try:
        v = _vals(idml_path)
    except Exception as e:
        return ["BLEED_CHECK_ERROR=%s" % e]
    bad = []
    if not (v["DocumentBleedInsideOrLeftOffset"] and v["DocumentBleedInsideOrLeftOffset"] > 1):
        bad.append("inside=0")
    if v["DocumentBleedOutsideOrRightOffset"] not in (0.0, None) and v["DocumentBleedOutsideOrRightOffset"] > 1:
        bad.append("outside!=0")
    for k in ("DocumentBleedTopOffset", "DocumentBleedBottomOffset"):
        if not (v[k] and v[k] > 1):
            bad.append(k.replace("DocumentBleed", "").replace("Offset", "") + "=0")
    if bad:
        return ["BLEED_WRONG=%s" % ",".join(bad)]
    return []

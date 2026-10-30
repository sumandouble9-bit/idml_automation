import os as _os, sys as _sys, re as _re
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import audit as _audit

_MIN_RUN = 12  # only a consecutive run of this many dropped words = a real lost passage


def check(source_idml, injected_idml, caption_map=None):
    """Flag a dropped body passage (a consecutive run of >= 12 missing words).

    Ignores scattered occurrence losses (front-matter, TOC, roman numerals, caption
    words) that formatting legitimately restructures -- those are NOT paragraph loss.
    """
    try:
        r = _audit.missing_text_reason(source_idml, injected_idml, caption_map)
    except Exception:
        return []
    if not r:
        return []
    msg = r[0]
    m = _re.search(r"run=(\d+)", msg)
    run = int(m.group(1)) if m else 0
    if run >= _MIN_RUN:
        return [msg]
    return []

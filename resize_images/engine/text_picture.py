"""Detect whether an image is a picture of text (light background with even dark text bands)."""

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def looks_like_text(path, max_w=120):
    """True when the image looks like scanned/printed text: light background, 3+ even dark bands with gaps."""
    if not _HAS_PIL:
        return False
    try:
        im = Image.open(path).convert("L")
    except Exception:
        return False
    w, h = im.size
    if h < 8 or w < 8:
        return False
    if w > max_w:
        im = im.resize((max_w, max(1, int(h * max_w / w))))
        w, h = im.size
    px = list(im.getdata())
    rows = [sum(px[r * w:(r + 1) * w]) / w for r in range(h)]
    overall = sum(rows) / h
    if overall < 180:                                     # background is not light
        return False
    dark_cut = overall * 0.82
    dark = [m < dark_cut for m in rows]
    bands = _runs(dark)
    if len(bands) < 3:
        return False
    heights = [n for _, n in bands]
    mean_h = sum(heights) / len(heights)
    if mean_h <= 0:
        return False
    std = (sum((x - mean_h) ** 2 for x in heights) / len(heights)) ** 0.5
    if std / mean_h > 0.8:                                # bands not evenly sized
        return False
    return (len(bands) - 1) >= 2                          # at least two clear white gaps


def _runs(flags):
    """Return [(start, length)] for each maximal run of True in a boolean list."""
    out, i, n = [], 0, len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            out.append((i, j - i))
            i = j
        else:
            i += 1
    return out

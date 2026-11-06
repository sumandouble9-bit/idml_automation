import os
from math import sqrt

from . import geometry as G
from .text_picture import looks_like_text

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

SKIP_EXTS = (".svg",)


class ImagePlan:
    """Sizing plan for one image: fitted size, its largest/smallest scale, and shrink fraction rmin."""

    def __init__(self, name, path, pw, ph, dpi, w, h, s_hi, s_lo, is_text):
        self.name = name
        self.path = path
        self.pw, self.ph, self.dpi = pw, ph, dpi
        self.w, self.h = w, h                             # chosen size (pt), starts at the largest allowed
        self.s_hi, self.s_lo = s_hi, s_lo
        self.rmin = (s_lo / s_hi) if s_hi else 1.0        # how far it may shrink, as a fraction of current
        self.max_h = h                                    # largest allowed height (pt), fixed
        self.min_h_abs = h * self.rmin                    # smallest allowed height (pt), fixed
        self.is_text = is_text

    def min_h(self):
        """Smallest height this image may shrink to (pt)."""
        return self.h * self.rmin

    def __repr__(self):
        return f"<ImagePlan {self.name} {self.w:.0f}x{self.h:.0f}pt rmin={self.rmin:.2f} text={self.is_text}>"


def read_pixels_dpi(path):
    """Return (pixel_w, pixel_h, dpi) for an image, defaulting to 72 dpi when unspecified."""
    with Image.open(path) as im:
        pw, ph = im.size
        dpi = 72.0
        try:
            d = im.info.get("dpi")
            if d and d[0] and d[0] > 1:
                dpi = float(d[0])
        except Exception:
            pass
    return pw, ph, dpi


def _fit_to_frame(pw, ph, text_w, frame_h):
    """Fit natural pixels into the column width and frame height; return (w, h) in pt."""
    w = min(pw, text_w)                                   # pw here is already natural pt width
    h = w * ph / pw
    if h > frame_h - G.PAD_PT:
        h = frame_h - G.PAD_PT
        w = h * pw / ph
    return w, h


def compute_size_range(pw, ph, dpi, is_text, text_w=None, frame_h=None):
    """Return (w, h, s_hi, s_lo) for one image from its pixels/dpi and text-picture flag."""
    text_w = G.TEXT_WIDTH_PT if text_w is None else text_w
    frame_h = G.FRAME_HEIGHT_PT if frame_h is None else frame_h
    nat_w = pw * 72.0 / dpi
    nat_h = ph * 72.0 / dpi
    w, h = _fit_to_frame(nat_w, nat_h, text_w, frame_h)
    floor = G.TEXT_MIN_SCALE if is_text else 0.0
    area = w * h
    if area > G.AREA_MAX:
        s_hi = max(sqrt(G.AREA_MAX / area), floor)
    elif area < G.AREA_MIN:
        s_hi = max(1.0, min(sqrt(G.AREA_MIN / area), pw * 72.0 / (G.MIN_PPI * w)))
    else:
        s_hi = 1.0
    if area > G.AREA_MIN:
        s_lo = min(s_hi, max(sqrt(G.AREA_MIN / area), floor))
    else:
        s_lo = s_hi
    return w, h, s_hi, s_lo


def plan_image(path, name=None):
    """Read one image and return its ImagePlan at the largest allowed size, or None if unsupported."""
    name = name or os.path.basename(path)
    if os.path.splitext(name)[1].lower() in SKIP_EXTS or not _HAS_PIL:
        return None
    try:
        pw, ph, dpi = read_pixels_dpi(path)
    except Exception:
        return None
    is_text = looks_like_text(path)
    w, h, s_hi, s_lo = compute_size_range(pw, ph, dpi, is_text)
    return ImagePlan(name, path, pw, ph, dpi, w * s_hi, h * s_hi, s_hi, s_lo, is_text)

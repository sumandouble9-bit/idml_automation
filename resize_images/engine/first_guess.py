"""STEP 3: the builder's own page estimate -- pre-shrink images that will not fit the space left on a page."""

from . import geometry as G


def first_guess(plans):
    """Walk images in order, tracking height used per page, shrinking those that overflow the space left."""
    y = 0.0
    first_page = True
    for p in plans:
        if y > 0:
            safety = G.SAFETY_FIRST_PT if first_page else G.SAFETY_LATER_PT
            avail = G.FRAME_HEIGHT_PT - y - safety - G.PAD_PT
            if p.h <= avail:
                pass                                       # fits at full size
            elif p.min_h() <= avail:
                scale = avail / p.h                        # largest size that still fits
                p.w *= scale
                p.h = avail
            else:
                y = 0.0                                    # assume it moves to the next page, full size
                first_page = False
        y += p.h + G.PAD_PT
        if y >= G.FRAME_HEIGHT_PT:
            y = 0.0
            first_page = False
    return plans

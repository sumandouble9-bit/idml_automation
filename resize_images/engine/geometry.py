"""Page/frame geometry and algorithm constants (5.5 x 8.5 in trim, body column)."""

PAGE_W_PT = 396.0
PAGE_H_PT = 612.0
MARGIN_TOP_PT = 36.0
MARGIN_BOTTOM_PT = 54.0

TEXT_WIDTH_PT = 324.0                                      # body column width
FRAME_HEIGHT_PT = PAGE_H_PT - MARGIN_TOP_PT - MARGIN_BOTTOM_PT   # 522
PAGE_AREA_PT = PAGE_W_PT * PAGE_H_PT

AREA_MIN = 0.05 * PAGE_AREA_PT
AREA_MAX = 0.30 * PAGE_AREA_PT
MIN_PPI = 150.0
TEXT_MIN_SCALE = 0.80
PAD_PT = 6.0
SAFETY_FIRST_PT = 10.0
SAFETY_LATER_PT = 40.0
REFINE_SAFETY_PT = 4.0
MAX_PASSES = 6
GAP_OK_MM = 3.0


def mm_to_pt(mm):
    """Convert millimetres to PostScript points."""
    return mm * 72.0 / 25.4


GAP_OK_PT = mm_to_pt(GAP_OK_MM)                            # ~8.5 pt

# Resize-step rules: only shrink images this tall (share of frame height), by at most this much.
MIN_IMGH_PCT = 50.0        # only resize images whose height is >= 50% of the frame
MAX_IMGH_PCT = 100.0       # ... and <= 100% of the frame
MAX_SHRINK_PCT = 35.0      # never shrink an image by more than this (floor = 65% of its height)

# Hard floor for BOTH steps: image + caption together is never shrunk below this share of the frame.
FLOOR_PCT = 0.35

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Tuple


class DocSetup:
    """
    Step 2: Normalizes document geometry (396 x 612 pt Letter-Half / 5.5 x 8.5 in),
    margins (Top 36pt, Bottom 54pt, Left/Right 36pt), 3mm bleed, and perfectly realigns
    every text frame within its page margin box so no text is shifted off to the right.
    """

    PAGE_W = 396.0
    PAGE_H = 612.0
    MARGIN_TOP = 36.0
    MARGIN_BOT = 54.0
    MARGIN_L = 36.0
    MARGIN_R = 36.0
    BLEED_TB = 8.503937
    BLEED_OUTSIDE = 8.503937

    def __init__(self, profile_path: str = None):
        # Allow default or override from profile
        pass

    def apply_preferences(self, preferences_root: ET.Element):
        """Applies page geometry and bleed to Resources/Preferences.xml."""
        for elem in preferences_root.iter():
            if "DocumentPreference" in elem.tag:
                elem.set("PageWidth", str(self.PAGE_W))
                elem.set("PageHeight", str(self.PAGE_H))
                elem.set("FacingPages", "true")
                elem.set("DocumentBleedUniformSize", "false")
                elem.set("DocumentBleedTopOffset", str(self.BLEED_TB))
                elem.set("DocumentBleedBottomOffset", str(self.BLEED_TB))
                elem.set("DocumentBleedInsideOrLeftOffset", "0")
                elem.set("DocumentBleedOutsideOrRightOffset", str(self.BLEED_OUTSIDE))

            elif "MarginPreference" in elem.tag:
                elem.set("Top", str(self.MARGIN_TOP))
                elem.set("Bottom", str(self.MARGIN_BOT))
                elem.set("Left", str(self.MARGIN_L))
                elem.set("Right", str(self.MARGIN_R))
                elem.set("ColumnCount", "1")
                elem.set("ColumnGutter", "0")
                elem.set("ColumnsPositions", f"0 {self.PAGE_W - self.MARGIN_L - self.MARGIN_R}")

    def normalize_spread_xml(self, xml_content: str) -> str:
        """
        Normalizes a Spread or MasterSpread XML content string:
        1. Updates MarginPreference
        2. Preserves Page spread coordinate origins while updating Page width and height
        3. Realigns TextFrames to fit strictly inside their respective Page margin boxes
        """
        # 1. Update MarginPreference tags
        for k, v in [
            ("Top", f"{self.MARGIN_TOP}"),
            ("Bottom", f"{self.MARGIN_BOT}"),
            ("Left", f"{self.MARGIN_L}"),
            ("Right", f"{self.MARGIN_R}"),
            ("ColumnCount", "1"),
            ("ColumnGutter", "0"),
            ("ColumnsPositions", f"0 {self.PAGE_W - self.MARGIN_L - self.MARGIN_R}"),
        ]:
            pattern_replace = re.compile(rf'(<MarginPreference\b[^>]*?)\s{re.escape(k)}="[^"]*"', re.DOTALL)
            xml_content, count = pattern_replace.subn(rf'\1 {k}="{v}"', xml_content)
            if count == 0:
                pattern_add = re.compile(r'(<MarginPreference\b)([^>]*?/?>)', re.DOTALL)
                xml_content = pattern_add.sub(rf'\1 {k}="{v}"\2', xml_content)

        # 2. Rewrite Page bounds preserving (y1, x1) spread origin
        page_bounds_re = re.compile(r'(<Page\b[^>]*?\sGeometricBounds=")([^"]+)(")', re.DOTALL)
        def _sub_page(m):
            head, bounds, tail = m.group(1), m.group(2), m.group(3)
            try:
                y1, x1, y2, x2 = [float(n) for n in bounds.split()]
            except Exception:
                return m.group(0)
            return f"{head}{y1} {x1} {y1 + self.PAGE_H} {x1 + self.PAGE_W}{tail}"
        xml_content = page_bounds_re.sub(_sub_page, xml_content)

        # 3. Realign TextFrames to page margins
        # Skip MasterSpreads so running header/footer frames retain their header geometry
        if "<idPkg:MasterSpread" in xml_content or "<MasterSpread" in xml_content:
            return xml_content

        MARGIN_W = self.PAGE_W - self.MARGIN_L - self.MARGIN_R
        MARGIN_H = self.PAGE_H - self.MARGIN_TOP - self.MARGIN_BOT

        # Find all pages in this spread
        pages = []
        for m in re.finditer(r'<Page\b[^>]*?>', xml_content):
            tag = m.group(0)
            gb = re.search(r'GeometricBounds="([^"]+)"', tag)
            it = re.search(r'ItemTransform="([^"]+)"', tag)
            if not gb or not it:
                continue
            try:
                y1, x1, y2, x2 = [float(v) for v in gb.group(1).split()]
                it_nums = [float(v) for v in it.group(1).split()]
                tx, ty = it_nums[4], it_nums[5]
                sx1, sy1 = x1 + tx, y1 + ty
                sx2, sy2 = x2 + tx, y2 + ty
                pages.append((sx1, sy1, sx2, sy2))
            except Exception:
                continue

        if not pages:
            return xml_content

        textframe_re = re.compile(r'<TextFrame\b.*?</TextFrame>', re.DOTALL)
        itemtransform_re = re.compile(r'ItemTransform="([^"]+)"')
        geombounds_re = re.compile(r'GeometricBounds="([^"]+)"')
        pathpoint_re = re.compile(r'<PathPointType\b[^/>]*/>')

        def _rewrite_frame(tf_xml: str) -> str:
            it = itemtransform_re.search(tf_xml)
            if not it:
                return tf_xml
            try:
                it_nums = [float(v) for v in it.group(1).split()]
                tx, ty = it_nums[4], it_nums[5]
            except Exception:
                return tf_xml

            anchors = re.findall(r'<PathPointType\b[^/>]*Anchor="([^"]+)"', tf_xml)
            if len(anchors) != 4:
                return tf_xml

            try:
                pts = [tuple(float(v) for v in a.split()) for a in anchors]
            except Exception:
                return tf_xml
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            f_x1 = tx + min(xs)
            f_x2 = tx + max(xs)
            f_y1 = ty + min(ys)
            f_y2 = ty + max(ys)

            # Match to overlapping page
            page = None
            best_overlap = 0.0
            for (sx1, sy1, sx2, sy2) in pages:
                ox = max(0.0, min(f_x2, sx2) - max(f_x1, sx1))
                oy = max(0.0, min(f_y2, sy2) - max(f_y1, sy1))
                area = ox * oy
                if area > best_overlap:
                    best_overlap = area
                    page = (sx1, sy1, sx2, sy2)

            if not page or best_overlap <= 0:
                # If frame is center-placed, pick nearest page
                cx = (f_x1 + f_x2) / 2
                cy = (f_y1 + f_y2) / 2
                best_d = float("inf")
                for p in pages:
                    sx1, sy1, sx2, sy2 = p
                    pcx = (sx1 + sx2) / 2
                    pcy = (sy1 + sy2) / 2
                    d = (pcx - cx) ** 2 + (pcy - cy) ** 2
                    if d < best_d:
                        best_d = d
                        page = p

            psx1, psy1, _, _ = page
            is_title_page = (len(pages) == 1)
            frame_h = (480.0 - self.MARGIN_TOP) if is_title_page else MARGIN_H

            new_tx = psx1 + self.MARGIN_L
            new_ty = psy1 + self.MARGIN_TOP
            new_it = f"1 0 0 1 {new_tx} {new_ty}"
            new_gb = f"0 0 {frame_h} {MARGIN_W}"

            tf_xml = itemtransform_re.sub(f'ItemTransform="{new_it}"', tf_xml, count=1)
            if geombounds_re.search(tf_xml):
                tf_xml = geombounds_re.sub(f'GeometricBounds="{new_gb}"', tf_xml, count=1)

            clockwise = [
                f"0 0",
                f"{MARGIN_W} 0",
                f"{MARGIN_W} {frame_h}",
                f"0 {frame_h}",
            ]
            idx = [0]
            def _pp_sub(m):
                pp = m.group(0)
                coord = clockwise[idx[0] % 4]
                idx[0] += 1
                pp = re.sub(r'Anchor="[^"]+"', f'Anchor="{coord}"', pp, count=1)
                pp = re.sub(r'LeftDirection="[^"]+"', f'LeftDirection="{coord}"', pp, count=1)
                pp = re.sub(r'RightDirection="[^"]+"', f'RightDirection="{coord}"', pp, count=1)
                return pp
            tf_xml = pathpoint_re.sub(_pp_sub, tf_xml)
            return tf_xml

        return textframe_re.sub(lambda m: _rewrite_frame(m.group(0)), xml_content)

import copy
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from typography_postprocessor_es_helpers import *
except ImportError:
    from .typography_postprocessor_es_helpers import *


def realign_spreads_es(tmp_dir: Path, stats: dict) -> None:
    """Guarantees 100% overlap between Margin box and body TextFrames across all spreads:
    - Verso (left) page: TextFrame bounds [-360, -270, -36, 252], centered at X=-198, Y=-9.
    - Recto (right) page: TextFrame bounds [36, -270, 360, 252], centered at X=198, Y=-9.
    - Title page (p1): horizontally centered between 36 and 360 (width 324).
    - Preserves running headers, footers, logo polygons, and small callouts (< 200pt).
    """
    # 1. Update Preferences.xml
    pref_xml = tmp_dir / "Resources" / "Preferences.xml"
    if pref_xml.exists():
        try:
            proot = ET.parse(pref_xml).getroot()
            pref_changed = False
            for dp in proot.iter():
                if lname(dp.tag) == "DocumentPreference":
                    dp.set("PageWidth", "396")
                    dp.set("PageHeight", "612")
                    dp.set("FacingPages", "true")
                    dp.set("DocumentBleedUniformSize", "false")
                    dp.set("DocumentBleedTopOffset", "8.503937")
                    dp.set("DocumentBleedBottomOffset", "8.503937")
                    dp.set("DocumentBleedInsideOrLeftOffset", "0")
                    dp.set("DocumentBleedOutsideOrRightOffset", "8.503937")
                    pref_changed = True
            for mp in proot.iter():
                if lname(mp.tag) == "MarginPreference":
                    mp.set("Top", "36")
                    mp.set("Bottom", "54")
                    mp.set("Left", "36")
                    mp.set("Right", "36")
                    mp.set("ColumnCount", "1")
                    mp.set("ColumnGutter", "0")
                    mp.set("ColumnsPositions", "0 324")
                    pref_changed = True
            for td in proot.iter():
                if lname(td.tag) == "TextDefault":
                    td.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                    td.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                    if "FontStyle" in td.attrib:
                        td.set("FontStyle", "Regular")
                    if "PointSize" in td.attrib:
                        td.set("PointSize", "9.65")
                    if "RuleBelow" in td.attrib:
                        td.set("RuleBelow", "false")
                    pref_changed = True
            if pref_changed:
                ET.ElementTree(proot).write(pref_xml, encoding="utf-8", xml_declaration=True)
        except Exception:
            pass

    spreads_dir = tmp_dir / "Spreads"
    if not spreads_dir.is_dir():
        return

    for sf in spreads_dir.glob("*.xml"):
        try:
            sroot = ET.parse(sf).getroot()
        except Exception:
            continue

        changed = False

        # Ensure MarginPreference on spread and pages
        for mp in sroot.iter():
            if lname(mp.tag) == "MarginPreference":
                mp.set("Top", "36")
                mp.set("Bottom", "54")
                mp.set("Left", "36")
                mp.set("Right", "36")
                mp.set("ColumnCount", "1")
                mp.set("ColumnGutter", "0")
                mp.set("ColumnsPositions", "0 324")
                changed = True

        # Collect pages and spread bounds
        pages = []
        for p in sroot.iter():
            if lname(p.tag) == "Page":
                p_name = p.attrib.get("Name", "")
                gb_str = p.attrib.get("GeometricBounds", "0 0 612 396")
                it_str = p.attrib.get("ItemTransform", "1 0 0 1 0 0")
                try:
                    gb = [float(v) for v in gb_str.split()]
                    it = [float(v) for v in it_str.split()]
                    pl = gb[1] + it[4]
                    pr = gb[3] + it[4]
                    pt = gb[0] + it[5]
                    pb = gb[2] + it[5]
                    pages.append((p_name, pl, pt, pr, pb))
                except Exception:
                    pass

        if not pages:
            if changed:
                ET.ElementTree(sroot).write(sf, encoding="utf-8", xml_declaration=True)
            continue

        # Check and realign TextFrames
        for tf in sroot.iter():
            if lname(tf.tag) != "TextFrame":
                continue

            it_str = tf.attrib.get("ItemTransform", "")
            if not it_str:
                continue
            try:
                it = [float(v) for v in it_str.split()]
            except Exception:
                continue

            ppa = next((e for e in tf.iter() if lname(e.tag) == "PathPointArray"), None)
            if ppa is None:
                continue
            pts_el = [c for c in ppa if lname(c.tag) == "PathPointType"]
            if len(pts_el) != 4:
                continue

            pts = []
            for p_el in pts_el:
                a = p_el.attrib.get("Anchor", "").split()
                if len(a) == 2:
                    try:
                        pts.append((float(a[0]), float(a[1])))
                    except Exception:
                        pass
            if len(pts) != 4:
                continue

            xs = [pt[0] for pt in pts]
            ys = [pt[1] for pt in pts]
            tfl = min(xs) + it[4]
            tfr = max(xs) + it[4]
            tft = min(ys) + it[5]
            tfb = max(ys) + it[5]

            w = tfr - tfl
            h = tfb - tft

            # Skip small callouts, running headers, footers
            if w < 200 or h < 200:
                continue

            # Match to closest page by horizontal center
            tf_cx = (tfl + tfr) / 2.0
            matched_page = None
            for p_name, pl, pt, pr, pb in pages:
                if pl - 15 <= tf_cx <= pr + 15:
                    matched_page = (p_name, pl, pt, pr, pb)
                    break
            if not matched_page:
                best_d = float("inf")
                for p_name, pl, pt, pr, pb in pages:
                    pcx = (pl + pr) / 2.0
                    d = abs(tf_cx - pcx)
                    if d < best_d:
                        best_d = d
                        matched_page = (p_name, pl, pt, pr, pb)

            if not matched_page:
                continue

            p_name, pl, pt, pr, pb = matched_page

            # Page 1 (Title): keep vertical bounds as title layout, enforce horizontal centering
            if p_name == "1":
                target_left = pl + 36.0
                target_right = pr - 36.0
                dl = round(tfl - target_left, 2)
                dr = round(tfr - target_right, 2)
                if abs(dl) > 0.5 or abs(dr) > 0.5:
                    shift_x = target_left - tfl
                    it[4] += shift_x
                    tf.set("ItemTransform", f"{it[0]} {it[1]} {it[2]} {it[3]} {it[4]:.12g} {it[5]:.12g}")
                    changed = True
                    stats["spread_frames_realigned"] += 1
                continue

            # Target Margin box: Top=36, Bottom=54, Left=36, Right=36
            ml = pl + 36.0
            mr = pr - 36.0
            mt = pt + 36.0
            mb = pb - 54.0

            dl = round(tfl - ml, 2)
            dr = round(tfr - mr, 2)
            dt = round(tft - mt, 2)
            db = round(tfb - mb, 2)

            if abs(dl) <= 0.5 and abs(dr) <= 0.5 and abs(dt) <= 0.5 and abs(db) <= 0.5:
                continue

            cx = (ml + mr) / 2.0
            cy = (mt + mb) / 2.0
            half_w = 324.0 / 2.0  # 162.0
            half_h = 522.0 / 2.0  # 261.0

            tf.set("ItemTransform", f"1 0 0 1 {cx:.12g} {cy:.12g}")
            if "GeometricBounds" in tf.attrib:
                del tf.attrib["GeometricBounds"]

            target_anchors = [
                f"{-half_w:.12g} {-half_h:.12g}",
                f"{-half_w:.12g} {half_h:.12g}",
                f"{half_w:.12g} {half_h:.12g}",
                f"{half_w:.12g} {-half_h:.12g}",
            ]
            for p_el, anc in zip(pts_el, target_anchors):
                p_el.set("Anchor", anc)
                p_el.set("LeftDirection", anc)
                p_el.set("RightDirection", anc)

            changed = True
            stats["spread_frames_realigned"] += 1

        if changed:
            ET.ElementTree(sroot).write(sf, encoding="utf-8", xml_declaration=True)


__all__ = ['realign_spreads_es']

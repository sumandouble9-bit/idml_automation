"""
Step 1 of the pipeline — Normalize document setup on every input IDML,
WITHOUT opening InDesign. Operates directly on the IDML XML via zipfile + regex.

For each IDML in input_files/:
  1. Back up the original to input_files/_original/<name>.idml on first run.
  2. Rewrite these XML attributes in-place:
       Resources/Preferences.xml  -> DocumentPreference page size + bleed
       Spreads/*.xml              -> every <MarginPreference ...> and Page GeometricBounds
       MasterSpreads/*.xml        -> every <MarginPreference ...> and Page GeometricBounds
  3. Save back to the original path (zip preserving mimetype as first stored entry).

Target values:
    Page:    139.7 x 215.9 mm  = 396 x 612 pt  (Letter-Half, Facing Pages)
    Margins: Top 12.7 mm = 36pt, Bottom 19.05 mm = 54pt,
             Inside 12.7 mm = 36pt, Outside 12.7 mm = 36pt, 1 column, 0 gutter
    Bleed:   Top 3 mm ≈ 8.503937pt, Bottom 3 mm, Inside 0, Outside 3 mm
"""

import io
import os
import re
import shutil
import sys
import xml.etree.ElementTree as _ET
import zipfile
from datetime import datetime
from pathlib import Path

# Paths: Defaults to local workflow folders if D:\IDML-Creation is not present
WORKFLOW_DIR = Path(__file__).resolve().parents[2]
LOCAL_INPUT_DIR = WORKFLOW_DIR / "Input"
LOCAL_OUTPUT_DIR = WORKFLOW_DIR / "page_resize_output"

_REPO_DIR = WORKFLOW_DIR.parent
INPUT_DIR = str(_REPO_DIR / "input_files") if (_REPO_DIR / "input_files").is_dir() else str(LOCAL_INPUT_DIR)
OUTPUT_DIR = str(_REPO_DIR / "page_resize_output") if (_REPO_DIR / "page_resize_output").is_dir() else str(LOCAL_OUTPUT_DIR)
LOG_PATH = os.path.join(OUTPUT_DIR, "_normalize_log.txt")

PAGE_W = 396.0
PAGE_H = 612.0
MARGIN_TOP = 36.0
MARGIN_BOT = 54.0
MARGIN_L = 36.0
MARGIN_R = 36.0
BLEED_TB = 8.503937
# Bleed on the inner (spine) edge + top/bottom; fore-edge = 0.
# -> page 1 right-side 0, page 2 left-side 0 (per requested layout).
BLEED_INSIDE = 8.503937
BLEED_OUTSIDE = 0.0


def _set_attr(xml_str: str, tag: str, attr: str, value: str) -> str:
    """Replace attr="..." inside every <tag ...> occurrence. Adds it if absent."""
    pattern_replace = re.compile(rf'(<{tag}\b[^>]*?)\s{re.escape(attr)}="[^"]*"', re.DOTALL)
    xml_str, n = pattern_replace.subn(rf'\1 {attr}="{value}"', xml_str)
    if n == 0:
        pattern_add = re.compile(rf'(<{tag}\b)([^>]*?/?>)', re.DOTALL)
        xml_str = pattern_add.sub(rf'\1 {attr}="{value}"\2', xml_str)
    return xml_str


def _rewrite_document_preference(xml_str: str) -> str:
    for k, v in [
        ("PageWidth", f"{PAGE_W}"),
        ("PageHeight", f"{PAGE_H}"),
        ("FacingPages", "true"),
        ("DocumentBleedUniformSize", "false"),
        ("DocumentBleedTopOffset", f"{BLEED_TB}"),
        ("DocumentBleedBottomOffset", f"{BLEED_TB}"),
        ("DocumentBleedInsideOrLeftOffset", f"{BLEED_INSIDE}"),
        ("DocumentBleedOutsideOrRightOffset", f"{BLEED_OUTSIDE}"),
    ]:
        xml_str = _set_attr(xml_str, "DocumentPreference", k, v)
    return xml_str


def _rewrite_margin_preferences(xml_str: str) -> str:
    for k, v in [
        ("Top", f"{MARGIN_TOP}"),
        ("Bottom", f"{MARGIN_BOT}"),
        ("Left", f"{MARGIN_L}"),
        ("Right", f"{MARGIN_R}"),
        ("ColumnCount", "1"),
        ("ColumnGutter", "0"),
        ("ColumnDirection", "Horizontal"),
        ("ColumnsPositions", f"0 {PAGE_W - MARGIN_L - MARGIN_R}"),
    ]:
        xml_str = _set_attr(xml_str, "MarginPreference", k, v)
    return xml_str


def _rewrite_text_default(xml_str: str) -> str:
    for k, v in [
        ("AppliedParagraphStyle", "ParagraphStyle/body_text"),
        ("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]"),
        ("FontStyle", "Regular"),
        ("PointSize", "9.65"),
        ("RuleBelow", "false"),
    ]:
        xml_str = _set_attr(xml_str, "TextDefault", k, v)
    return xml_str


_PAGE_TAG_RE = re.compile(r'<Page\b[^>]*?>', re.DOTALL)
_TEXTFRAME_RE = re.compile(r'<TextFrame\b.*?</TextFrame>', re.DOTALL)
_ATTR_ITEMTRANSFORM_RE = re.compile(r'ItemTransform="([^"]+)"')
_ATTR_GEOMBOUNDS_RE = re.compile(r'GeometricBounds="([^"]+)"')
_PATHPOINT_RE = re.compile(r'<PathPointType\b[^/>]*/>')


def _rewrite_page_bounds(xml_str: str, master_id: str = None, body_start_page: int = 7) -> str:
    """Rewrite every <Page ...> GeometricBounds and ItemTransform so that facing
    pages cleanly meet at the spine (X=0) and are vertically centered (Y=0)
    in InDesign spread coordinates.
    Also ensures correct AppliedMaster on pages (frontmatter < body_start_page = 'n', body >= body_start_page = master_id).
    """

    def _sub(m):
        tag = m.group(0)
        gb_m = _ATTR_GEOMBOUNDS_RE.search(tag)
        it_m = _ATTR_ITEMTRANSFORM_RE.search(tag)
        if not gb_m or not it_m:
            return tag
        try:
            y1, x1, y2, x2 = [float(v) for v in gb_m.group(1).split()]
            it_nums = [float(v) for v in it_m.group(1).split()]
            a, b, c, d, tx, ty = it_nums
        except Exception:
            return tag

        new_y2 = y1 + PAGE_H
        mid_y = (y1 + new_y2) / 2.0
        new_ty = -mid_y

        is_verso = (tx < -10.0) or (abs(x2 + tx) < 5.0 and x2 > 100.0)
        if is_verso:
            new_x2 = x1 + PAGE_W
            new_tx = -new_x2
        else:
            new_x2 = x1 + PAGE_W
            new_tx = 0.0

        new_gb = f"{y1} {x1} {new_y2} {new_x2}"
        new_it = f"{a} {b} {c} {d} {new_tx:.12g} {new_ty:.12g}"

        tag = _ATTR_GEOMBOUNDS_RE.sub(f'GeometricBounds="{new_gb}"', tag, count=1)
        tag = _ATTR_ITEMTRANSFORM_RE.sub(f'ItemTransform="{new_it}"', tag, count=1)

        # Enforce correct AppliedMaster on Spread pages
        name_m = re.search(r'Name="([^"]+)"', tag)
        if name_m:
            try:
                pnum = int(name_m.group(1))
            except ValueError:
                pnum = 0
            if 1 <= pnum < body_start_page:
                tag = re.sub(r'AppliedMaster="[^"]+"', 'AppliedMaster="n"', tag)
            elif pnum >= body_start_page and master_id:
                tag = re.sub(r'AppliedMaster="[^"]+"', f'AppliedMaster="{master_id}"', tag)

        return tag

    return _PAGE_TAG_RE.sub(_sub, xml_str)


def _rewrite_text_frames(xml_str: str) -> str:
    """Realign every TextFrame in a Spread/MasterSpread to match its page's margin box.

    - Determine which page a frame is on by comparing the frame's spread-space center
      to each Page's spread-space rect.
    - Set the frame's ItemTransform to place its local origin at the page's
      (inside-top) margin corner in spread coords.
    - Rewrite the frame's PathGeometry anchor points to a canonical rectangle
      of size (MARGIN_W x MARGIN_H) with local origin (0,0).
    """
    MARGIN_W = PAGE_W - MARGIN_L - MARGIN_R
    MARGIN_H = PAGE_H - MARGIN_TOP - MARGIN_BOT

    pages = []
    for m in re.finditer(r'<Page\b[^>]*?>', xml_str):
        tag = m.group(0)
        gb = _ATTR_GEOMBOUNDS_RE.search(tag)
        it = _ATTR_ITEMTRANSFORM_RE.search(tag)
        if not gb or not it:
            continue
        try:
            y1, x1, y2, x2 = [float(v) for v in gb.group(1).split()]
            it_nums = [float(v) for v in it.group(1).split()]
            tx, ty = it_nums[4], it_nums[5]
        except Exception:
            continue
        sx1, sy1 = x1 + tx, y1 + ty
        sx2, sy2 = x2 + tx, y2 + ty
        pages.append((sx1, sy1, sx2, sy2))
    if not pages:
        return xml_str

    # Frontmatter protection: NEVER clobber Page 1 (Title)
    page_names = [m.group(1) for m in re.finditer(r'<Page\b[^>]*?\sName="([^"]+)"', xml_str)]
    if "1" in page_names:
        return xml_str

    def _page_for_center(cx: float, cy: float):
        for (sx1, sy1, sx2, sy2) in pages:
            if sx1 <= cx <= sx2 and sy1 <= cy <= sy2:
                return (sx1, sy1, sx2, sy2)
        best = None
        best_d = float("inf")
        for p in pages:
            sx1, sy1, sx2, sy2 = p
            pcx = (sx1 + sx2) / 2
            pcy = (sy1 + sy2) / 2
            d = (pcx - cx) ** 2 + (pcy - cy) ** 2
            if d < best_d:
                best_d = d
                best = p
        return best

    def _rewrite_frame(tf_xml: str) -> str:
        # Protect dedicated copyright story frame on Page 2
        if 'ParentStory="u_copyright_story"' in tf_xml:
            return tf_xml

        it = _ATTR_ITEMTRANSFORM_RE.search(tf_xml)
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

        f_w = f_x2 - f_x1
        f_h = f_y2 - f_y1

        # Preserve running headers, running footers, and small callouts!
        # Do NOT blow up a 15pt header/footer into a 522pt frame that covers the page.
        if f_h < 280 or f_w < 200:
            return tf_xml

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
            return tf_xml

        psx1, psy1, _, _ = page
        target_x = psx1 + MARGIN_L
        target_y = psy1 + MARGIN_TOP

        # If already cleanly sized and positioned to margins, do not touch
        if (
            abs(f_w - MARGIN_W) < 4
            and abs(f_h - MARGIN_H) < 4
            and abs(f_x1 - target_x) < 4
            and abs(f_y1 - target_y) < 4
        ):
            return tf_xml

        new_tx = target_x
        new_ty = target_y
        new_it = f"1 0 0 1 {new_tx} {new_ty}"
        new_gb = f"0 0 {MARGIN_H} {MARGIN_W}"

        tf_xml = _ATTR_ITEMTRANSFORM_RE.sub(f'ItemTransform="{new_it}"', tf_xml, count=1)
        if _ATTR_GEOMBOUNDS_RE.search(tf_xml):
            tf_xml = _ATTR_GEOMBOUNDS_RE.sub(f'GeometricBounds="{new_gb}"', tf_xml, count=1)

        clockwise = [
            f"0 0",
            f"{MARGIN_W} 0",
            f"{MARGIN_W} {MARGIN_H}",
            f"0 {MARGIN_H}",
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

        tf_xml = _PATHPOINT_RE.sub(_pp_sub, tf_xml)
        return tf_xml

    return _TEXTFRAME_RE.sub(lambda m: _rewrite_frame(m.group(0)), xml_str)


def _extract_master_frame_geometry(master_xml: str) -> dict:
    """Return {ItemTransform_value: [anchor_str, ...]} for every TextFrame in a MasterSpread.

    Ported from the reference fix_page_setup.py. Frames are keyed by their ItemTransform
    so a translated / re-processed copy with different Self IDs can still be matched.
    """
    try:
        root = _ET.fromstring(master_xml)
    except _ET.ParseError:
        return {}
    frames = {}
    for tf in root.iter("TextFrame"):
        transform = tf.get("ItemTransform", "")
        points = [ppt.get("Anchor") for ppt in tf.iter("PathPointType") if ppt.get("Anchor")]
        if transform and points:
            frames[transform] = points
    return frames


def _apply_master_frame_geometry(master_xml: str, orig_geometry: dict) -> tuple:
    """Restore anchor points on every TextFrame whose ItemTransform matches the original.

    Fixes footer/page-number/running-head positions that any earlier processing may
    have shifted. Returns (new_xml, fixed_count).
    """
    try:
        root = _ET.fromstring(master_xml)
    except _ET.ParseError:
        return master_xml, 0
    fixed = 0
    for tf in root.iter("TextFrame"):
        transform = tf.get("ItemTransform", "")
        if transform in orig_geometry:
            orig_points = orig_geometry[transform]
            current_points = [ppt.get("Anchor") for ppt in tf.iter("PathPointType") if ppt.get("Anchor")]
            if current_points != orig_points:
                ppt_elements = list(tf.iter("PathPointType"))
                for i, ppt in enumerate(ppt_elements):
                    if i < len(orig_points):
                        ppt.set("Anchor", orig_points[i])
                        ppt.set("LeftDirection", orig_points[i])
                        ppt.set("RightDirection", orig_points[i])
                fixed += 1
    if fixed == 0:
        return master_xml, 0
    result = _ET.tostring(root, encoding="unicode", xml_declaration=False)
    if not result.startswith("<?xml"):
        result = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + result
    return result, fixed


def _normalize_one_idml(src_path: str, dst_path: str, reference_path: str = None) -> None:
    """Read IDML from src_path, rewrite XML in memory, write normalized copy to dst_path.

    If reference_path is given, MasterSpread TextFrame anchor points are pulled from
    that reference IDML and restored on matching frames in the output — preserving
    footer, running-head and page-number positions verbatim.
    src is never modified.
    """
    ref_masters = {}
    if reference_path and os.path.isfile(reference_path):
        with zipfile.ZipFile(reference_path) as rz:
            for info in rz.infolist():
                if info.filename.startswith("MasterSpreads/") and info.filename.endswith(".xml"):
                    try:
                        ref_masters[info.filename] = _extract_master_frame_geometry(
                            rz.read(info.filename).decode("utf-8")
                        )
                    except Exception:
                        pass

    with open(src_path, "rb") as f:
        data = f.read()

    with zipfile.ZipFile(io.BytesIO(data), "r") as zin:
        names = zin.namelist()
        assert "mimetype" in names, "Not a valid IDML (no mimetype entry)"
        members = {n: zin.read(n) for n in names}

    # Discover primary master ID from MasterSpreads
    master_id = None
    for name in names:
        if name.startswith("MasterSpreads/") and name.endswith(".xml"):
            m_txt = members[name].decode("utf-8", "ignore")
            m_self = re.search(r'<MasterSpread\b[^>]*?\sSelf="([^"]+)"', m_txt)
            if m_self:
                master_id = m_self.group(1)
                break

    # Discover body start page: 7 if About Author exists, else 5
    has_author = False
    for name in names:
        if name.startswith("Stories/") and name.endswith(".xml"):
            s_lower = members[name].decode("utf-8", "ignore").lower()
            if "sobre la autor" in s_lower or "about the author" in s_lower:
                has_author = True
                break
    body_start_page = 7 if has_author else 5

    for name, blob in list(members.items()):
        lower = name.lower()
        if not lower.endswith(".xml"):
            continue
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            continue

        new_text = text
        if lower.endswith("resources/preferences.xml"):
            new_text = _rewrite_document_preference(new_text)
            new_text = _rewrite_margin_preferences(new_text)
            new_text = _rewrite_text_default(new_text)
        elif lower.startswith("spreads/"):
            new_text = _rewrite_margin_preferences(new_text)
            new_text = _rewrite_page_bounds(new_text, master_id=master_id, body_start_page=body_start_page)
            new_text = _rewrite_text_frames(new_text)
        elif lower.startswith("masterspreads/"):
            new_text = _rewrite_margin_preferences(new_text)
            new_text = _rewrite_page_bounds(new_text, body_start_page=body_start_page)

        if name in ref_masters and ref_masters[name]:
            new_text, _fixed = _apply_master_frame_geometry(new_text, ref_masters[name])

        if new_text != text:
            members[name] = new_text.encode("utf-8")

    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    tmp_path = dst_path + ".tmp"
    with zipfile.ZipFile(tmp_path, "w", allowZip64=True) as zout:
        zi = zipfile.ZipInfo("mimetype")
        zi.compress_type = zipfile.ZIP_STORED
        zout.writestr(zi, members["mimetype"])
        for name in names:
            if name == "mimetype":
                continue
            zi = zipfile.ZipInfo(name)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, members[name])
    os.replace(tmp_path, dst_path)


def normalize_extracted_dir(work_dir: str, ref_dir: str = None) -> dict:
    """Applies normalization directly on an extracted IDML directory (for in-pipeline execution)."""
    pref_path = os.path.join(work_dir, "Resources", "Preferences.xml")
    if os.path.isfile(pref_path):
        with open(pref_path, "r", encoding="utf-8") as f:
            t = f.read()
        t = _rewrite_document_preference(t)
        t = _rewrite_margin_preferences(t)
        t = _rewrite_text_default(t)
        with open(pref_path, "w", encoding="utf-8") as f:
            f.write(t)

    masters_dir = os.path.join(work_dir, "MasterSpreads")
    master_id = None
    if os.path.isdir(masters_dir):
        for m in os.listdir(masters_dir):
            if m.endswith(".xml"):
                with open(os.path.join(masters_dir, m), "r", encoding="utf-8", errors="ignore") as fh:
                    m_txt = fh.read()
                    m_self = re.search(r'<MasterSpread\b[^>]*?\sSelf="([^"]+)"', m_txt)
                    if m_self:
                        master_id = m_self.group(1)
                        break

    spreads_dir = os.path.join(work_dir, "Spreads")
    spread_count = 0
    if os.path.isdir(spreads_dir):
        for s in os.listdir(spreads_dir):
            if s.endswith(".xml"):
                sp = os.path.join(spreads_dir, s)
                with open(sp, "r", encoding="utf-8") as f:
                    t = f.read()
                t = _rewrite_margin_preferences(t)
                t = _rewrite_page_bounds(t, master_id=master_id)
                t = _rewrite_text_frames(t)
                with open(sp, "w", encoding="utf-8") as f:
                    f.write(t)
                spread_count += 1

    masters_dir = os.path.join(work_dir, "MasterSpreads")
    master_count = 0
    if os.path.isdir(masters_dir):
        for m in os.listdir(masters_dir):
            if m.endswith(".xml"):
                mp = os.path.join(masters_dir, m)
                with open(mp, "r", encoding="utf-8") as f:
                    t = f.read()
                t = _rewrite_margin_preferences(t)
                t = _rewrite_page_bounds(t)
                with open(mp, "w", encoding="utf-8") as f:
                    f.write(t)
                master_count += 1

    return {
        "preferences_applied": True,
        "spreads_normalized": spread_count,
        "masters_normalized": master_count,
        "page_width": PAGE_W,
        "page_height": PAGE_H,
    }


def normalize_one_file(src_path: str, dst_path: str) -> bool:
    """Normalize a single IDML file in-place or to a destination path."""
    dst_dir = os.path.dirname(dst_path)
    os.makedirs(dst_dir, exist_ok=True)
    _normalize_one_idml(src_path, dst_path, reference_path=src_path)

    # Ensure Document fonts folder is preserved in output directory
    src_fonts = os.path.join(os.path.dirname(src_path), "Document fonts")
    dst_fonts = os.path.join(dst_dir, "Document fonts")
    if os.path.isdir(src_fonts) and not os.path.exists(dst_fonts):
        try:
            shutil.copytree(src_fonts, dst_fonts)
        except Exception:
            pass
    return True


def normalize_batch(input_folder: str, output_folder: str, target_files: list = None) -> tuple:
    """Batch-normalize IDML files from input_folder to output_folder."""
    os.makedirs(output_folder, exist_ok=True)
    if target_files:
        files = [os.path.basename(f) for f in target_files]
    else:
        files = [f for f in os.listdir(input_folder) if f.lower().endswith(".idml") and not f.startswith("~")]

    ok = fail = 0
    log_path = os.path.join(output_folder, "_normalize_log.txt")
    log = [
        "=== IDML Doc-Setup Normalization (offline, no InDesign) ===",
        f"Date: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"Source: {input_folder}",
        f"Output: {output_folder}",
        "-" * 70,
    ]
    for name in files:
        src = os.path.join(input_folder, name)
        dst = os.path.join(output_folder, name)
        try:
            normalize_one_file(src, dst)
            log.append(f"{name}: OK -> {dst}")
            ok += 1
        except Exception as e:
            print(f"  FAIL on {name}: {e}", flush=True)
            log.append(f"{name}: FAIL {e}")
            fail += 1

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log))
    return ok, fail


def main() -> None:
    input_folder = sys.argv[1] if len(sys.argv) > 1 else INPUT_DIR
    output_folder = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_DIR

    if os.path.isfile(input_folder):
        dst = os.path.join(output_folder, os.path.basename(input_folder)) if os.path.isdir(output_folder) else output_folder
        print(f"Normalizing single file: {input_folder} -> {dst}")
        normalize_one_file(input_folder, dst)
        print("Done.")
        return

    ok, fail = normalize_batch(input_folder, output_folder)
    print(f"\nDone. {ok} normalized, {fail} failed.")


if __name__ == "__main__":
    main()

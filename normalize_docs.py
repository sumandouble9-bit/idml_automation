import os

import re

import shutil

import zipfile

import io

from datetime import datetime

INPUT_DIR   = r"D:\IDML-Creation\input_files"

OUTPUT_DIR  = r"D:\IDML-Creation\page_resize_output"

LOG_PATH    = os.path.join(OUTPUT_DIR, "_normalize_log.txt")

PAGE_W        = 396.0

PAGE_H        = 612.0

MARGIN_TOP    = 36.0

MARGIN_BOT    = 54.0

MARGIN_L      = 36.0

MARGIN_R      = 36.0

BLEED_TB      = 8.503937

BLEED_INSIDE  = 0.0

BLEED_OUTSIDE = 8.503937

def _set_attr(xml_str: str, tag: str, attr: str, value: str) -> str:

    """Replace attr=\"...\" inside every <tag ...> occurrence. Adds it if absent."""

    pattern_replace = re.compile(rf'(<{tag}\b[^>]*?)\s{re.escape(attr)}="[^"]*"', re.DOTALL)

    xml_str, n = pattern_replace.subn(rf'\1 {attr}="{value}"', xml_str)

    if n == 0:

        pattern_add = re.compile(rf'(<{tag}\b)([^>]*?/?>)', re.DOTALL)

        xml_str = pattern_add.sub(rf'\1 {attr}="{value}"\2', xml_str)

    return xml_str

def _rewrite_document_preference(xml_str: str) -> str:

    for k, v in [

        ("PageWidth",  f"{PAGE_W}"),

        ("PageHeight", f"{PAGE_H}"),

        ("FacingPages", "true"),

        ("DocumentBleedUniformSize",           "false"),

        ("DocumentBleedTopOffset",             f"{BLEED_TB}"),

        ("DocumentBleedBottomOffset",          f"{BLEED_TB}"),

        ("DocumentBleedInsideOrLeftOffset",    f"{BLEED_INSIDE}"),

        ("DocumentBleedOutsideOrRightOffset",  f"{BLEED_OUTSIDE}"),

    ]:

        xml_str = _set_attr(xml_str, "DocumentPreference", k, v)

    return xml_str

def _rewrite_margin_preferences(xml_str: str) -> str:

    for k, v in [

        ("Top",           f"{MARGIN_TOP}"),

        ("Bottom",        f"{MARGIN_BOT}"),

        ("Left",          f"{MARGIN_L}"),

        ("Right",         f"{MARGIN_R}"),

        ("ColumnCount",   "1"),

        ("ColumnGutter",  "0"),

        ("ColumnDirection", "Horizontal"),

        ("ColumnsPositions", f"0 {PAGE_W - MARGIN_L - MARGIN_R}"),

    ]:

        xml_str = _set_attr(xml_str, "MarginPreference", k, v)

    return xml_str

_PAGE_BOUNDS_RE = re.compile(
    r'(<Page\b[^>]*?\sGeometricBounds=")([^"]+)(")',
    re.DOTALL,
)

def _rewrite_page_bounds(xml_str: str) -> str:
    """Rewrite every <Page ...> GeometricBounds preserving the y1/x1 origin the
    source uses (which the text frames' spread-coord positions depend on) and
    only setting y2 = y1 + PAGE_H, x2 = x1 + PAGE_W.
    """
    def _sub(m):
        head, bounds, tail = m.group(1), m.group(2), m.group(3)
        try:
            y1, x1, y2, x2 = [float(n) for n in bounds.split()]
        except Exception:
            return m.group(0)
        new_bounds = f"{y1} {x1} {y1 + PAGE_H} {x1 + PAGE_W}"
        return f"{head}{new_bounds}{tail}"
    return _PAGE_BOUNDS_RE.sub(_sub, xml_str)

_PAGE_TAG_RE           = re.compile(r'<Page\b[^>]*?>', re.DOTALL)
_TEXTFRAME_RE          = re.compile(r'<TextFrame\b.*?</TextFrame>', re.DOTALL)
_ATTR_ITEMTRANSFORM_RE = re.compile(r'ItemTransform="([^"]+)"')
_ATTR_GEOMBOUNDS_RE    = re.compile(r'GeometricBounds="([^"]+)"')
_PATHPOINT_RE          = re.compile(r'<PathPointType\b[^/>]*/>')

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

    def _page_for_center(cx: float, cy: float):
        for (sx1, sy1, sx2, sy2) in pages:
            if sx1 <= cx <= sx2 and sy1 <= cy <= sy2:
                return (sx1, sy1, sx2, sy2)
        best = None; best_d = float("inf")
        for p in pages:
            sx1, sy1, sx2, sy2 = p
            pcx = (sx1 + sx2) / 2
            pcy = (sy1 + sy2) / 2
            d = (pcx - cx) ** 2 + (pcy - cy) ** 2
            if d < best_d:
                best_d = d; best = p
        return best

    def _rewrite_frame(tf_xml: str) -> str:
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
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        f_x1 = tx + min(xs); f_x2 = tx + max(xs)
        f_y1 = ty + min(ys); f_y2 = ty + max(ys)

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
        new_tx = psx1 + MARGIN_L
        new_ty = psy1 + MARGIN_TOP
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
            pp = re.sub(r'Anchor="[^"]+"',         f'Anchor="{coord}"',         pp, count=1)
            pp = re.sub(r'LeftDirection="[^"]+"',  f'LeftDirection="{coord}"',  pp, count=1)
            pp = re.sub(r'RightDirection="[^"]+"', f'RightDirection="{coord}"', pp, count=1)
            return pp
        tf_xml = _PATHPOINT_RE.sub(_pp_sub, tf_xml)
        return tf_xml

    return _TEXTFRAME_RE.sub(lambda m: _rewrite_frame(m.group(0)), xml_str)

import xml.etree.ElementTree as _ET


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
    for tf in root.iter('TextFrame'):
        transform = tf.get('ItemTransform', '')
        points = [ppt.get('Anchor') for ppt in tf.iter('PathPointType') if ppt.get('Anchor')]
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
    for tf in root.iter('TextFrame'):
        transform = tf.get('ItemTransform', '')
        if transform in orig_geometry:
            orig_points = orig_geometry[transform]
            current_points = [ppt.get('Anchor') for ppt in tf.iter('PathPointType') if ppt.get('Anchor')]
            if current_points != orig_points:
                ppt_elements = list(tf.iter('PathPointType'))
                for i, ppt in enumerate(ppt_elements):
                    if i < len(orig_points):
                        ppt.set('Anchor', orig_points[i])
                        ppt.set('LeftDirection', orig_points[i])
                        ppt.set('RightDirection', orig_points[i])
                fixed += 1
    if fixed == 0:
        return master_xml, 0
    result = _ET.tostring(root, encoding='unicode', xml_declaration=False)
    if not result.startswith('<?xml'):
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
                if info.filename.startswith('MasterSpreads/') and info.filename.endswith('.xml'):
                    try:
                        ref_masters[info.filename] = _extract_master_frame_geometry(
                            rz.read(info.filename).decode('utf-8'))
                    except Exception:
                        pass

    with open(src_path, "rb") as f:

        data = f.read()

    with zipfile.ZipFile(io.BytesIO(data), "r") as zin:

        names = zin.namelist()

        assert "mimetype" in names, "Not a valid IDML (no mimetype entry)"

        members = {n: zin.read(n) for n in names}

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

        elif lower.startswith("spreads/"):

            new_text = _rewrite_margin_preferences(new_text)

            new_text = _rewrite_page_bounds(new_text)

            new_text = _rewrite_text_frames(new_text)

        elif lower.startswith("masterspreads/"):

            new_text = _rewrite_margin_preferences(new_text)

            new_text = _rewrite_page_bounds(new_text)

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

def main() -> None:

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    idml_files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(".idml")]

    if not idml_files:

        print(f"No IDML files found in {INPUT_DIR}")

        return

    log = [

        "=== IDML Doc-Setup Normalization (offline, no InDesign) ===",

        f"Date: {datetime.now():%Y-%m-%d %H:%M:%S}",

        f"Source: {INPUT_DIR}",

        f"Output: {OUTPUT_DIR}",

        f"Target: {PAGE_W}x{PAGE_H} pt, margins {MARGIN_TOP}/{MARGIN_BOT}/{MARGIN_L}/{MARGIN_R} pt, "

        f"bleed {BLEED_TB}/{BLEED_TB}/{BLEED_INSIDE}/{BLEED_OUTSIDE} pt",

        "-" * 70,

    ]

    ok = fail = 0

    for name in idml_files:

        src = os.path.join(INPUT_DIR, name)

        dst = os.path.join(OUTPUT_DIR, name)

        print(f"Normalizing: {name}  ->  {dst}", flush=True)

        try:

            _normalize_one_idml(src, dst, reference_path=src)

            log.append(f"{name}: OK -> {dst}")

            ok += 1

        except Exception as e:

            print(f"  FAIL: {e}", flush=True)

            log.append(f"{name}: FAIL {e}")

            fail += 1

    log.append("-" * 70)

    log.append(f"Summary: {ok} normalized, {fail} failed.")

    with open(LOG_PATH, "w", encoding="utf-8") as f:

        f.write("\n".join(log))

    print(f"\nDone. {ok} normalized, {fail} failed. Log: {LOG_PATH}")

if __name__ == "__main__":

    main()

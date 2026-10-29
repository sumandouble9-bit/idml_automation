# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def _ln(tag):
    return tag.rsplit("}", 1)[-1]


def _frame_height(rect):
    ys = []
    for pp in rect.iter():
        if _ln(pp.tag) == "PathPointType":
            parts = (pp.attrib.get("Anchor", "") or "").split()
            if len(parts) == 2:
                try:
                    ys.append(float(parts[1]))
                except ValueError:
                    pass
    if not ys:
        return 0.0
    return max(ys) - min(ys)


def fix_inline_image_leading(sroot):
    changed = False
    parent = {}
    for p in sroot.iter():
        for c in p:
            parent[c] = p
    def _in_cell(node):
        cur = parent.get(node)
        depth = 0
        while cur is not None and depth < 40:
            if _ln(cur.tag) in ("Cell", "Table"):
                return True
            cur = parent.get(cur)
            depth += 1
        return False
    for psr in sroot.iter():
        if _ln(psr.tag) != "ParagraphStyleRange":
            continue
        if _in_cell(psr):
            continue
        for csr in list(psr):
            if _ln(csr.tag) != "CharacterStyleRange":
                continue
            rects = [e for e in csr.iter() if _ln(e.tag) == "Rectangle"]
            if not rects:
                continue
            h = _frame_height(rects[0])
            if h <= 14:
                continue
            target = str(round(h + 2.0, 2))
            props = next((p for p in csr if _ln(p.tag) == "Properties"), None)
            if props is None:
                props = ET.Element("Properties")
                csr.insert(0, props)
            ld = next((l for l in props if _ln(l.tag) == "Leading"), None)
            if ld is None:
                ld = ET.SubElement(props, "Leading")
            ld.set("type", "unit")
            if ld.text != target:
                ld.text = target
                changed = True
    return changed


# Sets the Leading of the character run that holds an inline image Rectangle to the
# image frame's own height (fixed), so the line box reserves the full image height
# and InDesign renders the whole image at its anchor instead of clipping the top
# (auto leading is a percentage of height, e.g. 60%, which crops tall images). Only
# runs that actually contain a Rectangle image are touched; body text is untouched.


def _rect_bounds(rect):
    xs = []
    ys = []
    for pp in rect.iter():
        if _ln(pp.tag) == "PathPointType":
            a = (pp.attrib.get("Anchor", "") or "").split()
            if len(a) == 2:
                try:
                    xs.append(float(a[0]))
                    ys.append(float(a[1]))
                except ValueError:
                    pass
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _scale_point_attr(el, attr, cx, y0, s):
    v = (el.attrib.get(attr, "") or "").split()
    if len(v) != 2:
        return
    try:
        x = float(v[0])
        y = float(v[1])
    except ValueError:
        return
    nx = cx + (x - cx) * s
    ny = y0 + (y - y0) * s
    el.set(attr, "%s %s" % (nx, ny))


def resize_tall_images(sroot, max_h):
    changed = False
    parent = {}
    for p in sroot.iter():
        for c in p:
            parent[c] = p

    def _in_cell(node):
        cur = parent.get(node)
        depth = 0
        while cur is not None and depth < 40:
            if _ln(cur.tag) in ("Cell", "Table"):
                return True
            cur = parent.get(cur)
            depth += 1
        return False

    for rect in sroot.iter():
        if _ln(rect.tag) != "Rectangle":
            continue
        if _in_cell(rect):
            continue
        img = next((e for e in rect.iter() if _ln(e.tag) == "Image"), None)
        if img is None:
            continue
        b = _rect_bounds(rect)
        if not b:
            continue
        x0, y0, x1, y1 = b
        h = y1 - y0
        if h <= max_h or h <= 0:
            continue
        s = max_h / h
        cx = (x0 + x1) / 2.0
        for pp in rect.iter():
            if _ln(pp.tag) == "PathPointType":
                for a in ("Anchor", "LeftDirection", "RightDirection"):
                    _scale_point_attr(pp, a, cx, y0, s)
        it = (img.attrib.get("ItemTransform", "") or "").split()
        if len(it) == 6:
            try:
                a, bb, c, d, e, f = [float(v) for v in it]
                na, nd = a * s, d * s
                ne = cx + (e - cx) * s
                nf = y0 + (f - y0) * s
                img.set("ItemTransform", "%s %s %s %s %s %s" % (na, bb, c, nd, ne, nf))
            except ValueError:
                pass
        changed = True
    return changed


# Proportionally scales DOWN only the inline images whose frame height exceeds
# max_h (points), so a large image no longer consumes a whole page line by
# itself and body text can share the page with it (far fewer, non-wasted pages).
# Scaling is uniform about the frame's top-centre, so the image stays centred and
# anchored where its placeholder was; images already within max_h keep their
# original size. In-cell (table) images are never touched. Run BEFORE
# fix_inline_image_leading so the recomputed leading matches the new height.


def _usable_frame_height(extract_dir):
    from collections import Counter
    heights = []
    spreads_dir = os.path.join(extract_dir, "Spreads")
    if not os.path.isdir(spreads_dir):
        return 0.0
    for fn in os.listdir(spreads_dir):
        if not fn.lower().endswith(".xml"):
            continue
        try:
            root = ET.parse(os.path.join(spreads_dir, fn)).getroot()
        except ET.ParseError:
            continue
        for tf in root.iter():
            if _ln(tf.tag) != "TextFrame":
                continue
            ys = []
            for pp in tf.iter():
                if _ln(pp.tag) == "PathPointType":
                    a = (pp.attrib.get("Anchor", "") or "").split()
                    if len(a) == 2:
                        try:
                            ys.append(float(a[1]))
                        except ValueError:
                            pass
            if ys:
                heights.append(round(max(ys) - min(ys), 1))
    if not heights:
        return 0.0
    return Counter(heights).most_common(1)[0][0]


# Returns the height (points) of the book's main body text frame - the most
# common TextFrame height across all spreads. Used as the resize cap so an image
# is shrunk only when it is taller than a full text column (i.e. it genuinely
# cannot fit on one page); images that already fit keep their original size.


def apply_to_idml(idml_path, max_h="auto"):
    idml_path = str(idml_path)
    tmpd = tempfile.mkdtemp(prefix="idml_lead_")
    try:
        with zipfile.ZipFile(idml_path, "r") as z:
            names = z.namelist()
            z.extractall(tmpd)
        if max_h == "auto":
            max_h = _usable_frame_height(tmpd)
        any_changed = False
        stories_dir = os.path.join(tmpd, "Stories")
        if os.path.isdir(stories_dir):
            for fn in os.listdir(stories_dir):
                if not fn.lower().endswith(".xml"):
                    continue
                fp = os.path.join(stories_dir, fn)
                try:
                    tree = ET.parse(fp)
                except ET.ParseError:
                    continue
                root = tree.getroot()
                ch = False
                if max_h and resize_tall_images(root, max_h):
                    ch = True
                if fix_inline_image_leading(root):
                    ch = True
                if ch:
                    tree.write(fp, xml_declaration=True, encoding="UTF-8")
                    any_changed = True
        if any_changed:
            tmp_zip = idml_path + ".tmp"
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
                first = "mimetype"
                if first in names:
                    zout.write(os.path.join(tmpd, first), first, compress_type=zipfile.ZIP_STORED)
                for nm in names:
                    if nm == first:
                        continue
                    fp = os.path.join(tmpd, nm)
                    if os.path.isfile(fp):
                        zout.write(fp, nm)
            shutil.move(tmp_zip, idml_path)
        return any_changed
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


# Opens an injected IDML (a zip), applies fix_inline_image_leading to every
# Stories/*.xml so each inline image's line box reserves the full image height,
# then rewrites the IDML in place (mimetype stored first, uncompressed, as the
# IDML spec requires). This is a pure IDML edit: no InDesign, no re-pagination.

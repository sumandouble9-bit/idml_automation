import os
import sys
import glob
from math import sqrt

HERE = os.path.dirname(os.path.abspath(__file__))
RESIZE_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(RESIZE_DIR)
sys.path.insert(0, REPO)

from . import geometry as G
from . import refine, step1_resize, indesign_jobs

INPUT_DIR = os.path.join(REPO, "final_output_files", "idml_files")   # built books; use <book>.idml (never _injected)
OUT_DIR = os.path.join(RESIZE_DIR, "output")


class _Plan:
    """Size band for one placed image: name plus allowed max/min height in pt (image.h and image.h*rmin)."""

    def __init__(self, name, max_h, min_h):
        self.name = name
        self.max_h = max_h
        self.min_h_abs = min_h


def _list_images_js():
    """ExtendScript: list every non-logo linked image as 'name|frameW|frameH' (points), one per line."""
    return (
        'var doc=app.activeDocument; try{doc.recompose();}catch(e){}'
        'var gs=doc.allGraphics, out=[];'
        'for(var g=0;g<gs.length;g++){ try{ var gr=gs[g]; var fr=gr.parent;'
        ' var nm=""; try{ nm=gr.itemLink?gr.itemLink.name:""; }catch(e){}'
        ' if(!nm) continue; var U=nm.toUpperCase(); if(U.indexOf("LOGO")>=0||U.indexOf("LEAF-BOUND")>=0) continue;'
        ' var b=fr.geometricBounds; var w=(b[3]-b[1]).toFixed(2), h=(b[2]-b[0]).toFixed(2);'
        ' out.push(nm+"|"+w+"|"+h); }catch(e2){} }'
        'out.join(String.fromCharCode(10));'
    )


def _bounds(w, h):
    """From a placed image's width/height (pt), return (image_h, image_h*rmin) per the area/column rules."""
    if w <= 0 or h <= 0:
        return None
    aspect = w / h
    h_width = G.TEXT_WIDTH_PT / aspect
    h_frame = G.FRAME_HEIGHT_PT - G.PAD_PT
    h_area_max = sqrt(G.AREA_MAX / aspect)
    max_h = min(h_width, h_frame, h_area_max)
    min_h = min(sqrt(G.AREA_MIN / aspect), max_h)
    return max_h, min_h


def _plans_from_doc(app):
    """Build each placed image's size range from the IDML geometry only (keyed by link name)."""
    rows = app.DoScript(_list_images_js(), indesign_jobs.JS) or ""
    seen, plans = set(), []
    for row in rows.split("\n"):
        parts = row.strip().split("|")
        if len(parts) != 3:
            continue
        name, w, h = parts[0].strip(), parts[1], parts[2]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            band = _bounds(float(w), float(h))
        except ValueError:
            band = None
        if band:
            plans.append(_Plan(name, band[0], band[1]))
    return plans


def _resolve(book):
    """Resolve a book id/path to the plain built IDML (<book>.idml, never _injected) and its book id."""
    if os.path.isfile(book) and book.lower().endswith(".idml"):
        return book, os.path.splitext(os.path.basename(book))[0].replace("_injected", "")
    bid = os.path.splitext(os.path.basename(book))[0].replace("_injected", "")
    return os.path.join(INPUT_DIR, bid + ".idml"), bid


def _write_step1_log(path, bid, n_images, step1, step1_log):
    """Write the STEP 1 log: the band table and one line per image with full before/after numbers."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"STEP 1 log for {bid}  (step1_resize.py)\n")
        f.write("Band chosen from the FULL block (image + fig caption) height as a share of the frame; the\n")
        f.write("shrink is applied to the image. Blocks < 40% are deferred to STEP 2. Floor = 35% of frame.\n")
        f.write("  90-100% -> 35%   80-90% -> 40%   70-80% -> 40%   60-70% -> 45%   50-60% -> 45%   40-50% -> 30%\n")
        f.write(f"Images: {n_images}   STEP 1 shrinks: {step1}\n")
        f.write("-" * 92 + "\n")
        for ln in step1_log:
            f.write(ln + "\n")


def _write_step2_log(path, bid, n_images, kept, resized, whole, log):
    """Write the STEP 2 log: keep-together / gap-fill / ensure-whole, one line per image or page."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"STEP 2 log for {bid}  (refine.py)\n")
        f.write("Keep image+caption together, gap-fill the pushed image into the previous-page gap, and ensure\n")
        f.write("both sit on one page. The 35%-of-frame floor is on the FULL block (image + caption).\n")
        f.write(f"Images: {n_images}   Kept together: {kept}   Gap-fill resizes: {resized}   Straddle fixes: {whole}\n")
        f.write("-" * 92 + "\n")
        for ln in log:
            f.write(ln + "\n")


def process(app, book):
    """Open one IDML, resize images (STEP 1 then STEP 2), and export the IDML/PDF plus a log per step."""
    idml, bid = _resolve(book)
    if not os.path.isfile(idml):
        print(f"[resize] no IDML for {bid}: {idml}")
        return
    book_out = os.path.join(OUT_DIR, bid)
    os.makedirs(book_out, exist_ok=True)

    indesign_jobs.open_doc(app, idml)
    plans = _plans_from_doc(app)
    step1, step1_log = step1_resize.step1_resize(app)          # STEP 1 (separate module) first
    kept, resized, whole, log = refine.refine(app, plans)      # then the gap-fill / keep-together logic
    print(f"[resize] {bid}: {len(plans)} image(s); step1 {step1}; kept-together {kept}; gap-fill {resized}; straddle-fixed {whole}")

    out_idml = os.path.join(book_out, bid + ".idml")
    out_pdf = os.path.join(book_out, bid + ".pdf")
    indesign_jobs.export_idml(app, out_idml)
    try:
        indesign_jobs.export_pdf(app, out_pdf)
    except Exception as exc:
        print(f"[resize] PDF export skipped (is {os.path.basename(out_pdf)} open?): {exc}")
    indesign_jobs.close_doc(app)

    step1_report = os.path.join(book_out, bid + "_step1_log.txt")
    step2_report = os.path.join(book_out, bid + "_step2_log.txt")
    _write_step1_log(step1_report, bid, len(plans), step1, step1_log)
    _write_step2_log(step2_report, bid, len(plans), kept, resized, whole, log)
    print(f"[resize] {bid}: -> {out_idml} ; logs {step1_report} , {step2_report}")


def main(argv=None):
    """Resize images for the requested book(s); no argument processes every <book>.idml (not _injected)."""
    argv = argv if argv is not None else sys.argv[1:]
    books = argv or sorted(p for p in glob.glob(os.path.join(INPUT_DIR, "*.idml")) if not p.endswith("_injected.idml"))
    app = indesign_jobs.connect()
    if app is None:
        print("[resize] could not connect to InDesign.")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    for b in books:
        try:
            process(app, b)
        except Exception as exc:
            print(f"[resize] ERROR on {b}: {exc}")


if __name__ == "__main__":
    main()

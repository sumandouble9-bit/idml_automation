import os
import sys
import glob
import time
import subprocess

import win32com.client

JS = 1246973031

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INJECT_DIR = os.path.join(REPO, "final_output_files", "idml_files")
OUTPUT_DIR = os.path.join(HERE, "output")  # resize_images/output/


def _measure_js():
    """ExtendScript: per image report page, prev-page gap, image W/H and body frame W/H, in page order."""
    return r"""
    var doc = app.activeDocument;
    doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
    var pageH = doc.documentPreferences.pageHeight;
    var pageW = doc.documentPreferences.pageWidth;

    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    function baseName(p){ if(!p) return ""; var s=String(p).replace(/\\/g,"/"); s=s.substring(s.lastIndexOf("/")+1); var d=s.lastIndexOf("."); return (d>0?s.substring(0,d):s); }

    var mainStory = null, maxLen = -1;
    for (var s=0; s<doc.stories.length; s++){
        try { if (doc.stories[s].characters.length > maxLen){ maxLen = doc.stories[s].characters.length; mainStory = doc.stories[s]; } } catch(eS){}
    }

    function bodyFrameOn(page){
        try {
            var tfs = page.textFrames, best = null, bestLen = -1;
            for (var i=0;i<tfs.length;i++){
                try {
                    if (mainStory && tfs[i].parentStory.id === mainStory.id){
                        var L = tfs[i].characters.length;
                        if (L > bestLen){ bestLen = L; best = tfs[i]; }
                    }
                } catch(eF){}
            }
            return best;
        } catch(e){ return null; }
    }

    function frameBox(page){
        // Body text-frame width/height from the page margins (the glue box), never the full page.
        var mp = page.marginPreferences;
        return { w: (pageW - mp.left - mp.right), h: ((pageH - mp.bottom) - mp.top), top: mp.top, bot: (pageH - mp.bottom) };
    }

    function gapOn(page){
        // Empty space from the last body baseline DOWN TO THE BOTTOM MARGIN (glue line).
        var box = frameBox(page);
        var tf = bodyFrameOn(page);
        var lastBase = box.top;
        if (tf){ try { if (tf.lines.length > 0) lastBase = tf.lines[-1].baseline; } catch(eL){} }
        return box.bot - lastBase;
    }

    doc.recompose();
    var gs = doc.allGraphics;
    var rows = [];
    for (var g=0; g<gs.length; g++){
        try {
            var gr = gs[g];
            if (gr.itemLink && isLogo(gr.itemLink.name)) continue;
            var fr = gr.parent;
            var inCell = false;
            try { inCell = (fr.parent && fr.parent.constructor.name === "Cell"); } catch(eC){}
            if (inCell) continue;

            var page = null;
            try { page = fr.parentPage; } catch(eP){}
            if (page === null) continue;
            var pgNum = page.documentOffset + 1;

            var ib = fr.geometricBounds;              // [top, left, bottom, right]
            var imgH = ib[2] - ib[0], imgW = ib[3] - ib[1];

            var box = frameBox(page);
            var frameW = box.w, frameH = box.h;
            // A previous-page gap is image-caused only when the image was pushed to the TOP of its
            // page (no body text above it). A mid-page image sits inside normal text -- no image gap.
            var pushed = (ib[0] - box.top) <= 24;
            var prevPg = "-", prevGap = -1;
            if (pushed && page.documentOffset >= 1){
                prevPg = page.documentOffset;             // 1-based previous page number
                prevGap = gapOn(doc.pages[page.documentOffset - 1]);
            }

            var idx = 1e15;
            try { idx = fr.storyOffset.index; } catch(eI){}
            rows.push({ pg: pgNum, idx: idx, s:
                baseName(gr.itemLink ? gr.itemLink.name : "") + "|" + pgNum + "|" + prevPg + "|" +
                imgW.toFixed(1) + "|" + imgH.toFixed(1) + "|" + frameW.toFixed(1) + "|" + frameH.toFixed(1) + "|" +
                (prevGap < 0 ? "-" : prevGap.toFixed(1))
            });
        } catch(eG){}
    }
    // Page order first (reading order), then anchor position within the page.
    rows.sort(function(a,b){ return (a.pg - b.pg) || (a.idx - b.idx); });
    var out = [];
    for (var r=0; r<rows.length; r++) out.push(rows[r].s);
    out.join("\n");
    """


def _write_report(log_text, out_path, idml_name):
    """Write the measured rows as one aligned table (page-ordered, with a running image number)."""
    header = ("#", "Image No.", "Page", "PrevPg", "PrevGap", "Gap%",
              "ImgW", "ImgH", "FrameW", "FrameH", "ImgW%", "ImgH%", "Hdiff")
    widths = [3, 10, 5, 6, 8, 6, 7, 7, 7, 7, 6, 6, 8]
    total_w = sum(widths) + 3 * (len(widths) - 1)
    lines = [
        f"Image / previous-page gap measurements for: {idml_name}",
        "Rows are in page (reading) order; # is a running image count.",
        "PrevPg/PrevGap = the image's PREVIOUS page and the empty space on it, from the last body line",
        "                 down to the bottom margin (glue line), bounded by the text frame.",
        "FrameW/FrameH  = body text-frame width/height (page minus margins).",
        "ImgW%/ImgH%    = image width vs frame width / image height vs frame height.",
        "Gap%           = previous-page gap as a share of the frame height.",
        "Hdiff          = frame height minus image height (vertical pt of the frame the image does not use).",
        "-" * total_w,
        " | ".join(h.ljust(w) for h, w in zip(header, widths)),
        "-" * total_w,
    ]
    count = 0
    for row in log_text.split("\n"):
        row = row.strip()
        if not row:
            continue
        parts = row.split("|")
        if len(parts) != 8:
            continue
        name, page, prev_pg, img_w, img_h, frame_w, frame_h, prev_gap = parts
        try:
            f_w, f_h, i_w, i_h = float(frame_w), float(frame_h), float(img_w), float(img_h)
            img_w_pct = f"{i_w / f_w * 100:.0f}%" if f_w else "-"
            img_h_pct = f"{i_h / f_h * 100:.0f}%" if f_h else "-"
            diff = f"{f_h - i_h:.1f}"
        except ValueError:
            img_w_pct = img_h_pct = diff = "-"
        try:
            gap_pct = f"{float(prev_gap) / float(frame_h) * 100:.0f}%" if prev_gap != "-" and float(frame_h) else "-"
        except ValueError:
            gap_pct = "-"
        count += 1
        cells = (str(count), name, page, prev_pg, prev_gap, gap_pct,
                 img_w, img_h, frame_w, frame_h, img_w_pct, img_h_pct, diff)
        lines.append(" | ".join(c.ljust(w) for c, w in zip(cells, widths)))
    lines.append("-" * total_w)
    lines.append(f"Images measured: {count}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return count


def _connect():
    """Connect to Adobe InDesign via COM, retrying once after killing a stuck instance."""
    for attempt in range(3):
        try:
            app = win32com.client.Dispatch("InDesign.Application")
            app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", JS)
            return app
        except Exception:
            time.sleep(3)
            if attempt == 1:
                subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
                time.sleep(3)
    return None


def _resolve(a):
    """Resolve one arg to a plain IDML in final_output_files/idml_files (<book>.idml, never _injected)."""
    if os.path.isfile(a):
        return [a]
    exact = os.path.join(INJECT_DIR, f"{a}.idml")
    if os.path.isfile(exact):
        return [exact]
    return [p for p in glob.glob(os.path.join(INJECT_DIR, f"*{a}*.idml")) if not p.endswith("_injected.idml")]


def _targets(args):
    """Resolve input IDML(s): args, or every plain <book>.idml in final_output_files/idml_files."""
    if args:
        out = []
        for a in args:
            out += _resolve(a)
        return sorted(set(out))
    return sorted(p for p in glob.glob(os.path.join(INJECT_DIR, "*.idml")) if not p.endswith("_injected.idml"))


def measure_idml(app, idml_path):
    """Open one IDML read-only, measure every image, write the single gap log, and close without saving."""
    base = os.path.basename(idml_path)
    book = os.path.splitext(base)[0].replace("_injected", "")
    book_dir = os.path.join(OUTPUT_DIR, book)
    os.makedirs(book_dir, exist_ok=True)
    out_report = os.path.join(book_dir, book + "_image_gaps.txt")

    app.DoScript('var d = app.open(new File("%s"));' % idml_path.replace("\\", "/"), JS)
    log_text = app.DoScript(_measure_js(), JS) or ""
    n = _write_report(log_text, out_report, base)
    app.DoScript("app.activeDocument.close(SaveOptions.NO);", JS)
    print(f"{book}: measured {n} image(s) -> {out_report}", flush=True)


def main():
    """Measure images and their previous-page gaps for the requested book(s)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    targets = _targets(sys.argv[1:])
    if not targets:
        print("No IDML found. Pass a book id or path, or run the resize/injection first.")
        return
    app = _connect()
    if app is None:
        print("Error: could not connect to Adobe InDesign.")
        return
    for idml in targets:
        try:
            measure_idml(app, idml)
        except Exception as e:
            print(f"ERROR on {os.path.basename(idml)}: {e}", flush=True)


if __name__ == "__main__":
    main()

"""Sequentially shrink oversized images so they drop back into the empty gap on the previous page.

Resizing one image makes everything below it flow upward, which changes the gap before every later
image. A static report cannot capture that, so this tool drives Adobe InDesign and processes images
strictly in document order (image001, image002, ...): before each image it RE-MEASURES the live gap
on the previous page, applies the 35% gap rule, resizes the image to fit, recomposes, then moves on.

Decision rule (per image, measured live):
  * Gap%  = empty space at the bottom of the previous page / body text-frame height.
  * If Gap% >= GAP_THRESHOLD_PCT, shrink the image so the image+caption block fits the gap:
        target_block = gap - BUFFER_PT            (keeps a safety margin above the bottom margin)
        target_img_h = target_block - caption_h    (leave room for the caption that travels with it)
        scale        = target_img_h / current_img_h
    The image is only shrunk (scale < 1) and never below MIN_IMG_H_PT.

Inputs  : D:\\idml_automation\\final_output_files\\idml_files\\<book>_injected.idml
Outputs : D:\\idml_automation\\resize_images\\<book>.idml, <book>.pdf, <book>_image_gaps_after.txt

Usage: python sequential_cascade_resize.py [book_id | idml_path]   (no arg = every *_injected.idml)
"""

import os
import sys
import glob
import time
import subprocess

import win32com.client

JS = 1246973031

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INPUT_DIR = os.path.join(REPO, "final_output_files", "idml_files")
OUTPUT_DIR = os.path.join(HERE, "output")  # resize_images/output/

GAP_THRESHOLD_PCT = 30.0   # only act when the previous-page gap is at least this share of the frame
BUFFER_PT = 16.0           # safety margin kept below the image/caption so it never touches the margin
MIN_IMG_H_PT = 72.0        # never shrink an image below ~1 inch tall
OVERSIZE_PCT = 55.0        # pass 1: first cap any image taller than this share of the text frame


def _cascade_js():
    """ExtendScript that walks every anchored image in document order and shrinks oversized ones."""
    return r"""
    var doc = app.activeDocument;
    doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
    var pageH = doc.documentPreferences.pageHeight;
    var GAP_PCT = __GAP_PCT__, BUFFER = __BUFFER__, MINH = __MINH__, OVER = __OVER__;

    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    function baseName(p){ if(!p) return ""; var s=String(p).replace(/\\/g,"/"); s=s.substring(s.lastIndexOf("/")+1); var d=s.lastIndexOf("."); return (d>0?s.substring(0,d):s); }

    // Main body story = the longest story in the document.
    var mainStory = null, maxLen = -1;
    for (var s=0; s<doc.stories.length; s++){
        try { if (doc.stories[s].characters.length > maxLen){ maxLen = doc.stories[s].characters.length; mainStory = doc.stories[s]; } } catch(eS){}
    }

    function pageOf(fr){ try { return fr.parentPage; } catch(e){ return null; } }

    function bodyFrameOn(page){
        // Text frame on this page that belongs to the main body story.
        try {
            var tfs = page.textFrames;
            var best = null, bestLen = -1;
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

    function gapOn(page){
        // Empty space (pt) from the last body baseline DOWN TO THE BOTTOM MARGIN (the glue line),
        // bounded by the text frame -- never the full page. Gap% is a share of the text-frame height.
        var tf = bodyFrameOn(page);
        if (!tf) return null;
        var mp = page.marginPreferences;
        var marginTop = mp.top;
        var marginBot = pageH - mp.bottom;
        var frameH = marginBot - marginTop;
        var lastBase = marginTop;
        try { if (tf.lines.length > 0) lastBase = tf.lines[-1].baseline; } catch(eL){}
        var gap = marginBot - lastBase;
        return { gap: gap, pct: (frameH>0 ? gap/frameH*100 : 0), frameH: frameH };
    }

    function captionHeightAfter(fr){
        // Height (pt) of the fig-caption paragraph that follows the image's OWN paragraph.
        try {
            var imgPara = fr.parent.paragraphs[0];
            var st = imgPara.parentStory;
            var lastIdx = imgPara.characters[-1].index;
            if (lastIdx + 1 >= st.characters.length) return 0;
            var para = st.characters[lastIdx + 1].paragraphs[0];
            var sName = String(para.appliedParagraphStyle.name).toLowerCase();
            if (sName.indexOf("caption") === -1) return 0;
            var lines = para.lines.length || 1;
            var pts = 9;
            try { pts = para.lines[0].pointSize; } catch(ePt){}
            if (!(pts > 0) || pts > 100) pts = 9;
            var lead = pts * 1.2;                     // Auto-leading approximation (never read the Auto enum)
            var sb = 0, sa = 0;
            try { sb = para.spaceBefore; if (!(sb >= 0) || sb > 100) sb = 0; } catch(eSb){}
            try { sa = para.spaceAfter;  if (!(sa >= 0) || sa > 100) sa = 0; } catch(eSa){}
            return lines * lead + sb + sa + 6;
        } catch(e){ return 0; }
    }

    // Collect non-logo, non-cell anchored images in document (story) order.
    var graphics = doc.allGraphics;
    var items = [];
    for (var g=0; g<graphics.length; g++){
        try {
            var gr = graphics[g];
            if (gr.itemLink && isLogo(gr.itemLink.name)) continue;
            var fr = gr.parent;
            var inCell = false;
            try { inCell = (fr.parent && fr.parent.constructor.name === "Cell"); } catch(eC){}
            if (inCell) continue;
            var idx = 1e15;
            try { idx = fr.storyOffset.index; } catch(e1){ try { idx = fr.parentPage.documentOffset * 100000; } catch(e2){} }
            items.push({ fid: fr.id, name: (gr.itemLink ? baseName(gr.itemLink.name) : ""), idx: idx });
        } catch(eG){}
    }
    items.sort(function(a,b){ return a.idx - b.idx; });

    // Re-resolve a frame by its stable id each iteration: resizing earlier images reflows the
    // document and invalidates frame references captured up front.
    function frameById(fid){
        var gs = doc.allGraphics;
        for (var j=0; j<gs.length; j++){
            try { if (gs[j].parent.id === fid) return gs[j].parent; } catch(eJ){}
        }
        return null;
    }

    // Resize an image proportionally by `scale` (scale the placed content, fit the frame to it) and
    // keep its caption glued to it.
    function shrinkImage(fr, scale){
        var ib = fr.geometricBounds;
        try {
            var gph = (fr.graphics.length > 0) ? fr.graphics[0] : null;
            if (gph !== null){
                gph.horizontalScale = gph.horizontalScale * scale;
                gph.verticalScale   = gph.verticalScale * scale;
                fr.fit(FitOptions.FRAME_TO_CONTENT);
                try { fr.fit(FitOptions.CENTER_CONTENT); } catch(eC){}
            } else {
                fr.geometricBounds = [ ib[0], ib[1], ib[0] + (ib[2]-ib[0])*scale, ib[1] + (ib[3]-ib[1])*scale ];
                fr.fit(FitOptions.CONTENT_TO_FRAME);
                try { fr.fit(FitOptions.CENTER_CONTENT); } catch(eC2){}
            }
        } catch(eRz){}
        try { fr.parent.paragraphs[0].keepWithNext = 1; } catch(eKW){}
    }

    function frameHeightOf(page){
        var mp = page.marginPreferences;
        return pageH - mp.bottom - mp.top;
    }

    function gapCascade(){
        var out = [];
        for (var k=0; k<items.length; k++){
            var name = items[k].name;
            var action = "skip", scale = 1.0, gBefore = 0, pBefore = 0, imgW = 0, imgH = 0, capH = 0, newH = 0, gAfter = 0;
            try {
                doc.recompose();
                var fr = frameById(items[k].fid);
                if (fr === null){ out.push(name + "|?|?|0|0|0|0|0|skip(not-found)|1|0|0"); continue; }
                var imgPage = pageOf(fr);
                if (imgPage === null){ out.push(name + "|?|?|0|0|0|0|0|skip(no-page)|1|0|0"); continue; }
                var imgPgNum = imgPage.documentOffset + 1;
                if (imgPage.documentOffset < 1){ out.push(name + "|1|" + imgPgNum + "|0|0|0|0|0|skip(first-page)|1|0|0"); continue; }
                var prevPage = doc.pages[imgPage.documentOffset - 1];
                var prevPgNum = prevPage.documentOffset + 1;

                var gi = gapOn(prevPage);
                if (gi === null){ out.push(name + "|" + prevPgNum + "|" + imgPgNum + "|0|0|0|0|0|skip(no-frame)|1|0|0"); continue; }
                gBefore = gi.gap; pBefore = gi.pct;

                var ib = fr.geometricBounds;
                imgH = ib[2] - ib[0]; imgW = ib[3] - ib[1];
                capH = captionHeightAfter(fr);

                if (pBefore >= GAP_PCT){
                    // Shrink the image so the image + its FULL caption fit together in the gap, keeping
                    // a safety buffer; the caption must stay below the image on this same page.
                    var targetImg = gBefore - BUFFER - capH;
                    if (targetImg >= MINH && targetImg < imgH){
                        scale = targetImg / imgH;
                        newH = imgH * scale;
                        // Proportional resize (Shift+Ctrl+drag): scale the placed image content, then fit
                        // the anchored frame tightly to it. Scaling the content (not the frame bounds)
                        // avoids corrupting the anchored object and reliably reduces its reserved height.
                        try {
                            var gph = (fr.graphics.length > 0) ? fr.graphics[0] : null;
                            if (gph !== null){
                                gph.horizontalScale = gph.horizontalScale * scale;
                                gph.verticalScale   = gph.verticalScale * scale;
                                fr.fit(FitOptions.FRAME_TO_CONTENT);
                                try { fr.fit(FitOptions.CENTER_CONTENT); } catch(eCC){}
                            } else {
                                fr.geometricBounds = [ ib[0], ib[1], ib[0] + newH, ib[1] + imgW * scale ];
                                fr.fit(FitOptions.CONTENT_TO_FRAME);
                                try { fr.fit(FitOptions.CENTER_CONTENT); } catch(eCC2){}
                            }
                        } catch(eRz){}
                        // Keep the caption glued to the image so it can never spill to the next page.
                        try { fr.parent.paragraphs[0].keepWithNext = 1; } catch(eKW){}
                        try { doc.recompose(); } catch(eRc){}
                        action = "resized";
                    } else {
                        action = (targetImg < MINH) ? "skip(too-small)" : "skip(fits)";
                    }
                } else {
                    action = "skip(<" + GAP_PCT + "%)";
                }

                // Re-measure: did the image move up, and what gap is left on the previous page?
                try { doc.recompose(); } catch(eRc2){}
                var frA = frameById(items[k].fid);
                var pgA = frA ? pageOf(frA) : null;
                var imgPgAfter = pgA ? (pgA.documentOffset + 1) : imgPgNum;
                var pp = doc.pages[prevPgNum - 1];
                var ga = pp ? gapOn(pp) : null;
                gAfter = ga ? ga.gap : 0;

                out.push(name + "|" + prevPgNum + "|" + imgPgNum + "|" + gBefore.toFixed(1) + "|" + pBefore.toFixed(1) +
                         "|" + imgW.toFixed(1) + "|" + imgH.toFixed(1) + "|" + capH.toFixed(1) + "|" + action +
                         "|" + scale.toFixed(3) + "|" + newH.toFixed(1) + "|" + gAfter.toFixed(1) + "|" + imgPgAfter);
            } catch(eItem){
                out.push(name + "|?|?|0|0|0|0|0|error:" + eItem.message + "|1|0|0|?");
            }
        }
        return out;
    }

    function oversizeCap(){
        for (var k0=0; k0<items.length; k0++){
            try {
                doc.recompose();
                var fr0 = frameById(items[k0].fid);
                if (fr0 === null) continue;
                var pg0 = pageOf(fr0);
                if (pg0 === null) continue;
                var frameH0 = frameHeightOf(pg0);
                var ib0 = fr0.geometricBounds;
                var imgH0 = ib0[2] - ib0[0];
                if (imgH0 >= (OVER/100) * frameH0){
                    var target0 = (OVER/100) * frameH0;
                    if (target0 >= MINH && target0 < imgH0){
                        shrinkImage(fr0, target0 / imgH0);
                        doc.recompose();
                    }
                }
            } catch(eP1){}
        }
    }

    // STEP 1: gap-closing cascade (the 35% rule). Produces the report of what was resized.
    var out = gapCascade();
    // STEP 2 (disabled): cap oversized plates (>= OVER% of the text frame) down to OVER%.
    // oversizeCap();
    // STEP 3: run the gap cascade again -- only matters when Step 2 is enabled (capped images may now fit).
    gapCascade();
    out.join("\n");
    """.replace("__GAP_PCT__", str(GAP_THRESHOLD_PCT)).replace("__BUFFER__", str(BUFFER_PT)).replace("__MINH__", str(MIN_IMG_H_PT)).replace("__OVER__", str(OVERSIZE_PCT))


def _write_report(log_text, out_path, idml_name):
    """Parse the ExtendScript result and write an aligned before/after table."""
    header = ("Image No.", "Prev Pg", "Img Pg", "GapBefore", "Gap%", "Img W", "Img H",
              "Cap H", "Action", "Scale", "New H", "GapAfter", "ImgPgAfter")
    widths = [10, 7, 6, 9, 6, 7, 7, 6, 16, 6, 7, 8, 10]
    total_w = sum(widths) + 3 * (len(widths) - 1)
    lines = [
        f"Sequential cascade resize report for: {idml_name}",
        f"Rule: shrink an image when the previous-page gap >= {GAP_THRESHOLD_PCT:.0f}% of the text frame,",
        f"so the image+caption fits the gap minus a {BUFFER_PT:.0f}pt buffer; never below {MIN_IMG_H_PT:.0f}pt tall.",
        "GapBefore/After are the live gaps on the previous page before/after this image was handled.",
        "-" * total_w,
        " | ".join(h.ljust(w) for h, w in zip(header, widths)),
        "-" * total_w,
    ]
    resized = 0
    for row in log_text.split("\n"):
        row = row.strip()
        if not row:
            continue
        parts = row.split("|")
        if len(parts) == 12:
            parts.append("?")   # older rows without ImgPgAfter
        if len(parts) != 13:
            continue
        if parts[8] == "resized":
            resized += 1
        lines.append(" | ".join(c.ljust(w) for c, w in zip(parts, widths)))
    lines.append("-" * total_w)
    lines.append(f"Images resized: {resized}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return resized


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


def process_idml(app, idml_path):
    """Open one IDML, run the cascade, export the resized IDML + PDF, and write the after-report."""
    base = os.path.basename(idml_path)
    book = os.path.splitext(base)[0].replace("_injected", "")
    book_dir = os.path.join(OUTPUT_DIR, book)
    os.makedirs(book_dir, exist_ok=True)
    out_idml = os.path.join(book_dir, book + ".idml")
    out_pdf = os.path.join(book_dir, book + ".pdf")
    out_report = os.path.join(book_dir, book + "_image_gaps_after.txt")

    print(f"[cascade] Opening {base} ...", flush=True)
    app.DoScript(
        'app.scriptPreferences.enableRedraw = false;'
        'var d = app.open(new File("%s"));'
        'try { d.textPreferences.smartTextReflow = false; } catch(e){}' % idml_path.replace("\\", "/"),
        JS,
    )

    log_text = app.DoScript(_cascade_js(), JS) or ""
    resized = _write_report(log_text, out_report, base)
    print(f"[cascade] {book}: {resized} image(s) resized -> {out_report}", flush=True)

    app.DoScript(
        'var outIdml = new File("%s");'
        'app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, outIdml);'
        % out_idml.replace("\\", "/"),
        JS,
    )
    try:
        app.DoScript(
            'var pp = app.pdfExportPresets.itemByName("[High Quality Print]");'
            'app.activeDocument.exportFile(ExportFormat.PDF_TYPE, new File("%s"), false, pp);'
            % out_pdf.replace("\\", "/"),
            JS,
        )
        print(f"[cascade] {book}: exported PDF -> {out_pdf}", flush=True)
    except Exception as e:
        print(f"[cascade] {book}: PDF export skipped: {e}", flush=True)

    app.DoScript(
        'app.activeDocument.close(SaveOptions.NO);'
        'app.scriptPreferences.enableRedraw = true;',
        JS,
    )
    print(f"[cascade] {book}: exported IDML -> {out_idml}", flush=True)


def _targets(args):
    """Resolve the input IDML path(s): a book id -> <book>.idml, a path, or none = all plain *.idml."""
    def plain(pat):
        return [p for p in glob.glob(os.path.join(INPUT_DIR, pat)) if not p.endswith("_injected.idml")]
    if not args:
        return sorted(plain("*.idml"))
    out = []
    for a in args:
        if os.path.isfile(a):
            out.append(a)
            continue
        exact = os.path.join(INPUT_DIR, f"{a}.idml")
        out += [exact] if os.path.isfile(exact) else plain(f"*{a}*.idml")
    return sorted(set(out))


def main():
    """Run the sequential cascade resize over the requested book(s)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    targets = _targets(sys.argv[1:])
    if not targets:
        print(f"No input IDML found in {INPUT_DIR} (expected <book>_injected.idml).")
        return
    app = _connect()
    if app is None:
        print("Error: could not connect to Adobe InDesign.")
        return
    for idml in targets:
        try:
            process_idml(app, idml)
        except Exception as e:
            print(f"[cascade] ERROR on {os.path.basename(idml)}: {e}", flush=True)


if __name__ == "__main__":
    main()

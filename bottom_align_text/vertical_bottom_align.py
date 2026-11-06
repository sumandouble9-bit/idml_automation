import os
import sys
import glob
import time
import subprocess

import win32com.client

JS = 1246973031

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)                                       # module lives in bottom_align_text/
INPUT_DIR = os.path.join(REPO, "idml_input_files")                 # raw pipeline input
OUT_DIR = os.path.join(REPO, "Output", "vertical_bottom_align")    # separate output, never the main one
MM_TO_PT = 72.0 / 25.4                      # points per millimetre
BOTTOM_INSET_MM = 1.0                        # client spec: 1 mm gap between text and the bottom-margin glue line
BOTTOM_INSET_PT = BOTTOM_INSET_MM * MM_TO_PT
MIN_FULL_RATIO = 0.72                        # policy knob: a page filled to >= this share of its line
                                             # capacity is justified; below it the page is a chapter/section
                                             # end and is top-aligned, so short pages are never stretched.


def _apply_js():
    """ExtendScript: bottom-justify full body pages; top-align short (chapter-end) pages so they don't stretch.

    No magic numbers: the 1mm inset and the one-line fullness tolerance are passed in as named constants,
    and each page's line capacity is derived from that frame's OWN measured line height and inset spacing.
    """
    return r"""
    (function(){
    var doc = app.activeDocument;
    try { doc.recompose(); } catch(eR){}
    try { doc.textPreferences.smartTextReflow = false; } catch(eS){}   // freeze frame count before editing
    doc.viewPreferences.horizontalMeasurementUnits = MeasurementUnits.POINTS;
    doc.viewPreferences.verticalMeasurementUnits = MeasurementUnits.POINTS;
    var BOTTOM = __BOTTOM__, MIN_FULL = __RATIO__, NL = String.fromCharCode(10);

    function els(c){ try{ return c.everyItem().getElements(); }catch(e){ return []; } }
    function longestStory(d){ var best=null,max=-1,sts=els(d.stories); for(var i=0;i<sts.length;i++){ var L=0; try{L=sts[i].characters.length;}catch(e){} if(L>max){max=L;best=sts[i];} } return best; }

    var story = longestStory(doc);
    if (!story) return "frames=0 body=0 justified=0 topShort=0 tables=0";
    var frames = story.textContainers;                 // thread order
    var lastIdx = frames.length - 1;

    var rep = { body:0, justified:0, topShort:0, tables:0 };
    var logs = [];
    for (var f=0; f<frames.length; f++){
        var tf = frames[f];
        var pg = null; try{ pg = tf.parentPage; }catch(eP){} if (pg === null) continue;   // skip pasteboard/overset
        rep.body++;
        var tfp = tf.textFramePreferences;
        var pgName="?"; try{ pgName = pg.name; }catch(e){}

        if (tf.tables.length > 0){
            tfp.verticalJustification = VerticalJustification.TOP_ALIGN;
            rep.tables++;
            logs.push("p."+pgName+" table frame -> TOP align");
            continue;
        }

        var hasImg = false;
        try { hasImg = (tf.allGraphics.length > 0); } catch(eG){}
        if (hasImg){
            tfp.verticalJustification = VerticalJustification.TOP_ALIGN;
            logs.push("p."+pgName+" graphic frame -> TOP align");
            continue;
        }

        var hasHead = false;
        try {
            for (var pi = 0; pi < tf.paragraphs.length; pi++){
                var sn = tf.paragraphs[pi].appliedParagraphStyle.name.toLowerCase();
                if (sn.indexOf("chapter") >= 0 || sn.indexOf("sub-heading") >= 0 || sn.indexOf("heading") >= 0 || sn.indexOf("title") >= 0){
                    hasHead = true; break;
                }
            }
        } catch(eH){}
        if (hasHead){
            tfp.verticalJustification = VerticalJustification.TOP_ALIGN;
            logs.push("p."+pgName+" heading frame -> TOP align");
            continue;
        }

        // Is the frame full? Derive capacity from the frame's OWN geometry and measured line height.
        var gb = tf.geometricBounds, h = gb[2]-gb[0];
        var ins = tfp.insetSpacing;
        var topI = (ins instanceof Array)?ins[0]:ins, botI = (ins instanceof Array)?ins[2]:ins;
        var avail = h - topI - botI;
        var nl = 0; try{ nl = tf.lines.length; }catch(e){}
        var lh = 0;
        try { if (nl >= 2){ var dd = tf.lines[-1].baseline - tf.lines[0].baseline; if (dd > 0) lh = dd/(nl-1); } } catch(e){}

        // Full when the frame is filled to at least MIN_FULL of its line capacity. A frame too short to
        // measure a line height (fewer than 2 lines) is clearly a short page.
        var cap = (lh > 0) ? (avail/lh) : 0;
        var isFull = (cap > 0) && ((nl/cap) >= MIN_FULL);

        if (!isFull){
            tfp.verticalJustification = VerticalJustification.TOP_ALIGN;
            try { tf.label = "d9_top"; }catch(e){}
            rep.topShort++;
            logs.push("p."+pgName+" chapter-end ("+nl+"/"+cap.toFixed(0)+" lines) -> TOP align (no stretch)");
        } else {
            tfp.verticalJustification = VerticalJustification.JUSTIFY_ALIGN;
            tfp.verticalThreshold = 1.0;
            if (ins instanceof Array){ tfp.insetSpacing = [ins[0], ins[1], BOTTOM, ins[3]]; }
            else { tfp.insetSpacing = [ins, ins, BOTTOM, ins]; }
            rep.justified++;
            logs.push("p."+pgName+" body ("+nl+"/"+cap.toFixed(0)+" lines) -> JustifyAlign (bottom inset "+BOTTOM.toFixed(2)+"pt)");
        }
    }
    try { doc.recompose(); } catch(e){}

    return "frames="+frames.length+" body="+rep.body+
    " justified="+rep.justified+" topShort="+rep.topShort+" tables="+rep.tables+NL+logs.join(NL);
    })();
    """.replace("__BOTTOM__", "%.5f" % BOTTOM_INSET_PT).replace("__RATIO__", "%.4f" % MIN_FULL_RATIO)


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


def process_idml(app, in_path, out_path=None):
    """Open a raw IDML, section-aware bottom-align the body, export to out_path, and write a log beside it."""
    base = os.path.basename(in_path)
    book = os.path.splitext(base)[0].replace("_injected", "")
    if out_path is None:
        os.makedirs(OUT_DIR, exist_ok=True)
        out_path = os.path.join(OUT_DIR, book + "_valign.idml")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    out_js = out_path.replace("\\", "/")

    # PASS A: open the raw IDML, let smart text reflow compose the book to its FULL page count,
    # then export -- this makes every reflowed page a real, saved frame (not an auto-regenerated one).
    app.DoScript(
        'app.scriptPreferences.enableRedraw = false;'
        'var d = app.open(new File("%s"));'
        'try { d.recompose(); } catch(e){}'
        'app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, new File("%s"));'
        'app.activeDocument.close(SaveOptions.NO);' % (in_path.replace("\\", "/"), out_js),
        JS,
    )
    # PASS B: reopen the composed copy (now all frames are real) and apply the alignment, then export.
    app.DoScript('var d = app.open(new File("%s"));' % out_js, JS)
    out = app.DoScript(_apply_js(), JS) or ""
    app.DoScript(
        'app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, new File("%s"));'
        'app.activeDocument.close(SaveOptions.NO);'
        'app.scriptPreferences.enableRedraw = true;' % out_js,
        JS,
    )

    lines = [ln for ln in out.split("\n") if ln.strip()]
    summary = lines[0] if lines else ""
    report = os.path.join(os.path.dirname(out_path), book + "_valign_log.txt")
    with open(report, "w", encoding="utf-8") as f:
        f.write(f"Vertical bottom-align log for {book}  (vertical_bottom_align.py, raw input)\n")
        f.write("Front matter (before the first chapter/section break) is left untouched.\n")
        f.write("Body pages -> JustifyAlign + 1pt bottom inset. Chapter-end / sparse pages -> TopAlign (no stretch).\n")
        f.write(summary + "\n")
        f.write("-" * 70 + "\n")
        for ln in lines[1:]:
            f.write(ln + "\n")
    print(f"[v-align] {book}: {summary} -> {out_path} ; log {report}", flush=True)


def _targets(args):
    """Resolve input IDML(s): a book id, a path, a folder, or none = every idml_input_files/*.idml."""
    if not args:
        return sorted(glob.glob(os.path.join(INPUT_DIR, "*.idml")))
    out = []
    for a in args:
        if os.path.isfile(a):
            out.append(a)
        elif os.path.isdir(a):
            out += glob.glob(os.path.join(a, "*.idml"))
        else:
            exact = os.path.join(INPUT_DIR, f"{a}.idml")
            if os.path.isfile(exact):
                out.append(exact)
            else:
                out += glob.glob(os.path.join(INPUT_DIR, f"*{a}*.idml"))
    return sorted(set(out))


def main():
    """Bottom-align the body of the requested book(s) from the raw input into Output/vertical_bottom_align."""
    targets = _targets(sys.argv[1:])
    if not targets:
        print(f"No IDML found in {INPUT_DIR}. Pass a path or book id.")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    app = _connect()
    if app is None:
        print("Error: could not connect to Adobe InDesign.")
        return
    for idml in targets:
        try:
            process_idml(app, idml)
        except Exception as e:
            print(f"[v-align] ERROR on {os.path.basename(idml)}: {e}", flush=True)


if __name__ == "__main__":
    main()

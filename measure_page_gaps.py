import os
import sys
import glob
import time
import threading
import win32com.client
from datetime import datetime

JS = 1246973031
WF = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.environ.get("GAPFIX_INPUT", "").strip() or \
    os.path.join(WF, "final_output_files", "idml_files")
LOG_PATH = os.path.join(os.path.dirname(INPUT_DIR), "page_gaps_report.txt")

ONLY = sys.argv[1].strip() if len(sys.argv) > 1 else ""
if ONLY.lower().endswith(".idml"):
    ONLY = ONLY[:-5]

# Returns two sections separated by \u0002 :
#   PAGES : docOffset \t folio \t gap \t kind
#   IMAGES: docOffset \t folio \t imgName \t width \t height
JS_MEASURE = r'''
var doc = app.activeDocument;
try { doc.recompose(); } catch (eRC) {}   // populate layout/graphics when opened invisibly
var oldRuler = doc.viewPreferences.rulerOrigin;
doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
var pageLines = [], imgLines = [];
function isLogo(nm){ nm=(nm||"").toUpperCase(); return nm.indexOf("LEAF-BOUND")>=0 || nm.indexOf("LOGO")>=0; }

var tocLastDocIdx = -1;
for (var s = 0; s < doc.stories.length; s++){
    var st = doc.stories[s];
    try {
        var paras = st.paragraphs;
        for (var p = 0; p < paras.length; p++){
            var nm = "";
            try { nm = String(paras[p].appliedParagraphStyle.name).toLowerCase(); } catch (e1) {}
            if (nm.indexOf("toc") >= 0){
                try {
                    var tf = paras[p].parentTextFrames;
                    if (tf.length && tf[0].parentPage){
                        var di = tf[0].parentPage.documentOffset;
                        if (di > tocLastDocIdx) tocLastDocIdx = di;
                    }
                } catch (e2) {}
            }
        }
    } catch (eS) {}
}

// chapter-start pages: a page whose body carries a chapter-title style (H1).
var chapStart = {};
for (var cs = 0; cs < doc.stories.length; cs++){
    try {
        var cps = doc.stories[cs].paragraphs;
        for (var cq = 0; cq < cps.length; cq++){
            var csn = "";
            try { csn = String(cps[cq].appliedParagraphStyle.name).toLowerCase(); } catch (eCn) {}
            if ((csn.indexOf("chapter_name") >= 0 && csn.indexOf("01") < 0) || csn.indexOf("master_chapter") >= 0){
                try {
                    var ctf = cps[cq].parentTextFrames;
                    if (ctf.length && ctf[0].parentPage) chapStart[ctf[0].parentPage.documentOffset] = true;
                } catch (eCp) {}
            }
        }
    } catch (eCs) {}
}

// Images: skip small inline decorations (both dimensions < MIN_FIG) -- those are
// part of the text flow, not figures, so they are not logged and do not mark the
// page as image-ending.
var MIN_FIG = 150;
var imgBottom = {};
for (var g = 0; g < doc.allGraphics.length; g++){
    try {
        var gr = doc.allGraphics[g];
        var nm = gr.itemLink ? gr.itemLink.name : "";
        if (isLogo(nm)) continue;
        var frm = gr.parent;                // the frame (Rectangle)
        var pg = null; try { pg = frm.parentPage; } catch (ePg) {}
        if (!pg) continue;
        var gb = frm.geometricBounds;
        var w = Math.round((gb[3]-gb[1])*10)/10;
        var h = Math.round((gb[2]-gb[0])*10)/10;
        if (w < MIN_FIG && h < MIN_FIG) continue;   // small inline decoration -> treat as text
        var key = pg.documentOffset;
        if (imgBottom[key] === undefined || gb[2] > imgBottom[key]) imgBottom[key] = gb[2];
        if (pg.documentOffset > tocLastDocIdx){
            imgLines.push(pg.documentOffset + "\t" + pg.name + "\t" + nm + "\t" + w + "\t" + h);
        }
    } catch (eG) {}
}

for (var pi = 0; pi < doc.pages.length; pi++){
    var page = doc.pages[pi];
    if (page.documentOffset <= tocLastDocIdx) continue;
    var pb = page.bounds;
    var marginBottomY = pb[2] - page.marginPreferences.bottom;
    var lowest = null, kind = "empty";
    try {
        var tfs = page.textFrames;
        for (var t = 0; t < tfs.length; t++){
            var f = tfs[t];
            var fb = f.geometricBounds;
            if ((fb[2]-fb[0]) < 120) continue;
            var chs = f.characters;
            if (chs.length === 0) continue;
            var b = null;
            try { b = chs[chs.length-1].baseline; } catch (eB) { b = null; }
            if (b === null) continue;
            if (lowest === null || b > lowest){ lowest = b; kind = "text"; }
        }
    } catch (eT) {}
    var ib = imgBottom[page.documentOffset];
    if (ib !== undefined && (lowest === null || ib > lowest)){ lowest = ib; kind = "image"; }
    var gapStr = (lowest === null) ? "-" : String(Math.round((marginBottomY - lowest)*10)/10);
    // chapter boundary: this page is a chapter-end if the NEXT page is a chapter start.
    var chapEnd = chapStart[page.documentOffset + 1] ? 1 : 0;
    pageLines.push(page.documentOffset + "\t" + page.name + "\t" + gapStr + "\t" + kind + "\t" + chapEnd);
}

doc.viewPreferences.rulerOrigin = oldRuler;
pageLines.join("\n") + "\u0002" + imgLines.join("\n");
'''


def _quiet(app):
    """Suppress InDesign dialogs/alerts as much as scripting allows."""
    for cmd in ("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                "app.scriptPreferences.enableRedraw = false;"):
        try:
            app.DoScript(cmd, JS)
        except Exception:
            pass


def dismiss_modal():
    """Press Enter on any visible standard dialog ('#32770') to accept its default
    (e.g. 'open with missing links') so InDesign stops blocking. It only touches
    dialog windows, never the main document window, so the document stays open and
    can be measured."""
    try:
        import win32gui
        import win32con
    except Exception:
        return
    dialogs = []

    def _cb(hwnd, acc):
        try:
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) == "#32770":
                acc.append(hwnd)
        except Exception:
            pass

    try:
        win32gui.EnumWindows(_cb, dialogs)
    except Exception:
        return
    for hwnd in dialogs:
        try:
            win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        except Exception:
            pass


class _ModalWatcher(threading.Thread):
    """Background thread that keeps dismissing InDesign alert dialogs so opens and
    measurements never stay blocked. Only presses Enter on dialogs, so the document
    opens (missing links accepted) and is still measured."""
    daemon = True

    def __init__(self):
        super().__init__()
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            dismiss_modal()
            time.sleep(0.4)

    def stop(self):
        self._stop.set()


def main():
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*_injected.idml")))
    if ONLY:
        files = [f for f in files if os.path.basename(f).startswith(ONLY)]
    if not files:
        print("No matching *_injected.idml in", INPUT_DIR)
        return

    app = win32com.client.Dispatch("InDesign.Application")
    _quiet(app)
    watcher = _ModalWatcher()   # auto-dismiss any InDesign alert during the whole run
    watcher.start()

    report = ["=== Page-Gap & Image Report (pages after TOC) ===",
              "Date: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "Seq# = page order in the PDF (1-based).  Folio = printed page number.",
              "Gap(pt) = space from the bottom margin up to the lowest body content.",
              ""]

    for f in files:
        base = os.path.basename(f)
        print("Measuring:", base)
        # Open + measure with up to 2 attempts. A missing-link / missing-font alert
        # leaves a modal dialog active which blocks ALL further scripting ("Cannot
        # handle the request because a modal dialog or alert is active"); force-restart
        # InDesign to clear it, then retry once.
        # NOTE: must open WITH a window -- opened invisibly InDesign does not compose
        # the layout, so anchored images (in table cells) are not placed.
        # The background watcher keeps dismissing any missing-link / missing-font
        # alert, so the document still opens (links accepted) and is measured.
        # Two attempts: if a modal briefly blocked the COM call, clear it and grab
        # the document that opened, then measure it.
        doc = None
        res = ""
        for attempt in (1, 2):
            try:
                _quiet(app)
                if attempt == 1:
                    doc = app.Open(f)
                else:
                    dismiss_modal()
                    time.sleep(1.0)
                    doc = app.activeDocument          # the doc that opened behind the alert
                res = app.DoScript(JS_MEASURE, JS) or ""
                break
            except Exception as e:
                msg = str(e)
                if attempt == 1:
                    print("  [!] alert during open -- dismissing and retrying:", base)
                    dismiss_modal()
                    time.sleep(1.0)
                    continue
                report.append(base + " : OPEN/MEASURE ERROR " + msg)
        try:
            if doc is not None:
                doc.Close(1852776480)
        except Exception:
            pass
        if not res:
            continue

        sects = str(res).split("\u0002")
        page_rows = [r for r in (sects[0] if len(sects) > 0 else "").split("\n") if r.strip()]
        img_rows = [r for r in (sects[1] if len(sects) > 1 else "").split("\n") if r.strip()]

        gap_by_off = {}
        folio_by_off = {}
        parsed_pages = []
        for r in page_rows:
            c = r.split("\t")
            if len(c) < 5:
                continue
            try:
                off = int(c[0])
            except Exception:
                continue
            folio, gap, kind, chapend = c[1], c[2], c[3], c[4]
            parsed_pages.append((off, folio, gap, kind, chapend))
            gap_by_off[off] = gap
            folio_by_off[off] = folio

        report.append("#" * 80)
        report.append("BOOK: " + base)
        report.append("")
        report.append("[1] PER-PAGE BOTTOM GAP  (pages measured: %d)" % len(parsed_pages))
        report.append("%-10s %-10s %-8s %-12s" % ("Page", "Gap(pt)", "LastItem", "Note"))
        report.append("-" * 44)
        gaps = []
        for off, folio, gap, kind, chapend in parsed_pages:
            note = "chapter-end" if chapend == "1" else ""
            report.append("%-10s %-10s %-8s %-12s" % (folio, gap, kind, note))
            if chapend != "1":    # chapter-end gaps are intentional -> not counted
                try:
                    gaps.append(float(gap))
                except Exception:
                    pass
        if gaps:
            report.append("-" * 44)
            report.append("min=%.1f  max=%.1f  avg=%.1f  (chapter-end pages excluded)" %
                           (min(gaps), max(gaps), sum(gaps) / len(gaps)))
        report.append("")

        report.append("[2] IMAGES  (count: %d)" % len(img_rows))
        report.append("%-18s %-7s %-9s %-9s %-9s %-15s %-14s" %
                       ("Image", "Page", "PrevPage", "Width", "Height", "PrevPageGap(pt)", "Height-PrevGap"))
        report.append("-" * 86)
        for r in img_rows:
            c = r.split("\t")
            if len(c) < 5:
                continue
            try:
                off = int(c[0])
            except Exception:
                continue
            folio, iname, w, h = c[1], c[2], c[3], c[4]
            prev_off = off - 1
            prev_gap = gap_by_off.get(prev_off, "-")
            # Height - PrevPageGap: positive => image taller than the space left on
            # the previous page (so it had to move down); negative => it would have fit.
            try:
                hpg = "%.1f" % (float(h) - float(prev_gap))
            except Exception:
                hpg = "-"
            report.append("%-18s %-7s %-9s %-9s %-9s %-15s %-14s" %
                           (iname[:18], folio, folio_by_off.get(prev_off, "-"),
                            w, h, prev_gap, hpg))
        report.append("")

    try:
        watcher.stop()
    except Exception:
        pass

    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report))
    print("\nDone. Report:", LOG_PATH)


if __name__ == "__main__":
    main()

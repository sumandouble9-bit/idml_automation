# -*- coding: utf-8 -*-
# Fill the BOTTOM text gap on body pages.
#
# Where the gap between the last line of body text and the bottom margin is more
# than 1 mm, this vertically justifies that page's body text frame so the text
# fills down to ~1 mm from the bottom margin line.
#
# Scope / safety:
#   * TEXT pages only. Pages whose lowest content is a (large) image are left alone
#     -- image gaps are handled separately.
#   * CHAPTER-END pages are NOT filled: if the next page starts a new chapter, that
#     page's gap is intentional and is left as-is.
#   * Small inline decorations (< 150 pt in both dimensions) are treated as text.
#   * Non-destructive: reads final_output_files/idml_files and writes the fixed IDMLs
#     to final_output_files/text_gap_fixed (originals untouched).
#
# Run this AFTER measure_page_gaps.py.
#
# Usage: python fix_text_bottom_gap.py            (all books)
#        python fix_text_bottom_gap.py 9789361422768   (one book)
import os
import sys
import glob
import time
import threading
import win32com.client
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure_page_gaps as mpg   # reuse its JS_MEASURE to re-measure after the fix
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "image_inject"))
import resolve_overset as rovs    # shared overset resolver (adds tail frames/pages)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_cases"))
import text_gap_fill, caption_center, overset_resolve, image_refit
import chapter_image_split
import fix_justification
import sidebyside_images
import fix_paragraph_styles
import fix_table_center
import epub_tools                 # build each book's image->caption map
import epub_caption_apply         # re-centre captions as the FINAL step

EPUB_DIR_3B = os.environ.get("EPUB_DIR", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "epub_input_files")

JS = 1246973031
WF = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.environ.get("GAPFIX_INPUT", "").strip() or \
    os.path.join(WF, "final_output_files", "idml_files")
OUT_DIR = os.environ.get("GAPFIX_OUTPUT", "").strip() or INPUT_DIR   # same dir -> overwrite
_IMG_BASE = os.path.dirname(INPUT_DIR)                                # final_output_files/
LOG_PATH = os.path.join(_IMG_BASE, "_text_gap_fix_log.txt")
GAP_REPORT_PATH = os.path.join(_IMG_BASE, "page_gaps_report_AFTER_fix.txt")


def _append_gap_tables(report, base, res):
    """Parse measure_page_gaps JS output and append the per-book gap + image tables
    (same layout as the measurement report) to `report`."""
    sects = str(res).split("\u0002")
    page_rows = [r for r in (sects[0] if len(sects) > 0 else "").split("\n") if r.strip()]
    img_rows = [r for r in (sects[1] if len(sects) > 1 else "").split("\n") if r.strip()]
    gap_by_off, folio_by_off, parsed = {}, {}, []
    for r in page_rows:
        c = r.split("\t")
        if len(c) < 5:
            continue
        try:
            off = int(c[0])
        except Exception:
            continue
        parsed.append((off, c[1], c[2], c[3], c[4]))
        gap_by_off[off] = c[2]
        folio_by_off[off] = c[1]
    report.append("#" * 80)
    report.append("BOOK: " + base)
    report.append("")
    report.append("[1] PER-PAGE BOTTOM GAP  (pages measured: %d)" % len(parsed))
    report.append("%-10s %-10s %-8s %-12s" % ("Page", "Gap(pt)", "LastItem", "Note"))
    report.append("-" * 44)
    gaps = []
    for off, folio, gap, kind, chapend in parsed:
        note = "chapter-end" if chapend == "1" else ""
        report.append("%-10s %-10s %-8s %-12s" % (folio, gap, kind, note))
        if chapend != "1":
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
        prev_gap = gap_by_off.get(off - 1, "-")
        try:
            hpg = "%.1f" % (float(h) - float(prev_gap))
        except Exception:
            hpg = "-"
        report.append("%-18s %-7s %-9s %-9s %-9s %-15s %-14s" %
                       (iname[:18], folio, folio_by_off.get(off - 1, "-"), w, h, prev_gap, hpg))
    report.append("")

ONLY = sys.argv[1].strip() if len(sys.argv) > 1 else ""
if ONLY.lower().endswith(".idml"):
    ONLY = ONLY[:-5]


def _quiet(app):
    for cmd in ("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                "app.scriptPreferences.enableRedraw = false;"):
        try:
            app.DoScript(cmd, JS)
        except Exception:
            pass


def dismiss_modal():
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


# Reflow fill: relax widow/orphan + keep-lines-together on BODY paragraph styles
# so lines that were held back pull UP and fill each page at the ORIGINAL leading
# (no line/paragraph spacing is changed). Heading / front-matter styles are left
# untouched, so chapter page breaks remain and chapter-end pages stay short, and
# sub-headings still keep with their following text.
JS_FIX = r'''
var doc = app.activeDocument;
try { doc.recompose(); } catch (eR) {}

var NONBODY = ["chapter_name","sub-heading","heading","master_chapter","content_ch",
               "toc","verso","copyright","copy","author","auther","doublenine","title","caption"];
function isBody(nm){
    nm = (nm || "").toLowerCase();
    for (var i = 0; i < NONBODY.length; i++){ if (nm.indexOf(NONBODY[i]) >= 0) return false; }
    return true;
}

var relaxed = 0;
var styles = doc.allParagraphStyles;
for (var i = 0; i < styles.length; i++){
    try {
        var ps = styles[i];
        var nm = ps.name;
        if (nm === "[No Paragraph Style]") continue;
        if (!isBody(nm)) continue;
        // Enforce widow/orphan control: lines flow to fill pages, but never leave 1-line orphan/widow
        try { ps.keepLinesTogether = true; } catch (e1) {}
        try { ps.keepAllLinesTogether = false; } catch (e2) {}
        try { ps.keepFirstAndLastLines = true; } catch (e3) {}
        try { ps.minLinesAtStart = 2; } catch (e4) {}
        try { ps.minLinesAtEnd = 2; } catch (e5) {}
        relaxed++;
    } catch (eP) {}
}
try { doc.recompose(); } catch (eR2) {}
"BODY_STYLES_RELAXED=" + relaxed;
'''


JS_REFIT_OFFFRAME = """
var doc = app.activeDocument;
var fixed = 0;
var G = doc.allGraphics;
for (var i = 0; i < G.length; i++){
    try {
        var g = G[i];
        if (!g.itemLink) continue;
        var fr = g.parent;
        var fb = fr.geometricBounds;   // [y1,x1,y2,x2]
        var gb = g.geometricBounds;
        var noX = (gb[3] <= fb[1] + 1) || (gb[1] >= fb[3] - 1);
        var noY = (gb[2] <= fb[0] + 1) || (gb[0] >= fb[2] - 1);
        if (noX || noY){
            try { fr.fit(FitOptions.FIT_CONTENT_PROPORTIONALLY); } catch(e1){}
            try { fr.fit(FitOptions.CENTER_CONTENT); } catch(e2){}
            fixed++;
        }
    } catch(eG){}
}
fixed.toString();
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*_injected.idml")))
    if ONLY:
        files = [f for f in files if os.path.basename(f).startswith(ONLY)]
    if not files:
        print("No matching *_injected.idml in", INPUT_DIR)
        return

    app = None
    for attempt in range(4):
        try:
            app = win32com.client.Dispatch("InDesign.Application")
            break
        except Exception:
            time.sleep(2)
            if attempt in (1, 2):
                import subprocess
                subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
                time.sleep(3)
    if app is None:
        print("Error: Could not connect to Adobe InDesign.")
        return
    _quiet(app)
    watcher = _ModalWatcher()
    watcher.start()

    log = ["=== Text Bottom-Gap Fill Log ===",
           "Date: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "Reflow fill: body widow/orphan + keep-lines-together relaxed so lines pull",
           "up and fill pages at the original leading. Chapter breaks/headings untouched.",
           ""]
    gap_report = ["=== Page-Gap Report AFTER text fill (pages after TOC) ===",
                  "Date: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "Measured on the FILLED IDMLs. Gap(pt) = bottom margin to lowest body content.",
                  ""]

    for f in files:
        base = os.path.basename(f)
        print("Fixing:", base)
        doc = None
        res = ""
        res_meas = ""
        for attempt in (1, 2):
            try:
                _quiet(app)
                if attempt == 1:
                    doc = app.Open(f)
                else:
                    dismiss_modal(); time.sleep(1.0)
                    doc = app.activeDocument
                res = text_gap_fill.run(app)          # reflow fill (test_cases module)
                try:
                    _cis = chapter_image_split.run(app)   # split image out of chapter heading
                    res = res + " | " + str(_cis)
                    log.append("%-40s %s" % (base, _cis))
                except Exception as _ecis:
                    log.append(base + " : CHAPTER IMG SPLIT ERROR " + str(_ecis))
                try:
                    _isbn2 = base[:-len("_injected.idml")] if base.endswith("_injected.idml") else os.path.splitext(base)[0]
                    _epub2 = os.path.join(EPUB_DIR_3B, _isbn2 + ".epub")
                    if os.path.exists(_epub2):
                        _sbs = sidebyside_images.run(app, _epub2)
                        res = res + " | " + str(_sbs)
                        log.append("%-40s %s" % (base, _sbs))
                except Exception as _esbs:
                    log.append(base + " : SIDEBYSIDE ERROR " + str(_esbs))
                # FINAL caption pass: Step 3b is the last layout step, so re-centre
                # every EPUB caption here (split fused / de-dup / force centre). This
                # is what the working reference build does -- apply caption logic LAST
                # so nothing downstream can revert it to body text.
                try:
                    _isbn = base[:-len("_injected.idml")] if base.endswith("_injected.idml") else os.path.splitext(base)[0]
                    _epub = None
                    for d in [
                        EPUB_DIR_3B,
                        os.path.join(WF, "..", "epub_input_files"),
                        os.path.join(WF, "..", "epub_input_files_Spanish"),
                        os.path.join(WF, "epub_input_files"),
                    ]:
                        if d and os.path.isdir(d):
                            cand_ep = os.path.join(d, _isbn + ".epub")
                            if os.path.exists(cand_ep):
                                _epub = cand_ep
                                break
                            for f in os.listdir(d):
                                if f.lower().endswith(".epub") and _isbn.lower() in f.lower():
                                    _epub = os.path.join(d, f)
                                    break
                        if _epub:
                            break

                    if _epub and os.path.exists(_epub):
                        _cmap = epub_tools.build_caption_map(_epub)
                        _nc = caption_center.run(app, _cmap)
                        res = res + " | CAPTIONS_CENTERED=" + str(_nc)
                        log.append("%-40s captions re-centered: %s" % (base, _nc))
                        try:
                            _ps = fix_paragraph_styles.run(app, _epub)
                            res = res + " | " + str(_ps)
                            log.append("%-40s paragraph styles: %s" % (base, _ps))
                        except Exception as _eps:
                            log.append(base + " : PARAGRAPH STYLE FIX ERROR " + str(_eps))
                    else:
                        log.append(base + " : no EPUB for caption re-center (" + _isbn + ")")
                except Exception as _ecap:
                    log.append(base + " : CAPTION RE-CENTER ERROR " + str(_ecap))
                try:
                    _tc = fix_table_center.run(app)
                    res = res + " | " + str(_tc)
                    log.append("%-40s table center/split: %s" % (base, _tc))
                except Exception as _etc:
                    log.append(base + " : TABLE CENTER ERROR " + str(_etc))
                # Final layout step: resolve any overset ONCE here with the shared
                # routine, so relaxing the body styles can never leave a story
                # overflowing when it reaches the audit.
                try:
                    _pg, _ov, _jam = overset_resolve.run(app)
                    res = res + " | OVERSET_RESOLVED pages=%d left=%d jams=%d" % (_pg, _ov, len(_jam))
                    log.append("%-40s overset: added %d page(s), left %d, jams %d" % (base, _pg, _ov, len(_jam)))
                except Exception as _eov:
                    log.append(base + " : OVERSET RESOLVE ERROR " + str(_eov))
                # SAFETY: re-fit any image whose content has drifted OUTSIDE its
                # frame (renders blank), e.g. a tall figure pushed off-frame on X.
                # Only touches images with no frame/content overlap; others untouched.
                try:
                    _refit = image_refit.run(app)
                    res = res + " | OFFFRAME_REFIT=" + str(_refit)
                    log.append("%-40s off-frame images re-fitted: %s" % (base, _refit))
                except Exception as _erf:
                    log.append(base + " : OFFFRAME REFIT ERROR " + str(_erf))
                try:
                    _just = fix_justification.run(app)
                    res = res + " | " + str(_just)
                    log.append("%-40s %s" % (base, _just))
                except Exception as _ej:
                    log.append(base + " : JUSTIFY ERROR " + str(_ej))
                res_meas = app.DoScript(mpg.JS_MEASURE, JS) or ""   # re-measure the filled layout
                break
            except Exception as e:
                if attempt == 1:
                    print("  [!] alert during open -- dismissing and retrying:", base)
                    dismiss_modal(); time.sleep(1.0)
                    continue
                log.append(base + " : ERROR " + str(e))
        if not res:
            try:
                if doc is not None:
                    doc.Close(1852776480)
            except Exception:
                pass
            continue

        # Save back to the SAME file. Export to a temp first, close, then replace the
        # original -- so we never write to the IDML while it is still open.
        final_path = os.path.join(OUT_DIR, base)
        tmp_path = final_path + ".tmp.idml"
        saved = False
        try:
            app.DoScript(
                'app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, new File("%s"), false);'
                % tmp_path.replace(chr(92), "/"), JS)
            saved = True
        except Exception as e:
            log.append(base + " : SAVE ERROR " + str(e))
        try:
            doc.Close(1852776480)
        except Exception:
            pass
        if saved:
            try:
                os.replace(tmp_path, final_path)   # overwrite the previous output file
            except Exception as e:
                log.append(base + " : REPLACE ERROR " + str(e))
        log.append("%-40s %s" % (base, res))
        print("   ", res)
        if res_meas:
            _append_gap_tables(gap_report, base, res_meas)

    try:
        watcher.stop()
    except Exception:
        pass

    with open(LOG_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(log))
    with open(GAP_REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(gap_report))
    print("\nDone. Fixed IDMLs ->", OUT_DIR)
    print("Fix log         :", LOG_PATH)
    print("Gap report AFTER:", GAP_REPORT_PATH)


if __name__ == "__main__":
    main()

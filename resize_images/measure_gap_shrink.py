"""Analyse the previous-page bottom gap caused by each pushed image and the shrink % needed to fill it.

Read-only: opens an IDML, composes it, and for every image that was pushed to the TOP of its page
(so the page before it ends with an empty gap), reports the previous-page gap and how much the image
would have to shrink -- in percent -- for the image AND its caption to flow back up and fill that gap.
Nothing is changed or saved.

For each such image it prints:
  PrevGap  = empty pt on the previous page (last body baseline down to the bottom margin).
  CapH     = estimated caption height (pt), since the caption must travel with the image.
  NeedH    = image height that would exactly fill the gap = PrevGap - CapH - padding.
  CurH     = the image's current height.
  Shrink%  = (CurH - NeedH) / CurH * 100  -- how much smaller the image must get.
  Possible = YES only when NeedH stays at or above the 40%-of-frame floor; otherwise NO
             (filling the gap would shrink the image below the floor, so it is left where it is).

Input : a book id (resize_images\\output\\<book>\\<book>.idml, else final_output_files\\idml_files\\<book>.idml)
        or a full .idml path.  Default = every resized book under resize_images\\output.
Output: resize_images\\output\\<book>\\<book>_gap_shrink.txt  (one aligned table).

Usage: python measure_gap_shrink.py [book_id | idml_path]
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
OUTPUT_DIR = os.path.join(HERE, "output")

# Geometry / rules (points). Body frame is 324 x 522 on a 396 x 612 page.
FRAME_HEIGHT_PT = 522.0
FLOOR_PCT = 0.40                 # never require an image below 40% of the frame height
PAD_PT = 6.0                     # breathing space kept between the gap edges and the image+caption
PUSH_TOL = 24.0                  # an image within this of the top margin counts as "pushed to the top"


def _analyse_js():
    """ExtendScript: for each pushed image report prev-page gap, caption height, current height, need%."""
    return r"""
    var doc = app.activeDocument;
    doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
    var pageH = doc.documentPreferences.pageHeight;
    var pageW = doc.documentPreferences.pageWidth;
    var PAD = %PAD%, PUSH = %PUSH%;

    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    function baseName(p){ if(!p) return ""; var s=String(p).replace(/\\/g,"/"); s=s.substring(s.lastIndexOf("/")+1); var d=s.lastIndexOf("."); return (d>0?s.substring(0,d):s); }

    var mainStory = null, maxLen = -1;
    for (var s=0; s<doc.stories.length; s++){
        try { if (doc.stories[s].characters.length > maxLen){ maxLen = doc.stories[s].characters.length; mainStory = doc.stories[s]; } } catch(eS){}
    }
    function bodyFrameOn(page){
        try { var tfs=page.textFrames, best=null, bestLen=-1;
            for (var i=0;i<tfs.length;i++){ try{ if (mainStory && tfs[i].parentStory.id===mainStory.id){ var L=tfs[i].characters.length; if(L>bestLen){bestLen=L;best=tfs[i];} } }catch(eF){} }
            return best; } catch(e){ return null; }
    }
    function frameBox(page){ var mp=page.marginPreferences; return { w:(pageW-mp.left-mp.right), h:((pageH-mp.bottom)-mp.top), top:mp.top, bot:(pageH-mp.bottom) }; }
    function gapOn(page){ var box=frameBox(page); var tf=bodyFrameOn(page); var lb=box.top; if(tf){ try{ if(tf.lines.length>0) lb=tf.lines[-1].baseline; }catch(eL){} } return box.bot-lb; }

    // caption = the paragraph right after the image's own paragraph, if its style name says caption/fig.
    function captionParaOf(fr){
        try { var anchor=fr.parent; var imgPara=anchor.paragraphs[0]; var story=imgPara.parentStory;
            var lastIdx=imgPara.insertionPoints[-1].index;
            if(lastIdx>=story.characters.length) return null;
            var capPara=story.insertionPoints[lastIdx].paragraphs[0];
            var sn=""; try{ sn=capPara.appliedParagraphStyle.name.toLowerCase(); }catch(e){}
            if(sn.indexOf("caption")>=0||sn.indexOf("fig")>=0) return capPara;
            return null;
        } catch(e){ return null; }
    }
    function captionHeight(capPara){ if(!capPara) return 0; var n=0; try{ n=capPara.lines.length; }catch(e){} if(n<=0) return 0; var ps=9; try{ ps=capPara.pointSize; if(!(ps>0)) ps=9; }catch(e){ ps=9; } return n*(ps*1.2)+4; }

    doc.recompose();
    var gs = doc.allGraphics, rows = [];
    for (var g=0; g<gs.length; g++){
        try {
            var gr=gs[g]; if (gr.itemLink && isLogo(gr.itemLink.name)) continue;
            var fr=gr.parent;
            var inCell=false; try{ inCell=(fr.parent && fr.parent.constructor.name==="Cell"); }catch(eC){}
            if(inCell) continue;
            var page=null; try{ page=fr.parentPage; }catch(eP){}
            if(page===null) continue;

            var ib=fr.geometricBounds; var imgH=ib[2]-ib[0];
            var box=frameBox(page);
            var pushed=(ib[0]-box.top)<=PUSH;
            if(!(pushed && page.documentOffset>=1)) continue;    // only images that leave a gap on the page before

            var prevPg=page.documentOffset;                      // 1-based previous page number
            var prevGap=gapOn(doc.pages[page.documentOffset-1]);
            var capH=captionHeight(captionParaOf(fr));
            var needH=prevGap-capH-PAD;                           // image height that would exactly fill the gap

            rows.push({ pg: page.documentOffset+1, s:
                baseName(gr.itemLink?gr.itemLink.name:"") + "|" + (page.documentOffset+1) + "|" + prevPg + "|" +
                prevGap.toFixed(1) + "|" + capH.toFixed(1) + "|" + imgH.toFixed(1) + "|" + needH.toFixed(1) + "|" + box.h.toFixed(1)
            });
        } catch(eG){}
    }
    rows.sort(function(a,b){ return a.pg-b.pg; });
    var out=[]; for (var r=0;r<rows.length;r++) out.push(rows[r].s);
    out.join("\n");
    """.replace("%PAD%", "%.1f" % PAD_PT).replace("%PUSH%", "%.1f" % PUSH_TOL)


def _write_report(log_text, out_path, idml_name):
    """Turn the measured rows into one aligned table, computing Shrink% and feasibility per image."""
    header = ("#", "Image No.", "Page", "PrevPg", "PrevGap", "CapH", "CurH", "GapDiff", "GapDiff%", "NeedH", "Shrink%", "FloorH", "Possible")
    widths = [3, 10, 5, 6, 8, 6, 7, 8, 9, 7, 8, 7, 9]
    total_w = sum(widths) + 3 * (len(widths) - 1)
    floor_h = FRAME_HEIGHT_PT * FLOOR_PCT
    lines = [
        f"Previous-page gap / image-shrink analysis for: {idml_name}",
        "One row per image that was pushed to the top of its page (so the page before ends in a gap).",
        "PrevPg/PrevGap = the previous page and its empty pt (last body line down to the bottom margin).",
        "CapH  = estimated caption height; the caption must move up with the image.",
        "CurH  = current image height.   NeedH = PrevGap - CapH - padding (height that fills the gap).",
        "GapDiff = PrevGap - CurH -- previous-page gap minus the image height (negative = image taller than gap).",
        "GapDiff% = GapDiff / CurH * 100 -- that difference as a share of the image height.",
        "Shrink% = (CurH - NeedH) / CurH * 100 -- how much the image must shrink to fill the gap.",
        f"FloorH  = 40%% of the frame height ({floor_h:.0f}pt). Possible = YES only when NeedH >= FloorH.",
        "-" * total_w,
        " | ".join(h.ljust(w) for h, w in zip(header, widths)),
        "-" * total_w,
    ]
    count = possible_n = 0
    for row in log_text.split("\n"):
        row = row.strip()
        if not row:
            continue
        parts = row.split("|")
        if len(parts) != 8:
            continue
        name, page, prev_pg, prev_gap, cap_h, cur_h, need_h, _frame_h = parts
        try:
            gap, capH, curH, needH = float(prev_gap), float(cap_h), float(cur_h), float(need_h)
        except ValueError:
            continue
        shrink = (curH - needH) / curH * 100 if curH > 0 else 0.0
        possible = needH >= floor_h and needH < curH          # worth shrinking and stays above the floor
        if possible:
            possible_n += 1
        count += 1
        gap_diff = gap - curH
        gap_diff_pct = gap_diff / curH * 100 if curH > 0 else 0.0
        cells = (str(count), name, page, prev_pg, f"{gap:.1f}", f"{capH:.1f}", f"{curH:.1f}",
                 f"{gap_diff:.1f}", f"{gap_diff_pct:.1f}%", f"{needH:.1f}", f"{shrink:.1f}%", f"{floor_h:.0f}", "YES" if possible else "NO")
        lines.append(" | ".join(c.ljust(w) for c, w in zip(cells, widths)))
    lines.append("-" * total_w)
    lines.append(f"Pushed images: {count}   Fillable (NeedH >= floor): {possible_n}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return count, possible_n


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
    """Resolve one arg to an IDML: full path, else the resized output <book>.idml. No other fallback."""
    if os.path.isfile(a):
        return [a]
    out = os.path.join(OUTPUT_DIR, a, a + ".idml")
    if os.path.isfile(out):
        return [out]
    return []


def _targets(args):
    """Resolve input IDML(s): args, or every resized <book>.idml under resize_images/output."""
    if args:
        out = []
        for a in args:
            out += _resolve(a)
        return sorted(set(out))
    return sorted(glob.glob(os.path.join(OUTPUT_DIR, "*", "*.idml")))


def analyse_idml(app, idml_path):
    """Open one IDML read-only, analyse every pushed image's prev-page gap, write the log, close no-save."""
    base = os.path.basename(idml_path)
    book = os.path.splitext(base)[0].replace("_injected", "")
    book_dir = os.path.join(OUTPUT_DIR, book)
    os.makedirs(book_dir, exist_ok=True)
    out_report = os.path.join(book_dir, book + "_gap_shrink.txt")

    app.DoScript('var d = app.open(new File("%s"));' % idml_path.replace("\\", "/"), JS)
    log_text = app.DoScript(_analyse_js(), JS) or ""
    n, ok = _write_report(log_text, out_report, base)
    app.DoScript("app.activeDocument.close(SaveOptions.NO);", JS)
    print(f"{book}: {n} pushed image(s), {ok} fillable -> {out_report}", flush=True)


def main():
    """Analyse previous-page gaps and required shrink % for the requested book(s)."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    targets = _targets(sys.argv[1:])
    if not targets:
        print("No IDML found. Pass a book id or path, or run the resize first.")
        return
    app = _connect()
    if app is None:
        print("Error: could not connect to Adobe InDesign.")
        return
    for idml in targets:
        try:
            analyse_idml(app, idml)
        except Exception as e:
            print(f"ERROR on {os.path.basename(idml)}: {e}", flush=True)


if __name__ == "__main__":
    main()

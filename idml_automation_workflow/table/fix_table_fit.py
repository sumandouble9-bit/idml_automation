import os
import sys
import time
import subprocess
from datetime import datetime

import win32com.client

JS = 1246973031


def _is_rpc_error(exc: Exception) -> bool:
    # True if the exception is an InDesign COM hang/crash/modal condition worth restarting for.
    s = str(exc).lower()
    return (
        "remote procedure call" in s
        or "rpc server" in s
        or "-2147023170" in s
        or "-2147023174" in s
        or "call was rejected" in s
        or "modal dialog or alert is active" in s
        or "30486" in s
    )


def restart_indesign(wait_seconds: int = 6):
    # Force-kill InDesign, relaunch it, and return a fresh COM Application object.
    print("  [restart] Killing InDesign.exe ...", flush=True)
    for proc in ("InDesign.exe", "Adobe Crash Processor.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True)
        except Exception:
            pass
    time.sleep(wait_seconds)
    print("  [restart] Relaunching InDesign via COM ...", flush=True)
    for _ in range(6):
        try:
            app = win32com.client.Dispatch("InDesign.Application")
            try:
                app.DoScript(
                    "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                    JS,
                )
            except Exception:
                pass
            print("  [restart] InDesign is back.", flush=True)
            return app
        except Exception:
            time.sleep(5)
    raise RuntimeError("Could not restart InDesign after multiple attempts")


def _break_poem_tables(app):
    # Split poem/verse tables so they can break across pages instead of overflowing.
    js = r'''
    var doc = app.activeDocument;
    var pageH = doc.documentPreferences.pageHeight;

    function textAreaH(tb){
        var th = pageH - 90;   // fallback (~default top+bottom)
        try {
            var pg = tb.storyOffset.parentTextFrames[0].parentPage;
            var mp = pg.marginPreferences;
            th = pageH - mp.top - mp.bottom;
        } catch (e) {}
        return th;
    }

    // Collect qualifying tables first (converting changes the story as we go).
    var victims = [];
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                if (tb.rows.length !== 1 || tb.columns.length !== 1) continue;
                var hasImg = false;
                try { hasImg = (tb.cells[0].allGraphics.length > 0); } catch (eG) {}
                if (hasImg) continue;
                // Convert a single-cell table to flowing text when it is taller than
                // the text area OR its cell is overset -- the text then flows onto the
                // next page (the split the user wants), losslessly.
                var oset = false; try { oset = tb.cells[0].overflows; } catch (eO) {}
                if (tb.rows[0].height > textAreaH(tb) + 1 || oset) victims.push(tb);
            } catch (eT) {}
        }
    }

    var converted = 0;
    for (var v = 0; v < victims.length; v++){
        try { victims[v].convertToText("\t", "\r"); converted++; }
        catch (eC) {
            try { victims[v].convertToText(); converted++; } catch (eC2) {}
        }
    }
    "POEM_TABLES_BROKEN=" + converted;
    '''
    return app.DoScript(js, JS)

def _fix_tables_and_breakable(app):
    # Resize table columns/insets to fit the text and mark rows breakable across pages.
    js = r'''
    var doc = app.activeDocument;
    var oldRuler = doc.viewPreferences.rulerOrigin;
    doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN;
    var facing = doc.documentPreferences.facingPages;
    var COL_FLOOR = 12;   // never shrink a column below this (pt)

    function marginWidth(pg){
        var pb = pg.bounds, mp = pg.marginPreferences, l, r;
        if (facing && pg.side == PageSideOptions.LEFT_HAND){ l = pb[1]+mp.right; r = pb[3]-mp.left; }
        else { l = pb[1]+mp.left; r = pb[3]-mp.right; }
        return r - l;
    }
    function usableWidthFor(tb){
        var w = 0;
        try {
            var tf = tb.storyOffset.parentTextFrames[0];
            var gb = tf.geometricBounds;
            var cols = 1, gut = 0;
            try { cols = tf.textFramePreferences.textColumnCount; } catch (e1) {}
            try { gut  = tf.textFramePreferences.textColumnGutter; } catch (e2) {}
            w = ((gb[3]-gb[1]) - (cols-1)*gut) / cols;
        } catch (eT) {}
        if (!w || w <= 0){ try { w = marginWidth(tb.storyOffset.parentTextFrames[0].parentPage); } catch (eP) {} }
        if (!w || w <= 0) w = 324;
        return w;
    }
    function tblWidth(tb){ var w = 0; for (var c=0;c<tb.columns.length;c++) w += tb.columns[c].width; return w; }
    function osCount(tb){ var n = 0; for (var c=0;c<tb.cells.length;c++){ if (tb.cells[c].overflows) n++; } return n; }
    // Columns that contain at least one overset cell. We iterate the column's
    // own cells (cell.parent.index is NOT reliably the column index in this DOM,
    // so we must ask each column for its cells directly).
    function needyCols(tb){
        var a = [];
        for (var ci=0; ci<tb.columns.length; ci++){
            var bad = false;
            try {
                var cells = tb.columns[ci].cells;
                for (var k=0;k<cells.length;k++){ if (cells[k].overflows){ bad = true; break; } }
            } catch (e) {}
            if (bad) a.push(ci);
        }
        return a;
    }
    function isNeedy(need, idx){ for (var i=0;i<need.length;i++) if (need[i]===idx) return true; return false; }
    function widestDonor(tb, need){
        var best = -1, bestW = COL_FLOOR;
        for (var c=0;c<tb.columns.length;c++){
            if (isNeedy(need,c)) continue;
            var w = tb.columns[c].width;
            if (w > bestW){ bestW = w; best = c; }
        }
        return best;
    }
    function snapWidths(tb){ var a=[]; for (var c=0;c<tb.columns.length;c++) a.push(tb.columns[c].width); return a; }
    function restoreWidths(tb, a){ for (var c=0;c<tb.columns.length && c<a.length;c++){ try { tb.columns[c].width = a[c]; } catch(e){} } }
    // Remember the width layout with the fewest overset cells seen so far.
    function checkpoint(tb, best){ var n = osCount(tb); if (n < best.os){ best.os = n; best.w = snapWidths(tb); } return n; }

    var rowsBreak = 0, tablesTouched = 0, cellsFixedTotal = 0, tablesStillOverset = 0;

    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            tablesTouched++;

            // --- make body rows breakable so tables can split across pages ----
            try {
                var rows = tb.rows;
                for (var r = 0; r < rows.length; r++){
                    var row = rows[r];
                    try { row.autoGrow = true; } catch (eA) {}
                    var isBody = true;
                    try { isBody = (row.rowType == RowTypes.BODY_ROW); } catch (eRT) {}
                    if (isBody){ try { row.keepWithNextRow = false; rowsBreak++; } catch (eK) {} }
                }
            } catch (eRows) {}

            // --- red-dot fix (no font change) --------------------------------
            //  Strategy: shrink an over-wide table to the column, tighten insets,
            //  then feed width to the columns that hold overset cells (spare width
            //  first, then from the widest column that has room). Throughout, we
            //  remember the column layout that produced the FEWEST overset cells
            //  and restore that at the end — so the fix keeps every partial win and
            //  is never worse than where it started. Font size is never touched.
            var before = osCount(tb);
            if (before > 0){
                var usable = usableWidthFor(tb);
                var best = { os: before, w: snapWidths(tb) };

                // 1) if the table is wider than the column, take width off the
                //    widest columns (down to the floor) until it fits — this also
                //    stops the table crossing the side margin.
                var guardW = 0;
                while (tblWidth(tb) > usable + 0.5 && guardW < 400){
                    guardW++;
                    // Shrink only a column that has NO overset content, so the number
                    // columns (and any text column) are never starved to hide data.
                    // Prefer a non-needy column; fall back to the widest overall only
                    // if every column already holds overset content.
                    var needW = needyCols(tb);
                    var wc = -1, wcW = COL_FLOOR;
                    for (var c=0;c<tb.columns.length;c++){
                        if (isNeedy(needW, c)) continue;
                        if (tb.columns[c].width > wcW){ wcW = tb.columns[c].width; wc = c; }
                    }
                    if (wc < 0){   // all columns are needy -> shrink the widest overall
                        for (var c2=0;c2<tb.columns.length;c2++){ if (tb.columns[c2].width > wcW){ wcW = tb.columns[c2].width; wc = c2; } }
                    }
                    if (wc < 0) break;
                    var cut = Math.min(6, tb.columns[wc].width - COL_FLOOR);
                    if (cut <= 0.5) break;
                    try { tb.columns[wc].width -= cut; } catch (e) { break; }
                    st.recompose();
                }
                checkpoint(tb, best);

                // 2) tighten side insets to 2pt, then feed the needy columns.
                for (var c=0;c<tb.cells.length;c++){
                    try { if (tb.cells[c].leftInset  > 2) tb.cells[c].leftInset  = 2; } catch (e) {}
                    try { if (tb.cells[c].rightInset > 2) tb.cells[c].rightInset = 2; } catch (e) {}
                }
                st.recompose(); checkpoint(tb, best);

                for (var pass=0; pass<400; pass++){
                    var need = needyCols(tb); if (need.length === 0) break;
                    var slack = usable - tblWidth(tb);
                    var give;
                    if (slack > 0.5){
                        give = Math.min(6, slack);
                    } else {
                        var donor = widestDonor(tb, need);
                        if (donor < 0) break;                 // nothing left to give
                        var room = tb.columns[donor].width - COL_FLOOR;
                        if (room <= 0.5) break;
                        give = Math.min(4, room);
                        try { tb.columns[donor].width -= give; } catch (e) { break; }
                    }
                    var share = give / need.length;
                    for (var i=0;i<need.length;i++){ try { tb.columns[need[i]].width += share; } catch (e) {} }
                    st.recompose(); checkpoint(tb, best);
                }

                // 3) still tight? drop side insets to 0 and feed once more.
                if (osCount(tb) > 0){
                    for (var c3=0;c3<tb.cells.length;c3++){
                        try { if (tb.cells[c3].leftInset  > 0) tb.cells[c3].leftInset  = 0; } catch (e) {}
                        try { if (tb.cells[c3].rightInset > 0) tb.cells[c3].rightInset = 0; } catch (e) {}
                    }
                    st.recompose(); checkpoint(tb, best);
                    for (var pass2=0; pass2<400; pass2++){
                        var need2 = needyCols(tb); if (need2.length === 0) break;
                        var slack2 = usable - tblWidth(tb);
                        var give2;
                        if (slack2 > 0.5){ give2 = Math.min(6, slack2); }
                        else {
                            var d2 = widestDonor(tb, need2);
                            if (d2 < 0) break;
                            var room2 = tb.columns[d2].width - COL_FLOOR;
                            if (room2 <= 0.5) break;
                            give2 = Math.min(4, room2);
                            try { tb.columns[d2].width -= give2; } catch (e) { break; }
                        }
                        var sh2 = give2 / need2.length;
                        for (var j=0;j<need2.length;j++){ try { tb.columns[need2[j]].width += sh2; } catch (e) {} }
                        st.recompose(); checkpoint(tb, best);
                    }
                }

                // 4) settle on the best layout we saw (fewest overset cells).
                if (best.os < osCount(tb)){ restoreWidths(tb, best.w); st.recompose(); }
                var after = osCount(tb);
                cellsFixedTotal += (before - after);
                if (after > 0) tablesStillOverset++;
            }
        }
    }

    doc.viewPreferences.rulerOrigin = oldRuler;
    "ROWS_BREAKABLE=" + rowsBreak + "|TABLES=" + tablesTouched +
    "|CELLS_FIXED=" + cellsFixedTotal + "|TABLES_STILL_OVERSET=" + tablesStillOverset;
    '''
    return app.DoScript(js, JS)

def _fix_vertical(app):
    # Reflow tables vertically so a tall table splits across pages rather than growing the frame.
    js = r'''
    var doc = app.activeDocument;
    var oldRuler = doc.viewPreferences.rulerOrigin;
    doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
    var pageH = doc.documentPreferences.pageHeight;
    var pageW = doc.documentPreferences.pageWidth;
    var facing = doc.documentPreferences.facingPages;

    var CAP_PER_STORY = 40;   // if a story needs more pages than this, revert it
    var framesReset = 0, framesReverted = 0, pagesAdded = 0;

    function frameGeom(page) {
        var mp = page.marginPreferences;
        var top = mp.top, bottom = pageH - mp.bottom, left, right;
        if (facing && page.side == PageSideOptions.LEFT_HAND) { left = mp.right; right = pageW - mp.left; }
        else { left = mp.left; right = pageW - mp.right; }
        return [top, left, bottom, right];
    }
    function storyOverset(s){ var n=0; var cs=s.textContainers; for (var j=0;j<cs.length;j++){ if (cs[j].overflows) n++; } return n; }

    for (var si = 0; si < doc.stories.length; si++){
        var s = doc.stories[si];
        if (s.textContainers.length === 0) continue;

        // Overset in this story BEFORE we touch it. We will not let it end worse.
        var osBefore = storyOverset(s);

        // Collect this story's threaded body frames grown past their margin box
        // (how the injection forces an un-splittable block onto one page).
        var grown = [];   // {f, saved, box}
        var cont = s.textContainers;
        for (var c = 0; c < cont.length; c++){
            var fr = cont[c];
            if (fr.constructor.name !== "TextFrame") continue;
            var threaded = false;
            try { if (fr.previousTextFrame !== null) threaded = true; } catch (ep) {}
            try { if (fr.nextTextFrame     !== null) threaded = true; } catch (en) {}
            if (!threaded) continue;
            var pg = null; try { pg = fr.parentPage; } catch (e) {}
            if (!pg) continue;
            var box = frameGeom(pg), gb;
            try { gb = fr.geometricBounds; } catch (e) { continue; }
            if (gb[2] > box[2] + 2 || gb[3] > box[3] + 2 || gb[0] < box[0] - 2 || gb[1] < box[1] - 2){
                grown.push({ f: fr, saved: gb, box: box });
            }
        }

        // Reset grown frames to their margin box so their content re-breaks.
        for (var g = 0; g < grown.length; g++){
            try { grown[g].f.geometricBounds = grown[g].box; } catch (e) {}
        }
        if (grown.length > 0) s.recompose();

        // Nothing to place and nothing was grown -> leave this story alone.
        if (grown.length === 0 && !s.textContainers[s.textContainers.length - 1].overflows) continue;

        // Reflow: add full-margin pages until the story is placed, within a
        // budget. Record added pages so we can undo cleanly.
        var addedPages = [];
        var lastFrame = s.textContainers[s.textContainers.length - 1];
        var jam = false, guard = 0;
        while (lastFrame.constructor.name === "TextFrame" && lastFrame.overflows){
            guard++;
            if (guard > CAP_PER_STORY){ jam = true; break; }          // runaway / limp
            var np = doc.pages.add();
            var nf = np.textFrames.add();
            nf.geometricBounds = frameGeom(np);
            lastFrame.nextTextFrame = nf;
            addedPages.push(np);
            lastFrame = nf;
            s.recompose();
            if (nf.characters.length < 5 && nf.overflows){ jam = true; break; }  // un-splittable / limping unit
        }

        // Undo the story's changes if it jammed / ran away, OR if we somehow
        // ended with MORE overset than we started with (never hide text).
        var mustRevert = jam || (storyOverset(s) > osBefore);
        if (mustRevert){
            for (var a = addedPages.length - 1; a >= 0; a--){
                try {
                    var pg2 = addedPages[a];
                    for (var f = pg2.textFrames.length - 1; f >= 0; f--){ try { pg2.textFrames[f].remove(); } catch (e) {} }
                    pg2.remove();
                } catch (e) {}
            }
            for (var g2 = 0; g2 < grown.length; g2++){
                try { grown[g2].f.geometricBounds = grown[g2].saved; } catch (e) {}
            }
            s.recompose();
            framesReverted += grown.length;
        } else {
            framesReset += grown.length;
            pagesAdded += addedPages.length;
        }
    }

    // FINAL PASS — place any text still overset (e.g. the width fixes made a
    // story a little taller). Pure page-adding, no frame resets, with strict
    // limp detection and a hard total budget so it can NEVER run away: if a
    // fresh full-page frame cannot even take 5 characters, the next unit is
    // un-splittable, so we stop that story and leave it rather than balloon.
    var TOTAL_CAP = 60;
    var tailPages = 0;
    for (var ti = 0; ti < doc.stories.length; ti++){
        var s2 = doc.stories[ti];
        if (s2.textContainers.length === 0) continue;
        s2.recompose();
        var lf2 = s2.textContainers[s2.textContainers.length - 1];
        while (lf2.constructor.name === "TextFrame" && lf2.overflows && tailPages < TOTAL_CAP){
            var np2 = doc.pages.add();
            var nf2 = np2.textFrames.add();
            nf2.geometricBounds = frameGeom(np2);
            lf2.nextTextFrame = nf2;
            lf2 = nf2;
            tailPages++;
            s2.recompose();
            if (nf2.overflows && nf2.characters.length < 5) break;   // un-splittable -> stop this story
        }
    }
    pagesAdded += tailPages;

    doc.viewPreferences.rulerOrigin = oldRuler;

    var oversetLeft = 0;
    for (var q = 0; q < doc.stories.length; q++){
        var cs = doc.stories[q].textContainers;
        for (var j = 0; j < cs.length; j++){ if (cs[j].overflows) oversetLeft++; }
    }
    "FRAMES_RESET=" + framesReset + "|FRAMES_REVERTED=" + framesReverted +
    "|PAGES_ADDED=" + pagesAdded + "|TAIL_PAGES=" + tailPages + "|OVERSET_FRAMES=" + oversetLeft;
    '''
    return app.DoScript(js, JS)

def _align_autogrow_cells(app):
    # Left-align and auto-grow table cells so their text stays visible.
    js = r'''
    var doc = app.activeDocument;
    var J = Justification;
    function isJust(j){ return j==J.LEFT_JUSTIFIED || j==J.RIGHT_JUSTIFIED || j==J.CENTER_JUSTIFIED || j==J.FULLY_JUSTIFIED; }
    var touched = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                var hasImg = false;
                for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){
                    try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch (eH) {}
                }
                if (hasImg) continue;                      // leave image tables alone

                for (var c = 0; c < tb.cells.length; c++){
                    var cell = tb.cells[c];
                    try {
                        var ps = cell.paragraphs;
                        for (var p = 0; p < ps.length; p++){
                            var pp = ps[p];
                            // Hyphenate long cell words so they fit in a narrow column
                            // WITHOUT stealing width from the number columns (which
                            // would hide the data). Left-align so justified text does
                            // not spread words apart.
                            try { pp.hyphenation = true; } catch (e1) {}
                            try { pp.hyphenateCapitalizedWords = true; } catch (e2) {}
                            try { pp.hyphenateAfterFirst = 2; } catch (e3) {}
                            try { pp.hyphenateBeforeLast = 2; } catch (e4) {}
                            try { pp.minimumHyphenatedWordLength = 4; } catch (e5) {}
                            try { if (isJust(pp.justification)) pp.justification = J.LEFT_ALIGN; } catch (e6) {}
                        }
                    } catch (eC) {}
                }
                for (var r = 0; r < tb.rows.length; r++){ try { tb.rows[r].autoGrow = true; } catch (eR) {} }
                touched++;
            } catch (eT) {}
        }
    }
    "CELLS_ALIGNED=" + touched;
    '''
    return app.DoScript(js, JS)

def _hyphenate_overset_cells(app):
    # Enable hyphenation in overset cells so long words break and the text fits.
    js = r'''
    var doc = app.activeDocument;
    var fixed = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                for (var c = 0; c < tb.cells.length; c++){
                    var cell = tb.cells[c];
                    try {
                        if (!cell.overflows) continue;           // only cells still clipped
                        var ps = cell.paragraphs;
                        for (var p = 0; p < ps.length; p++){
                            var pp = ps[p];
                            try { pp.hyphenation = true; } catch (e1) {}
                            try { pp.hyphenateCapitalizedWords = true; } catch (e2) {}
                            try { pp.hyphenateAfterFirst = 2; } catch (e3) {}
                            try { pp.hyphenateBeforeLast = 2; } catch (e4) {}
                            try { pp.minimumHyphenatedWordLength = 4; } catch (e5) {}
                        }
                        st.recompose();
                        fixed++;
                    } catch (eC) {}
                }
            } catch (eT) {}
        }
    }
    "OVERSET_CELLS_HYPHENATED=" + fixed;
    '''
    return app.DoScript(js, JS)

def _center_narrow_tables(app):
    # Center narrow left-aligned tables within the text column.
    js = r'''
    var doc = app.activeDocument;
    var oldRuler = doc.viewPreferences.rulerOrigin;
    doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN;
    var facing = doc.documentPreferences.facingPages;
    var MIN_SPACE = 12;   // only centre when at least this much empty space remains

    // Gap above and below each table, matched to the body paragraph gap
    // (spaceBefore + spaceAfter) so a table is separated like two paragraphs.
    var TABLE_GAP = 4.5;
    try { var _bs = doc.paragraphStyles.itemByName("body_text"); if (_bs.isValid) TABLE_GAP = _bs.spaceBefore + _bs.spaceAfter; } catch (eGap) {}

    function marginWidth(pg){
        var pb = pg.bounds, mp = pg.marginPreferences, l, r;
        if (facing && pg.side == PageSideOptions.LEFT_HAND){ l = pb[1]+mp.right; r = pb[3]-mp.left; }
        else { l = pb[1]+mp.left; r = pb[3]-mp.right; }
        return r - l;
    }
    function usableWidthFor(tb){
        var w = 0;
        try {
            var tf = tb.storyOffset.parentTextFrames[0];
            var gb = tf.geometricBounds;
            var cols = 1, gut = 0;
            try { cols = tf.textFramePreferences.textColumnCount; } catch (e1) {}
            try { gut  = tf.textFramePreferences.textColumnGutter; } catch (e2) {}
            w = ((gb[3]-gb[1]) - (cols-1)*gut) / cols;
        } catch (eT) {}
        if (!w || w <= 0){ try { w = marginWidth(tb.storyOffset.parentTextFrames[0].parentPage); } catch (eP) {} }
        if (!w || w <= 0) w = 324;
        return w;
    }
    function tblWidth(tb){ var w = 0; for (var c=0;c<tb.columns.length;c++) w += tb.columns[c].width; return w; }

    var centered = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                // skip image tables (positioned by the image layout pass)
                var hasImg = false;
                for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){
                    try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch (eH) {}
                }
                if (hasImg) continue;

                var usable = usableWidthFor(tb);
                // Never allow more usable width than the page MARGIN box. The frame
                // may have been grown wider than the margin by the reflow jam-escape;
                // centring against that would push the table past the margin. Capping
                // to the margin keeps every table inside the text area (all files).
                try {
                    var _pg = tb.storyOffset.parentTextFrames[0].parentPage;
                    var _mw = marginWidth(_pg);
                    if (_mw > 0 && usable > _mw) usable = _mw;
                } catch (eMW) {}
                var tw = tblWidth(tb);
                var leftover = usable - tw;

                // Always normalise the table paragraph's indents. A table anchored in
                // a styled paragraph (e.g. quotes_normal) inherits that paragraph's
                // left indent, which shifts the whole table right and pushes a
                // full-width table past the margin. Clear it, then centre only if the
                // table is genuinely narrower than the column.
                try { tb.spaceBefore = TABLE_GAP; } catch (eSB) {}
                try { tb.spaceAfter  = TABLE_GAP; } catch (eSA) {}
                var para = tb.storyOffset.paragraphs[0];
                try { para.firstLineIndent = 0; } catch (eF) {}
                // If body text shares the table's paragraph (a merged last-cell value
                // plus following narrative), a centring left indent would push that
                // text in too. Keep such paragraphs flush-left so the body stays at the
                // margin; only centre a paragraph that holds the table alone.
                var paraChars = 0; try { paraChars = para.characters.length; } catch (eCC) {}
                if (leftover < MIN_SPACE || paraChars > 20) {
                    try { para.leftIndent = 0; } catch (eI0) {}   // flush to margin
                    continue;
                }
                try { para.leftIndent  = leftover / 2; } catch (eI) {}
                centered++;
            } catch (eTbl) {}
        }
    }
    doc.viewPreferences.rulerOrigin = oldRuler;
    "TABLES_CENTERED=" + centered;
    '''
    return app.DoScript(js, JS)


def enforce_text_size(app, size=9.65):
    """Force NORMAL body text and TABLE text to a fixed point size (default 9.65),
    without touching headings. Sets the common body paragraph styles to `size` and
    every (non-image) table cell's text to `size`. Headings keep their own styles
    and sizes; table FIT is still handled by width/hyphenation, never by shrinking
    the font below this size. Returns the count of table cells set."""
    js = r'''
    var doc = app.activeDocument;
    var SZ = %SZ%;
    // NOTE: document-wide body paragraph font size/style (9.65 pt Palatino
    // Regular) is enforced in the FORMATTING step (typography_and_styles.py),
    // not here. This table pass only normalises TABLE cells to the same size
    // so cell text matches the body; headings/body prose are untouched here.
    // Table cells -> SZ (skip image tables).
    var n = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                var hasImg = false;
                for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){
                    try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch (eH) {}
                }
                if (hasImg) continue;
                for (var c = 0; c < tb.cells.length; c++){
                    try {
                        var cps = tb.cells[c].paragraphs;
                        for (var p = 0; p < cps.length; p++){ try { cps[p].pointSize = SZ; } catch (eP) {} }
                        n++;
                    } catch (eC) {}
                }
            } catch (eT) {}
        }
    }
    "SIZE_ENFORCED_CELLS=" + n;
    '''.replace("%SZ%", str(size))
    return app.DoScript(js, JS)


def _collapse_empty_rows(app, const_h=4.0):
    """Remove genuinely-empty table rows (spacer rows whose every cell has no text
    and no image), from last to first so indices stay valid. A row that has text in
    ANY cell is never touched and no cell content is ever cleared - so a header row
    like ['', 'Miles.'] keeps its text instead of being blanked."""
    js = r"""
    var doc = app.activeDocument;
    var n = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            if (tb.rows.length === 1 && tb.columns.length === 1) continue;
            for (var r = tb.rows.length - 1; r >= 0; r--){
                try {
                    var row = tb.rows[r];
                    var cells = row.cells;
                    // Simple rule: a row is empty ONLY when EVERY cell has no graphic
                    // and no non-whitespace text. If any single cell has content (e.g.
                    // the 'Miles.' header cell in a ['', 'Miles.'] row), the whole row
                    // is kept. Read text via texts[0].contents (robust; contents can be
                    // an array) and count NBSP as whitespace.
                    var empty = true;
                    for (var c = 0; c < cells.length; c++){
                        var cc = cells[c];
                        try { if (cc.allGraphics.length > 0){ empty = false; break; } } catch (eG0) {}
                        var raw = "";
                        try { raw = cc.texts[0].contents; } catch (eT0) {
                            try { raw = cc.contents; } catch (eT1) { raw = ""; }
                        }
                        if (raw && raw.constructor === Array) raw = raw.join("");
                        if (String(raw).replace(/[\s\u00a0\u2028\r\n]/g, "").length > 0){ empty = false; break; }
                    }
                    if (empty && tb.rows.length > 1){ row.remove(); n++; }
                } catch (eR) {}
            }
        }
    }
    "EMPTY_ROWS_REMOVED=" + n;
    """
    return app.DoScript(js, JS)


def _remove_all_table_borders(app):
    """Disable ALL table borders: set every cell's four edge stroke weights to 0
    across every table in the document. Requested so table rules do not print."""
    js = r"""
    var doc = app.activeDocument;
    var n = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            for (var c = 0; c < tb.cells.length; c++){
                try {
                    var cell = tb.cells[c];
                    cell.topEdgeStrokeWeight = 0;
                    cell.bottomEdgeStrokeWeight = 0;
                    cell.leftEdgeStrokeWeight = 0;
                    cell.rightEdgeStrokeWeight = 0;
                    n++;
                } catch (eC) {}
            }
        }
    }
    "TABLE_BORDERS_REMOVED=" + n;
    """
    return app.DoScript(js, JS)


def _left_align_table_cells(app):
    """Left-align every TEXT cell in every table so content starts at the cell's
    left edge (not centred). Image cells are skipped -- their figures are centred
    separately via anchorXoffset. Returns count of cells left-aligned."""
    js = r"""
    var doc = app.activeDocument;
    var n = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            for (var c = 0; c < tb.cells.length; c++){
                try {
                    var cell = tb.cells[c];
                    if (cell.allGraphics.length > 0) continue;   // leave image cells
                    var paras = cell.paragraphs;
                    for (var p = 0; p < paras.length; p++){
                        try { paras[p].justification = Justification.LEFT_ALIGN; } catch (eP) {}
                        // Remove the body first-line / left indent inside cells so text
                        // starts flush at the cell's left edge (not pushed right, which
                        // looks like centering).
                        try { paras[p].firstLineIndent = 0; } catch (eFi) {}
                        try { paras[p].leftIndent = 0; } catch (eLi) {}
                    }
                    n++;
                } catch (eC) {}
            }
        }
    }
    "CELLS_LEFT_ALIGNED=" + n;
    """
    return app.DoScript(js, JS)


def _split_multiline_list_cells(app):
    """Make single-column list/poem tables splittable across pages.

    Some sources cram a whole list or poem into ONE table cell, with the lines
    separated by soft returns -- producing a single very tall row that cannot
    break and overflows the page. InDesign only splits a table BETWEEN rows, so
    this expands such a 1-column table into one row per line (lossless). The
    result is an ordinary multi-row table that flows onto the next page when it
    reaches the bottom margin and reflows automatically when text above changes.
    Only single-column, text-only tables are touched. Returns count rebuilt."""
    js = r"""
    var doc = app.activeDocument;
    var rebuilt = 0;
    var SR = String.fromCharCode(8232);      // \u2028 soft return
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                if (tb.columns.length !== 1) continue;        // single-column only
                // no images anywhere in the table
                var hasImg = false;
                for (var g = 0; g < tb.cells.length && !hasImg; g++){
                    try { if (tb.cells[g].allGraphics.length > 0) hasImg = true; } catch (eG) {}
                }
                if (hasImg) continue;
                // Collect every line across the existing rows.
                var lines = [];
                for (var r = 0; r < tb.rows.length; r++){
                    var raw = String(tb.rows[r].cells[0].contents);
                    var parts = raw.split(/[\r\n\u2028]/);
                    for (var p = 0; p < parts.length; p++){
                        var ln = parts[p];
                        if (ln.replace(/\s/g, "").length > 0) lines.push(ln);
                    }
                }
                // Only act when lines were packed into fewer rows (internal breaks).
                if (lines.length <= tb.rows.length) continue;
                if (lines.length < 2) continue;
                // Rebuild: shrink to one row, then add one row per line.
                while (tb.rows.length > 1){
                    try { tb.rows[tb.rows.length - 1].remove(); } catch (eR) {}
                }
                tb.rows[0].cells[0].contents = lines[0];
                for (var k = 1; k < lines.length; k++){
                    tb.rows.add(LocationOptions.AT_END);
                    tb.rows[tb.rows.length - 1].cells[0].contents = lines[k];
                }
                // Let every row keep its own height and break across pages.
                for (var r2 = 0; r2 < tb.rows.length; r2++){
                    try { tb.rows[r2].autoGrow = true; } catch (eAg) {}
                    try { tb.rows[r2].keepWithNextRow = false; } catch (eKw) {}
                }
                rebuilt++;
            } catch (eT) {}
        }
    }
    "LIST_TABLES_SPLIT=" + rebuilt;
    """
    return app.DoScript(js, JS)


def _compact_cell_content(app):
    """Make data-table rows compact and tidy, without losing text.

    Many source cells carry extra blank paragraphs (leading/trailing empty
    lines) that inflate the row height, leaving big vertical gaps and overset
    'red dot' markers even though the real text is short. For every text cell
    this trims leading/trailing blank lines only (never internal content),
    top-aligns the cell so text starts at the top-left, and lets each row grow
    just to its content. Returns count of cells trimmed."""
    js = r"""
    var doc = app.activeDocument;
    var n = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            for (var c = 0; c < tb.cells.length; c++){
                try {
                    var cell = tb.cells[c];
                    if (cell.allGraphics.length > 0) continue;
                    try { cell.verticalJustification = VerticalJustification.TOP_ALIGN; } catch (eV) {}
                    var raw = String(cell.contents);
                    var trimmed = raw.replace(/^\s+/, "").replace(/\s+$/, "");
                    if (trimmed !== raw){ cell.contents = trimmed; n++; }
                } catch (eC) {}
            }
            for (var r = 0; r < tb.rows.length; r++){
                try {
                    tb.rows[r].autoGrow = true;
                    if (tb.rows[r].minimumHeight > 6) tb.rows[r].minimumHeight = 6;
                } catch (eR) {}
            }
        }
    }
    "CELLS_COMPACTED=" + n;
    """
    return app.DoScript(js, JS)


def _flow_overset_tail(app):
    """Dedicated handler for poem / single-cell table text.

    Converting a crammed single-cell list or poem into flowing text (so it can
    split across pages) EXPANDS it, which can push following text past the last
    frame of the story and overset / truncate it. The main injection reflow runs
    BEFORE the table fix, so it never sees this expansion. This pass adds threaded
    pages to every story until its last frame no longer overflows, so no poem or
    list text is lost. Returns the number of pages added."""
    js = r"""
    var doc = app.activeDocument;
    var pageW = doc.documentPreferences.pageWidth;
    var pageH = doc.documentPreferences.pageHeight;
    var oldRuler = doc.viewPreferences.rulerOrigin;
    doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;

    function frameGeom(page) {
        var top = page.marginPreferences.top;
        var bottom = pageH - page.marginPreferences.bottom;
        var left, right;
        if (doc.documentPreferences.facingPages && page.side == PageSideOptions.LEFT_HAND) {
            left  = page.marginPreferences.right;
            right = pageW - page.marginPreferences.left;
        } else {
            left  = page.marginPreferences.left;
            right = pageW - page.marginPreferences.right;
        }
        return [top, left, bottom, right];
    }

    var pagesAdded = 0;
    for (var i = 0; i < doc.stories.length; i++) {
        var s = doc.stories[i];
        try { s.recompose(); } catch (eR) {}
        if (s.textContainers.length === 0) continue;
        var lastFrame = s.textContainers[s.textContainers.length - 1];
        if (lastFrame.constructor.name !== "TextFrame") continue;
        var guard = 0;
        while (lastFrame.overflows) {
            guard++;
            if (guard > 6000) break;                 // safety
            var newPage = doc.pages.add();
            var newFrame = newPage.textFrames.add();
            newFrame.geometricBounds = frameGeom(newPage);
            lastFrame.nextTextFrame = newFrame;
            lastFrame = newFrame;
            pagesAdded++;
            try { s.recompose(); } catch (eR2) {}
            // If a fresh full-size frame still accepts nothing, it is an
            // unbreakable unit (not our poem/list case) -- stop to avoid a loop.
            if (lastFrame.characters.length === 0 && lastFrame.overflows) break;
        }
    }
    doc.viewPreferences.rulerOrigin = oldRuler;
    "TAIL_PAGES_ADDED=" + pagesAdded;
    """
    return app.DoScript(js, JS)


def convert_single_cell_tables(app):
    """Convert every single-cell (1 row x 1 col, no image) table into flowing text.

    Meant to run BEFORE the main overset reflow. A long poem/list crammed into one
    table cell is a single unbreakable row: during reflow it cannot split, so it is
    forced onto one grown page and the text after it (and its own tail) is lost. As
    flowing text it breaks across pages normally, so the reflow paginates it and
    nothing is truncated. convertToText is lossless. Returns count converted."""
    js = r"""
    var doc = app.activeDocument;
    var victims = [];
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                if (tb.rows.length !== 1 || tb.columns.length !== 1) continue;
                var hasImg = false;
                try { hasImg = (tb.cells[0].allGraphics.length > 0); } catch (eG) {}
                if (hasImg) continue;
                victims.push(tb);
            } catch (eT) {}
        }
    }
    var n = 0;
    for (var v = 0; v < victims.length; v++){
        var txt = null;
        try { txt = victims[v].convertToText("\t", "\r"); n++; }
        catch (eC) { try { txt = victims[v].convertToText(); n++; } catch (eC2) {} }
        // Ensure a trailing paragraph break so the converted text does NOT merge
        // onto the same line as the paragraph that follows it.
        if (txt !== null) {
            try {
                var lastCh = txt.characters[-1].contents;
                if (lastCh !== "\r" && lastCh !== "\n") {
                    txt.insertionPoints[-1].contents = "\r";
                }
            } catch (eB) {}
        }
    }
    "SINGLE_CELL_TABLES_CONVERTED=" + n;
    """
    return app.DoScript(js, JS)


def _fit_image_tables_to_margin(app):
    """Shrink an IMAGE table so it fits the text area, WITHOUT changing the
    paragraph indent.

    A figure table anchored in an indented paragraph (e.g. a block quote with a
    left indent) starts at margin+indent; if it is full width it then spills past
    the right margin. We cannot zero the paragraph indent (that un-indents the
    quote text that shares the paragraph), so instead we scale the table columns
    down to the available indented width. The image layout pass then re-fits the
    pictures into the smaller cells. Returns count of tables shrunk."""
    js = r"""
    var doc = app.activeDocument;
    var oldRuler = doc.viewPreferences.rulerOrigin;
    doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN;
    var facing = doc.documentPreferences.facingPages;
    function marginWidth(pg){
        var pb = pg.bounds, mp = pg.marginPreferences, l, r;
        if (facing && pg.side == PageSideOptions.LEFT_HAND){ l = pb[1]+mp.right; r = pb[3]-mp.left; }
        else { l = pb[1]+mp.left; r = pb[3]-mp.right; }
        return r - l;
    }
    var n = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            var tb = st.tables[t];
            try {
                var hasImg = false;
                for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){
                    try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch (eH) {}
                }
                if (!hasImg) continue;
                var pg = tb.storyOffset.parentTextFrames[0].parentPage;
                var mw = marginWidth(pg);
                var li = 0, ri = 0;
                try { li = tb.storyOffset.paragraphs[0].leftIndent;  } catch (eLi) {}
                try { ri = tb.storyOffset.paragraphs[0].rightIndent; } catch (eRi) {}
                // Fit within the paragraph's indented text column (BOTH indents) so a
                // figure in a block quote lines up with the quoted text column.
                var avail = mw - li - ri - 2;            // small safety gap
                var tw = 0;
                for (var c = 0; c < tb.columns.length; c++) tw += tb.columns[c].width;
                if (tw > avail && avail > 0){
                    var scale = avail / tw;
                    for (var c2 = 0; c2 < tb.columns.length; c2++){
                        try { tb.columns[c2].width = tb.columns[c2].width * scale; } catch (eC) {}
                    }
                    n++;
                }
            } catch (eT) {}
        }
    }
    doc.viewPreferences.rulerOrigin = oldRuler;
    "IMAGE_TABLES_FITTED=" + n;
    """
    return app.DoScript(js, JS)


def fix_tables_in_doc(app):
    """Public entry point for the pipeline, run on the already-open document.

    Fixes table CELL overset (red dots) and keeps tables within the text column by
    auto-resizing column widths and cell insets only -- the table TEXT font size is
    never changed and no word spacing is added -- makes body rows breakable, and
    centres narrow left-aligned tables.

    Run this AFTER the document is laid out (after the main reflow) so cells are
    composed and their overset state is accurate. It then re-flows vertically --
    resetting any force-grown frames so a tall table SPLITS across pages instead of
    the text frame being grown (guarded so the page count can never run away), which
    is what keeps the body text flowing normally. Returns a summary.
    """
    rS = enforce_text_size(app, 9.65)
    rE = _collapse_empty_rows(app)
    rC = _compact_cell_content(app)
    rSp = "LIST_TABLES_SPLIT=via_text_flow"
    r0 = _break_poem_tables(app)
    rA = _align_autogrow_cells(app)
    rL = _left_align_table_cells(app)
    r1 = _fix_tables_and_breakable(app)
    rI = _fit_image_tables_to_margin(app)
    r2 = _center_narrow_tables(app)
    rB = _remove_all_table_borders(app)
    r3 = _fix_vertical(app)
    rF = _flow_overset_tail(app)
    return "%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s" % (rS, rE, rC, rSp, r0, rA, rL, r1, r2, rB, r3, rF, rI)


def _open_doc(app, idml_path):
    # Open an IDML in InDesign with user interaction and redraw disabled.
    js = f'''
    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
    app.scriptPreferences.enableRedraw = false;
    var doc = app.open(new File("{idml_path.replace(chr(92), '/')}"));
    try {{ doc.textPreferences.smartTextReflow = false; }} catch (e1) {{}}
    try {{ app.textPreferences.smartTextReflow = false; }} catch (e2) {{}}
    doc.pages.length + "";
    '''
    return app.DoScript(js, JS)


def _export_and_close(app, out_path):
    # Export the active document back to IDML and close it without saving.
    js = f'''
    var outFile = new File("{out_path.replace(chr(92), '/')}");
    app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, outFile);
    app.activeDocument.close(SaveOptions.NO);
    app.scriptPreferences.enableRedraw = true;
    "ok";
    '''
    return app.DoScript(js, JS)


def _collect_targets(target):
    # Return the list of target IDML paths from a file or directory argument.
    if os.path.isfile(target) and target.lower().endswith(".idml"):
        return [target]
    if os.path.isdir(target):
        return [os.path.join(target, f) for f in sorted(os.listdir(target))
                if f.lower().endswith(".idml")]
    return []


def main():
    # Standalone entry point: run the table-fit passes over a file or folder of IDMLs.
    _HERE = os.path.dirname(os.path.abspath(__file__))
    default_in  = os.path.join(_HERE, "output_files", "idml_files")
    out_dir     = os.path.join(_HERE, "output_files", "table_output_file")

    target = sys.argv[1] if len(sys.argv) > 1 else default_in
    idmls = _collect_targets(target)
    if not idmls:
        print(f"No .idml files found at: {target}")
        return

    os.makedirs(out_dir, exist_ok=True)

    try:
        app = win32com.client.Dispatch("InDesign.Application")
    except Exception:
        print("Error: Ensure Adobe InDesign is installed and running.")
        return
    try:
        app.DoScript(
            "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
            JS,
        )
    except Exception:
        pass

    print(f"Found {len(idmls)} IDML file(s).")
    print(f"Writing fixed copies to: {out_dir}\n")
    log = [f"=== Table fit / visibility fix — {datetime.now():%Y-%m-%d %H:%M:%S} ===",
           f"Output folder: {out_dir}"]

    MAX_RETRIES = 3
    for idml_path in idmls:
        name = os.path.basename(idml_path)
        out_path = os.path.join(out_dir, name)
        attempts = 0
        while True:
            try:
                print(f"{'-'*56}\nProcessing: {name}")
                pages_before = _open_doc(app, idml_path)
                print(f"  Pages before: {pages_before}")

                r0 = _break_poem_tables(app)
                print(f"  Poems:  {r0}")
                log.append(f"{name}: {r0}")

                r1 = _fix_tables_and_breakable(app)
                print(f"  Tables: {r1}")
                log.append(f"{name}: {r1}")

                r2 = _fix_vertical(app)
                print(f"  Layout: {r2}")
                log.append(f"{name}: {r2}")

                pages_after = "0"
                try:
                    pages_after = app.DoScript("app.activeDocument.pages.length + '';", JS)
                except Exception:
                    pass
                print(f"  Pages after:  {pages_after}")

                _export_and_close(app, out_path)
                print(f"  Saved: table_output_file\\{name}")
                log.append(f"{name}: pages {pages_before} -> {pages_after}")
                break

            except Exception as err:
                if _is_rpc_error(err) and attempts < MAX_RETRIES:
                    attempts += 1
                    print(f"  [!] InDesign hang on {name} "
                          f"(attempt {attempts}/{MAX_RETRIES}): {err}", flush=True)
                    try:
                        app = restart_indesign()
                    except Exception as re:
                        print(f"  [!] Restart failed: {re}", flush=True)
                        log.append(f"{name}: restart failed {re}")
                        break
                    continue
                print(f"  [!] Error on {name}: {err}", flush=True)
                log.append(f"{name}: ERROR {err}")
                break

    log_path = os.path.join(out_dir, "table_fit_log.txt")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log))
    except Exception:
        pass

    print(f"\n{'-'*56}\nDone. Fixed copies in: {out_dir}\n  Log: {log_path}")


if __name__ == "__main__":
    main()

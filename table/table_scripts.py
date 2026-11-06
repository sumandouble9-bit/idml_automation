"""ExtendScript (InDesign JS) builders for table fitting; each returns the script text for app.DoScript."""

try:
    from table_scripts_extra import *
except ImportError:
    from .table_scripts_extra import *


def _break_poem_tables_js():
    """ExtendScript for _break_poem_tables()."""
    return r'''
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


def _fix_tables_and_breakable_js():
    """ExtendScript for _fix_tables_and_breakable()."""
    return r'''
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

                var isSmallTable = (tb.columns.length <= 2);
                for (var pass=0; pass<400; pass++){
                    var need = needyCols(tb); if (need.length === 0) break;
                    var slack = isSmallTable ? 0 : (usable - tblWidth(tb));
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
                        var slack2 = isSmallTable ? 0 : (usable - tblWidth(tb));
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


def _fix_vertical_js():
    """ExtendScript for _fix_vertical()."""
    return r'''
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


def _align_autogrow_cells_js():
    """ExtendScript for _align_autogrow_cells()."""
    return r'''
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


def _hyphenate_overset_cells_js():
    """ExtendScript for _hyphenate_overset_cells()."""
    return r'''
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


def _center_narrow_tables_js():
    """ExtendScript for _center_narrow_tables()."""
    return r'''
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

                var tpara = tb.storyOffset.paragraphs[0];
                var stOffset = tb.storyOffset.index;
                var pStart = tpara.insertionPoints[0].index;
                var pEnd = tpara.insertionPoints[tpara.insertionPoints.length - 1].index;

                if (stOffset + 1 < pEnd) {
                    try {
                        tb.storyOffset.parentStory.insertionPoints[stOffset + 1].contents = "\r";
                        tpara = tb.storyOffset.paragraphs[0];
                        var nextPara = tb.storyOffset.parentStory.insertionPoints[stOffset + 2].paragraphs[0];
                        if (nextPara && nextPara.isValid && nextPara != tpara) {
                            try { nextPara.leftIndent = 0; } catch (eI) {}
                            try { nextPara.firstLineIndent = 18; } catch (eFL) {}
                            var _bStyle = doc.paragraphStyles.itemByName("body_text");
                            if (_bStyle && _bStyle.isValid) { try { nextPara.appliedParagraphStyle = _bStyle; } catch (eS) {} }
                        }
                    } catch (eSplit) {}
                }

                if (stOffset > pStart) {
                    try {
                        tb.storyOffset.contents = "\r";
                        tpara = tb.storyOffset.paragraphs[0];
                    } catch (eSplitPre) {}
                }

                try { tpara.firstLineIndent = 0; } catch (eF) {}
                try { tpara.rightIndent = 0; } catch (eR) {}
                try { tpara.justification = Justification.LEFT_ALIGN; } catch (eJ) {}
                if (leftover > 4) {
                    try { tpara.leftIndent = leftover / 2; centered++; } catch (eI) {}
                } else {
                    try { tpara.leftIndent = 0; } catch (eI0) {}
                }
            } catch (eTbl) {}
        }
    }
    doc.viewPreferences.rulerOrigin = oldRuler;
    "TABLES_CENTERED=" + centered;
    '''

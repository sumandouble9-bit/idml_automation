"""
Fix image layout — a standalone pass that runs AFTER image injection.

It does NOT change the injection logic and it NEVER detaches images (detaching
makes text reflow behind a page-fixed image, i.e. overlap). Images always stay
in the text flow so text makes room for them.

Two structural problems it repairs (never by detaching):

  1. Images placed inside a TABLE whose total width is wider than the text column
     (e.g. two figures in a 2-column table, 468pt wide in a 324pt column) — the
     table then spills past the margin. For every table wider than the usable
     column width (column - 8pt, to keep a 4pt gap each side) it scales the column
     widths down proportionally so the table fits, and refits the images inside
     the cells.

  2. Any single image whose FRAME sticks out past its page margin box — too wide
     (touches/crosses the left/right margin) or too TALL (crosses the top/bottom
     margin, e.g. a full-page figure taller than the text area). This is the
     "oversized image outside the margin line" case. Such an image is scaled down
     PROPORTIONALLY, in place, until it fits inside the margin box (with the usual
     4pt side gap and a little headroom for its line + caption). Placement only
     caps an image against its host frame, which on a near-empty page can be far
     taller than the real text area — so genuinely tall images can still overflow;
     this pass runs after pagination is final and catches them.

Everything stays in the text flow, so nothing overlaps. Returns a short summary
string, e.g. "tables=1 images=2".
"""

import win32com.client

JS = 1246973031


def fit_logo_fully(app):
    """SEPARATE pass. After the logo is relinked, the new logo image can be larger
    than its frame, so the frame CLIPS it (only part of the logo shows). This fits
    the WHOLE logo inside its frame, proportionally (no distortion) and centred, so
    the entire logo is visible. The frame's size/position is unchanged. Returns the
    count of logos fitted.
    """
    js = r'''
    var doc = app.activeDocument;
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    var n = 0;
    for (var i = 0; i < doc.allGraphics.length; i++){
        try {
            var g = doc.allGraphics[i];
            if (!g.itemLink || !isLogo(g.itemLink.name)) continue;
            var frm = g.parent;
            try { frm.fit(FitOptions.PROPORTIONALLY); } catch(e1){}   // whole image inside the frame
            try { frm.fit(FitOptions.CENTER_CONTENT); } catch(e2){}   // centred in the frame
            try { frm.strokeWeight = 0; } catch(e3){}                 // no border/bars around the logo
            try { var none = doc.swatches.itemByName("None"); if (none) frm.strokeColor = none; } catch(e4){}
            n++;
        } catch (eG) {}
    }
    n.toString();
    '''
    return app.DoScript(js, JS)


def place_logo_above_margin(app):
    """SEPARATE pass. The LeafBound logo can dip below the bottom margin line (it
    straddles it, with the lower part down in the footer / off the page). This moves
    the logo UP so it sits ABOVE the bottom margin line -- its bottom edge aligned to
    the margin -- at the very bottom of the text block, keeping it horizontally where
    it is. The logo's height and width are NEVER changed (no resizing); it is only
    shifted vertically. A logo already fully above the line is left alone. Returns the
    count of logos repositioned.
    """
    js = r'''
    var doc = app.activeDocument;
    var oldRuler = doc.viewPreferences.rulerOrigin;
    doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN;
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    var moved = 0;
    for (var i = 0; i < doc.allGraphics.length; i++){
        try {
            var g = doc.allGraphics[i];
            if (!g.itemLink || !isLogo(g.itemLink.name)) continue;
            var frm = g.parent;
            var pg = null; try { pg = frm.parentPage; } catch(eP){}
            if (!pg) continue;
            var pb = pg.bounds;                       // [top,left,bottom,right] in spread coords
            var marginBottom = pb[2] - pg.marginPreferences.bottom;
            var bb = frm.geometricBounds;

            // Only act when the logo dips BELOW the bottom margin line (its bottom is
            // past the line). A logo already fully above the line is left as-is.
            if (bb[2] <= marginBottom + 2) continue;

            // Move it up so its BOTTOM sits on the bottom margin line (logo entirely
            // above the line). NEVER resize -- height and width stay exactly the same.
            var dy = marginBottom - bb[2];            // negative -> up
            if (bb[0] + dy < pb[0] + 2) dy = (pb[0] + 2) - bb[0];   // don't run off the page top
            if (Math.abs(dy) > 0.5){
                frm.geometricBounds = [bb[0] + dy, bb[1], bb[2] + dy, bb[3]];
                moved++;
            }
        } catch (eG) {}
    }
    doc.viewPreferences.rulerOrigin = oldRuler;
    moved.toString();
    '''
    return app.DoScript(js, JS)


def remove_image_table_borders(app):
    """SEPARATE pass. Some books lay two/four figures side by side inside a TABLE
    (e.g. the two telephone illustrations). That table draws a black box (its cell
    borders) around the images. This removes the border ONLY from tables that
    contain an image (figure tables) and from the image frames themselves — real
    DATA tables (no image) keep their borders. Sets every cell edge stroke to 0 and
    clears the image-frame stroke. Nothing else is touched. Returns the count of
    figure tables cleared.
    """
    js = r'''
    var doc = app.activeDocument;
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    var none = null; try { none = doc.swatches.itemByName("None"); } catch(eN){}
    var cleared = 0;

    // 1) Figure tables: drop cell borders on any table that contains an image.
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            try {
                var tb = st.tables[t];
                var hasImg = false;
                for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){
                    try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch(eH){}
                }
                if (!hasImg) continue;                       // leave real data tables alone
                for (var c = 0; c < tb.cells.length; c++){
                    var cell = tb.cells[c];
                    try { cell.topEdgeStrokeWeight = 0; } catch(e1){}
                    try { cell.bottomEdgeStrokeWeight = 0; } catch(e2){}
                    try { cell.leftEdgeStrokeWeight = 0; } catch(e3){}
                    try { cell.rightEdgeStrokeWeight = 0; } catch(e4){}
                    if (none){
                        try { cell.topEdgeStrokeColor = none; } catch(e5){}
                        try { cell.bottomEdgeStrokeColor = none; } catch(e6){}
                        try { cell.leftEdgeStrokeColor = none; } catch(e7){}
                        try { cell.rightEdgeStrokeColor = none; } catch(e8){}
                    }
                }
                cleared++;
            } catch(eT){}
        }
    }

    // 2) Any image frame with its own stroke -> clear it too.
    for (var gi = 0; gi < doc.allGraphics.length; gi++){
        try {
            var g = doc.allGraphics[gi];
            if (g.itemLink && isLogo(g.itemLink.name)) continue;
            var frm = g.parent;
            try { if (frm.strokeWeight && frm.strokeWeight > 0) frm.strokeWeight = 0; } catch(eS){}
            if (none){ try { frm.strokeColor = none; } catch(eSC){} }
        } catch(eG){}
    }
    cleared.toString();
    '''
    return app.DoScript(js, JS)


def fix_image_layout(app):
    js = r'''
    var doc = app.activeDocument;
    var oldRuler = doc.viewPreferences.rulerOrigin;
    doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN;
    var facing = doc.documentPreferences.facingPages;
    var SIDE_PAD = 4;   // 4pt gap kept on each side

    function marginWidth(pg){
        var pb = pg.bounds, mp = pg.marginPreferences, l, r;
        if (facing && pg.side == PageSideOptions.LEFT_HAND){ l = pb[1]+mp.right; r = pb[3]-mp.left; }
        else { l = pb[1]+mp.left; r = pb[3]-mp.right; }
        return r - l;
    }

    // Full margin box {top,bottom,left,right} for a page (mirrors the audit).
    function marginBox(pg){
        var pb = pg.bounds, mp = pg.marginPreferences, l, r;
        if (facing && pg.side == PageSideOptions.LEFT_HAND){ l = pb[1]+mp.right; r = pb[3]-mp.left; }
        else { l = pb[1]+mp.left; r = pb[3]-mp.right; }
        return { top: pb[0]+mp.top, bottom: pb[2]-mp.bottom, left: l, right: r };
    }
    function isLogo(name){ if(!name) return false; var n=name.toUpperCase(); return n.indexOf("LEAF-BOUND")>=0 || n.indexOf("LOGO")>=0; }

    // Work out the FULL body-column width for a table (its host frame's column).
    // A figure table is sized to span the full text column so its left/right edges
    // line up exactly with the paragraph left/right margins (no side gap for tables).
    // Falls back to the page margin width.
    function usableWidthFor(table){
        var w = 0;
        try {
            var tf = table.storyOffset.parentTextFrames[0];
            var gb = tf.geometricBounds;
            var cols = 1, gut = 0;
            try { cols = tf.textFramePreferences.textColumnCount; } catch (e1) {}
            try { gut  = tf.textFramePreferences.textColumnGutter; } catch (e2) {}
            w = ((gb[3]-gb[1]) - (cols-1)*gut) / cols;
        } catch (eT) {}
        if (!w || w <= 0){
            try { w = marginWidth(table.storyOffset.parentTextFrames[0].parentPage); } catch (eP) {}
        }
        if (!w || w <= 0) w = 324;   // sensible default for these books
        return w;                    // full column width -> aligns with paragraph margins
    }

    var fixed = 0;
    for (var s = 0; s < doc.stories.length; s++){
        var st = doc.stories[s];
        for (var t = 0; t < st.tables.length; t++){
            try {
                var tb = st.tables[t];
                // only tables that actually contain an image
                var hasImg = false;
                for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){
                    try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch (eH) {}
                }
                if (!hasImg) continue;

                var usable = usableWidthFor(tb);
                var tw = 0;
                for (var c1 = 0; c1 < tb.columns.length; c1++) tw += tb.columns[c1].width;
                if (tw <= usable + 1) continue;   // already fits

                var scale = usable / tw;
                for (var c2 = 0; c2 < tb.columns.length; c2++){
                    try { tb.columns[c2].width = tb.columns[c2].width * scale; } catch (eC) {}
                }
                // Refit the images to their now-narrower cells.
                for (var cc = 0; cc < tb.cells.length; cc++){
                    var cell = tb.cells[cc];
                    try {
                        for (var g = 0; g < cell.allGraphics.length; g++){
                            var frm = cell.allGraphics[g].parent;
                            try { frm.fit(FitOptions.PROPORTIONALLY); } catch (eF1) {}
                            try { frm.fit(FitOptions.FRAME_TO_CONTENT); } catch (eF2) {}
                        }
                    } catch (eCell) {}
                }
                fixed++;
            } catch (eTbl) {}
        }
    }

    // ------------------------------------------------------------------
    // Pass 2: shrink any single image whose FRAME spills past its page
    // margin box (too wide OR too tall) so it sits fully inside the margins.
    // Proportional, in place; the image is never detached.
    // ------------------------------------------------------------------
    var imgsFixed = 0;
    for (var gi = 0; gi < doc.allGraphics.length; gi++){
        try {
            var g = doc.allGraphics[gi];
            var nm = g.itemLink ? g.itemLink.name : "";
            if (isLogo(nm)) continue;

            var frm = g.parent;
            // Skip images living inside a table cell — Pass 1 already fitted those,
            // and their geometry is governed by the (now-corrected) table width.
            var inCell = false;
            try { inCell = (frm.parent && frm.parent.constructor.name === "Cell"); } catch (eIC) {}
            if (inCell) continue;

            var pg = null; try { pg = frm.parentPage; } catch (ePg) {}
            if (!pg) continue;                       // can't compute a margin box; leave it

            var mb = marginBox(pg);
            var availW = (mb.right - mb.left) - 2*SIDE_PAD;      // keep 4pt gap each side
            var availH = (mb.bottom - mb.top) * 0.92;           // headroom for line + caption
            if (availW <= 0 || availH <= 0) continue;

            var bb = frm.geometricBounds;
            var fw = bb[3] - bb[1];
            var fh = bb[2] - bb[0];
            var scale = 1.0;
            if (fw > availW) scale = Math.min(scale, availW / fw);
            if (fh > availH) scale = Math.min(scale, availH / fh);

            // (a) Shrink proportionally if the image is genuinely too big.
            if (scale < 1.0) {
                var newW = fw * scale;
                var newH = fh * scale;
                // Shrink from the existing top-left; the smaller size keeps it
                // inside the margins.
                frm.geometricBounds = [bb[0], bb[1], bb[0] + newH, bb[1] + newW];
                try { frm.fit(FitOptions.CONTENT_TO_FRAME); } catch (eF) {}
                imgsFixed++;
                bb = frm.geometricBounds;             // refresh after resize
            }

            // (b) Clamp POSITION: an image that fits in size can still be
            // SHIFTED so its frame spills past a margin (e.g. right edge 9pt
            // beyond the right margin). How we fix it depends on whether the
            // image is ANCHORED (inline) or PAGE-FIXED.
            var cbb = frm.geometricBounds;
            var overR = cbb[3] > mb.right + 1, overL = cbb[1] < mb.left - 1;
            var overB = cbb[2] > mb.bottom + 1, overT = cbb[0] < mb.top - 1;
            if (overR || overL || overB || overT) {
                // Page-fixed frames can be nudged back inside the margin box.
                // (Anchored/in-cell images do not respond to geometricBounds moves --
                // those are centred in their cells by center_images_in_cells().)
                var dx = 0, dy = 0;
                if (overR)      dx = mb.right - cbb[3];
                else if (overL) dx = mb.left  - cbb[1];
                if (overB)      dy = mb.bottom - cbb[2];
                else if (overT) dy = mb.top   - cbb[0];
                if (dx != 0 || dy != 0) {
                    try {
                        frm.geometricBounds = [cbb[0] + dy, cbb[1] + dx, cbb[2] + dy, cbb[3] + dx];
                        imgsFixed++;
                    } catch (eMove) {}
                }
            }
        } catch (eG) {}
    }

    // ------------------------------------------------------------------
    // Pass 3: fit side-by-side image ROWS within the margin box. Some figures
    // are placed as a row of images sitting next to each other (e.g. two flags,
    // "Walking / Trotting / Canter / Galloping", the two phone illustrations).
    // When the row's combined width spills past the column, the whole group is
    // scaled down together so it fits — the images STAY side by side (never
    // stacked, never detached). Purely geometric: a "row" is a set of images on
    // one page whose vertical ranges overlap, so stacked or single images (which
    // do not overlap vertically) are never touched.
    // ------------------------------------------------------------------
    var rowsFixed = 0;
    var items = [];
    for (var gi2 = 0; gi2 < doc.allGraphics.length; gi2++){
        try {
            var gg = doc.allGraphics[gi2];
            var nm2 = gg.itemLink ? gg.itemLink.name : "";
            if (isLogo(nm2)) continue;
            var fr2 = gg.parent;
            var inCell2 = false;
            try { inCell2 = (fr2.parent && fr2.parent.constructor.name === "Cell"); } catch (e) {}
            if (inCell2) continue;                       // tables handled in Pass 1
            var pg2 = null; try { pg2 = fr2.parentPage; } catch (e) {}
            if (!pg2) continue;
            items.push({ fr: fr2, pg: pg2, bb: fr2.geometricBounds });
        } catch (e) {}
    }
    var pagesMap = {};
    for (var ii = 0; ii < items.length; ii++){
        var pid = items[ii].pg.id;
        (pagesMap[pid] = pagesMap[pid] || []).push(items[ii]);
    }
    for (var pk in pagesMap){
        var arr = pagesMap[pk];
        if (arr.length < 2) continue;
        arr.sort(function(a, b){ return a.bb[0] - b.bb[0]; });   // by top edge
        var usedRow = [];
        for (var a1 = 0; a1 < arr.length; a1++){
            if (usedRow[a1]) continue;
            var cluster = [arr[a1]]; usedRow[a1] = true;
            var top = arr[a1].bb[0], bot = arr[a1].bb[2];
            for (var a2 = a1 + 1; a2 < arr.length; a2++){
                if (usedRow[a2]) continue;
                var t2 = arr[a2].bb[0], b2 = arr[a2].bb[2];
                var ov = Math.min(bot, b2) - Math.max(top, t2);       // vertical overlap
                var minH = Math.min(bot - top, b2 - t2);
                if (minH > 0 && ov > 0.4 * minH){                     // same visual row
                    cluster.push(arr[a2]); usedRow[a2] = true;
                    top = Math.min(top, t2); bot = Math.max(bot, b2);
                }
            }
            if (cluster.length < 2) continue;
            var minLeft = 1e9, maxRight = -1e9;
            for (var c = 0; c < cluster.length; c++){
                if (cluster[c].bb[1] < minLeft) minLeft = cluster[c].bb[1];
                if (cluster[c].bb[3] > maxRight) maxRight = cluster[c].bb[3];
            }
            var mb2 = marginBox(cluster[0].pg);
            var usable2 = (mb2.right - mb2.left) - 2 * SIDE_PAD;
            var extent = maxRight - minLeft;
            if (usable2 > 0 && extent > usable2 + 1){
                var sc = usable2 / extent;
                for (var c2 = 0; c2 < cluster.length; c2++){
                    try {
                        var f = cluster[c2].fr, b = f.geometricBounds;
                        var w = (b[3] - b[1]) * sc, h = (b[2] - b[0]) * sc;
                        f.geometricBounds = [b[0], b[1], b[0] + h, b[1] + w];
                        try { f.fit(FitOptions.CONTENT_TO_FRAME); } catch (eF3) {}
                    } catch (eC3) {}
                }
                rowsFixed++;
            }
        }
    }

    doc.viewPreferences.rulerOrigin = oldRuler;
    "tables=" + fixed + " images=" + imgsFixed + " rows=" + rowsFixed;
    '''
    return app.DoScript(js, JS)


def center_images_in_cells(app):
    """Centre every image that is anchored inside a TABLE CELL horizontally within
    its own column. Figure tables (e.g. two side-by-side illustrations) sometimes
    inject with a uniform rightward anchor offset, leaving a big gap on one side
    and pushing the outer image past the page margin. Anchored images ignore
    geometricBounds / alignment edits, but their anchorXoffset DOES move them, so
    we compute the offset that centres each image in its column and apply it.
    Only images already off-centre by > 2pt are touched. Returns count fixed."""
    js = r'''
    var doc = app.activeDocument;
    var GAP = 14;                 // small gap kept between side-by-side figures
    var fixed = 0;
    var centeredFrames = [];
    // Group every cell-anchored image by its table + row, so a row of
    // side-by-side figures is handled as one unit.
    var groups = {};
    for (var i = 0; i < doc.allGraphics.length; i++) {
        try {
            var g = doc.allGraphics[i];
            var frm = g.parent;
            var p = frm, cell = null, tbl = null, tf = null;
            for (var k = 0; k < 12 && p; k++) {
                var cn = p.constructor.name;
                if (cn == "Cell"      && !cell) cell = p;
                if (cn == "Table"     && !tbl)  tbl  = p;
                if (cn == "TextFrame" && !tf)   tf   = p;
                try { p = p.parent; } catch (e) { p = null; }
            }
            if (!cell || !tbl || !tf) continue;             // only in-cell images
            var parts = String(cell.name).split(":");
            var col = parseInt(parts[0], 10), row = parseInt(parts[1], 10);
            if (isNaN(col) || isNaN(row)) continue;
            var key = tbl.id + "|" + row;
            if (!groups[key]) groups[key] = [];
            groups[key].push({ frm: frm, col: col, tbl: tbl, tf: tf });
        } catch (eC) {}
    }
    // Lay each group out centred within the table width: images kept at their
    // original size (never resized) and packed with a fixed GAP between them,
    // the whole group centred. This removes the large middle gap that per-column
    // centring produced, and keeps the outer image inside the page margin.
    for (var key in groups) {
        try {
            var arr = groups[key];
            arr.sort(function (a, b) { return a.col - b.col; });
            var tbl = arr[0].tbl, tf = arr[0].tf;
            // Include the table paragraph's left indent: a figure table anchored
            // in an indented block quote starts at frameLeft + indent, so the image
            // group must be centred within that shifted span, not at the frame edge.
            var _li = 0;
            try { _li = tbl.storyOffset.paragraphs[0].leftIndent; } catch (e_li) {}
            var tableLeft = tf.geometricBounds[1] + tf.textFramePreferences.insetSpacing[0] + _li;
            var widths = [], total = 0;
            for (var j = 0; j < arr.length; j++) {
                var b = arr[j].frm.geometricBounds;
                var w = b[3] - b[1];
                widths.push(w); total += w;
            }
            total += GAP * (arr.length - 1);
            var startX = tableLeft + (tbl.width - total) / 2;
            var x = startX;
            for (var j = 0; j < arr.length; j++) {
                var b2 = arr[j].frm.geometricBounds;
                var cur = (b2[1] + b2[3]) / 2;
                var target = x + widths[j] / 2;
                var shift = target - cur;
                if (Math.abs(shift) > 1) {
                    try {
                        var aos = arr[j].frm.anchoredObjectSettings;
                        aos.anchorXoffset = (aos.anchorXoffset || 0) + shift;
                        centeredFrames.push(arr[j].frm);
                        fixed++;
                    } catch (eA) {}
                }
                x += widths[j] + GAP;
            }
        } catch (eG) {}
    }
    try { doc.recompose(); } catch (eR) {}
    for (var f = 0; f < centeredFrames.length; f++) {
        try { centeredFrames[f].fit(FitOptions.CENTER_CONTENT); } catch (eFit) {}
    }
    "CELL_IMAGES_CENTERED=" + fixed;
    '''
    return app.DoScript(js, JS)

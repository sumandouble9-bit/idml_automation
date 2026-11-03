"""ExtendScript (InDesign JS) builders for table fitting (part 2); each returns the script text for app.DoScript."""


def enforce_text_size_js(size=9.65):
    """ExtendScript for enforce_text_size()."""
    return r'''
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
                        for (var p = 0; p < cps.length; p++){
                            try { cps[p].clearOverrides(OverrideType.CHARACTER_ONLY); } catch (eCO) {}
                            try { cps[p].pointSize = SZ; } catch (eP) {}
                            try { cps[p].leading = 12; } catch (eL) {}
                        }
                        n++;
                    } catch (eC) {}
                }
            } catch (eT) {}
        }
    }
    "SIZE_ENFORCED_CELLS=" + n;
    '''.replace("%SZ%", str(size))


def _collapse_empty_rows_js():
    """ExtendScript for _collapse_empty_rows()."""
    return r"""
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


def _remove_all_table_borders_js():
    """ExtendScript for _remove_all_table_borders()."""
    return r"""
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


def _left_align_table_cells_js():
    """ExtendScript for _left_align_table_cells()."""
    return r"""
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


def _split_multiline_list_cells_js():
    """ExtendScript for _split_multiline_list_cells()."""
    return r"""
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


def _compact_cell_content_js():
    """ExtendScript for _compact_cell_content()."""
    return r"""
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


def _flow_overset_tail_js():
    """ExtendScript for _flow_overset_tail()."""
    return r"""
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


def convert_single_cell_tables_js():
    """ExtendScript for convert_single_cell_tables()."""
    return r"""
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


def _fit_image_tables_to_margin_js():
    """ExtendScript for _fit_image_tables_to_margin()."""
    return r"""
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


__all__ = [
    'enforce_text_size_js',
    '_collapse_empty_rows_js',
    '_remove_all_table_borders_js',
    '_left_align_table_cells_js',
    '_split_multiline_list_cells_js',
    '_compact_cell_content_js',
    '_flow_overset_tail_js',
    'convert_single_cell_tables_js',
    '_fit_image_tables_to_margin_js',
]

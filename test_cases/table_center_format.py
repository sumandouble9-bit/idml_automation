JS = 1246973031

_JS = r"""
var doc = app.activeDocument;
var oldRuler = doc.viewPreferences.rulerOrigin;
doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN;
var facing = doc.documentPreferences.facingPages;
var MIN_SPACE = 12;

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
        try { cols = tf.textFramePreferences.textColumnCount; } catch(e1){}
        try { gut  = tf.textFramePreferences.textColumnGutter; } catch(e2){}
        w = ((gb[3]-gb[1]) - (cols-1)*gut) / cols;
    } catch(eT){}
    if (!w || w <= 0){ try { w = marginWidth(tb.storyOffset.parentTextFrames[0].parentPage); } catch(eP){} }
    if (!w || w <= 0) w = 324;
    return w;
}
function tblWidth(tb){ var w=0; for (var c=0;c<tb.columns.length;c++) w += tb.columns[c].width; return w; }

var bodyStyle = null;
var aps = doc.allParagraphStyles;
for (var i=0;i<aps.length;i++){ if (aps[i].name == "body_text"){ bodyStyle = aps[i]; break; } }

var split = 0, centered = 0;
for (var s = 0; s < doc.stories.length; s++){
    var st = doc.stories[s];
    var tbs = st.tables;
    for (var t = 0; t < tbs.length; t++){
        try {
            var tb = tbs[t];
            var hasImg = false;
            for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){
                try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch (eH) {}
            }
            if (hasImg) continue;

            var tpara = tb.storyOffset.paragraphs[0];
            var stOffset = tb.storyOffset.index;
            var pStart = tpara.insertionPoints[0].index;
            var pEnd = tpara.insertionPoints[tpara.insertionPoints.length - 1].index;

            if (stOffset + 1 < pEnd) {
                try {
                    tb.storyOffset.parentStory.insertionPoints[stOffset + 1].contents = "\r";
                    split++;
                    tpara = tb.storyOffset.paragraphs[0];
                    var nextPara = tb.storyOffset.parentStory.insertionPoints[stOffset + 2].paragraphs[0];
                    if (nextPara && nextPara.isValid && nextPara != tpara) {
                        try { nextPara.leftIndent = 0; } catch (eI) {}
                        try { nextPara.firstLineIndent = 18; } catch (eFL) {}
                        if (bodyStyle && bodyStyle.isValid) { try { nextPara.appliedParagraphStyle = bodyStyle; } catch (eS) {} }
                    }
                } catch (eSplit) {}
            }

            if (stOffset > pStart) {
                try {
                    tb.storyOffset.contents = "\r";
                    split++;
                    tpara = tb.storyOffset.paragraphs[0];
                } catch (eSplitPre) {}
            }

            try { tpara.firstLineIndent = 0; } catch (eF) {}
            var tw = tblWidth(tb);
            var colW = usableWidthFor(tb);
            var leftover = colW - tw;
            var isNarrow = (leftover >= 6) || (tb.columns.length <= 2 && leftover > 4);
            if (isNarrow && leftover > 0) {
                try { tpara.leftIndent = leftover / 2; centered++; } catch (eC) {}
            } else {
                try { tpara.leftIndent = 0; } catch (eZ) {}
            }
        } catch(eT){}
    }
}
doc.viewPreferences.rulerOrigin = oldRuler;
"TABLES_SPLIT=" + split + " TABLES_CENTERED=" + centered;
"""


def run(app):
    """Separate body text that is merged into a table's paragraph into its own
    paragraph (at the margin), then centre narrow tables. Fixes both the table
    not centring and the following paragraph starting at the table's position."""
    return app.DoScript(_JS, JS)

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
            for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++){ try { if (tb.cells[c0].allGraphics.length > 0) hasImg = true; } catch(eH){} }
            if (hasImg) continue;

            var story = tb.storyOffset.parentStory;
            var idx = tb.storyOffset.index;
            var para = tb.storyOffset.paragraphs[0];

            if (String(para.contents).length > 2){                 // body text shares the table's paragraph
                story.insertionPoints[idx + 1].contents = "\r";     // break right after the table marker
                try {
                    var bodyPara = story.characters[idx + 2].paragraphs[0];
                    bodyPara.leftIndent = 0;
                } catch(eB){}
                split++;
            }

            var usable = usableWidthFor(tb);
            try { var pg = tb.storyOffset.parentTextFrames[0].parentPage; var mw = marginWidth(pg); if (mw > 0 && usable > mw) usable = mw; } catch(eM){}
            var leftover = usable - tblWidth(tb);
            var tpara = tb.storyOffset.paragraphs[0];
            try { tpara.firstLineIndent = 0; } catch(eF){}
            if (leftover >= MIN_SPACE){ try { tpara.leftIndent = leftover / 2; centered++; } catch(eC){} }
            else { try { tpara.leftIndent = 0; } catch(eZ){} }
        } catch(eT){}
    }
}
doc.viewPreferences.rulerOrigin = oldRuler;
"TABLES_SPLIT=" + split + " TABLES_CENTERED=" + centered;
"""


def run(app):
    # Separate body text that is merged into a table's paragraph into its own
    # paragraph (at the margin), then centre narrow tables. Fixes both the table
    # not centring and the following paragraph starting at the table's position.
    return app.DoScript(_JS, JS)

import check_common

_BODY = r"""
    var tblOverset = [], tblOutside = [];
    for (var tsi = 0; tsi < doc.stories.length; tsi++){
        var tsto = doc.stories[tsi];
        for (var tti = 0; tti < tsto.tables.length; tti++){
            var tbl = tsto.tables[tti];
            var tpg = null, tfb = null, tInset = 0;
            try {
                var tfr = tbl.storyOffset.parentTextFrames;
                if (tfr.length){
                    tpg = tfr[0].parentPage;
                    tfb = tfr[0].geometricBounds;
                    try { tInset = tfr[0].textFramePreferences.insetSpacing[0]; } catch (eIn) {}
                }
            } catch (eTF) {}
            var tpage = tpg ? tpg.name : "?";
            var oc = 0;
            try {
                for (var cci = 0; cci < tbl.cells.length; cci++){
                    try {
                        var ccell = tbl.cells[cci];
                        if (ccell.overflows) oc++;   // any red-dot overset cell counts
                    } catch (eCe) {}
                }
            } catch (eCells) {}
            if (oc > 0) tblOverset.push("tbl#" + (tti + 1) + " " + oc + " cell(s) p." + tpage);
            if (tpg && tfb){
                var tmb = marginBox(tpg);
                var pLeft = 0;
                try { pLeft = tbl.storyOffset.paragraphs[0].leftIndent; } catch (ePL) {}
                var tLeft = tfb[1] + tInset + pLeft;
                var tRight = tLeft + tbl.width;
                var marginW = tmb.right - tmb.left;
                if (tRight > tmb.right + 2 || tLeft < tmb.left - 2 || tbl.width > marginW + 2){
                    tblOutside.push("tbl#" + (tti + 1) + " x[" + Math.round(tLeft) + ".." + Math.round(tRight) +
                        "] margin[" + Math.round(tmb.left) + ".." + Math.round(tmb.right) + "] p." + tpage);
                }
            }
        }
    }
    if (tblOverset.length > 0) problems.push("TABLE_CELL_OVERSET=" + tblOverset.length + ":" + tblOverset.join(";"));
    if (tblOutside.length > 0) problems.push("TABLE_OUTSIDE_MARGIN=" + tblOutside.length + ":" + tblOutside.join(";"));
"""


def check(app, caption_map=None):
    """Flag table cells that are overset or tables past the margin."""
    return check_common.run(app, _BODY)

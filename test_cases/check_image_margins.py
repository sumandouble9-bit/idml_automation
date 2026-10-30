import check_common

_BODY = r"""
    var offPageDetails = [], notCenteredDetails = [], outsideMarginDetails = [], overlapDetails = [], logoBadDetails = [];
    for (var i = 0; i < doc.allGraphics.length; i++) {
        try {
            var g    = doc.allGraphics[i];
            var name = g.itemLink ? g.itemLink.name : "?";
            if (isLogo(name)) {
                try {
                    var lfrm = g.parent, lbb = lfrm.geometricBounds, lpg = null;
                    try { lpg = lfrm.parentPage; } catch (eLp) {}
                    if (lpg) {
                        var lpb = lpg.bounds;
                        var offpage = (lbb[0] < lpb[0]-2 || lbb[2] > lpb[2]+2 || lbb[1] < lpb[1]-2 || lbb[3] > lpb[3]+2);
                        if (offpage) {
                            logoBadDetails.push(name + " (y[" + Math.round(lbb[0]) + ".." + Math.round(lbb[2]) +
                                "] pageBottom=" + Math.round(lpb[2]) + " p." + lpg.name + " off-page)");
                        }
                    } else {
                        logoBadDetails.push(name + " (no page -- off layout)");
                    }
                } catch (eLg) {}
                continue;                               // logos get only this check
            }

            var frm = g.parent;
            var bb  = frm.geometricBounds;
            var fh  = bb[2] - bb[0], fw = bb[3] - bb[1];
            var pg = null; try { pg = frm.parentPage; } catch (ePP) {}
            var pageName = pg ? pg.name : "?";

            if (fh > pageH || fw > pageW) {
                offPageDetails.push(name + " (" + Math.round(fw) + "x" + Math.round(fh) + "pt on p." + pageName + ")");
                continue;
            }

            if (pg) {
                var mb = marginBox(pg);
                if (bb[1] < mb.left-2 || bb[3] > mb.right+2 || bb[0] < mb.top-2 || bb[2] > mb.bottom+2) {
                    outsideMarginDetails.push(name + " (x[" + Math.round(bb[1]) + ".." + Math.round(bb[3]) +
                        "] y[" + Math.round(bb[0]) + ".." + Math.round(bb[2]) +
                        "] outside margin x[" + Math.round(mb.left) + ".." + Math.round(mb.right) +
                        "] y[" + Math.round(mb.top) + ".." + Math.round(mb.bottom) + "] p." + pageName + ")");
                }
            } else {
                outsideMarginDetails.push(name + " (no page — off-layout)");
            }

            var pt = frm.parent;
            var isAnchored = false;
            try { isAnchored = (pt && pt.paragraphs && pt.paragraphs.length > 0); } catch (eIA) {}

            var isPageFixed = false;
            try { isPageFixed = (pt && (pt.constructor.name === "Spread" || pt.constructor.name === "Page")); } catch (ePF) {}
            if (isPageFixed && pg) {
                try {
                    var tfs = pg.textFrames;
                    for (var tfi = 0; tfi < tfs.length; tfi++) {
                        var tf = tfs[tfi];
                        if (tf === frm) continue;
                        var hasText = false;
                        try { hasText = (tf.characters.length > 2); } catch (eTX) {}
                        if (hasText && rectsOverlap(bb, tf.geometricBounds)) {
                            overlapDetails.push(name + " (overlaps text on p." + pageName + ")");
                            break;
                        }
                    }
                } catch (eOv) {}
            }

            if (isAnchored) {
                var aosAlign = "n/a", paraJust = "n/a", isCentered = false;
                try {
                    var aos = frm.anchoredObjectSettings;
                    if (aos) {
                        aosAlign = String(aos.horizontalAlignment);
                        if (aos.horizontalAlignment == HorizontalAlignment.CENTER_ALIGN) isCentered = true;
                    }
                } catch (eA) {}
                if (!isCentered) {
                    try {
                        paraJust = String(pt.paragraphs[0].justification);
                        if (pt.paragraphs[0].justification == Justification.CENTER_ALIGN) isCentered = true;
                    } catch (eP) {}
                }
                if (!isCentered) {
                    notCenteredDetails.push(name + " (aos=" + aosAlign + " para=" + paraJust + " p." + pageName + ")");
                }
            }
        } catch (eG) {}
    }
    if (offPageDetails.length > 0)       problems.push("OVERSIZED_IMAGES=" + offPageDetails.length + ":" + offPageDetails.join(";"));
    if (outsideMarginDetails.length > 0) problems.push("IMAGES_OUTSIDE_MARGIN=" + outsideMarginDetails.length + ":" + outsideMarginDetails.join(";"));
    if (overlapDetails.length > 0)       problems.push("IMAGES_OVERLAP_TEXT=" + overlapDetails.length + ":" + overlapDetails.join(";"));
    if (notCenteredDetails.length > 0)   problems.push("NOT_CENTERED="   + notCenteredDetails.length + ":" + notCenteredDetails.join(";"));
    if (logoBadDetails.length > 0)       problems.push("LOGO_OUTSIDE_MARGIN=" + logoBadDetails.length + ":" + logoBadDetails.join(";"));
    try { doc.recompose(); } catch(eRC){}
    function _ovf(G, FR){
        var a = G.geometricBounds, b = FR.geometricBounds;
        var x1 = Math.max(a[1], b[1]), y1 = Math.max(a[0], b[0]);
        var x2 = Math.min(a[3], b[3]), y2 = Math.min(a[2], b[2]);
        var w = x2 - x1; if (w < 0) w = 0;
        var h = y2 - y1; if (h < 0) h = 0;
        var ar = (a[3] - a[1]) * (a[2] - a[0]);
        return ar > 0 ? (w * h) / ar : 1;
    }
    var offFrame = [];
    for (var of1 = 0; of1 < doc.allGraphics.length; of1++){
        try {
            var og = doc.allGraphics[of1];
            if (!og.itemLink) continue;
            if (isLogo(og.itemLink.name)) continue;
            var ofr = og.parent;
            if (_ovf(og, ofr) < 0.5){
                var opg = "?"; try { if (ofr.parentPage) opg = ofr.parentPage.name; } catch(eop){}
                offFrame.push(og.itemLink.name + " (p." + opg + ")");
            }
        } catch(eof){}
    }
    if (offFrame.length > 0) problems.push("IMAGE_OFF_FRAME=" + offFrame.length + ":" + offFrame.join(";"));
"""


def check(app, caption_map=None):
    """Flag images off-page, outside the margin, over text, not centred, or off-frame."""
    return check_common.run(app, _BODY)

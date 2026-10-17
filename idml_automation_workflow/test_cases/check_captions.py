import check_common

_BODY = r"""
    var CAP = __CAP__;
    function normCap(s){ return String(s).replace(/[^a-zA-Z0-9]/g, "").toLowerCase(); }
    var capMissing = [];     // EPUB caption not found below the image at all
    var capNotFig  = [];     // caption present but NOT styled as a centred 'fig caption'
    var capDup     = [];     // caption present TWICE (duplicate) for one image
    for (var ci = 0; ci < doc.allGraphics.length; ci++){
        try {
            var cg = doc.allGraphics[ci];
            var cname = cg.itemLink ? cg.itemLink.name : "";
            if (isLogo(cname)) continue;
            var want = CAP[cname];
            if (!want) continue;                       // no caption expected for this image
            var cframe = cg.parent;
            var cImgPara = cframe.parent.paragraphs[0];
            var cHost = cImgPara.parentStory;
            var cLast = cImgPara.characters[-1].index;
            var cpg = "?"; try { if (cframe.parentPage) cpg = cframe.parentPage.name; } catch (ePg) {}
            if (cLast + 1 >= cHost.characters.length){
                capMissing.push(cname + " (p." + cpg + ")"); continue;
            }
            var belowP = cHost.characters[cLast + 1].paragraphs[0];
            var belowIsImg = false;
            try { belowIsImg = (belowP.allPageItems.length > 0); } catch (eBI) {}
            if (belowIsImg) continue;

            var bn = normCap(belowP.contents), wn = normCap(want);
            var matched = (bn.length > 0 && (bn === wn ||
                (bn.length >= 3 && (wn.indexOf(bn) === 0 || bn.indexOf(wn) === 0)) ||
                (wn.length >= 4 && bn.indexOf(wn) !== -1)));
            if (!matched){ capMissing.push(cname + " (p." + cpg + ")"); continue; }

            var styleName = ""; try { styleName = belowP.appliedParagraphStyle.name; } catch (eSN) {}
            if (styleName !== "fig caption"){
                capNotFig.push(cname + " (p." + cpg + ")");
            } else {
                var bJust = null; try { bJust = belowP.justification; } catch (eBJ) {}
                if (bJust !== Justification.CENTER_ALIGN){
                    capNotFig.push(cname + " (p." + cpg + ") [left/right]");
                }
            }

            try {
                var bLast = belowP.characters[-1].index;
                if (bLast + 1 < cHost.characters.length){
                    var nextP = cHost.characters[bLast + 1].paragraphs[0];
                    var nImg = false; try { nImg = (nextP.allPageItems.length > 0); } catch (eNI) {}
                    var nStyle = ""; try { nStyle = nextP.appliedParagraphStyle.name; } catch (eNS) {}
                    var nn = normCap(nextP.contents);
                    if (!nImg && nStyle === "fig caption" && nn === wn){
                        capDup.push(cname + " (p." + cpg + ")");               // duplicate caption paragraph
                    } else if (!nImg && wn.length >= 4 && nn.length > wn.length && nn.indexOf(wn) === 0){
                        capDup.push(cname + " (p." + cpg + ") [body-dup]");    // caption repeated at start of body text
                    }
                }
            } catch (eDup) {}
        } catch (eCC) {}
    }
    if (capMissing.length > 0) problems.push("CAPTION_MISSING=" + capMissing.length + ":" + capMissing.join(";"));
    if (capNotFig.length  > 0) problems.push("CAPTION_NOT_CENTERED=" + capNotFig.length + ":" + capNotFig.join(";"));
    if (capDup.length     > 0) problems.push("DUPLICATE_CAPTION=" + capDup.length + ":" + capDup.join(";"));
"""


def check(app, caption_map=None):
    """Flag EPUB captions that are missing, not centred, or duplicated."""
    items = ','.join('"%s":"%s"' % (check_common.escape_js(k), check_common.escape_js(v))
                     for k, v in (caption_map or {}).items())
    body = _BODY.replace('__CAP__', '{' + items + '}')
    return check_common.run(app, body)

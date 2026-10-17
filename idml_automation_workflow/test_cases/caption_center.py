JS = 1246973031


def run(app, caption_map):
    """FINAL caption pass (runs last). Makes the paragraph directly below every
    captioned image a single, centred "fig caption" paragraph:

      * a caption fused onto the front of the body paragraph is split off,
      * a caption on the first forced-line-break line is split off,
      * a standalone caption left in body style is restyled, and
      * a caption repeated at the start of the FOLLOWING body paragraph is removed
        (no duplicate), for BOTH the split and the standalone cases.

    Matching is on NORMALISED text (letters/digits only), so apostrophe/dash
    encoding never breaks it; splitting is by character position (never by
    deleting a matched string); and every "fig caption" paragraph is forced to
    CENTER_ALIGN. Returns the number of captions normalised.
    """
    if not caption_map:
        return "0"

    def esc(s):
        return (s.replace("\\", "\\\\").replace('"', '\\"')
                 .replace("\r", " ").replace("\n", " "))
    items = ",".join('"%s":"%s"' % (esc(k), esc(v)) for k, v in caption_map.items())
    cap_literal = "{" + items + "}"

    js = r"""
    var CAP = __CAP__;
    var doc = app.activeDocument;
    var LF = 10, CR = String.fromCharCode(13);
    function norm(s){ return String(s).replace(/[^a-zA-Z0-9]/g, "").toLowerCase(); }
    function isAlnum(ch){ return (ch >= "0" && ch <= "9") || (ch >= "a" && ch <= "z") || (ch >= "A" && ch <= "Z"); }
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    function figStyle(){
        var st = doc.paragraphStyles.itemByName("fig caption");
        if (!st.isValid){ st = doc.paragraphStyles.add({name:"fig caption"}); }
        try { st.justification = Justification.CENTER_ALIGN; } catch(e){}
        try { st.pointSize = 9; } catch(e){}
        return st;
    }
    function styleCaption(p){
        try {
            p.appliedParagraphStyle = figStyle();
            p.justification = Justification.CENTER_ALIGN;
            try { p.appliedCharacterStyle = doc.characterStyles[0]; } catch(eC){}
            try { p.fontStyle = "Regular"; } catch(eF){}
            p.pointSize = 9;
            var ws = p.words;
            for (var i=0;i<ws.length;i++){ var t=ws[i].contents; if((t===t.toUpperCase())&&(t!==t.toLowerCase())) ws[i].pointSize = 8; }
        } catch(e){}
    }
    function capPrefixLen(s, capN){
        var acc = "", k;
        for (k = 0; k < s.length; k++){
            var ch = s.charAt(k);
            if (isAlnum(ch)) acc += ch.toLowerCase();
            if (acc.length > capN.length) return -1;
            if (capN.indexOf(acc) !== 0) return -1;
            if (acc.length === capN.length){
                var j = k + 1;
                while (j < s.length){
                    var c2 = s.charCodeAt(j);
                    if (c2 === 10 || c2 === 13) break;
                    if (isAlnum(s.charAt(j))) break;
                    j++;
                }
                return j;
            }
        }
        return -1;
    }

    var fixed = 0;
    var graphics = doc.allGraphics;
    for (var gi = 0; gi < graphics.length; gi++){
        try {
            var g = graphics[gi];
            var name = g.itemLink ? g.itemLink.name : "";
            if (isLogo(name)) continue;
            var cap = CAP[name];
            if (!cap) continue;
            var capN = norm(cap);
            if (capN.length < 3) continue;

            var anchorChar = g.parent.parent;
            var imgPara = anchorChar.paragraphs[0];
            var host = imgPara.parentStory;
            var li = imgPara.characters[-1].index;
            if (li + 1 >= host.characters.length) continue;

            var belowP = host.characters[li + 1].paragraphs[0];
            var belowImg = false;
            try { belowImg = (belowP.allPageItems.length > 0); } catch(eB){}
            if (belowImg) continue;

            var styleName = "";
            try { styleName = belowP.appliedParagraphStyle.name; } catch(eS){}

            var whole = belowP.contents;
            var pre = capPrefixLen(whole, capN);
            var startIdx = belowP.characters[0].index;
            var wholeNormLen = norm(whole).length;
            var capPara = belowP;

            if (styleName === "fig caption"){
                // already a caption paragraph -> leave it, but still de-dup below.
            } else if (pre < 0){
                continue;
            } else if (wholeNormLen === capN.length){
                styleCaption(belowP);
                capPara = belowP;
                fixed++;
            } else {
                var splitChar = host.characters[startIdx + pre];
                var sc = "";
                try { sc = splitChar.contents; } catch(eSC){}
                if (sc.charCodeAt(0) === LF){ splitChar.contents = CR; }
                else { host.insertionPoints[startIdx + pre].contents = CR; }
                capPara = host.characters[startIdx].paragraphs[0];
                styleCaption(capPara);
                fixed++;
            }

            // De-dup (BOTH cases): strip a caption repeated at the front of the
            // following body paragraph, only when real body text remains.
            try {
                var bodyStart = capPara.characters[-1].index + 1;
                if (bodyStart < host.characters.length){
                    var bodyPara = host.characters[bodyStart].paragraphs[0];
                    var bImg = false; try { bImg = (bodyPara.allPageItems.length > 0); } catch(eBI){}
                    var bStyle = ""; try { bStyle = bodyPara.appliedParagraphStyle.name; } catch(eBS){}
                    if (!bImg && bStyle !== "fig caption"){
                        var bPre = capPrefixLen(bodyPara.contents, capN);
                        if (bPre > 0 && norm(bodyPara.contents).length > capN.length + 2){
                            var bStart = bodyPara.characters[0].index;
                            host.characters.itemByRange(bStart, bStart + bPre - 1).remove();
                        }
                    }
                }
            } catch(eD){}
        } catch (eG) {}
    }

    // ENFORCE: the 'fig caption' style AND every paragraph using it are centred.
    try {
        var _fc = doc.paragraphStyles.itemByName("fig caption");
        if (_fc.isValid){ try { _fc.justification = Justification.CENTER_ALIGN; } catch(eFS){} }
        for (var si2 = 0; si2 < doc.stories.length; si2++){
            var _ps = doc.stories[si2].paragraphs;
            for (var pj = 0; pj < _ps.length; pj++){
                try {
                    var _nm = ""; try { _nm = _ps[pj].appliedParagraphStyle.name; } catch(e1){}
                    if (_nm === "fig caption"){ _ps[pj].justification = Justification.CENTER_ALIGN; }
                } catch(e2){}
            }
        }
    } catch(eEnf){}
    fixed.toString();
    """
    js = js.replace("__CAP__", cap_literal)
    return app.DoScript(js, JS)

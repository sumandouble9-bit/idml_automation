"""
Apply EPUB captions to already-injected images (runs AFTER injection, before
export). For every anchored body image whose file name has an EPUB caption:

  1. remove any nearby paragraph (just above or just below the image) whose text
     already equals that caption -- this clears the original caption whether it
     sat above the image, was moved below by the injector, or was interleaved in
     a packed multi-image paragraph (no duplicate caption is left),
  2. insert the EPUB caption as a fresh paragraph directly BELOW the image, and
  3. style it as the "fig caption" (centred, 9pt, all-caps words 8pt, non-bold).

Images are never detached, so nothing overlaps text. Returns the count applied.
"""

import win32com.client

JS = 1246973031


def apply_captions(app, caption_map):
    if not caption_map:
        return "0"

    # Build a JS object literal { "imageNNN.jpg": "caption", ... }.
    def esc(s):
        return (s.replace("\\", "\\\\").replace('"', '\\"')
                 .replace("\r", " ").replace("\n", " "))
    items = ",".join('"%s":"%s"' % (esc(k), esc(v)) for k, v in caption_map.items())
    cap_literal = "{" + items + "}"

    js = r"""
    var CAP = __CAP__;
    var doc = app.activeDocument;
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    function norm(s){ return String(s).replace(/[^a-zA-Z0-9]/g, "").toLowerCase(); }
    function figStyle(){
        var st = doc.paragraphStyles.itemByName("fig caption");
        if (!st.isValid){
            st = doc.paragraphStyles.add({name:"fig caption"});
            try { st.justification = Justification.CENTER_ALIGN; } catch(e){}
            try { st.pointSize = 9; } catch(e){}
        }
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

    var applied = 0;
    var graphics = doc.allGraphics;
    for (var gi = 0; gi < graphics.length; gi++){
        try {
            var g = graphics[gi];
            var name = g.itemLink ? g.itemLink.name : "";
            if (isLogo(name)) continue;
            var cap = CAP[name];
            if (!cap) continue;
            var capN = norm(cap);

            var fr = g.parent;
            var ip = fr.parent;
            if (!ip || !ip.paragraphs) continue;
            var imgPara = ip.paragraphs[0];
            var host = imgPara.parentStory;

            // A paragraph counts as "the original caption" if its text equals the
            // EPUB caption, or is a shorter prefix of it (the IDML often has a short
            // label like "Fig. 8." while the EPUB caption is the full sentence).
            function capMatch(txt){
                var o = norm(txt);
                if (o.length === 0) return false;
                if (o === capN) return true;                                 // identical caption
                // A shorter figure label that is a PREFIX of the caption ("Fig. 8." vs
                // the full sentence). Bounded so it can only match a short label.
                if (o.length >= 3 && o.length < capN.length && capN.indexOf(o) === 0) return true;
                // The caption plus a little trailing punctuation/space (o starts with the
                // caption and is only slightly longer). NOT a general "contains" test:
                // a body paragraph that merely mentions the caption text must never match,
                // or the whole paragraph would be deleted as if it were the caption.
                if (capN.length >= 4 && o.length <= capN.length + 4 && o.indexOf(capN) === 0) return true;
                return false;
            }

            // 0) If the EPUB caption is ALREADY the paragraph directly below this
            //    image (the injector may have placed it from an inline caption),
            //    leave it exactly where it is and only (re)style it. Do NOT run the
            //    remove/re-insert dance: when two images share the SAME caption on
            //    one spread (e.g. a split figure image097 "A-M" + image098 "N-Z",
            //    both captioned "Morse and Semaphore Codes."), the removal pass of
            //    the second image would otherwise delete the FIRST image's correct
            //    caption, leaving one image with no caption.
            var alreadyBelow = false;
            try {
                var _last0 = imgPara.characters[-1].index;
                if (_last0 + 1 < host.characters.length){
                    var _bp = host.characters[_last0 + 1].paragraphs[0];
                    var _bImg = false;
                    try { _bImg = (_bp.allPageItems.length > 0); } catch(e0a){}
                    if (!_bImg && capMatch(_bp.contents)){
                        styleCaption(_bp);
                        alreadyBelow = true;
                    }
                }
            } catch(e0){}
            if (alreadyBelow){ applied++; continue; }

            // 1) Remove EVERY matching caption paragraph immediately above/below the
            //    image (split figures repeat the same caption, so there can be several).
            for (var pass = 0; pass < 12; pass++){
                var removed = false;
                var first = imgPara.characters[0].index;
                var last  = imgPara.characters[-1].index;
                // below
                if (last + 1 < host.characters.length){
                    var below = host.characters[last + 1].paragraphs[0];
                    var hasImgBelow = false;
                    try { hasImgBelow = (below.allPageItems.length > 0); } catch(eB){}
                    if (!hasImgBelow && capMatch(below.contents)){ below.remove(); removed = true; }
                }
                if (removed) { imgPara = ip.paragraphs[0]; continue; }
                // above
                first = imgPara.characters[0].index;
                if (first >= 1){
                    var above = host.characters[first - 1].paragraphs[0];
                    var hasImgAbove = false;
                    try { hasImgAbove = (above.allPageItems.length > 0); } catch(eA){}
                    if (!hasImgAbove && capMatch(above.contents)){ above.remove(); removed = true; }
                }
                if (!removed) break;
                imgPara = ip.paragraphs[0];
            }

            // 2) Insert the caption directly AFTER the anchored image character.
            //    Anchoring the insertion to the image character (not to a computed
            //    story offset) guarantees it lands right below the image and can
            //    never drift past a following body paragraph.
            var anchorChar = fr.parent;                 // the anchored-object character
            anchorChar.insertionPoints[-1].contents = "\r" + cap;

            // 3) Style the freshly inserted caption paragraph (the paragraph right
            //    after the image paragraph).
            var imgP = anchorChar.paragraphs[0];
            var capIdx = imgP.characters[-1].index + 1;
            if (capIdx < host.characters.length){
                styleCaption(host.characters[capIdx].paragraphs[0]);
            }
            applied++;
        } catch (eG) {}
    }
    applied.toString();
    """
    js = js.replace("__CAP__", cap_literal)
    return app.DoScript(js, JS)


def cleanup_caption_artifacts(app, caption_map):
    """SEPARATE final pass. Generic (driven only by each book's own EPUB captions,
    nothing hardcoded). After the caption passes, a packed figure can leave two
    artifacts near an image:

      1. a DUPLICATE caption paragraph (the same caption text twice), or
      2. a caption FUSED onto the front of the following body paragraph, e.g.
         "Morse and Semaphore Codes.Every scout ought to learn..." — with that
         whole paragraph wrongly styled as a caption.

    For every image that has an EPUB caption, this looks at the few paragraphs just
    below it and, using that image's caption text as the key:
      * removes an exact-duplicate caption paragraph, and
      * for a paragraph that STARTS with the caption but continues into body text,
        strips the caption prefix and restores the paragraph to the body style
        (taken from the paragraph that follows — so it adapts to each book).

    It only ever touches a paragraph that matches the image's own caption, so a
    normal caption or body paragraph is never altered. Returns the count fixed.
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
    function norm(s){ return String(s).replace(/[^a-zA-Z0-9]/g, "").toLowerCase(); }
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
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
            if (capN.length < 4) continue;

            var anchorChar = g.parent.parent;
            var imgPara = anchorChar.paragraphs[0];
            var host = imgPara.parentStory;
            var ci = imgPara.characters[-1].index + 1;
            var capSeen = 0;

            for (var step = 0; step < 6 && ci < host.characters.length; step++){
                var para = host.characters[ci].paragraphs[0];
                var hasImg = false;
                try { hasImg = (para.allPageItems.length > 0); } catch(eI){}
                if (hasImg) break;                       // reached the next image

                var pn = norm(para.contents);
                var startIdx = para.characters[0].index;
                var endNext  = para.characters[-1].index + 1;

                if (pn === capN){                        // an exact caption paragraph
                    capSeen++;
                    if (capSeen > 1){                    // a duplicate -> remove it
                        para.remove(); fixed++;
                        ci = startIdx;                   // next paragraph now sits here
                        continue;
                    }
                    ci = endNext; continue;              // the legitimate caption; keep it
                } else if (pn.length > capN.length && pn.indexOf(capN) === 0){
                    // caption text fused onto the front of the following (body) paragraph
                    var full = para.contents;
                    var matchLen = 0;
                    if (full.indexOf(cap) === 0){
                        matchLen = cap.length;
                    } else if (full.toLowerCase().indexOf(cap.toLowerCase()) === 0){
                        matchLen = cap.length;
                    }
                    if (matchLen > 0){
                        var followStyle = null;
                        try {
                            if (endNext < host.characters.length) {
                                var candidate = host.characters[endNext].paragraphs[0].appliedParagraphStyle;
                                if (candidate && candidate.isValid) {
                                    var cName = candidate.name.toLowerCase();
                                    if (cName.indexOf("chapter") === -1 && cName.indexOf("heading") === -1 && cName.indexOf("title") === -1 && cName.indexOf("toc") === -1) {
                                        followStyle = candidate;
                                    }
                                }
                            }
                        } catch(eF){}
                        para.characters.itemByRange(0, matchLen - 1).remove();   // strip the caption prefix
                        var np = host.characters[startIdx].paragraphs[0];
                        try {
                            if (followStyle && followStyle.isValid) {
                                np.appliedParagraphStyle = followStyle;
                            } else {
                                var bs = doc.paragraphStyles.itemByName("body_text");
                                if (bs.isValid) np.appliedParagraphStyle = bs;
                            }
                        } catch(eS){}
                        fixed++;
                    }
                    break;                                // handled this image
                } else {
                    break;                                // a normal body paragraph -> stop
                }
            }
        } catch (eG) {}
    }
    fixed.toString();
    """
    js = js.replace("__CAP__", cap_literal)
    return app.DoScript(js, JS)


def normalize_captions_below_images(app, caption_map):
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


def ensure_split_figure_captions(app, caption_map):
    """SEPARATE pass (does not change apply_captions): for a split figure whose two
    pieces sit one directly after the other (e.g. image097 then image098, both
    captioned "Morse and Semaphore Codes."), the FIRST piece has no caption below
    it because the next paragraph is the second image. This inserts the missing
    caption directly below any captioned image whose next paragraph is another
    image, so BOTH halves get their caption. It never removes anything and never
    double-inserts (once a caption sits below, the next paragraph is no longer an
    image). Returns the number of captions inserted.
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
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    function figStyle(){
        var st = doc.paragraphStyles.itemByName("fig caption");
        if (!st.isValid){ st = doc.paragraphStyles.add({name:"fig caption"});
            try { st.justification = Justification.CENTER_ALIGN; } catch(e){}
            try { st.pointSize = 9; } catch(e){} }
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
    var inserted = 0;
    var graphics = doc.allGraphics;
    for (var gi = 0; gi < graphics.length; gi++){
        try {
            var g = graphics[gi];
            var name = g.itemLink ? g.itemLink.name : "";
            if (isLogo(name)) continue;
            var cap = CAP[name];
            if (!cap) continue;

            var anchorChar = g.parent.parent;                 // the anchored-object character
            var imgPara = anchorChar.paragraphs[0];
            var host = imgPara.parentStory;
            var lastIdx = imgPara.characters[-1].index;
            if (lastIdx + 1 >= host.characters.length) continue;

            var belowP = host.characters[lastIdx + 1].paragraphs[0];
            var belowIsImg = false;
            try { belowIsImg = (belowP.allPageItems.length > 0); } catch(eB){}
            if (!belowIsImg) continue;                        // caption already there / normal case

            // Next paragraph is another image -> this image has no caption below it.
            anchorChar.insertionPoints[-1].contents = "\r" + cap;
            var capIdx = anchorChar.paragraphs[0].characters[-1].index + 1;
            if (capIdx < host.characters.length){
                styleCaption(host.characters[capIdx].paragraphs[0]);
            }
            inserted++;
        } catch (eG) {}
    }
    inserted.toString();
    """
    js = js.replace("__CAP__", cap_literal)
    return app.DoScript(js, JS)

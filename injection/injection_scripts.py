"""ExtendScript (InDesign JS) builders used by the EPUB injection pass; each returns the script text for app.DoScript."""


def inline_leading_js():
    """Reserve each body image's full height inline so a tall image never overlaps the text."""
    return r"""
    var d = app.activeDocument;
    var n = 0;
    function isLogoName(nm){ if(!nm) return false; var u=nm.toUpperCase(); return u.indexOf('LEAF-BOUND')>=0 || u.indexOf('LOGO')>=0; }
    for (var i = 0; i < d.allGraphics.length; i++){
        try {
            var g = d.allGraphics[i];
            if (g.itemLink && isLogoName(g.itemLink.name)) continue;
            var frm = g.parent;
            var inCell = false;
            try { inCell = (frm.parent && frm.parent.constructor.name === "Cell"); } catch (eIC){}
            if (inCell) continue;
            var bb = frm.geometricBounds;
            var imgH = bb[2] - bb[0];
            if (imgH <= 0) continue;
            try { var aos = frm.anchoredObjectSettings; aos.anchoredPosition = AnchorPosition.INLINE_POSITION; } catch (eAos){}
            try {
                var par = frm.parent.paragraphs[0];
                par.leading = imgH + 4;
                par.spaceBefore = 6;
                par.spaceAfter = 0;
                par.justification = Justification.CENTER_ALIGN;
                n++;
            } catch (ePar){}
            try { frm.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch (eTW){}
        } catch (eG){}
    }
    "INLINE_LEADING=" + n;
    """


def force_inline_js():
    """Force every body image to inline anchoring, centered (kept for reference, normally unused)."""
    return r"""
    var d = app.activeDocument;
    var n = 0;
    function isLogoName(nm){ if(!nm) return false; var u=nm.toUpperCase(); return u.indexOf('LEAF-BOUND')>=0 || u.indexOf('LOGO')>=0; }
    for (var i = 0; i < d.allGraphics.length; i++){
        try {
            var g = d.allGraphics[i];
            if (g.itemLink && isLogoName(g.itemLink.name)) continue;
            var frm = g.parent;
            var inCell = false;
            try { inCell = (frm.parent && frm.parent.constructor.name === "Cell"); } catch (eIC){}
            if (inCell) continue;
            try { var aos = frm.anchoredObjectSettings; aos.anchoredPosition = AnchorPosition.INLINE_POSITION; n++; } catch (eAos){}
            try { frm.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch (eTW){}
            try {
                if (frm.parent && frm.parent.paragraphs && frm.parent.paragraphs.length > 0){
                    frm.parent.paragraphs[0].justification = Justification.CENTER_ALIGN;
                }
            } catch (eJ){}
        } catch (eG){}
    }
    "FORCED_INLINE=" + n;
    """


def split_packed_js(keep_js):
    """Split a paragraph packing several image placeholders into one paragraph per placeholder."""
    js = r'''
    var doc = app.activeDocument;
    var KEEP = __KEEP__;
    function countPH(s){ var c=0, re=/###Insert.*?here###/g; while(re.exec(s)!==null) c++; return c; }
    function phNames(s){ var out=[], re=/###Insert\s+(image\d+)/gi, m; while((m=re.exec(s))!==null) out.push(m[1].toLowerCase()); return out; }
    function isKeep(ns){ if(ns.length<2) return false; for(var i=0;i<ns.length-1;i++){ var k=[ns[i],ns[i+1]].sort().join("|"); for(var j=0;j<KEEP.length;j++){ if(KEEP[j]==k) return true; } } return false; }
    app.findGrepPreferences = NothingEnum.nothing;
    app.findGrepPreferences.findWhat = "###Insert.*?here###";
    var matches = doc.findGrep();
    app.findGrepPreferences = NothingEnum.nothing;
    var seen = {}, targets = [];
    for (var i = 0; i < matches.length; i++){
        try {
            var p = matches[i].paragraphs[0], st = p.parentStory;
            var key = st.id + ":" + p.characters[0].index;
            if (seen[key]) continue; seen[key] = true;
            if (countPH(p.contents) >= 2) targets.push({ sid: st.id, idx: p.characters[0].index });
        } catch (e) {}
    }
    targets.sort(function(a, b){ return b.idx - a.idx; });   // last-to-first so edits don't shift others
    var splitCount = 0;
    for (var t = 0; t < targets.length; t++){
        try {
            var story = doc.stories.itemByID(targets[t].sid);
            var para  = story.characters[targets[t].idx].paragraphs[0];
            var raw = para.contents.replace(/[\r\n]+$/, "");
            if (isKeep(phNames(raw))) {
                // Side-by-side pair: rebuild the SOURCE's borderless N-column
                // table so the images land in CELLS (which never overlap body
                // text), one placeholder per cell. Placement then fills each cell
                // and the downstream table/cell-image passes fit + centre them.
                try {
                    var phre = /###Insert.*?here###/g, mm, phs = [];
                    while ((mm = phre.exec(raw)) !== null) phs.push(mm[0]);
                    if (phs.length >= 2) {
                        var hostW = 0;
                        try {
                            var ptf = para.parentTextFrames;
                            if (ptf && ptf.length > 0) { var gbh = ptf[0].geometricBounds; hostW = gbh[3] - gbh[1]; }
                        } catch (eHW) {}
                        para.contents = phs.join("\t");
                        var fresh = story.characters[targets[t].idx].paragraphs[0];
                        var tbl = fresh.texts[0].convertToTable("\t", "\r");
                        try {
                            tbl.cells.everyItem().topEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().bottomEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().leftEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().rightEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().topInset = 0;
                            tbl.cells.everyItem().bottomInset = 0;
                            tbl.cells.everyItem().leftInset = 0;
                            tbl.cells.everyItem().rightInset = 0;
                            tbl.cells.everyItem().verticalJustification = VerticalJustification.CENTER_ALIGN;
                        } catch (eB) {}
                        try {
                            if (hostW > 0 && tbl.columns.length > 0) {
                                var eachW = hostW / tbl.columns.length;
                                for (var ci = 0; ci < tbl.columns.length; ci++) tbl.columns[ci].width = eachW;
                            }
                        } catch (eCW) {}
                        splitCount++;
                    }
                } catch (eT) {}
                continue;   // side-by-side pair handled as a table
            }
            var re = /###Insert.*?here###/g, m, prev = 0, segs = [];
            while ((m = re.exec(raw)) !== null){ segs.push(raw.substring(prev, m.index) + m[0]); prev = re.lastIndex; }
            var trailing = raw.substring(prev);
            if (segs.length > 0 && trailing.replace(/\s+/g, "").length > 0) segs[segs.length - 1] += trailing;
            if (segs.length >= 2){ para.contents = segs.join("\r"); splitCount++; }
        } catch (e2) {}
    }
    splitCount.toString();
    '''
    return js.replace("__KEEP__", keep_js)


def relocate_labels_js():
    """Normalise short figure-label paragraphs (e.g. 'Fig. 1') into centred captions below the image."""
    return r'''
    var doc = app.activeDocument;
    var LABEL = /^(figs?|figure|img|image)\.?\s*\d+\.?$/i;
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
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
            // Plain regular text, no inherited character style / bold.
            try { p.appliedCharacterStyle = doc.characterStyles[0]; } catch(eC){}
            try { p.fontStyle = "Regular"; } catch(eF){}
            // Baseline 9pt; ALL-CAPS words -> 8pt.
            p.pointSize = 9;
            var ws = p.words;
            for (var i = 0; i < ws.length; i++) {
                var t = ws[i].contents;
                if ((t === t.toUpperCase()) && (t !== t.toLowerCase())) ws[i].pointSize = 8;
            }
        } catch(e){}
    }
    var count = 0;
    var graphics = doc.allGraphics;
    for (var g = 0; g < graphics.length; g++){
        try {
            var gr = graphics[g];
            if (gr.itemLink && isLogo(gr.itemLink.name)) continue;
            var frame = gr.parent;
            if (!frame || !frame.parent) continue;
            var imgPara = frame.parent.paragraphs[0];
            var host = imgPara.parentStory;
            var imgFirst = imgPara.characters[0].index;

            // 1) Label directly ABOVE the image -> move it BELOW, then style.
            if (imgFirst >= 1){
                var prevPara = host.characters[imgFirst - 1].paragraphs[0];
                var ptxt = prevPara.contents.replace(/[\r\n]+/g, "").replace(/^\s+|\s+$/g, "");
                if (LABEL.test(ptxt)){
                    prevPara.move(LocationOptions.AFTER, imgPara);
                    var ip = frame.parent.paragraphs[0];
                    var lastIdx = ip.characters[-1].index;
                    if (lastIdx + 1 < host.characters.length){
                        styleCaption(host.characters[lastIdx + 1].paragraphs[0]);
                    }
                    count++;
                    continue;
                }
            }

            // 2) Label already directly BELOW the image -> just style it.
            var lastIdx2 = imgPara.characters[-1].index;
            if (lastIdx2 + 1 < host.characters.length){
                var nextPara = host.characters[lastIdx2 + 1].paragraphs[0];
                var ntxt = nextPara.contents.replace(/[\r\n]+/g, "").replace(/^\s+|\s+$/g, "");
                if (LABEL.test(ntxt)){
                    styleCaption(nextPara);
                    count++;
                }
            }
        } catch (eG) {}
    }
    count.toString();
    '''


def open_doc_js(clean_idml_path):
    """Open the given IDML with redraw and smart text reflow disabled."""
    return f"""
    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
    app.scriptPreferences.enableRedraw = false;
    var idmlPath = "{clean_idml_path}";
    var doc = app.open(new File(idmlPath));

    try {{ doc.textPreferences.smartTextReflow = false; }} catch (eSTR) {{}}
    try {{ app.textPreferences.smartTextReflow = false; }} catch (eSTRa) {{}}
    """


def find_all_placeholders_js():
    """Return every '###Insert ... here###' placeholder's contents, joined by '|||'."""
    return """
    app.findGrepPreferences = NothingEnum.nothing;
    app.findGrepPreferences.findWhat = "###Insert[\\\\s~s]+.*?[\\\\s~s]+here###";
    var matches = app.activeDocument.findGrep();
    var results = [];
    for (var i = 0; i < matches.length; i++) {
        results.push(matches[i].contents);
    }
    app.findGrepPreferences = NothingEnum.nothing;
    results.join("|||");
    """


def place_image_js(js_name, clean_img_path):
    """Find one placeholder by image name, place the image, and style its caption below it."""
    return f"""
                            var __result = "false";
                            var __name = "{js_name}";
                            // Robust placeholder finder: the literal image name cannot be embedded
                            // directly in the GREP because InDesign findGrep fails to anchor a
                            // literal token across a <Content> run boundary (some placeholders are
                            // split into two runs, e.g. "###Insert " + "imageNNN.jpg here###").
                            // Instead we match the whole "###Insert ... here###" span (which does
                            // cross run boundaries) and filter by name via indexOf.
                            function findPH() {{
                                app.findGrepPreferences = NothingEnum.nothing;
                                app.findGrepPreferences.findWhat = "###Insert.*?here###";
                                var all = app.activeDocument.findGrep();
                                app.findGrepPreferences = NothingEnum.nothing;
                                for (var k = 0; k < all.length; k++) {{
                                    if (all[k].contents.indexOf(__name) !== -1) return all[k];
                                }}
                                return null;
                            }}
                            try {{
                                var match = findPH();

                                if (match !== null) {{
                                    var matchStr = match.contents;

                                    // Side-by-side detection: step1 flattens a 2-column image
                                    // table into ONE paragraph holding two "###Insert" tokens
                                    // (e.g. image064 + image065). Such images must sit on one
                                    // line, not stacked. A paragraph with >=2 placeholders, or
                                    // whose sibling image is already placed while a placeholder
                                    // remains, is a side-by-side group.
                                    var _phPara0 = "";
                                    try {{ _phPara0 = match.paragraphs[0].contents; }} catch (ePP0) {{}}
                                    var _phCount = (_phPara0.match(/###Insert/g) || []).length;
                                    var _sibGraphics = 0;
                                    try {{ _sibGraphics = match.paragraphs[0].allGraphics.length; }} catch (eSG0) {{}}
                                    var sideBySide = (_phCount >= 2) || (_sibGraphics >= 1 && _phPara0.indexOf("###Insert") !== -1);

                                    var maxAllowedWidth = 324;
                                    try {{
                                        if (match.parentTextFrames && match.parentTextFrames.length > 0) {{
                                            var tfBounds = match.parentTextFrames[0].geometricBounds;
                                            maxAllowedWidth = tfBounds[3] - tfBounds[1];
                                        }}
                                    }} catch (eWidth) {{}}

                                    var captionText = "";
                                    try {{
                                        var paraTxt = match.paragraphs[0].contents;
                                        captionText = paraTxt.replace(matchStr, "")
                                                             .replace(/[\\r\\n\\t\\u00A0\\u2028\\uFEFF]/g, " ")
                                                             .replace(/\\s+/g, " ")
                                                             .replace(/^\\s+|\\s+$/g, "");
                                        if (/^(chapter|cap[íi]tulo|book|libro|part|parte|[ivxlcdm0-9]+[\\s\\.\\:\\-])/i.test(captionText)) {{
                                            captionText = "";
                                        }}
                                    }} catch (eCap) {{}}
                                    // A side-by-side sibling placeholder is NOT a caption.
                                    if (sideBySide) {{ captionText = ""; }}

                                    try {{
                                        if (captionText.length > 0) {{
                                            match.paragraphs[0].contents = matchStr + "\\r" + captionText + "\\r";
                                            match = findPH();
                                        }}
                                    }} catch (eRew) {{}}

                                    if (match === null) {{
                                        app.findGrepPreferences = NothingEnum.nothing;
                                        __result = "false";
                                    }} else {{
                                        var _story = match.parentStory;
                                        var _pIdx = match.paragraphs[0].index;

                                        var targetFile = new File("{clean_img_path}");
                                        var placedItems = match.place(targetFile);

                                        if (placedItems && placedItems.length > 0) {{
                                            try {{
                                                var frame = placedItems[0].parent;
                                                frame.fit(FitOptions.FRAME_TO_CONTENT);

                                                try {{ frame.textWrapPreferences.textWrapMode = TextWrapModes.NONE; }} catch (eTW) {{}}

                                                try {{
                                                    var aos = frame.anchoredObjectSettings;
                                                    if (sideBySide) {{
                                                        // Inline so both images flow on the SAME
                                                        // (centered) line, side by side.
                                                        aos.anchoredPosition = AnchorPosition.INLINE_POSITION;
                                                    }} else {{
                                                        // ABOVE_LINE places the image as a block above its anchor
                                                        // line, taking its full height with no baseline/leading
                                                        // interaction (the proven, no-crop placement). spaceBefore/
                                                        // spaceAfter give a small gap; centring is via the anchored
                                                        // object settings below.
                                                        aos.anchoredPosition         = AnchorPosition.ABOVE_LINE;
                                                        aos.spaceBefore              = 6;
                                                        aos.spaceAfter               = 0;
                                                        aos.horizontalAlignment      = HorizontalAlignment.CENTER_ALIGN;
                                                        aos.horizontalReferencePoint = AnchoredRelativeTo.COLUMN_EDGE;
                                                    }}
                                                }} catch (eAnc) {{}}

                                                try {{
                                                    // Leave a 4pt gap on the left and right of every image so it
                                                    // never touches the column margins (max width = column - 8pt).
                                                    var SIDE_PAD = 4;
                                                    var hostTF = (match.parentTextFrames && match.parentTextFrames.length > 0) ? match.parentTextFrames[0] : null;
                                                    var maxW = maxAllowedWidth - 2 * SIDE_PAD;
                                                    var maxH = 450;
                                                    if (hostTF) {{
                                                        var tb = hostTF.geometricBounds;
                                                        maxW = (tb[3] - tb[1]) - 2 * SIDE_PAD;
                                                        maxH = (tb[2] - tb[0]) * 0.90;
                                                    }}
                                                    // Each side-by-side image gets half the column
                                                    // (minus a 10pt inter-image gap) so the pair fits.
                                                    if (sideBySide) {{ maxW = (maxW - 10) / 2; }}
                                                    var gb = frame.geometricBounds;
                                                    var fw = gb[3] - gb[1];
                                                    var fh = gb[2] - gb[0];
                                                    var scale = 1.0;
                                                    if (fw > maxW) scale = Math.min(scale, maxW / fw);
                                                    if (fh > maxH) scale = Math.min(scale, maxH / fh);
                                                    if (scale < 1.0) {{
                                                        frame.geometricBounds = [gb[0], gb[1], gb[0] + fh * scale, gb[1] + fw * scale];
                                                        frame.fit(FitOptions.CONTENT_TO_FRAME);
                                                    }}
                                                }} catch (eFit) {{}}

                                                try {{ frame.parent.paragraphs[0].justification = Justification.CENTER_ALIGN; }} catch (eP1) {{}}

                                                // Figure caption = the inline text that was moved BELOW the
                                                // image. It only exists when the placeholder had image + text
                                                // (captionText.length > 0). Such a paragraph gets the dedicated
                                                // "fig caption" paragraph style (created once per doc: centred,
                                                // 9pt base). ALL-CAPS words are then overridden to 8pt (per-word
                                                // sizing cannot live in a paragraph style).
                                                try {{
                                                    if (captionText.length > 0) {{
                                                        var _doc = app.activeDocument;
                                                        // Re-derive the caption paragraph AFTER placement from the
                                                        // anchored image frame. NOTE: paragraph.index is a CHARACTER
                                                        // offset (not a paragraph ordinal), so paragraphs[idx+1] is
                                                        // wrong; instead we step one character past the image
                                                        // paragraph's end and read that paragraph.
                                                        var _imgPara = frame.parent.paragraphs[0];
                                                        var _host = _imgPara.parentStory;
                                                        var _lastChar = _imgPara.characters[-1].index;
                                                        if ((_lastChar + 1) < _host.characters.length) {{
                                                            var figStyle = _doc.paragraphStyles.itemByName("fig caption");
                                                            if (!figStyle.isValid) {{
                                                                figStyle = _doc.paragraphStyles.add({{name: "fig caption"}});
                                                                try {{ figStyle.justification = Justification.CENTER_ALIGN; }} catch (eFJ) {{}}
                                                                try {{ figStyle.pointSize = 9; }} catch (eFS) {{}}
                                                            }}

                                                            var capPara = _host.characters[_lastChar + 1].paragraphs[0];
                                                            var sName = capPara.appliedParagraphStyle.name.toLowerCase();
                                                            var isHeading = (sName.indexOf("chapter") !== -1 || sName.indexOf("chap") !== -1 || sName.indexOf("sub-heading") !== -1);
                                                            if (!isHeading) {{
                                                                capPara.appliedParagraphStyle = figStyle;
                                                                capPara.justification = Justification.CENTER_ALIGN;
                                                                // Strip any inherited character style / bold so the
                                                                // whole caption is plain regular text (the source often
                                                                // has the title in a "boldtext" character style).
                                                                try {{ capPara.appliedCharacterStyle = _doc.characterStyles[0]; }} catch (eCS) {{}}
                                                                try {{ capPara.fontStyle = "Regular"; }} catch (eFSr) {{}}
                                                                // Baseline 9pt (covers spaces/punctuation), then bump
                                                                // ALL-CAPS words to 8pt.
                                                                capPara.pointSize = 9;
                                                                var capWords = capPara.words;
                                                                for (var cw = 0; cw < capWords.length; cw++) {{
                                                                    var wtext = capWords[cw].contents;
                                                                    var isAllCaps = (wtext === wtext.toUpperCase()) && (wtext !== wtext.toLowerCase());
                                                                    if (isAllCaps) capWords[cw].pointSize = 8;
                                                                }}
                                                            }}
                                                        }}
                                                    }}
                                                }} catch (eP2) {{}}
                                            }} catch (ePost) {{}}
                                        }}
                                        app.findGrepPreferences = NothingEnum.nothing;
                                        __result = "true";
                                    }}
                                }} else {{
                                    app.findGrepPreferences = NothingEnum.nothing;
                                    __result = "false";
                                }}
                            }} catch (topErr) {{
                                try {{ app.findGrepPreferences = NothingEnum.nothing; }} catch (e){{}}
                                __result = "err:" + topErr.message;
                            }}
                            __result;
                            """


def fix_nbsp_js():
    """Normalise non-breaking spaces to regular spaces document-wide."""
    return """
                var doc = app.activeDocument;
                app.findGrepPreferences = NothingEnum.nothing;
                app.changeGrepPreferences = NothingEnum.nothing;
                app.findGrepPreferences.findWhat = "~S|~s";
                app.changeGrepPreferences.changeTo = " ";
                var changed = doc.changeGrep();
                app.findGrepPreferences = NothingEnum.nothing;
                app.changeGrepPreferences = NothingEnum.nothing;
                changed.length + "";
                """


def hyphenate_body_js():
    """Enable hyphenation and keep-together behaviour across paragraph styles; chapters break to next page."""
    return r"""
                var doc = app.activeDocument;
                var styles = doc.allParagraphStyles;
                var n = 0;
                for (var i = 0; i < styles.length; i++){
                    try { styles[i].hyphenation = true; } catch(e){}
                    try { styles[i].hyphenateCapitalizedWords = true; } catch(e){}
                    var sName = styles[i].name.toLowerCase();
                    if ((sName.indexOf("chapter") !== -1 || sName.indexOf("chap") !== -1) && sName.indexOf("after") === -1) {
                        try { styles[i].startParagraph = StartParagraph.NEXT_PAGE; } catch(e1){
                            try { styles[i].startParagraph = StartParagraph.nextPage; } catch(e2){}
                        }
                        try { styles[i].keepAllLinesTogether = true; } catch(e){}
                        try { styles[i].keepLinesTogether = true; } catch(e){}
                        try { styles[i].keepWithNext = 2; } catch(e){}
                    }
                    if (sName.indexOf("after") !== -1) {
                        try { styles[i].startParagraph = StartParagraph.ANYWHERE; } catch(e1){
                            try { styles[i].startParagraph = StartParagraph.anywhere; } catch(e2){}
                        }
                    }
                    if (sName.indexOf("sub-heading") !== -1 || sName.indexOf("heading") !== -1) {
                        try { styles[i].keepWithNext = 2; } catch(e){}
                        try { styles[i].keepLinesTogether = true; } catch(e){}
                    }
                    if (sName.indexOf("body") !== -1 || sName.indexOf("normal") !== -1 || sName.indexOf("basic") !== -1 || sName.indexOf("noindent") !== -1) {
                        try { styles[i].keepLinesTogether = true; } catch(e){}
                        try { styles[i].keepAllLinesTogether = false; } catch(e){}
                        try { styles[i].keepFirstAndLastLines = true; } catch(e){}
                        try { styles[i].minLinesAtStart = 2; } catch(e){}
                        try { styles[i].minLinesAtEnd = 2; } catch(e){}
                    }
                    n++;
                }


                n + "";
                """


def resolve_overset_js():
    """Grow the body story by adding margin-bounded pages, shrinking oversized images that jam the flow."""
    return """
                var doc = app.activeDocument;
                var oldRuler = doc.viewPreferences.rulerOrigin;
                doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
                var pageH = doc.documentPreferences.pageHeight;
                var pageW = doc.documentPreferences.pageWidth;
                var pagesAdded = 0;
                var jams = [];

                var HEIGHT_STEP = 72;   // grow ~1 line-block per step
                var WIDTH_STEP  = 12;   // gentle width relief for over-wide unbreakable lines
                var MAX_STEPS   = 40;   // up to ~40 * 72pt (~5 pages) of forced growth

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

                function describeStuck(frame, story) {
                    var info = { idx: -1, style: "", text: "" };
                    try {
                        var prev = frame.previousTextFrame;
                        info.idx = prev.characters[-1].index + 1;
                        var par = story.characters[info.idx].paragraphs[0];
                        info.style = par.appliedParagraphStyle.name;
                        var t = par.contents.replace(/[\\r\\n\\t]+/g, " ");
                        info.text = (t.length > 140) ? t.substring(0, 140) + "..." : t;
                    } catch (e) {}
                    return info;
                }

                // Shrink the oversized anchored image that is jamming the flow so a
                // margin-sized frame can accept it. The text frame is NEVER grown past
                // the page margins; instead the image is scaled down proportionally
                // until it fits, so text keeps flowing continuously and nothing is lost.
                // Returns true if an image near the stuck index was found and shrunk.
                function shrinkStuckGraphic(story, idx, frac) {
                    try {
                        var gs = doc.allGraphics;
                        var best = null, bestDist = 1e9;
                        for (var gi = 0; gi < gs.length; gi++) {
                            try {
                                var fr = gs[gi].parent;
                                var anc = fr.parent;
                                var ps = null;
                                try { ps = anc.parentStory; } catch (e1) { continue; }
                                if (!ps || ps.id !== story.id) continue;
                                var ci = -1;
                                try { ci = anc.index; } catch (e2) { continue; }
                                var d = Math.abs(ci - idx);
                                if (d < bestDist) { bestDist = d; best = fr; }
                            } catch (eIn) {}
                        }
                        if (best && bestDist <= 4) {
                            var gb = best.geometricBounds;
                            var h = gb[2] - gb[0], w = gb[3] - gb[1];
                            if (h > 24 && w > 24) {
                                best.geometricBounds = [gb[0], gb[1], gb[0] + h * frac, gb[1] + w * frac];
                                try { best.fit(FitOptions.CONTENT_TO_FRAME); } catch (eF) {}
                                return true;
                            }
                        }
                    } catch (eTop) {}
                    return false;
                }

                for (var i = 0; i < doc.stories.length; i++) {
                    var s = doc.stories[i];
                    s.recompose();
                    if (s.textContainers.length === 0) continue;
                    var lastFrame = s.textContainers[s.textContainers.length - 1];
                    if (lastFrame.constructor.name !== "TextFrame") continue;

                    // Standalone front-matter stories (Title on Page 1, Copyright on Page 2)
                    // must NEVER have pages added at the end of the document.
                    // Only the flowing body text story should spawn pages.
                    try {
                        var firstContainer = s.textContainers[0];
                        if (firstContainer.parentPage) {
                            var pNum = parseInt(firstContainer.parentPage.name, 10);
                            if (pNum === 1 || pNum === 2) continue;
                            if (s.textContainers.length === 1 && (pNum <= 6 || s.characters.length < 2000)) continue;
                        }
                    } catch (eFm) {}

                    var guard = 0;
                    while (lastFrame.overflows) {
                        guard++;
                        if (guard > 30000) { jams.push("ABORT|story " + i + "|guard limit reached"); break; }

                        var newPage = doc.pages.add();
                        pagesAdded++;
                        var newFrame = newPage.textFrames.add();
                        newFrame.geometricBounds = frameGeom(newPage);
                        lastFrame.nextTextFrame = newFrame;
                        lastFrame = newFrame;
                        s.recompose();

                        if (lastFrame.characters.length === 0 && lastFrame.overflows) {
                            // JAM: the next content unit cannot fit or break on a normal page.
                            var stuck = describeStuck(lastFrame, s);

                            // ESCAPE WITHOUT GROWING THE FRAME: the frame stays exactly at
                            // the page margin bounds. The jam is almost always a single
                            // anchored image taller than the column; shrink that image step
                            // by step until the margin-sized frame accepts it, so the text
                            // keeps flowing continuously and nothing is lost. The frame is
                            // never enlarged beyond the margin guides.
                            var steps = 0;
                            while (lastFrame.characters.length === 0 && lastFrame.overflows && steps < MAX_STEPS) {
                                var shrank = shrinkStuckGraphic(s, stuck.idx, 0.90);
                                if (!shrank) break;   // nothing to shrink -> genuine non-image jam
                                steps++;
                                s.recompose();
                            }
                            var fh = (lastFrame.geometricBounds[2] - lastFrame.geometricBounds[0]);

                            if (lastFrame.characters.length === 0 && lastFrame.overflows) {
                                // Still unplaceable after shrinking: capture the remaining overset text.
                                var remaining = "";
                                try {
                                    var start = lastFrame.previousTextFrame.characters[-1].index + 1;
                                    remaining = s.contents.substring(start);
                                    if (remaining.length > 4000) remaining = remaining.substring(0, 4000) + " ...[truncated]";
                                    remaining = remaining.replace(/[\\r\\n\\t]+/g, " ");
                                } catch (e) {}
                                jams.push("UNRESOLVED|page~" + doc.pages.length + "|storyIdx=" + stuck.idx +
                                          "|style=" + stuck.style + "|stuck=[" + stuck.text + "]|REMAINING_TEXT=[" + remaining + "]");
                                break; // cannot proceed on this thread; stop to avoid an infinite loop
                            } else {
                                jams.push("SHRUNK|page~" + doc.pages.length + "|storyIdx=" + stuck.idx +
                                          "|style=" + stuck.style + "|frameHeight=" + fh.toFixed(0) + "pt|content=[" + stuck.text + "]");
                            }
                        }
                    }
                }
                doc.viewPreferences.rulerOrigin = oldRuler;

                var oversetLeft = 0;
                for (var q = 0; q < doc.stories.length; q++) {
                    var cs = doc.stories[q].textContainers;
                    for (var j = 0; j < cs.length; j++) { if (cs[j].overflows) oversetLeft++; }
                }
                "PAGES=" + pagesAdded + "|OVERSET=" + oversetLeft + "|JAMS=" + jams.length + "\\n" + jams.join("\\n");
                """


def center_all_js():
    """Center every non-inline, non-cell body graphic within its column and center its paragraph."""
    return """
                var d = app.activeDocument;
                var fixed = 0;
                function isLogoName(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf('LEAF-BOUND')>=0 || u.indexOf('LOGO')>=0; }
                for (var i = 0; i < d.allGraphics.length; i++) {
                    try {
                        var g = d.allGraphics[i];
                        if (g.itemLink && isLogoName(g.itemLink.name)) continue;
                        var frm = g.parent;
                        var _skipFloat = false;
                        try { if (frm.label == "INLINE_SINGLE_IMG") _skipFloat = true; } catch (eLbl) {}
                        var _inCellSweep = false;
                        try { _inCellSweep = (frm.parent && frm.parent.constructor.name === "Cell"); } catch (eIC2) {}
                        try {
                            var aosChk = frm.anchoredObjectSettings;
                            if (!_inCellSweep && aosChk.anchoredPosition == AnchorPosition.INLINE_POSITION) _skipFloat = true;
                        } catch (ePos) {}
                        if (!_skipFloat) {
                            try {
                                var aos = frm.anchoredObjectSettings;
                                aos.horizontalAlignment      = HorizontalAlignment.CENTER_ALIGN;
                                aos.horizontalReferencePoint = AnchoredRelativeTo.COLUMN_EDGE;
                            } catch (eA) {}
                            try { frm.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch (eTW) {}
                        }
                        try {
                            if (frm.parent && frm.parent.paragraphs && frm.parent.paragraphs.length > 0) {
                                frm.parent.paragraphs[0].justification = Justification.CENTER_ALIGN;
                                fixed++;
                            }
                        } catch (eP) {}
                    } catch (eG) {}
                }
                "centered " + fixed + " graphics";
                """


def page_count_js():
    """Return the active document's page count as a string."""
    return "app.activeDocument.pages.length + '';"


def export_js(clean_output_idml):
    """Export the active document to IDML, close without saving, and re-enable redraw."""
    return f"""
                var outFile = new File("{clean_output_idml}");
                app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, outFile);
                app.activeDocument.close(SaveOptions.NO);
                app.scriptPreferences.enableRedraw = true;
                """

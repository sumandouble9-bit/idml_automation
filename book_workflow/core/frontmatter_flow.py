JS_LANG = 1246973031

TOC_HEADINGS = ("contents", "table of contents", "contenido", "tabla de contenido", "tabla de contenidos", "indice")
TOC_STYLE_KEYS = ("toc", "content_ch", "part_contents")
SCAN_PARAGRAPHS = 2000
TOC_ENTRY_MAX_CHARS = 160

_JS_CONSTANTS = r"""
    var NL = String.fromCharCode(10), LS = String.fromCharCode(8232), BOM = String.fromCharCode(65279);
    var HEADINGS = __HEADINGS__, STYLE_KEYS = __STYLEKEYS__, SCAN = __SCAN__, ENTRY_MAX = __ENTRYMAX__;
"""

_JS_TEXT_HELPERS = r"""
    function has(list, v){ for (var i = 0; i < list.length; i++){ if (list[i] === v) return true; } return false; }
    function clean(t){ return String(t).split(LS).join("").split(BOM).join("").replace(/\s+/g, " ").replace(/^ | $/g, ""); }
    function textOf(p){ try { return clean(p.contents); } catch(e) { return ""; } }
    function styleOf(p){ try { return p.appliedParagraphStyle.name.toLowerCase(); } catch(e) { return ""; } }
    function pageOf(p){
        try { return p.insertionPoints[0].parentTextFrames[0].parentPage.documentOffset + 1; } catch(e) { return -1; }
    }
    function isHeading(txt){
        return txt !== "" && has(HEADINGS, txt.toLowerCase().split(String.fromCharCode(237)).join("i"));
    }
    function isTocEntry(p, txt){
        var sn = styleOf(p);
        for (var k = 0; k < STYLE_KEYS.length; k++){ if (sn.indexOf(STYLE_KEYS[k]) >= 0) return true; }
        return txt.length < ENTRY_MAX && /[\t. ]\d{1,4}$/.test(txt);
    }
"""

_JS_LOCATE = r"""
    function mainStory(doc){
        var best = null, max = -1;
        for (var s = 0; s < doc.stories.length; s++){
            var len = 0; try { len = doc.stories[s].characters.length; } catch(e) {}
            if (len > max){ max = len; best = doc.stories[s]; }
        }
        return best;
    }
    function locate(paras){
        var head = -1, last = -1, n = Math.min(paras.length, SCAN);
        for (var i = 0; i < n; i++){
            var txt = textOf(paras[i]);
            if (head < 0){ if (isHeading(txt)){ head = i; last = i; } continue; }
            if (txt === "") continue;
            if (isTocEntry(paras[i], txt)){ last = i; continue; }
            return { head: head, last: last, first: i };
        }
        return { head: head, last: last, first: -1 };
    }
"""

_JS_FIXES = r"""
    function recompose(doc){ try { doc.recompose(); } catch(e) {} }
    function forceOdd(doc, para, fixes, label){
        var page = pageOf(para);
        if (!(page > 0 && page % 2 === 0)) return;
        try { para.startParagraph = StartParagraph.NEXT_ODD_PAGE; fixes.push(label); } catch(e) {}
        recompose(doc);
    }
    function keepOnSpacerPage(doc, paras, loc, fixes){
        var spacer = paras[loc.first - 1];
        if (loc.first - 1 <= loc.last || textOf(spacer) !== "") return;
        var spacerPage = pageOf(spacer);
        if (!(spacerPage > 0 && pageOf(paras[loc.first]) > spacerPage)) return;
        try { paras[loc.first].startParagraph = StartParagraph.ANYWHERE; fixes.push("content->spacer-page"); } catch(e) {}
        recompose(doc);
    }
"""

_JS_MASTERS = r"""
    function bodyMaster(doc, firstPage){
        for (var pi = firstPage - 1; pi < doc.pages.length; pi++){
            try { if (doc.pages[pi].appliedMaster) return doc.pages[pi].appliedMaster; } catch(e) {}
        }
        for (var m = 0; m < doc.masterSpreads.length; m++){
            if (doc.masterSpreads[m].name.toLowerCase().indexOf("master") >= 0) return doc.masterSpreads[m];
        }
        return null;
    }
    function applyMasters(doc, firstPage){
        var master = bodyMaster(doc, firstPage), cleared = 0, applied = 0;
        for (var q = 0; q < doc.pages.length; q++){
            var pg = doc.pages[q], cur = null;
            try { cur = pg.appliedMaster; } catch(e) {}
            if (q < firstPage - 1){
                if (cur){ try { pg.appliedMaster = NothingEnum.NOTHING; cleared++; } catch(e) {} }
            } else if (master && (!cur || cur.id !== master.id)){
                try { pg.appliedMaster = master; applied++; } catch(e) {}
            }
        }
        return { cleared: cleared, applied: applied };
    }
"""

_JS_MAIN = r"""
    function report(tocFirst, tocLast, firstPage, fixes, masters){
        return "FLOW toc=" + tocFirst + "-" + tocLast + " tocPages=" + (tocLast - tocFirst + 1) +
               " firstContent=" + firstPage + " blankAfterToc=" + (firstPage - tocLast - 1) +
               " fixes=" + (fixes.length ? fixes.join(",") : "none") +
               " masterNone=1-" + (firstPage - 1) + " masterCleared=" + masters.cleared + " masterApplied=" + masters.applied;
    }
    var doc = app.activeDocument;
    recompose(doc);
    var story = mainStory(doc);
    if (!story) return "FLOW skipped=no-story";
    var paras = story.paragraphs, loc = locate(paras), fixes = [];
    if (loc.head < 0) return "FLOW skipped=no-toc";
    if (loc.first < 0) return "FLOW skipped=no-content-after-toc";
    forceOdd(doc, paras[loc.head], fixes, "toc->odd");
    keepOnSpacerPage(doc, paras, loc, fixes);
    forceOdd(doc, paras[loc.first], fixes, "content->odd");
    var firstPage = pageOf(paras[loc.first]);
    if (firstPage < 1) return "FLOW skipped=content-not-placed";
    var masters = applyMasters(doc, firstPage);
    return report(pageOf(paras[loc.head]), pageOf(paras[loc.last]), firstPage, fixes, masters);
"""


def _constants_js():
    """Return the script constants with the heading texts, style keys and limits filled in."""
    headings = "[" + ",".join('"%s"' % h for h in TOC_HEADINGS) + "]"
    keys = "[" + ",".join('"%s"' % k for k in TOC_STYLE_KEYS) + "]"
    return (_JS_CONSTANTS
            .replace("__HEADINGS__", headings)
            .replace("__STYLEKEYS__", keys)
            .replace("__SCAN__", str(SCAN_PARAGRAPHS))
            .replace("__ENTRYMAX__", str(TOC_ENTRY_MAX_CHARS)))


def frontmatter_flow_js():
    """Return the ExtendScript of the real-layout front-matter pass, assembled from its small parts."""
    parts = (_constants_js(), _JS_TEXT_HELPERS, _JS_LOCATE, _JS_FIXES, _JS_MASTERS, _JS_MAIN)
    return "(function(){" + "".join(parts) + "})();"


def layout_changed(report):
    """True when the pass moved the TOC or the chapters to another page (so overset must be re-resolved)."""
    return report.startswith("FLOW toc=") and "fixes=none" not in report


def apply_frontmatter_flow(app):
    """Run the pass on the document open in InDesign and return its one-line report (or the reason it skipped)."""
    return str(app.DoScript(frontmatter_flow_js(), JS_LANG) or "")

JS = 1246973031

JS_FIX = r'''
var doc = app.activeDocument;
try { doc.recompose(); } catch (eR) {}

var NONBODY = ["chapter_name","sub-heading","heading","master_chapter","content_ch",
               "toc","verso","copyright","copy","author","auther","doublenine","title","caption"];
function isBody(nm){
    nm = (nm || "").toLowerCase();
    for (var i = 0; i < NONBODY.length; i++){ if (nm.indexOf(NONBODY[i]) >= 0) return false; }
    return true;
}

var relaxed = 0;
var styles = doc.allParagraphStyles;
for (var i = 0; i < styles.length; i++){
    try {
        var ps = styles[i];
        var nm = ps.name;
        if (nm === "[No Paragraph Style]") continue;
        if (!isBody(nm)) continue;
        // Enforce widow/orphan control: lines flow to fill pages, but never leave 1-line orphan/widow
        try { ps.keepLinesTogether = true; } catch (e1) {}
        try { ps.keepAllLinesTogether = false; } catch (e2) {}
        try { ps.keepFirstAndLastLines = true; } catch (e3) {}
        try { ps.minLinesAtStart = 2; } catch (e4) {}
        try { ps.minLinesAtEnd = 2; } catch (e5) {}
        relaxed++;
    } catch (eP) {}
}
try { doc.recompose(); } catch (eR2) {}
"BODY_STYLES_RELAXED=" + relaxed;
'''


def run(app):
    return app.DoScript(JS_FIX, JS) or ''

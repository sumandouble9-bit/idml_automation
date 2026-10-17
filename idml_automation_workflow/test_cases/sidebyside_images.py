import os as _os, re as _re, zipfile as _zip

JS = 1246973031


def epub_pairs(epub_path):
    """Return a set of frozenset({imgA, imgB}) for images that share one container
    (side-by-side) in the EPUB XHTML."""
    pairs = set()
    if not (epub_path and _os.path.exists(epub_path)):
        return pairs
    try:
        with _zip.ZipFile(epub_path) as z:
            for n in z.namelist():
                if not n.lower().endswith((".xhtml", ".html", ".htm")):
                    continue
                c = z.read(n).decode("utf-8", "replace")
                # any container (p/div/figure/tr/span) holding >= 2 <img>
                for m in _re.finditer(r"<(p|div|figure|tr|span)\b[^>]*>(.*?)</\1>", c, _re.I | _re.S):
                    inner = m.group(2)
                    imgs = _re.findall(r'<img\b[^>]*src="([^"]+)"', inner, _re.I)
                    if len(imgs) >= 2:
                        bases = [_os.path.basename(s).lower() for s in imgs]
                        for i in range(len(bases) - 1):
                            pairs.add(frozenset((bases[i], bases[i + 1])))
    except Exception:
        pass
    return pairs


def _pairs_literal(pairs):
    items = []
    for pr in pairs:
        a = sorted(pr)
        if len(a) == 2:
            items.append('"%s|%s"' % (a[0], a[1]))
    return "[" + ",".join(items) + "]"


_JS = r"""
var PAIRS = __PAIRS__;        // array of "a.jpg|b.jpg" (sorted)
var d = app.activeDocument;
function key(a,b){ var x=[a.toLowerCase(),b.toLowerCase()].sort(); return x[0]+"|"+x[1]; }
function isPair(a,b){ var k=key(a,b); for(var i=0;i<PAIRS.length;i++){ if(PAIRS[i]==k) return true; } return false; }
var done = 0;
// Walk stories; find two consecutive paragraphs each holding exactly one anchored
// image whose names form a known side-by-side pair, then place them on ONE line.
for (var si=0; si<d.stories.length; si++){
    var st = d.stories[si];
    var ps = st.paragraphs;
    for (var pi=0; pi<ps.length-1; pi++){
        try {
            var p1 = ps[pi], p2 = ps[pi+1];
            if (p1.allPageItems.length!=1 || p2.allPageItems.length!=1) continue;
            var g1 = p1.allGraphics, g2 = p2.allGraphics;
            if (g1.length!=1 || g2.length!=1) continue;
            if (!g1[0].itemLink || !g2[0].itemLink) continue;
            var n1 = g1[0].itemLink.name, n2 = g2[0].itemLink.name;
            if (!isPair(n1, n2)) continue;
            // column width from host frame
            var host = p1.parentTextFrames.length? p1.parentTextFrames[0] : null;
            var colW = 324; if (host){ var tb=host.geometricBounds; colW=tb[3]-tb[1]; }
            var GAP = 10, halfW = (colW - GAP) / 2;
            // resize each image frame to <= halfW, keep aspect
            var frames = [g1[0].parent, g2[0].parent];
            for (var f=0; f<2; f++){
                var fr = frames[f];
                var gb = fr.geometricBounds; var w=gb[3]-gb[1], h=gb[2]-gb[0];
                if (w > halfW){ var s=halfW/w; fr.geometricBounds=[gb[0],gb[1],gb[0]+h*s,gb[1]+halfW]; fr.fit(FitOptions.CONTENT_TO_FRAME); }
                try { fr.anchoredObjectSettings.anchoredPosition = AnchorPosition.INLINE_POSITION; } catch(e){}
                try { fr.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch(e){}
            }
            // merge the two paragraphs into one line: replace the paragraph break at
            // the end of p1 with a tab so both inline images sit on one centered line.
            var endIdx = p1.characters[-1].index;             // the CR of p1
            st.characters[endIdx].contents = "\t";
            var line = st.characters[endIdx-1].paragraphs[0];
            try { line.justification = Justification.CENTER_ALIGN; } catch(e){}
            done++;
        } catch(e){}
    }
}
try { d.recompose(); } catch(e){}
"SIDEBYSIDE=" + done;
"""


def run(app, epub_path):
    """Place EPUB side-by-side image pairs on one centered line (scaled to fit)."""
    pairs = epub_pairs(epub_path)
    if not pairs:
        return "SIDEBYSIDE=0(no pairs)"
    js = _JS.replace("__PAIRS__", _pairs_literal(pairs))
    try:
        return app.DoScript(js, JS)
    except Exception as e:
        return "SIDEBYSIDE=err:%s" % e

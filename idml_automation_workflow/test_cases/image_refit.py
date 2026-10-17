import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "image_inject"))
import fix_image_layout

JS = 1246973031

_JS_FALLBACK = """
var doc = app.activeDocument;
try { doc.recompose(); } catch(e){}
function _ovf(g, fr){
    var a = g.geometricBounds, b = fr.geometricBounds;
    var x1 = Math.max(a[1], b[1]), y1 = Math.max(a[0], b[0]);
    var x2 = Math.min(a[3], b[3]), y2 = Math.min(a[2], b[2]);
    var w = x2 - x1; if (w < 0) w = 0;
    var h = y2 - y1; if (h < 0) h = 0;
    var ar = (a[3] - a[1]) * (a[2] - a[0]);
    return ar > 0 ? (w * h) / ar : 1;
}
var fixed = 0;
var graphics = doc.allGraphics;
for (var i = 0; i < graphics.length; i++){
    try {
        var g = graphics[i];
        if (!g.itemLink) continue;
        var fr = g.parent;
        if (_ovf(g, fr) < 0.5){
            try { fr.fit(FitOptions.FIT_CONTENT_PROPORTIONALLY); } catch(e1){}
            try { fr.fit(FitOptions.CENTER_CONTENT); } catch(e2){}
            fixed++;
        }
    } catch(eg){}
}
fixed.toString();
"""


def run(app):
    # Apply the project's margin-aware layout, then one proportional-fit pass for
    # any image whose content sits off its frame (renders blank).
    try:
        fix_image_layout.fix_image_layout(app)
    except Exception:
        pass
    try:
        return int(app.DoScript(_JS_FALLBACK, JS) or "0")
    except Exception:
        return 0


_JS_DETECT = """
var doc = app.activeDocument;
function _ovf(g, fr){
    var a = g.geometricBounds, b = fr.geometricBounds;
    var x1 = Math.max(a[1], b[1]), y1 = Math.max(a[0], b[0]);
    var x2 = Math.min(a[3], b[3]), y2 = Math.min(a[2], b[2]);
    var w = x2 - x1; if (w < 0) w = 0;
    var h = y2 - y1; if (h < 0) h = 0;
    var ar = (a[3] - a[1]) * (a[2] - a[0]);
    return ar > 0 ? (w * h) / ar : 1;
}
var off = [];
var graphics = doc.allGraphics;
for (var i = 0; i < graphics.length; i++){
    try {
        var g = graphics[i];
        if (!g.itemLink) continue;
        var nm = g.itemLink.name.toUpperCase();
        if (nm.indexOf("LOGO") >= 0 || nm.indexOf("LEAF-BOUND") >= 0) continue;
        var fr = g.parent;
        if (_ovf(g, fr) < 0.5){
            var pg = "?"; try { if (fr.parentPage) pg = fr.parentPage.name; } catch(ep){}
            off.push(g.itemLink.name + " (p." + pg + ")");
        }
    } catch(eg){}
}
off.join("\u0001");
"""


def offframe(app):
    # Off-frame image names measured on the CURRENT composition (no recompose),
    # so it reflects the state that will be exported.
    try:
        result = str(app.DoScript(_JS_DETECT, JS) or "")
    except Exception:
        return []
    return [n for n in result.split("\u0001") if n]

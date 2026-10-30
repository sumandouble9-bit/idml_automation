JS = 1246973031

PRELUDE = r"""
var doc = app.activeDocument;
try { doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN; } catch (eRO) {}
var problems = [];
var pageBounds = doc.pages[0].bounds;
var pageH = pageBounds[2] - pageBounds[0];
var pageW = pageBounds[3] - pageBounds[1];
var facing = doc.documentPreferences.facingPages;
function isLogo(name){ if(!name) return false; var n=name.toUpperCase(); return n.indexOf("LEAF-BOUND")>=0 || n.indexOf("LOGO")>=0; }
function marginBox(pg){ var pb=pg.bounds, mp=pg.marginPreferences, l, r; if(facing && pg.side==PageSideOptions.LEFT_HAND){ l=pb[1]+mp.right; r=pb[3]-mp.left; } else { l=pb[1]+mp.left; r=pb[3]-mp.right; } return {top:pb[0]+mp.top, bottom:pb[2]-mp.bottom, left:l, right:r}; }
function rectsOverlap(a, b){ return !(a[3]<=b[1]+1 || a[1]>=b[3]-1 || a[2]<=b[0]+1 || a[0]>=b[2]-1); }
function normCap(s){ return String(s).replace(/[^a-zA-Z0-9]/g, "").toLowerCase(); }
"""

_SUFFIX = '\nproblems.join("\u0001");'


def run(app, body):
    """Run one check body with the shared prelude and return its problem strings."""
    result = app.DoScript(PRELUDE + body + _SUFFIX, JS) or ""
    return [p for p in str(result).split("\u0001") if p]


def escape_js(text):
    """Escape a Python string for use inside a JS double-quoted literal."""
    return (text.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\r", " ").replace("\n", " "))


_COUNTS_JS = r"""
var doc = app.activeDocument;
var tables = 0, images = 0, placeholders = 0;
for (var s = 0; s < doc.stories.length; s++){ try { tables += doc.stories[s].tables.length; } catch(e){} }
for (var i = 0; i < doc.allGraphics.length; i++){
    try { var g = doc.allGraphics[i]; var n = g.itemLink ? g.itemLink.name.toUpperCase() : "";
          if (n.indexOf("LOGO") < 0 && n.indexOf("LEAF-BOUND") < 0) images++; } catch(e){}
}
try { app.findGrepPreferences = NothingEnum.nothing; app.findGrepPreferences.findWhat = "###Insert .*? here###";
      placeholders = doc.findGrep().length; app.findGrepPreferences = NothingEnum.nothing; } catch(e){}
"TABLES=" + tables + "~IMAGES=" + images + "~PH_LEFT=" + placeholders;
"""


def counts(app):
    """Return document counts (tables, images, leftover placeholders) for the summary."""
    result = str(app.DoScript(_COUNTS_JS, JS) or "")
    data = {}
    for pair in result.split("~"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            data[key] = value
    return data

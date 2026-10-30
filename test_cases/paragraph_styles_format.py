import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import epub_classes

JS = 1246973031


def _obj(keys):
    """Formats a set of keys into a JavaScript object literal."""
    return "{" + ",".join('"%s":1' % k for k in keys if k) + "}"


_JS = r"""
var CENTER = __CENTER__;
var BLOCK  = __BLOCK__;
var RIGHT  = __RIGHT__;
var doc = app.activeDocument;
function key(s){ return String(s).replace(/[^a-zA-Z0-9]/g, "").toLowerCase().substring(0, 60); }
var bodyStyle = null;
var _aps = doc.allParagraphStyles;
for (var _i = 0; _i < _aps.length; _i++){ if (_aps[_i].name == "body_text"){ bodyStyle = _aps[_i]; break; } }
var nCenter = 0, nBlock = 0, nRight = 0;
for (var si = 0; si < doc.stories.length; si++){
    var paras = doc.stories[si].paragraphs;
    for (var pi = 0; pi < paras.length; pi++){
        try {
            var p = paras[pi];
            var k = key(p.contents);
            if (k.length < 4) continue;
            var sn = ""; try { sn = p.appliedParagraphStyle.name.toLowerCase(); } catch(e){}
            var isCenter = !!CENTER[k];
            var isRight = !!RIGHT[k];
            var isBlock = !!BLOCK[k];
            if (isCenter){
                try { if (p.justification != Justification.CENTER_ALIGN){ p.justification = Justification.CENTER_ALIGN; nCenter++; } } catch(e){}
            } else if (isRight){
                try { if (p.justification != Justification.RIGHT_ALIGN){ p.justification = Justification.RIGHT_ALIGN; nRight++; } } catch(e){}
            }
            if ((sn.indexOf("quote") >= 0 || sn.indexOf("block") >= 0) && !isBlock && !isCenter && !isRight){
                try { if (bodyStyle){ p.appliedParagraphStyle = bodyStyle; nBlock++; } } catch(e){}
            }
            var ptxt = p.contents;
            if (ptxt.indexOf("\u2028") >= 0 || ptxt.indexOf("\n") >= 0){
                try {
                    if (isRight){
                        p.justification = Justification.RIGHT_ALIGN;
                    } else if (isCenter){
                        p.justification = Justification.CENTER_ALIGN;
                    } else if (p.justification == Justification.LEFT_JUSTIFIED || p.justification == Justification.FULLY_JUSTIFIED){
                        p.justification = Justification.LEFT_ALIGN;
                    }
                } catch(e){}
            }
        } catch(eP){}
    }
}
"CENTER=" + nCenter + " BLOCK_RESET=" + nBlock + " RIGHT=" + nRight;
"""


def run(app, epub_path):
    """Re-apply EPUB paragraph alignment (center/right) and un-stick the block/quote
    style from normal paragraphs, driven dynamically by the book's own classes."""
    cls = epub_classes.extract(epub_path)
    js = (_JS.replace("__CENTER__", _obj(cls["center"]))
             .replace("__BLOCK__", _obj(cls["block"]))
             .replace("__RIGHT__", _obj(cls["right"])))
    return app.DoScript(js, JS)

"""Style-level justification formatting pass.

ONE lightweight pass (no per-paragraph loop) so it never hangs
InDesign on large docs. Setting the style justifies every body paragraph that has
no explicit override; verse paragraphs keep their own LeftAlign override.
"""

JS = 1246973031

_JS = r"""
var d = app.activeDocument;
var BODY = {"body_text":1,"noindent":1,"Normal":1,"quotes_normal":1,"noindentj":1,"noindent1":1,"bodytext_noendent":1};
var aps = d.allParagraphStyles;
var n = 0;
for (var i = 0; i < aps.length; i++){
    var s = aps[i]; var nm = ""; try { nm = s.name; } catch(e){ continue; }
    if (!BODY[nm]) continue;
    try { s.pointSize = 9.65; } catch(e){}
    if (nm === "body_text"){
        try { s.justification = Justification.LEFT_JUSTIFIED; } catch(e){}
        try { s.minimumWordSpacing = 100; s.desiredWordSpacing = 100; s.maximumWordSpacing = 100; } catch(e){}
        try { s.minimumLetterSpacing = 0; s.desiredLetterSpacing = 0; s.maximumLetterSpacing = 5; } catch(e){}
        try { s.minimumGlyphScaling = 100; s.desiredGlyphScaling = 100; s.maximumGlyphScaling = 100; } catch(e){}
        try { s.hyphenation = true; } catch(e){}
    }
    n++;
}
try { d.recompose(); } catch(e){}
"BODYSTYLES=" + n;
"""


def run(app):
    """Enforce body style = 9.65pt + (body_text) LeftJustified, uniform word spacing,
    hyphenation. Style-level only, so it is a single fast call that won't hang InDesign."""
    try:
        return app.DoScript(_JS, JS)
    except Exception as e:
        return "BODYSTYLES=err:%s" % e

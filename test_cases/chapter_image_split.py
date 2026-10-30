JS = 1246973031

_JS = r"""
var d = app.activeDocument;
function hs(nm){ nm=(nm||"").toLowerCase(); return nm.indexOf("chapter_name")>=0 || nm.indexOf("master_chapter")>=0; }
function bodyStyle(){ var a=d.allParagraphStyles; for(var i=0;i<a.length;i++){ if(a[i].name=="body_text") return a[i]; } return d.paragraphStyles.item(0); }
var BODY = bodyStyle();
var moved = 0;
for (var si=0; si<d.stories.length; si++){
    var st = d.stories[si];
    var idxs = [];
    var ps = st.paragraphs;
    for (var pi=0; pi<ps.length; pi++){
        var p = ps[pi]; var s=""; try { s=p.appliedParagraphStyle.name; } catch(e){}
        if (hs(s) && p.allPageItems.length>0){ idxs.push(p.characters[0].index); }
    }
    idxs.sort(function(a,b){ return b-a; });
    for (var t=0; t<idxs.length; t++){
        try {
            var para = st.characters[idxs[t]].paragraphs[0];
            var chars = para.characters;
            var cut = -1;
            for (var c=0; c<chars.length; c++){
                var cc = chars[c].contents;
                if (cc==="\uFFFC" || cc===" " || cc==="\t" || cc==="\u00A0") continue;
                cut = chars[c].index; break;
            }
            if (cut > para.characters[0].index){
                st.characters[cut].insertionPoints[0].contents = "\r";
                var imgPara  = st.characters[idxs[t]].paragraphs[0];
                var headPara = st.characters[cut+1].paragraphs[0];
                try { imgPara.appliedParagraphStyle = BODY; } catch(e){}
                try { imgPara.startParagraph = StartParagraph.ANYWHERE; } catch(e){}
                try { imgPara.justification = Justification.CENTER_ALIGN; } catch(e){}
                try { headPara.startParagraph = StartParagraph.NEXT_PAGE; } catch(e){}
                moved++;
            }
        } catch(e){}
    }
}
try { d.recompose(); } catch(e){}
"CHAPTER_IMG_SPLIT=" + moved;
"""


def run(app):
    """Split an anchored image out of a chapter-heading paragraph into its own body
    paragraph before it, so the heading starts clean on its new page."""
    try:
        return app.DoScript(_JS, JS)
    except Exception as e:
        return "CHAPTER_IMG_SPLIT=err:%s" % e

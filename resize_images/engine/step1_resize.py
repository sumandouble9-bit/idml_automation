"""STEP 1: shrink each image by a table percentage of the FULL block (image + fig caption) height.

Runs BEFORE STEP 2. The band is chosen from the full block height (image height + caption height) as a
share of the body frame; the shrink is applied to the image, with the caption travelling with it. Blocks
below 40% of the frame are left for STEP 2. Neither step shrinks the block below 35% of the frame.
    90-100% -> 35%   80-90% -> 40%   70-80% -> 40%   60-70% -> 45%   50-60% -> 45%   40-50% -> 30%
Only image size changes -- no text, caption, font, style or vertical-justification edits.
"""

from . import geometry as G
from .indesign_jobs import JS

_STEP1_JS = r'''
var FLOOR35 = __FLOOR35__, NL=String.fromCharCode(10);
var doc=app.activeDocument; doc.recompose();
var pageH=doc.documentPreferences.pageHeight;
function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0||u.indexOf("LOGO")>=0; }
function frameBoxH(page){ var mp=page.marginPreferences; return (pageH-mp.bottom)-mp.top; }
function frameH(fr){ var b=fr.geometricBounds; return b[2]-b[0]; }
function nameOf(gr){ try{ return gr.itemLink?gr.itemLink.name:""; }catch(e){ return ""; } }
function anchoredInText(fr){ try{ return fr.parent&&fr.parent.constructor&&(fr.parent.constructor.name==="Character"||fr.parent.constructor.name==="InsertionPoint"); }catch(e){ return false; } }
function resizeTo(fr,g,targetH){ var curH=frameH(fr); if(curH<=0)return; var sc=targetH/curH; try{ g.horizontalScale=g.horizontalScale*sc; g.verticalScale=g.verticalScale*sc; fr.fit(FitOptions.FRAME_TO_CONTENT); }catch(e){} }
// band by the FULL block (image + caption) height as a share of the frame.
function pctShrink(pct){ if(pct>=90)return 35; if(pct>=80)return 40; if(pct>=70)return 40; if(pct>=60)return 45; if(pct>=50)return 45; if(pct>=40)return 30; return 0; }

// caption = paragraph right after the image's own paragraph, when its style name says caption/fig.
function captionParaOf(fr){
    try{ var anchor=fr.parent; var imgPara=anchor.paragraphs[0]; var story=imgPara.parentStory;
        var lastIdx=imgPara.insertionPoints[-1].index;
        if(lastIdx>=story.characters.length) return null;
        var capPara=story.insertionPoints[lastIdx].paragraphs[0];
        var sn=""; try{ sn=capPara.appliedParagraphStyle.name.toLowerCase(); }catch(e){}
        return (sn.indexOf("caption")>=0||sn.indexOf("fig")>=0)?capPara:null;
    }catch(e){ return null; }
}
function captionHeight(capPara){ if(!capPara) return 0; var n=0; try{ n=capPara.lines.length; }catch(e){} if(n<=0) return 0; var ps=9; try{ ps=capPara.pointSize; if(!(ps>0)) ps=9; }catch(e){ ps=9; } return n*(ps*1.2)+4; }

var gs=doc.allGraphics, cnt=0, logs=[];
for(var g=0;g<gs.length;g++){ try{
  var gr=gs[g]; var nm=nameOf(gr); if(!nm||isLogo(nm)) continue;
  var fr=gr.parent; if(!anchoredInText(fr)) continue;
  var page=null; try{page=fr.parentPage;}catch(e){} if(page===null) continue;
  var fh=frameBoxH(page); var imgH=frameH(fr); if(fh<=0||imgH<=0) continue;
  var capH=captionHeight(captionParaOf(fr));
  var fullH=imgH+capH; var pct=fullH/fh*100; var sh=pctShrink(pct);
  var pgN=page.documentOffset+1;
  if(sh<=0){ logs.push("image "+nm+" | p."+pgN+" | imgH "+imgH.toFixed(0)+" capH "+capH.toFixed(0)+" fullH "+fullH.toFixed(0)+" ("+pct.toFixed(0)+"% of frame) | <40% -> deferred to STEP 2"); continue; }
  var nhImg=imgH*(1-sh/100);
  var minImg=FLOOR35-capH; if(minImg<0) minImg=0;      // keep image+caption together >= 35% of frame
  var clamped=false; if(nhImg<minImg){ nhImg=minImg; clamped=true; }
  if(imgH-nhImg<=1){ logs.push("image "+nm+" | p."+pgN+" | imgH "+imgH.toFixed(0)+" capH "+capH.toFixed(0)+" fullH "+fullH.toFixed(0)+" ("+pct.toFixed(0)+"%) | band shrink "+sh+"% but already at 35% floor -> left as-is"); continue; }
  resizeTo(fr,gr,nhImg); cnt++;
  var newFull=nhImg+capH; var newPct=newFull/fh*100;
  logs.push("image "+nm+" | p."+pgN+" | imgH "+imgH.toFixed(0)+" capH "+capH.toFixed(0)+" fullH "+fullH.toFixed(0)+" ("+pct.toFixed(0)+"% of frame) | band shrink "+sh+"%"+(clamped?" (clamped at 35% floor)":"")+" | -> imgH "+nhImg.toFixed(0)+" fullH "+newFull.toFixed(0)+" ("+newPct.toFixed(0)+"% of frame)");
}catch(e){} }
doc.recompose();
"STEP1="+cnt+NL+logs.join(NL);
'''


def _step1_js():
    """Substitute the 35%-of-frame floor into the STEP 1 ExtendScript."""
    return _STEP1_JS.replace("__FLOOR35__", "%.2f" % (G.FRAME_HEIGHT_PT * G.FLOOR_PCT))


def step1_resize(app):
    """Apply the STEP 1 table-based shrink on the open document; return (count, log_lines)."""
    out = app.DoScript(_step1_js(), JS) or ""
    lines = [ln for ln in out.split("\n") if ln.strip()]
    count = 0
    if lines and lines[0].startswith("STEP1="):
        try:
            count = int(lines[0].split("=", 1)[1])
        except ValueError:
            count = 0
        lines = lines[1:]
    return count, lines

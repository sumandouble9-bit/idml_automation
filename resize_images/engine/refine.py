from . import geometry as G
from .indesign_jobs import JS

_REFINE_JS = r'''
var MX = __MX__;
var GAP_OK=__GAPOK__, BOTTOM_INSET=1.0, REFINE_SAFETY=__RSAFE__, PAD=__PAD__, MAX_PASSES=__MAXP__, FLOOR35=__FLOOR35__, NL=String.fromCharCode(10);
var doc=app.activeDocument;
doc.viewPreferences.rulerOrigin=RulerOrigin.PAGE_ORIGIN;
var pageH=doc.documentPreferences.pageHeight, pageW=doc.documentPreferences.pageWidth;

var mainStory=null, maxLen=-1;
for(var s=0;s<doc.stories.length;s++){ try{ if(doc.stories[s].characters.length>maxLen){ maxLen=doc.stories[s].characters.length; mainStory=doc.stories[s]; } }catch(e){} }
function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0||u.indexOf("LOGO")>=0; }
function marginTop(p){ return p.marginPreferences.top; }
function frameBox(page){ var mp=page.marginPreferences; return { top:mp.top, bot:(pageH-mp.bottom), h:((pageH-mp.bottom)-mp.top) }; }
function bodyFrameOn(page){ var best=null,bestLen=-1; try{ var tfs=page.textFrames; for(var i=0;i<tfs.length;i++){ try{ if(mainStory&&tfs[i].parentStory.id===mainStory.id){ var L=tfs[i].characters.length; if(L>bestLen){bestLen=L;best=tfs[i];} } }catch(e){} } }catch(e2){} return best; }
function gapOn(page){ var box=frameBox(page); var tf=bodyFrameOn(page); var lb=box.top; if(tf){ try{ if(tf.lines.length>0) lb=tf.lines[-1].baseline; }catch(e){} } return box.bot-lb; }
function frameH(fr){ var b=fr.geometricBounds; return b[2]-b[0]; }
function topImageOn(page){ var best=null,bestY=1e9,gs=doc.allGraphics; for(var g=0;g<gs.length;g++){ try{ var fr=gs[g].parent; var pg=null; try{pg=fr.parentPage;}catch(eP){} if(pg===null||pg.id!==page.id) continue; var y0=fr.geometricBounds[0]; if(y0<bestY){ bestY=y0; best={frame:fr,graphic:gs[g],y0:y0}; } }catch(e){} } return best; }
function nameOf(gr){ try{ return gr.itemLink?gr.itemLink.name:""; }catch(e){ return ""; } }
function resizeTo(info,targetH){ var fr=info.frame, g=info.graphic; var curH=frameH(fr); if(curH<=0)return; var sc=targetH/curH; try{ g.horizontalScale=g.horizontalScale*sc; g.verticalScale=g.verticalScale*sc; fr.fit(FitOptions.FRAME_TO_CONTENT); }catch(e){} }
function anchoredInText(fr){ try{ return fr.parent && fr.parent.constructor && (fr.parent.constructor.name==="Character"||fr.parent.constructor.name==="InsertionPoint"); }catch(e){ return false; } }

function captionParaOf(fr){
    try{
        var anchor=fr.parent; var imgPara=anchor.paragraphs[0]; var story=imgPara.parentStory;
        var lastIdx=imgPara.insertionPoints[-1].index;
        if(lastIdx>=story.characters.length) return {img:imgPara, cap:null};
        var capPara=story.insertionPoints[lastIdx].paragraphs[0];
        var isCap=false; try{ var sn=capPara.appliedParagraphStyle.name.toLowerCase(); isCap=(sn.indexOf("caption")>=0||sn.indexOf("fig")>=0); }catch(e){}
        return { img:imgPara, cap:(isCap?capPara:null) };
    }catch(e){ return {img:null, cap:null}; }
}
function captionHeight(capPara){ if(!capPara) return 0; var nLines=0; try{ nLines=capPara.lines.length; }catch(e){} if(nLines<=0) return 0; var ps=9; try{ ps=capPara.pointSize; if(!(ps>0)) ps=9; }catch(e){ ps=9; } return nLines*(ps*1.2)+4; }
function paraEndPage(para){ try{ return para.lines[-1].parentTextFrames[0].parentPage.documentOffset; }catch(e){ return -1; } }
function imgFramePage(fr){ try{ return fr.parentPage.documentOffset; }catch(e){ return -2; } }
function findGraphicByFrameId(id){ var gs=doc.allGraphics; for(var i=0;i<gs.length;i++){ try{ if(gs[i].parent.id===id) return gs[i]; }catch(e){} } return null; }

// Make every image+caption one unbreakable block. keepAllLinesTogether needs keepLinesTogether=true to work.
function keepImageCaptionTogether(){
    var gs=doc.allGraphics, cnt=0;
    for(var g=0;g<gs.length;g++){ try{ var gr=gs[g]; var nm=nameOf(gr); if(!nm||isLogo(nm)) continue;
        var pc=captionParaOf(gr.parent); if(!pc.img||!pc.cap) continue;
        try{ pc.img.keepWithNext=1; }catch(e){}
        try{ pc.cap.keepLinesTogether=true; }catch(e){}
        try{ pc.cap.keepAllLinesTogether=true; }catch(e){}
        try{ pc.cap.keepWithPrevious=true; }catch(e){}
        cnt++; }catch(e){} }
    return cnt;
}

var kept = keepImageCaptionTogether();
var audit=[], totalResized=0;

// Gap-fill: pull a pushed image (with its caption) up into the previous-page gap. The 35%-of-frame floor
// is on the FULL block (image + caption), so the image's own floor is FLOOR35 - captionHeight. Blocks
// already at or below 35% are never shrunk further (STEP 1 left them here, but they still may flow up as-is).
for(var pass=0; pass<MAX_PASSES; pass++){
    doc.recompose(); audit=[]; var changed=0, n=doc.pages.length;
    for(var k=0;k<n-1;k++){
        var page=doc.pages[k]; var gap=gapOn(page);
        if(gap<=GAP_OK) continue;
        var nextPage=doc.pages[k+1]; var top=topImageOn(nextPage);
        var topIsImage = top && (top.y0 <= marginTop(nextPage)+24);
        if(!topIsImage){ audit.push("p."+page.name+" gap "+gap.toFixed(0)+"pt not image-caused; left as-is"); continue; }
        var nm=nameOf(top.graphic), lim=MX[nm];
        var maxH=lim?lim[0]:frameH(top.frame), minH=lim?lim[1]:0, curH=frameH(top.frame);
        var pc=captionParaOf(top.frame); var capH=captionHeight(pc.cap);
        var fullH=curH+capH;
        var imgFloor=Math.max(minH, FLOOR35-capH); if(imgFloor<0) imgFloor=0;   // image floor keeps block >= 35%
        if(fullH<=FLOOR35+1){ audit.push("p."+page.name+" -> p."+nextPage.name+" "+nm+": block "+fullH.toFixed(0)+"pt already <=35% floor -> not shrunk"); continue; }
        var room=gap-BOTTOM_INSET-REFINE_SAFETY-PAD-capH;              // pt available for the image above the caption
        if(room<imgFloor){ audit.push("p."+page.name+" -> p."+nextPage.name+" "+nm+": leave together (block needs "+(imgFloor+capH).toFixed(0)+"pt, prev gap "+gap.toFixed(0)+"pt)"); continue; }
        var th=Math.min(room,maxH,curH);
        if(curH-th>2){ resizeTo(top,th); changed++; totalResized++;
            audit.push("p."+page.name+" -> p."+nextPage.name+" "+nm+": gap-fill imgH "+curH.toFixed(0)+" -> "+th.toFixed(0)+"pt (caption "+capH.toFixed(0)+"pt, block -> "+(th+capH).toFixed(0)+"pt) into prev p."+page.documentOffset+" gap "+gap.toFixed(0)+"pt"); }
        else { audit.push("p."+page.name+" -> p."+nextPage.name+" "+nm+": already fits prev gap (imgH "+curH.toFixed(0)+"pt)"); }
    }
    if(changed===0) break;
}

// Ensure-whole: if image+caption still straddle a page break, shrink the image 5% per step until both sit
// on one page -- but never below the image floor (block >= 35% of frame).
var straddleFixed=0;
doc.recompose();
var gsW=doc.allGraphics, ids=[];
for(var w=0;w<gsW.length;w++){ try{ var gr=gsW[w]; var nm=nameOf(gr); if(!nm||isLogo(nm)) continue; if(!anchoredInText(gr.parent)) continue; ids.push({id:gr.parent.id, name:nm}); }catch(e){} }
for(var q=0;q<ids.length;q++){
    var it=ids[q]; var lim=MX[it.name]; var fixedThis=false;
    for(var step=0; step<10; step++){
        doc.recompose();
        var gr=findGraphicByFrameId(it.id); if(!gr) break;
        var fr=gr.parent; var curH=frameH(fr);
        var pc=captionParaOf(fr); var capH=captionHeight(pc.cap); var endPara = pc.cap ? pc.cap : pc.img;
        var floorH=Math.max(lim?lim[1]:40, FLOOR35-capH); if(floorH<0) floorH=0;
        if(curH<=floorH+1) break;                              // at the block floor: leave alone
        var ip=imgFramePage(fr), ep=paraEndPage(endPara);
        if(ip<0||ep<0) break;
        if(ip===ep) break;
        var newH=curH*0.95;                                    // gentle 5% step
        if(newH<floorH) newH=floorH;
        if(curH-newH<1) break;
        resizeTo({frame:fr,graphic:gr}, newH); fixedThis=true;
    }
    if(fixedThis){ straddleFixed++; audit.push("image "+it.name+": shrunk 5%/step so image+caption sit on one page"); }
}
doc.recompose();
"KEPT="+kept+" RESIZED="+totalResized+" WHOLE="+straddleFixed+NL+audit.join(NL);
'''


def _map_literal(plans):
    """Build a JS object {name:[image_h, image_h*rmin]} of each image's allowed height band (pt)."""
    parts = []
    for p in plans:
        nm = p.name.replace('"', '\\"')
        parts.append('"%s":[%.2f,%.2f]' % (nm, p.max_h, p.min_h_abs))
    return "{" + ",".join(parts) + "}"


def _refine_js(plans):
    """Substitute the image size-range map and constants into the refine ExtendScript."""
    return (_REFINE_JS
            .replace("__MX__", _map_literal(plans))
            .replace("__GAPOK__", "%.2f" % G.GAP_OK_PT)
            .replace("__RSAFE__", "%.2f" % G.REFINE_SAFETY_PT)
            .replace("__PAD__", "%.2f" % G.PAD_PT)
            .replace("__MAXP__", str(G.MAX_PASSES))
            .replace("__FLOOR35__", "%.2f" % (G.FRAME_HEIGHT_PT * G.FLOOR_PCT)))


def refine(app, plans):
    """Run keep-together + gap-fill + ensure-whole; return (kept, resized, whole, audit_lines)."""
    out = app.DoScript(_refine_js(plans), JS) or ""
    lines = [ln for ln in out.split("\n") if ln.strip()]
    kept, resized, whole = 0, 0, 0
    if lines and lines[0].startswith("KEPT="):
        for tok in lines[0].split():
            k, _, v = tok.partition("=")
            try:
                if k == "KEPT": kept = int(v)
                elif k == "RESIZED": resized = int(v)
                elif k == "WHOLE": whole = int(v)
            except ValueError:
                pass
        lines = lines[1:]
    return kept, resized, whole, lines

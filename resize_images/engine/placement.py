"""STEP 2: resize each planned image to its target points and place it at its ###Insert### marker."""

import os

from . import geometry as G
from .indesign_jobs import JS

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


def write_sized_images(plans, links_dir):
    """Resize each plan's image to its first-guess target size (at 72 dpi) into links_dir; return name->path."""
    os.makedirs(links_dir, exist_ok=True)
    out = {}
    for p in plans:
        dst = os.path.join(links_dir, p.name)
        try:
            with Image.open(p.path) as im:
                tw = max(1, int(round(p.w)))
                th = max(1, int(round(p.h)))
                im2 = im.resize((tw, th), Image.LANCZOS)
                if im2.mode not in ("RGB", "RGBA", "L", "CMYK"):
                    im2 = im2.convert("RGB")
                im2.save(dst, dpi=(72, 72))
            out[p.name] = dst
        except Exception:
            out[p.name] = p.path
    return out


def _place_js(name, path):
    """ExtendScript: place one pre-sized image at the marker containing `name`; styling is best-effort."""
    js_name = name.replace("\\", "\\\\").replace('"', '\\"')
    p = path.replace("\\", "/")
    return (
        'var __r="false"; var __name="%s";'
        'try{app.activeDocument.recompose();}catch(eRC){}'
        'app.findGrepPreferences=NothingEnum.nothing;'
        'app.findGrepPreferences.findWhat="###Insert.*?here###";'
        'var all=app.activeDocument.findGrep();'
        'app.findGrepPreferences=NothingEnum.nothing;'
        'var match=null;'
        'for(var k=0;k<all.length;k++){ if(all[k].contents.indexOf(__name)!==-1){match=all[k];break;} }'
        'if(match!==null){'
        ' try{'
        '  var placed=match.place(new File("%s"));'
        '  if(placed&&placed.length>0){'
        '   __r="true";'                                      # success the moment the image is placed
        '   var frame=placed[0].parent;'
        '   try{ frame.fit(FitOptions.FRAME_TO_CONTENT); }catch(eF){}'
        '   try{ frame.textWrapPreferences.textWrapMode=TextWrapModes.NONE; }catch(eT){}'
        '   try{ var aos=frame.anchoredObjectSettings;'
        '        aos.anchoredPosition=AnchorPosition.ABOVE_LINE;'
        '        aos.horizontalAlignment=HorizontalAlignment.CENTER_ALIGN;'
        '        aos.horizontalReferencePoint=AnchoredRelativeTo.COLUMN_EDGE; }catch(eA){}'
        '   try{ frame.parent.paragraphs[0].justification=Justification.CENTER_ALIGN; }catch(eP){}'
        '  }'
        ' }catch(e){ __r="err:"+e.message; }'
        '}'
        'app.findGrepPreferences=NothingEnum.nothing;'
        '__r;'
        % (js_name, p)
    )


def maxW_default():
    """Default maximum image width (body column width) in points."""
    return G.TEXT_WIDTH_PT


def place_all(app, name_to_path):
    """Place every sized image at its marker; return (placed, failed, failures[])."""
    placed, failed, failures = 0, 0, []
    for name, path in name_to_path.items():
        try:
            res = app.DoScript(_place_js(name, path), JS)
        except Exception as exc:
            failed += 1
            failures.append(f"{name} (py: {exc})")
            continue
        if res == "true":
            placed += 1
        else:
            failed += 1
            failures.append(f"{name} ({res})")
    return placed, failed, failures

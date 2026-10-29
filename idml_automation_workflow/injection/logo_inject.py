"""
Dedicated, ISOLATED logo injection.

Handles ONLY the LeafBound logo, nothing else (filters strictly by the logo link
name), so it can never affect body-image injection or any image's position.

It is deliberately simple and does exactly what the template intends:
  1. relink every logo link to `logo_path` (the trimmed logo, no transparent padding),
  2. keep the ORIGINAL placeholder frame exactly as it is -- same position, same
     height, same width (the frame is NEVER moved or resized),
  3. fit the whole logo inside that original frame so it is fully visible, and
  4. remove any border/stroke on the frame.
"""

import win32com.client

JS = 1246973031


def inject_logo(app, logo_path):
    # Relink every logo link, fit the logo inside its original frame (never moved/resized), and clear the border.
    js = r'''
    var doc = app.activeDocument;
    var LOGO = new File("%LOGO%");
    function isLogoName(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }

    // 1) Relink every logo link to the new logo. Body images are never touched.
    if (LOGO.exists){
        for (var l = 0; l < doc.links.length; l++){
            try { if (isLogoName(doc.links[l].name)){ doc.links[l].relink(LOGO); doc.links[l].update(); } } catch(eL){}
        }
    }

    // 2) For each logo frame: fit the logo fully INSIDE the original frame. The
    //    frame's position, width and height are left exactly as the template had
    //    them -- nothing is moved or resized.
    var done = 0;
    for (var i = 0; i < doc.allGraphics.length; i++){
        try {
            var g = doc.allGraphics[i];
            if (!g.itemLink || !isLogoName(g.itemLink.name)) continue;   // ONLY logos
            var frm = g.parent;
            try { frm.fit(FitOptions.PROPORTIONALLY); } catch(e1){}      // whole logo inside the frame
            try { frm.fit(FitOptions.CENTER_CONTENT); } catch(e2){}      // centred in the frame
            try { frm.strokeWeight = 0; } catch(e3){}                    // no border
            try { var none = doc.swatches.itemByName("None"); if (none) frm.strokeColor = none; } catch(e4){}
            done++;
        } catch (eG) {}
    }
    done.toString();
    '''
    js = js.replace("%LOGO%", logo_path.replace("\\", "/"))
    return app.DoScript(js, JS)

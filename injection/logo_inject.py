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

    // 2) For each logo frame: align Page 1 logo to bottom margin line,
    //    and fit the logo fully INSIDE the frame with no border.
    var done = 0;
    for (var i = 0; i < doc.allGraphics.length; i++){
        try {
            var g = doc.allGraphics[i];
            if (!g.itemLink || !isLogoName(g.itemLink.name)) continue;   // ONLY logos
            var frm = g.parent;
            // On Page 1 (Title page), ensure the logo sits right above the bottom margin line
            try {
                var pg = frm.parentPage;
                if (pg && pg.name == "1") {
                    var gb = frm.geometricBounds; // [top, left, bottom, right]
                    var frmH = gb[2] - gb[0];
                    var pgBottom = pg.bounds[2];
                    var botMargin = pg.marginPreferences.bottom;
                    var targetBottom = pgBottom - botMargin;
                    frm.geometricBounds = [targetBottom - frmH, gb[1], targetBottom, gb[3]];
                }
            } catch(ePos) {}
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

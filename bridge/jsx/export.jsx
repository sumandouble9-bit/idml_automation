// InDesign ExtendScript: export.jsx
// Comprehensive Layout Normalization, Live Typography Enforcement,
// Adaptive Squeeze-to-Fit Image Placement, Overset Resolution, and PDF/X Export

(function() {
    var idmlPath = (typeof inputPath !== 'undefined') ? inputPath : (arguments.length > 0 ? arguments[0] : "");
    var pdfPath = (typeof outputPath !== 'undefined') ? outputPath : (arguments.length > 1 ? arguments[1] : "");
    var logoFile = (typeof logoPath !== 'undefined') ? File(logoPath) : File("C:/Users/LENOVO/Desktop/idml_automation/logo/LEAF-BOUND-trimmed.png");

    var idmlFile = File(idmlPath);
    var outputPdf = File(pdfPath);

    if (!idmlFile.exists) {
        return;
    }

    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
    var doc = app.open(idmlFile);

    try {
        var pageW = doc.documentPreferences.pageWidth;
        var pageH = doc.documentPreferences.pageHeight;
        var noneSwatch = null;
        try { noneSwatch = doc.swatches.itemByName("None"); } catch(eN) {}

        // -------------------------------------------------------------
        // 1. RELINK LEAF-BOUND LOGO & SECURE TITLE PAGE CLEARANCE
        // -------------------------------------------------------------
        function isLogoName(n) {
            if (!n) return false;
            var u = n.toUpperCase();
            return u.indexOf("LEAF-BOUND") >= 0 || u.indexOf("LOGO") >= 0;
        }

        if (logoFile.exists) {
            for (var l = 0; l < doc.links.length; l++) {
                try {
                    if (isLogoName(doc.links[l].name)) {
                        doc.links[l].relink(logoFile);
                        doc.links[l].update();
                    }
                } catch(eRelink) {}
            }
        }

        // Fit logo proportionally, center, and clear stroke
        for (var gi = 0; gi < doc.allGraphics.length; gi++) {
            try {
                var g = doc.allGraphics[gi];
                if (!g.itemLink || !isLogoName(g.itemLink.name)) continue;
                var frm = g.parent;
                try { frm.fit(FitOptions.PROPORTIONALLY); } catch(eF1) {}
                try { frm.fit(FitOptions.CENTER_CONTENT); } catch(eF2) {}
                try { frm.strokeWeight = 0; } catch(eF3) {}
                if (noneSwatch) { try { frm.strokeColor = noneSwatch; } catch(eF4) {} }
            } catch(eG) {}
        }

        // On Page 1: Ensure Title/Author frame stops above 480 pt so it NEVER collides with the logo
        if (doc.pages.length >= 1) {
            var p1 = doc.pages[0];
            for (var f1 = 0; f1 < p1.textFrames.length; f1++) {
                var tf1 = p1.textFrames[f1];
                var gb1 = tf1.geometricBounds;
                if (gb1[2] > 480) {
                    tf1.geometricBounds = [gb1[0], gb1[1], 480, gb1[3]];
                }
            }
        }

        // -------------------------------------------------------------
        // 2. LIVE TYPOGRAPHY & FONT ENFORCEMENT
        // -------------------------------------------------------------
        try {
            // Body prose styles
            var bodyStyles = [
                "body_text", "Normal", "NormalParagraphStyle", "[Basic Paragraph]",
                "noindent", "noindentj", "bodytext_noendent", "bodytext_Noendent", "copybody"
            ];
            for (var bi = 0; bi < bodyStyles.length; bi++) {
                var st = doc.paragraphStyles.itemByName(bodyStyles[bi]);
                if (st && st.isValid) {
                    try { st.appliedFont = "Palatino Linotype"; } catch(e) {}
                    try { st.pointSize = 9.65; } catch(e) {}
                    try { st.leading = 12; } catch(e) {}
                    try { st.justification = Justification.LEFT_JUSTIFIED; } catch(e) {}
                    try { st.hyphenation = true; } catch(e) {}
                    if (bodyStyles[bi] === "body_text" || bodyStyles[bi] === "Normal") {
                        try { st.firstLineIndent = 18; } catch(e) {}
                    }
                }
            }

            // Chapter titles & headings
            var headingStyles = ["chapter_name", "chapter_name01", "master_chapter_name", "Heading 1"];
            for (var hi = 0; hi < headingStyles.length; hi++) {
                var hs = doc.paragraphStyles.itemByName(headingStyles[hi]);
                if (hs && hs.isValid) {
                    try { hs.appliedFont = "Gill Sans MT"; } catch(e) {
                        try { hs.appliedFont = "Palatino Linotype"; } catch(e2) {}
                    }
                    try { hs.pointSize = 16; } catch(e) {}
                    try { hs.leading = 20; } catch(e) {}
                    try { hs.justification = Justification.CENTER_ALIGN; } catch(e) {}
                    try { hs.hyphenation = false; } catch(e) {}
                }
            }

            // Sub-headings
            var subhead = doc.paragraphStyles.itemByName("Sub-heading");
            if (subhead && subhead.isValid) {
                try { subhead.appliedFont = "Palatino Linotype"; } catch(e) {}
                try { subhead.pointSize = 12; } catch(e) {}
                try { subhead.leading = 15; } catch(e) {}
                try { subhead.justification = Justification.CENTER_ALIGN; } catch(e) {}
            }

            // Book Title & Author on Cover/Title page
            var titleSt = doc.paragraphStyles.itemByName("main_page_title");
            if (titleSt && titleSt.isValid) {
                try { titleSt.pointSize = 24; } catch(e) {}
                try { titleSt.leading = 30; } catch(e) {}
                try { titleSt.justification = Justification.CENTER_ALIGN; } catch(e) {}
                try { titleSt.hyphenation = false; } catch(e) {} // Title must never hyphenate
            }
            var versoTitleSt = doc.paragraphStyles.itemByName("verso_title");
            if (versoTitleSt && versoTitleSt.isValid) {
                try { versoTitleSt.hyphenation = false; } catch(e) {}
            }
            var authorSt = doc.paragraphStyles.itemByName("author_name");
            if (authorSt && authorSt.isValid) {
                try { authorSt.pointSize = 14; } catch(e) {}
                try { authorSt.leading = 18; } catch(e) {}
                try { authorSt.justification = Justification.CENTER_ALIGN; } catch(e) {}
            }

            // Table of Contents styles
            var tocStyles = ["toc_normaltext", "part_contents_text", "toc_bold"];
            for (var ti = 0; ti < tocStyles.length; ti++) {
                var ts = doc.paragraphStyles.itemByName(tocStyles[ti]);
                if (ts && ts.isValid) {
                    try { ts.appliedFont = "Palatino Linotype"; } catch(e) {}
                    try { ts.pointSize = 9.65; } catch(e) {}
                    try { ts.leading = 13; } catch(e) {}
                    try { ts.justification = Justification.LEFT_ALIGN; } catch(e) {}
                    try { ts.hyphenation = false; } catch(e) {}
                }
            }

            // Dedicated Figure Caption style (centered, 9 pt, atomic binding)
            var figCapStyle = doc.paragraphStyles.itemByName("fig caption");
            if (!figCapStyle || !figCapStyle.isValid) {
                figCapStyle = doc.paragraphStyles.add({name: "fig caption"});
            }
            try { figCapStyle.appliedFont = "Palatino Linotype"; } catch(e) {}
            try { figCapStyle.fontStyle = "Regular"; } catch(e) {}
            try { figCapStyle.pointSize = 9; } catch(e) {}
            try { figCapStyle.leading = 11; } catch(e) {}
            try { figCapStyle.justification = Justification.CENTER_ALIGN; } catch(e) {}
            try { figCapStyle.keepWithPrevious = false; } catch(e) {}
            try { figCapStyle.spaceBefore = 4; } catch(e) {}
            try { figCapStyle.spaceAfter = 6; } catch(e) {}
            try { figCapStyle.hyphenation = false; } catch(e) {}
        } catch(eTypo) {}

        // -------------------------------------------------------------
        // 3. IMAGE INJECTION WITH ADAPTIVE SQUEEZE-TO-FIT & DEAD CENTERING
        // -------------------------------------------------------------
        doc.recompose();

        // Forward-order processing with live recomposition so every image is measured
        // and sized against the exact, true document geometry of preceding placements.
        var maxTokenSafety = 200;
        var tokenCount = 0;

        while (tokenCount < maxTokenSafety) {
            tokenCount++;
            doc.recompose();

            app.findGrepPreferences = NothingEnum.nothing;
            app.findGrepPreferences.findWhat = "###IMAGE_TOKEN: [^#]+###";
            var currentMatches = doc.findGrep();
            if (!currentMatches || currentMatches.length === 0) break;

            var m = currentMatches[0];
            try {
                var mText = m.contents;
                var pathMatch = mText.match(/path=(.+?)(?:\s*\||$)/);
                var capMatch = mText.match(/cap=(.*?)(?:\s*\|\s*style=|\s*###|$)/);
                var styleMatch = mText.match(/style=(.*?)(?:\s*###|$)/);

                if (!pathMatch) {
                    m.contents = "";
                    continue;
                }
                var imgPath = pathMatch[1].replace(/^\s+|\s+$/g, "");
                var captionText = capMatch ? capMatch[1].replace(/^\s+|\s+$/g, "") : "";
                var capStyle = styleMatch ? styleMatch[1].replace(/^\s+|\s+$/g, "") : "Regular";

                var imgFile = File(imgPath);
                if (!imgFile.exists) {
                    m.contents = "";
                    continue;
                }

                // Query geometry and remaining vertical room on host page
                var hostTF = (m.parentTextFrames && m.parentTextFrames.length > 0) ? m.parentTextFrames[0] : null;
                var colW = 316;
                var availableH = 480;
                var isTopPage = false;

                if (hostTF) {
                    var tfBounds = hostTF.geometricBounds;
                    colW = (tfBounds[3] - tfBounds[1]) - 8;
                    var page = hostTF.parentPage;
                    if (page) {
                        var topMargin = page.bounds[0] + page.marginPreferences.top;
                        var bottomMargin = page.bounds[2] - page.marginPreferences.bottom;
                        if (bottomMargin > 558) bottomMargin = 558;
                        var currentY = m.insertionPoints[0].baseline;
                        isTopPage = (currentY <= (topMargin + 40));
                        availableH = bottomMargin - currentY;
                        if (availableH < 0) availableH = 0;
                    }
                }

                // Format parent paragraph and prepare anchor insertion point
                var parentPara = m.paragraphs[0];
                var targetIns = m.insertionPoints[0];

                if (captionText.length > 0) {
                    m.contents = captionText;
                    if (figCapStyle && figCapStyle.isValid) {
                        try { parentPara.appliedParagraphStyle = figCapStyle; } catch(eP) {}
                    }
                    if (capStyle && capStyle !== "") {
                        try { parentPara.fontStyle = capStyle; } catch(eFS) {}
                        try { m.fontStyle = capStyle; } catch(eFS2) {}
                    }
                    parentPara.justification = Justification.CENTER_ALIGN;
                    parentPara.firstLineIndent = 0;
                    parentPara.leftIndent = 0;
                    parentPara.rightIndent = 0;
                    parentPara.spaceBefore = 4;
                    parentPara.spaceAfter = 6;
                    targetIns = parentPara.insertionPoints[0];
                } else {
                    m.contents = "";
                    parentPara.justification = Justification.CENTER_ALIGN;
                    parentPara.firstLineIndent = 0;
                    parentPara.leftIndent = 0;
                    parentPara.rightIndent = 0;
                    parentPara.spaceBefore = 6;
                    parentPara.spaceAfter = 6;
                    targetIns = parentPara.insertionPoints[0];
                }

                // Exact placeholder placement: place image directly at target insertion point
                var placed = targetIns.place(imgFile);
                if (!placed || placed.length === 0) continue;
                var f = placed[0].parent;

                // Retain natural unresized dimensions
                f.fit(FitOptions.FRAME_TO_CONTENT);
                try { f.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch(eTW) {}

                var gb = f.geometricBounds;
                var fw = gb[3] - gb[1];
                var fh = gb[2] - gb[0];

                // Only scale down proportionally if image exceeds printable column width or full column height
                // so it never clips or bleeds past the page margins
                var maxW = colW;
                var maxH = 480;
                var scale = 1.0;
                if (fw > maxW) scale = Math.min(scale, maxW / fw);
                if (fh > maxH) scale = Math.min(scale, maxH / fh);

                if (scale < 1.0) {
                    f.geometricBounds = [gb[0], gb[1], gb[0] + fh * scale, gb[1] + fw * scale];
                    f.fit(FitOptions.CONTENT_TO_FRAME);
                }

                f.strokeWeight = 0;
                if (noneSwatch) { try { f.strokeColor = noneSwatch; } catch(eS) {} }

                var aos = f.anchoredObjectSettings;
                aos.anchoredPosition = AnchorPosition.ABOVE_LINE;
                aos.horizontalAlignment = HorizontalAlignment.CENTER_ALIGN;
                aos.horizontalReferencePoint = AnchoredRelativeTo.COLUMN_EDGE;
                try { aos.anchorSpaceAbove = 4; } catch(eAos) {}

                try {
                    parentPara.keepAllLinesTogether = true;
                } catch(eK) {}

                doc.recompose();
            } catch(eMatch) {
                try { m.contents = ""; } catch(eClear) {}
            }
        }
        app.findGrepPreferences = NothingEnum.nothing;

        // -------------------------------------------------------------
        // 4. REMOVE BORDERS FROM FIGURE TABLES
        // -------------------------------------------------------------
        for (var s = 0; s < doc.stories.length; s++) {
            var st = doc.stories[s];
            for (var t = 0; t < st.tables.length; t++) {
                try {
                    var tb = st.tables[t];
                    var hasImg = false;
                    for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++) {
                        if (tb.cells[c0].allGraphics.length > 0) hasImg = true;
                    }
                    if (!hasImg) continue;
                    for (var c = 0; c < tb.cells.length; c++) {
                        var cell = tb.cells[c];
                        try { cell.topEdgeStrokeWeight = 0; } catch(e1) {}
                        try { cell.bottomEdgeStrokeWeight = 0; } catch(e2) {}
                        try { cell.leftEdgeStrokeWeight = 0; } catch(e3) {}
                        try { cell.rightEdgeStrokeWeight = 0; } catch(e4) {}
                        if (noneSwatch) {
                            try { cell.topEdgeStrokeColor = noneSwatch; } catch(e5) {}
                            try { cell.bottomEdgeStrokeColor = noneSwatch; } catch(e6) {}
                            try { cell.leftEdgeStrokeColor = noneSwatch; } catch(e7) {}
                            try { cell.rightEdgeStrokeColor = noneSwatch; } catch(e8) {}
                        }
                    }
                } catch(eTbl) {}
            }
        }

        // -------------------------------------------------------------
        // 4b. BREAK UN-SPLITTABLE SINGLE-CELL TEXT TABLES (Poems / Boxed Quotes)
        // -------------------------------------------------------------
        // A 1x1, text-only table that is taller than the text area or has overset
        // cannot split at row boundaries (it has only one row). Converting it to
        // ordinary flowing text lets the poem lines break across pages within margins.
        // Real data tables (multiple rows/columns) and boxes holding an image are preserved.
        var poemVictims = [];
        for (var s = 0; s < doc.stories.length; s++) {
            var st = doc.stories[s];
            for (var t = 0; t < st.tables.length; t++) {
                var tb = st.tables[t];
                try {
                    if (tb.rows.length !== 1 || tb.columns.length !== 1) continue;
                    var hasImg = false;
                    try { hasImg = (tb.cells[0].allGraphics.length > 0); } catch(eG) {}
                    if (hasImg) continue;

                    var th = pageH - 90;
                    try {
                        var pg = tb.storyOffset.parentTextFrames[0].parentPage;
                        th = pageH - pg.marginPreferences.top - pg.marginPreferences.bottom;
                    } catch(ePg) {}

                    var oset = false;
                    try { oset = tb.cells[0].overflows; } catch(eO) {}
                    if (tb.rows[0].height > (th - 40) || oset || tb.contents.length > 500) {
                        poemVictims.push(tb);
                    }
                } catch(eT) {}
            }
        }
        for (var v = 0; v < poemVictims.length; v++) {
            try { poemVictims[v].convertToText("\t", "\r"); } catch(eC) {
                try { poemVictims[v].convertToText(); } catch(eC2) {}
            }
        }

        // -------------------------------------------------------------
        // 4c. MAKE MULTI-ROW DATA TABLE BODY ROWS BREAKABLE ACROSS PAGES
        // -------------------------------------------------------------
        for (var s = 0; s < doc.stories.length; s++) {
            var st = doc.stories[s];
            for (var t = 0; t < st.tables.length; t++) {
                var tb = st.tables[t];
                try {
                    for (var r = 0; r < tb.rows.length; r++) {
                        var row = tb.rows[r];
                        try { row.autoGrow = true; } catch(eA) {}
                        var isBody = true;
                        try { isBody = (row.rowType === RowTypes.BODY_ROW); } catch(eRT) {}
                        if (isBody) {
                            try { row.keepWithNextRow = false; } catch(eK) {}
                        }
                    }
                } catch(eRows) {}
            }
        }

        // -------------------------------------------------------------
        // 5. HELPER: Calculate exact page margin bounds
        // -------------------------------------------------------------
        function getPageMarginBounds(p) {
            var top = p.marginPreferences.top;
            var bottom = pageH - p.marginPreferences.bottom;
            if (bottom > 558) bottom = 558; // Capped above running footer

            var left, right;
            if (doc.documentPreferences.facingPages && p.side === PageSideOptions.LEFT_HAND) {
                left = p.marginPreferences.right;
                right = pageW - p.marginPreferences.left;
            } else {
                left = p.marginPreferences.left;
                right = pageW - p.marginPreferences.right;
            }
            return [top, left, bottom, right];
        }

        // -------------------------------------------------------------
        // 6. REALIGN ALL EXISTING TEXT FRAMES TO PAGE MARGINS & TOP ALIGN
        // -------------------------------------------------------------
        for (var pi = 0; pi < doc.pages.length; pi++) {
            var pg = doc.pages[pi];
            if (pi === 0) continue; // Keep Page 1 (Title) custom clearance
            var targetBounds = getPageMarginBounds(pg);
            for (var fi = 0; fi < pg.textFrames.length; fi++) {
                var f = pg.textFrames[fi];
                var currentBounds = f.geometricBounds;
                var currentH = currentBounds[2] - currentBounds[0];
                var currentW = currentBounds[3] - currentBounds[1];
                if (currentH > 200 && currentW > 150) {
                    f.geometricBounds = targetBounds;
                    // Standard book typography: align text cleanly from top margin down.
                    // Never use unbounded JUSTIFY_ALIGN which creates massive accordion voids between paragraphs.
                    try {
                        f.textFramePreferences.verticalJustification = VerticalJustification.TOP_ALIGN;
                    } catch(eVJ) {}
                }
            }
        }

        // Center Copyright frame vertically on Page 2
        try {
            if (doc.pages.length >= 2) {
                var p2 = doc.pages[1];
                for (var t = 0; t < p2.textFrames.length; t++) {
                    p2.textFrames[t].textFramePreferences.verticalJustification = VerticalJustification.CENTER_ALIGN;
                }
            }
        } catch(eC) {}

        // -------------------------------------------------------------
        // 7. OVERSET RESOLUTION & THREADING (Expand & Add Pages)
        // -------------------------------------------------------------
        doc.recompose();

        // Step 7a: Expand overflowing frames on their page up to 558
        for (var s = 0; s < doc.stories.length; s++) {
            var story = doc.stories[s];
            story.recompose();
            for (var tc = 0; tc < story.textContainers.length; tc++) {
                var tf = story.textContainers[tc];
                if (tf.constructor.name === "TextFrame" && tf.overflows) {
                    var gb = tf.geometricBounds;
                    if (gb[2] < 558 && (!tf.parentPage || tf.parentPage.documentOffset > 0)) {
                        tf.geometricBounds = [gb[0], gb[1], 558, gb[3]];
                        story.recompose();
                    }
                }
            }
        }

        // Step 7b: Thread new pages with A-Master while story overflows
        for (var s = 0; s < doc.stories.length; s++) {
            var story = doc.stories[s];
            story.recompose();
            if (story.textContainers.length === 0) continue;
            // Only skip isolated frontmatter stories (e.g. title or copyright single frame)
            if (story.textContainers.length === 1 && story.characters.length < 1000) continue;

            var lastTf = story.textContainers[story.textContainers.length - 1];
            if (lastTf.constructor.name !== "TextFrame") continue;

            var safety = 0;
            while ((lastTf.overflows || story.overflows) && safety < 800) {
                safety++;
                var newPage = doc.pages.add(LocationOptions.AT_END);
                try {
                    if (doc.masterSpreads.itemByName("A-Master").isValid) {
                        newPage.appliedMaster = doc.masterSpreads.itemByName("A-Master");
                    }
                } catch(eM) {}

                var newTf = newPage.textFrames.add();
                newTf.geometricBounds = getPageMarginBounds(newPage);
                lastTf.nextTextFrame = newTf;
                lastTf = newTf;
                story.recompose();
            }
        }

        // -------------------------------------------------------------
        // 8. EVEN PAGE COUNT (Print spread requirement)
        // -------------------------------------------------------------
        if (doc.pages.length % 2 !== 0) {
            var blankPage = doc.pages.add(LocationOptions.AT_END);
            blankPage.appliedMaster = null;
        }

        // Recompose full document
        doc.recompose();

        // Save updated IDML
        try {
            doc.exportFile(ExportFormat.INDESIGN_MARKUP, idmlFile);
        } catch(eSave) {}

        // -------------------------------------------------------------
        // 9. PDF/X EXPORT (Two-Page Facing Spreads)
        // -------------------------------------------------------------
        try {
            doc.pdfExportPreferences.pageLayoutOptions = PageLayoutOptions.TWO_UP_FACING;
        } catch(eL) {}

        var preset = app.pdfExportPresets.item("[PDF/X-1a:2001]");
        if (!preset.isValid) {
            preset = app.pdfExportPresets.item("[PDF/X-4:2010]");
        }
        if (!preset.isValid) {
            preset = app.pdfExportPresets.item("[High Quality Print]");
        }

        doc.exportFile(ExportFormat.PDF_TYPE, outputPdf, false, preset);
        doc.close(SaveOptions.NO);

    } catch (err) {
        try { doc.close(SaveOptions.NO); } catch(eClose) {}
        throw err;
    }
})();

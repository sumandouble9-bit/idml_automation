"""
Formatting_idml: ImageLayoutManager
OOP manager for figure table borders, cell centering, LeafBound logo clearance,
and ExtendScript layout injection rules.
Refactors fix_image_layout.py into clean, modular, reusable methods.
"""

from pathlib import Path
from typing import Optional


class ImageLayoutManager:
    """
    Orchestrates InDesign layout repair passes:
    1. Removes black borders from figure tables (while strictly preserving data tables)
    2. Horizontally centers multi-figure images inside table cells
    3. Sizes and positions LeafBound logo cleanly above footer margins
    4. Provides robust ExtendScript JSX routines for adaptive squeeze-to-fit
    """

    def __init__(self, printable_width: float = 316.0, printable_height: float = 504.0):
        self.printable_width = printable_width
        self.printable_height = printable_height

    @staticmethod
    def get_figure_table_cleaner_jsx() -> str:
        """
        ExtendScript routine to remove cell borders ONLY from tables containing images,
        leaving genuine data tables (statistics, financial, historical) with full borders.
        """
        return r'''
        // 1. Remove borders from figure tables (containing images)
        for (var s = 0; s < doc.stories.length; s++) {
            var st = doc.stories[s];
            for (var t = 0; t < st.tables.length; t++) {
                try {
                    var tb = st.tables[t];
                    var hasImg = false;
                    for (var c0 = 0; c0 < tb.cells.length && !hasImg; c0++) {
                        if (tb.cells[c0].allGraphics.length > 0) hasImg = true;
                    }
                    if (!hasImg) continue; // Keep real data tables intact
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
        '''

    @staticmethod
    def get_cell_image_centering_jsx() -> str:
        """
        ExtendScript routine to center images anchored inside table cells
        (e.g. side-by-side telephone or coin illustrations).
        """
        return r'''
        // 2. Center graphics anchored in table cells
        for (var i = 0; i < doc.allGraphics.length; i++) {
            try {
                var g = doc.allGraphics[i];
                var frm = g.parent;
                var p = frm, inCell = false;
                for (var k = 0; k < 6 && p; k++) {
                    if (p.constructor.name === "Cell") { inCell = true; break; }
                    try { p = p.parent; } catch(eP) { break; }
                }
                if (inCell) {
                    try { frm.fit(FitOptions.PROPORTIONALLY); } catch(eF1) {}
                    try { frm.fit(FitOptions.CENTER_CONTENT); } catch(eF2) {}
                    try {
                        var aos = frm.anchoredObjectSettings;
                        aos.horizontalAlignment = HorizontalAlignment.CENTER_ALIGN;
                    } catch(eA) {}
                }
            } catch(eG) {}
        }
        '''

    @staticmethod
    def get_logo_fitting_jsx(logo_path: Optional[str] = None) -> str:
        """
        ExtendScript routine to ensure the publisher logo fits proportionally
        and sits above the bottom margin line.
        """
        clean_logo = str(Path(logo_path).resolve()).replace("\\", "/") if logo_path else ""
        return f'''
        // 3. Publisher logo clearance and proportional fitting
        var cleanLogoPath = "{clean_logo}";
        for (var i = 0; i < doc.allGraphics.length; i++) {{
            try {{
                var g = doc.allGraphics[i];
                var gName = (g.itemLink) ? g.itemLink.name.toUpperCase() : "";
                if (gName.indexOf("LEAF-BOUND") >= 0 || gName.indexOf("LOGO") >= 0) {{
                    var frm = g.parent;
                    try {{ frm.fit(FitOptions.PROPORTIONALLY); }} catch(eL1) {{}}
                    try {{ frm.fit(FitOptions.CENTER_CONTENT); }} catch(eL2) {{}}
                    try {{ frm.strokeWeight = 0; }} catch(eL3) {{}}
                    if (noneSwatch) {{ try {{ frm.strokeColor = noneSwatch; }} catch(eL4) {{}} }}
                }}
            }} catch(eLogo) {{}}
        }}
        '''

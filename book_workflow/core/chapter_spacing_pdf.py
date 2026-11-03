import argparse
import math
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from toc_synchronizer import sync_idml_toc_from_pdf
except ImportError:
    try:
        from .toc_synchronizer import sync_idml_toc_from_pdf
    except ImportError:
        sync_idml_toc_from_pdf = None

try:
    from chapter_spacing_common import *
except ImportError:
    from .chapter_spacing_common import *


def get_indesign_app():
    """Acquire InDesign application instance via COM with graceful recovery and restart support."""
    import win32com.client
    # 1. Try active running instance
    for name in ["InDesign.Application.2025", "InDesign.Application"]:
        try:
            app = win32com.client.GetActiveObject(name)
            if app:
                return app
        except Exception:
            pass
            
    # 2. Try Dispatch
    for name in ["InDesign.Application.2025", "InDesign.Application"]:
        try:
            app = win32com.client.Dispatch(name)
            if app:
                return app
        except Exception:
            pass
            
    # 3. Clean restart via convert_to_pdf
    scripts_dir = Path(__file__).resolve().parent.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        from convert_to_pdf import restart_indesign
        return restart_indesign(wait_seconds=3)
    except Exception:
        pass
        
    raise RuntimeError("Could not connect to or start Adobe InDesign. Please ensure Adobe InDesign is installed.")


def export_idml_to_pdf(idml_path: str | Path, pdf_path: str | Path, app=None) -> bool:
    """Export an IDML document to High Quality Print PDF using Adobe InDesign."""
    src = Path(idml_path).resolve().as_posix()
    dst = Path(pdf_path).resolve().as_posix()
    
    for attempt in range(2):
        try:
            if app is None:
                app = get_indesign_app()
            jsx = f"""
            try {{
                app.scriptPreferences.userInteractionLevel = 1699640946;
                var doc = app.open(new File("{src}"));

                // User Requirement: if content is not showing full content, increase text frame preserving other formatting
                var didGrow = false;
                for (var s = 0; s < doc.stories.length; s++) {{
                    var story = doc.stories[s];
                    story.recompose();
                    for (var f = 0; f < story.textContainers.length; f++) {{
                        var tf = story.textContainers[f];
                        if (tf.constructor.name === "TextFrame" && tf.overflows) {{
                            var page = tf.parentPage;
                            var maxB = page ? (doc.documentPreferences.pageHeight - page.marginPreferences.bottom) : (tf.geometricBounds[2] + 72);
                            var gb = tf.geometricBounds;
                            if (gb[2] < maxB) {{
                                tf.geometricBounds = [gb[0], gb[1], maxB, gb[3]];
                                story.recompose();
                                didGrow = true;
                            }}
                            var step = 0;
                            while (tf.overflows && step < 15) {{
                                var cgb = tf.geometricBounds;
                                tf.geometricBounds = [cgb[0], cgb[1], cgb[2] + 36, cgb[3]];
                                story.recompose();
                                didGrow = true;
                                step++;
                            }}
                        }}
                    }}
                }}
                if (didGrow) {{
                    try {{ doc.save(new File("{src}")); }} catch(eSave) {{}}
                }}

                var pdfPreset = app.pdfExportPresets.itemByName("[High Quality Print]");
                if (!pdfPreset.isValid) {{
                    pdfPreset = app.pdfExportPresets[0];
                }}
                try {{
                    app.pdfExportPreferences.properties = pdfPreset.properties;
                    app.pdfExportPreferences.useDocumentBleedWithPDF = true;
                    doc.exportFile(ExportFormat.PDF_TYPE, new File("{dst}"), false);
                }} catch(eBleed) {{
                    doc.exportFile(ExportFormat.PDF_TYPE, new File("{dst}"), false, pdfPreset);
                }}
                doc.close(SaveOptions.NO);
                "OK";
            }} catch(e) {{
                "ERR:" + e.message;
            }}
            """
            res = app.DoScript(jsx, 1246973031)
            if str(res) == "OK":
                return True
        except Exception:
            if attempt == 0:
                try:
                    scripts_dir = Path(__file__).resolve().parent.parent
                    if str(scripts_dir) not in sys.path:
                        sys.path.insert(0, str(scripts_dir))
                    from convert_to_pdf import restart_indesign
                    app = restart_indesign(wait_seconds=3)
                except Exception:
                    app = None
            else:
                return False
    return False


__all__ = [
    'get_indesign_app',
    'export_idml_to_pdf',
]

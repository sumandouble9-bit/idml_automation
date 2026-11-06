import time
import subprocess

import win32com.client

JS = 1246973031


def connect(attempts=3):
    """Connect to InDesign via COM, killing a stuck instance once if needed; return the app or None."""
    for attempt in range(attempts):
        try:
            app = win32com.client.Dispatch("InDesign.Application")
            app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", JS)
            return app
        except Exception:
            time.sleep(3)
            if attempt == 1:
                subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
                time.sleep(3)
    return None


def open_doc(app, path):
    """Open an IDML with redraw and smart text reflow disabled."""
    p = path.replace("\\", "/")
    app.DoScript(
        'app.scriptPreferences.enableRedraw=false;'
        'var d=app.open(new File("%s"));'
        'try{d.textPreferences.smartTextReflow=false;}catch(e){}'
        'try{d.recompose();}catch(e){}' % p,
        JS,
    )


def page_count(app):
    """Return the open document's page count."""
    try:
        return int(app.DoScript('app.activeDocument.pages.length+"";', JS))
    except Exception:
        return 0


def export_idml(app, path):
    """Export the active document as IDML."""
    p = path.replace("\\", "/")
    app.DoScript('app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, new File("%s"));' % p, JS)


def export_pdf(app, path):
    """Export the active document to PDF with the High Quality Print preset."""
    p = path.replace("\\", "/")
    app.DoScript(
        'var pr=app.pdfExportPresets.itemByName("[High Quality Print]");'
        'if(!pr.isValid)pr=app.pdfExportPresets[0];'
        'app.activeDocument.exportFile(ExportFormat.PDF_TYPE, new File("%s"), false, pr);' % p,
        JS,
    )


def close_doc(app):
    """Close the active document without saving."""
    app.DoScript("app.activeDocument.close(SaveOptions.NO);", JS)

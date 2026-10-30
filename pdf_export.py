JS = 1246973031


def export_pdf(app, pdf_path, preset_name="[High Quality Print]"):
    """Export the active document to a print-quality PDF using a named preset."""
    target = pdf_path.replace(chr(92), "/")
    js = (
        'try { app.pdfExportPreferences.pageRange = PageRange.ALL_PAGES; } catch(e){}'
        'var preset = app.pdfExportPresets.itemByName("%s");'
        'if (!preset.isValid) preset = app.pdfExportPresets[0];'
        'app.activeDocument.exportFile(ExportFormat.PDF_TYPE, new File("%s"), false, preset);'
        % (preset_name, target)
    )
    app.DoScript(js, JS)


def close_doc(app):
    """Close the active document without saving."""
    app.DoScript("app.activeDocument.close(SaveOptions.NO);", JS)

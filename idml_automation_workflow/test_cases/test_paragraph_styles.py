import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "image_inject"))
import win32com.client
import fix_paragraph_styles

JS = 1246973031


def _probe(app, needle):
    # Return "style|justification" of the first paragraph containing needle.
    js = (
        'var doc=app.activeDocument;'
        'app.findTextPreferences=NothingEnum.nothing;'
        'app.findTextPreferences.findWhat=%r;'
        'var f=doc.findText();'
        'var r="NOTFOUND";'
        'if(f.length){var p=f[0].paragraphs[0];'
        'var s="";try{s=p.appliedParagraphStyle.name;}catch(e){}'
        'var j="";try{j=String(p.justification);}catch(e){}'
        'r=s+"|"+j;}'
        'r;' % needle
    )
    return str(app.DoScript(js, JS))


def run_case(app, idml_path, epub_path, scenarios):
    app.DoScript('app.open(new File("%s"));' % idml_path.replace(chr(92), "/"), JS)
    print("result:", fix_paragraph_styles.run(app, epub_path))
    passed = True
    for needle, expect_style, expect_just in scenarios:
        got = _probe(app, needle)
        style, _, just = got.partition("|")
        ok_style = (expect_style is None) or (expect_style.lower() in style.lower())
        ok_just = (expect_just is None) or (expect_just.lower() in just.lower())
        ok = ok_style and ok_just
        passed = passed and ok
        print("  [%s] %-34s -> style=%s just=%s (want style~%s just~%s)"
              % ("PASS" if ok else "FAIL", repr(needle)[:34], style, just, expect_style, expect_just))
    try:
        app.DoScript("app.activeDocument.close(SaveOptions.NO);", JS)
    except Exception:
        pass
    return passed


if __name__ == "__main__":
    app = win32com.client.Dispatch("InDesign.Application")
    try:
        app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", JS)
    except Exception:
        pass
    WF = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))

    def find(isbn):
        for c in [_os.path.join(WF, "final_output_files", "idml_files", isbn + "_injected.idml"),
                  _os.path.join(WF, "final_output_files", "rejected_files", "idml_files", isbn + "_injected.idml")]:
            if _os.path.exists(c):
                return c
        return None

    isbn = "9789361422768"
    idml = find(isbn)
    epub = _os.path.join(WF, "..", "epub_input_files", isbn + ".epub")
    print("book:", isbn, "idml:", idml)
    scenarios = [
        ("Perhaps no poet is a conscious", "body_text", None),   # normal para un-stuck from block
        ("Come forth from thy oozy",       "quotes",    None),   # real block stays block
        ("A sweltering day in Australia",  None,        "CENTER"),# center re-applied
    ]
    ok = run_case(app, idml, epub, scenarios)
    print("\nOVERALL:", "PASS" if ok else "FAIL")

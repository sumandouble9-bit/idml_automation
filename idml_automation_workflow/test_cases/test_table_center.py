import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import win32com.client
try:
    import table_center_format as fix_table_center
except ImportError:
    import fix_table_center

JS = 1246973031


def _probe(app, needle):
    js = ('var doc=app.activeDocument;app.findTextPreferences=NothingEnum.nothing;'
          'app.findTextPreferences.findWhat=%r;var f=doc.findText();'
          'f.length?String(f[0].paragraphs[0].leftIndent):"NF";' % needle)
    try:
        return float(app.DoScript(js, JS))
    except Exception:
        return None


def _narrow_table_indents(app):
    js = (r'var doc=app.activeDocument;var out=[];'
          r'for(var s=0;s<doc.stories.length;s++){var st=doc.stories[s];'
          r'for(var t=0;t<st.tables.length;t++){var tb=st.tables[t];'
          r'var w=0;for(var c=0;c<tb.columns.length;c++)w+=tb.columns[c].width;'
          r'var fw=324;try{var g=tb.storyOffset.parentTextFrames[0].geometricBounds;fw=g[3]-g[1];}catch(e){}'
          r'if(w<fw-14)out.push(tb.storyOffset.paragraphs[0].leftIndent.toFixed(1));}}out.join(",");')
    return [float(x) for x in str(app.DoScript(js, JS)).split(",") if x]


def run_case(app, idml_path, body_needles):
    app.DoScript('app.open(new File("%s"));' % idml_path.replace(chr(92), "/"), JS)
    print("result:", fix_table_center.run(app))
    ok = True
    narrow = _narrow_table_indents(app)
    centered = [x for x in narrow if x > 1]
    c1 = len(centered) > 0
    print("  [%s] narrow tables centered: %d/%d (leftIndent>0)" % ("PASS" if c1 else "FAIL", len(centered), len(narrow)))
    ok = ok and c1
    for nd in body_needles:
        li = _probe(app, nd)
        c = (li is not None and li == 0)
        print("  [%s] body %-34s leftIndent=%s (want 0)" % ("PASS" if c else "FAIL", repr(nd)[:34], li))
        ok = ok and c
    try:
        app.DoScript("app.activeDocument.close(SaveOptions.NO);", JS)
    except Exception:
        pass
    return ok


if __name__ == "__main__":
    app = win32com.client.Dispatch("InDesign.Application")
    try:
        app.DoScript("app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;", JS)
    except Exception:
        pass
    WF = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    isbn = "9789361422768"
    idml = None
    for c in [_os.path.join(WF, "final_output_files", "idml_files", isbn + "_injected.idml"),
              _os.path.join(WF, "final_output_files", "rejected_files", "idml_files", isbn + "_injected.idml")]:
        if _os.path.exists(c):
            idml = c
            break
    print("book:", isbn, "idml:", idml)
    ok = run_case(app, idml, ["The item in the above list", "I was in Adelaide again"])
    print("\nOVERALL:", "PASS" if ok else "FAIL")

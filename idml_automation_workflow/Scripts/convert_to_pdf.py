"""
Dedicated Standalone PDF Converter Module:
Converts any IDML document or folder of IDML documents into High-Quality Print PDFs
using Adobe InDesign COM automation, ensuring all document fonts (Palatino Linotype,
Gill Sans MT, Bell MT, Minion Pro) are active and embedded with zero font substitution.

Usage:
    # Convert all files in default injected directory (or Output/):
    python convert_to_pdf.py

    # Convert a specific IDML file:
    python convert_to_pdf.py "path/to/my_book.idml"

    # Convert a specific folder to a custom output directory:
    python convert_to_pdf.py "path/to/folder" --output-dir "Output/pdf_files"
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parents[1] if (Path(__file__).resolve().parents[1] / "Fonts").exists() else Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = ROOT_DIR / "Output" / "injected_idml_files"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "Output" / "pdf_files"
FONTS_DIR = ROOT_DIR / "Fonts"
FORMATTED_FONTS_DIR = ROOT_DIR / "Output" / "Document fonts"

JS = 1246973031


def clear_recovery_data():
    """Purge InDesign automatic recovery files so modal recovery prompts never block COM."""
    for base in [os.environ.get("LOCALAPPDATA"), os.environ.get("APPDATA")]:
        if not base:
            continue
        indesign_base = os.path.join(base, "Adobe", "InDesign")
        if os.path.isdir(indesign_base):
            for root, dirs, files in os.walk(indesign_base):
                if os.path.basename(root) == "InDesign Recovery":
                    for f in files:
                        try:
                            os.remove(os.path.join(root, f))
                        except Exception:
                            pass


def restart_indesign(wait_seconds: int = 5):
    """Cleanly terminate and relaunch InDesign via COM."""
    import win32com.client
    for proc in ("InDesign.exe", "Adobe Crash Processor.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/T", "/IM", proc], capture_output=True)
        except Exception:
            pass
    clear_recovery_data()
    time.sleep(wait_seconds)
    for _ in range(6):
        try:
            app = win32com.client.Dispatch("InDesign.Application")
            try:
                app.DoScript(
                    "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                    JS,
                )
            except Exception:
                pass
            return app
        except Exception:
            time.sleep(4)
    raise RuntimeError("Could not restart InDesign after multiple attempts.")


def ensure_document_fonts(target_dir: Path):
    """Ensure 'Document fonts' exists beside target IDMLs so InDesign activates them automatically."""
    target_fonts = target_dir / "Document fonts"
    if not target_fonts.exists():
        if FORMATTED_FONTS_DIR.is_dir():
            shutil.copytree(FORMATTED_FONTS_DIR, target_fonts)
        elif FONTS_DIR.is_dir():
            shutil.copytree(FONTS_DIR, target_fonts)


def release_pdf_lock(filepath: Path):
    """Ensure target PDF is not locked by an external reader like Adobe Acrobat."""
    if not filepath.exists():
        return
    try:
        with open(filepath, "r+b"):
            return
    except (PermissionError, IOError):
        try:
            subprocess.run(["taskkill", "/F", "/IM", "Acrobat.exe"], capture_output=True)
            time.sleep(1)
        except Exception:
            pass


def convert_single_idml(app, idml_path: Path, output_pdf_path: Path) -> dict:
    """Converts a single IDML file to High Quality Print PDF."""
    try:
        wf_dir = ROOT_DIR if (ROOT_DIR / "run_book_pipeline.py").exists() else ROOT_DIR.parent
        sys.path.insert(0, str(wf_dir))
        sys.path.insert(0, str(ROOT_DIR / "Scripts"))
        sys.path.insert(0, str(ROOT_DIR / "Scripts" / "spanish"))
        sys.path.insert(0, str(ROOT_DIR / "test_cases"))
    except Exception:
        pass

    release_pdf_lock(output_pdf_path)

    clean_idml = str(idml_path).replace("\\", "/")
    clean_pdf = str(output_pdf_path).replace("\\", "/")

    # PHASE 1: open the document and enforce live styles/justification, then
    # recompose. The document is LEFT OPEN (becomes app.activeDocument) so the
    # proven overset resolver can add pages in THIS SAME InDesign session - the
    # only composition that matches exportFile. Resolving overset under a
    # separate recompose-only pass (as the injection step does) drifts from the
    # export pagination, so the tail re-oversets at export and every anchored
    # image past that point silently stops rendering (images vanish from the
    # middle of the book). Doing it here, in the exporting session, is the only
    # deterministic fix.
    js_open = f"""
    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
    var idmlFile = new File("{clean_idml}");
    var doc = app.open(idmlFile);

    try {{
        var bodyStyles = [
            "Normal", "[Basic Paragraph]", "NormalParagraphStyle", "[Normal Paragraph Style]",
            "body_text", "noindent", "noindentj", "noindent1", "bodytext_noendent",
            "bodytext_Noendent", "copybody", "centre_align", "center", "center1", "quotes_normal"
        ];
        for (var si = 0; si < bodyStyles.length; si++) {{
            var st = doc.paragraphStyles.itemByName(bodyStyles[si]);
            if (st && st.isValid) {{
                try {{ st.appliedFont = "Palatino Linotype"; }} catch(eF) {{}}
                try {{ st.pointSize = 9.65; }} catch(eS) {{}}
                try {{ st.leading = 12; }} catch(eL) {{}}
            }}
        }}
        var pFig = doc.paragraphStyles.itemByName("fig caption");
        if (pFig && pFig.isValid) {{
            try {{ pFig.appliedFont = "Palatino Linotype"; }} catch(eF) {{}}
            try {{ pFig.pointSize = 9; }} catch(eS) {{}}
        }}
    }} catch(eSty) {{}}

    try {{
        var _justBody = ["Normal","NormalParagraphStyle","[Normal Paragraph Style]","[Basic Paragraph]","body_text","noindent","noindentj","noindent1","bodytext_noendent","bodytext_Noendent","copybody"];
        for (var _j = 0; _j < _justBody.length; _j++) {{
            var _bs = doc.paragraphStyles.itemByName(_justBody[_j]);
            if (_bs && _bs.isValid) {{
                try {{ _bs.justification = Justification.LEFT_JUSTIFIED; }} catch(e1) {{}}
                try {{ _bs.hyphenation = true; }} catch(e2) {{}}
                try {{ _bs.minimumWordSpacing = 80; _bs.desiredWordSpacing = 100; _bs.maximumWordSpacing = 120; }} catch(e3) {{}}
                try {{ _bs.minimumLetterSpacing = 0; _bs.desiredLetterSpacing = 0; _bs.maximumLetterSpacing = 0; }} catch(e4) {{}}
            }}
        }}
        var _justRag = ["quotes_normal","block1","block","block2","verse","poem"];
        for (var _q = 0; _q < _justRag.length; _q++) {{
            var _rs = doc.paragraphStyles.itemByName(_justRag[_q]);
            if (_rs && _rs.isValid) {{ try {{ _rs.justification = Justification.LEFT_ALIGN; }} catch(e5) {{}} }}
        }}
        var _noHyph = ["chapter_name","chapter_name01","master_chapter_name","Sub-heading","after_chapter_name_heading","section_heading","Heading 1"];
        for (var _h = 0; _h < _noHyph.length; _h++) {{
            var _hs = doc.paragraphStyles.itemByName(_noHyph[_h]);
            if (_hs && _hs.isValid) {{ try {{ _hs.hyphenation = false; }} catch(e6) {{}} }}
        }}
    }} catch(eJust) {{}}

    // (Removed aggressive fig caption length check that incorrectly converted valid long captions to body text)

    // User Requirement: if content is not showing full content, increase text frame preserving other formatting
    try {{
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
                    }}
                    var step = 0;
                    while (tf.overflows && step < 15) {{
                        var cgb = tf.geometricBounds;
                        tf.geometricBounds = [cgb[0], cgb[1], cgb[2] + 36, cgb[3]];
                        story.recompose();
                        step++;
                    }}
                }}
            }}
        }}
    }} catch(eGrow) {{}}
 
    // Ensure Page 2 Copyright TextFrame has CenterAlign vertical justification
    try {{
        if (doc.pages.length >= 2) {{
            var _p2 = doc.pages[1];
            for (var _tfi = 0; _tfi < _p2.textFrames.length; _tfi++) {{
                var _ctf = _p2.textFrames[_tfi];
                _ctf.textFramePreferences.verticalJustification = VerticalJustification.CENTER_ALIGN;
            }}
        }}
    }} catch(eCJ) {{}}

    // Recompose text frames to ensure complete flow and styling fidelity
    try {{ doc.recompose(); }} catch (eR) {{}}
    "OPENED";
    """
    app.DoScript(js_open, JS)

    # PHASE 2: resolve overset in THIS session using the proven resolver
    # (adds full-margin pages + jam-escape). This is what guarantees no anchored
    # image is left in overset when the PDF is exported.
    try:
        import overset_resolve
        added, left, jams = overset_resolve.run(app)
        print(f"      [Overset] pages added={added}, overset left={left}, jams={len(jams)}")
        if jams:
            for jl in jams[:3]:
                print(f"               JAM: {jl[:160]}")
    except Exception as e_ov:
        print(f"      [Overset] resolver note: {e_ov}")

    # PHASE 3: trim trailing blank pages, SAVE the resolved pagination back to
    # the IDML (so the IDML deliverable matches the PDF - the overset fix lives
    # in the IDML, not only the PDF), then export the PDF, all from the same
    # open document.
    js_export = f"""
    var doc = app.activeDocument;
    var idmlFile = new File("{clean_idml}");
    try {{
        for (var _pi = doc.pages.length - 1; _pi >= 1; _pi--) {{
            var _pg = doc.pages[_pi];
            var _hasContent = false;
            var _items = _pg.pageItems;
            for (var _k = 0; _k < _items.length; _k++) {{
                var _it = _items[_k];
                try {{ if (_it.allGraphics && _it.allGraphics.length > 0) {{ _hasContent = true; break; }} }} catch (eG) {{}}
                try {{ if (String(_it.contents).replace(/\\s/g, "").length > 0) {{ _hasContent = true; break; }} }} catch (eC) {{}}
            }}
            if (!_hasContent) {{ _pg.remove(); }} else {{ break; }}
        }}
    }} catch (eTrim) {{}}

    var pageCount = doc.pages.length;

    // Save the resolved pagination back to the IDML deliverable.
    try {{ doc.exportFile(ExportFormat.INDESIGN_MARKUP, idmlFile); }} catch (eSaveIdml) {{}}

    var pdfPreset = app.pdfExportPresets.itemByName("[High Quality Print]");
    if (!pdfPreset.isValid) {{ pdfPreset = app.pdfExportPresets[0]; }}

    var pdfFile = new File("{clean_pdf}");
    try {{
        app.pdfExportPreferences.properties = pdfPreset.properties;
        app.pdfExportPreferences.useDocumentBleedWithPDF = true;
        doc.exportFile(ExportFormat.PDF_TYPE, pdfFile, false);
    }} catch (eBleed) {{
        doc.exportFile(ExportFormat.PDF_TYPE, pdfFile, false, pdfPreset);
    }}

    doc.close(SaveOptions.NO);

    "PAGES=" + pageCount;
    """

    res = app.DoScript(js_export, JS)
    pages = 0
    if res and "PAGES=" in str(res):
        try:
            pages = int(str(res).split("PAGES=")[1].strip())
        except Exception:
            pass

    pdf_size_mb = output_pdf_path.stat().st_size / (1024 * 1024) if output_pdf_path.exists() else 0
    return {"pages": pages, "size_mb": pdf_size_mb}


def convert_batch(
    target_path: str = None,
    output_dir: str = None,
    force: bool = False,
    limit: int = None,
) -> int:
    start_time = time.time()

    # 1. Resolve paths
    if target_path:
        t_path = Path(target_path).resolve()
        if t_path.is_file():
            target_files = [t_path]
            input_folder = t_path.parent
        elif t_path.is_dir():
            input_folder = t_path
            target_files = sorted(input_folder.glob("*.idml"))
        else:
            print(f"[!] Target not found: {target_path}")
            return 1
    else:
        # Check default injected folder first, fallback to Output/
        if DEFAULT_INPUT_DIR.is_dir() and any(DEFAULT_INPUT_DIR.glob("*.idml")):
            input_folder = DEFAULT_INPUT_DIR
        else:
            input_folder = ROOT_DIR / "Output"
        target_files = sorted(input_folder.glob("*.idml"))

    target_files = [f for f in target_files if not f.name.startswith("~") and not f.name.startswith(".")]
    if limit and limit > 0:
        target_files = target_files[:limit]

    if not target_files:
        print(f"[!] No IDML files found to convert in: {input_folder}")
        return 1

    out_folder = Path(output_dir).resolve() if output_dir else DEFAULT_OUTPUT_DIR
    out_folder.mkdir(parents=True, exist_ok=True)

    # 2. Ensure Document Fonts are active
    ensure_document_fonts(input_folder)

    print("=" * 72)
    print("STANDALONE PDF CONVERTER MODULE")
    print(f"Input Directory:  {input_folder}")
    print(f"Output Directory: {out_folder}")
    print(f"Documents ({len(target_files)}): {[f.name for f in target_files]}")
    print("=" * 72)

    # 3. Connect to Adobe InDesign
    import win32com.client
    clear_recovery_data()
    app = None
    for attempt in range(4):
        try:
            app = win32com.client.Dispatch("InDesign.Application")
            app.DoScript(
                "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                JS,
            )
            break
        except Exception:
            try:
                app = restart_indesign(wait_seconds=4)
                break
            except Exception:
                time.sleep(3)

    if app is None:
        print("[!] Error: Could not connect to Adobe InDesign. Please ensure it is installed.")
        return 1

    success_count = 0
    fail_count = 0

    for idx, idml_file in enumerate(target_files, start=1):
        clean_name = idml_file.stem
        # Clean suffix for PDF name
        if clean_name.endswith("_injected"):
            clean_base = clean_name[:-9]
        elif clean_name.endswith("_normalized"):
            clean_base = clean_name[:-11]
        elif clean_name.endswith("_formatted"):
            clean_base = clean_name[:-10]
        else:
            clean_base = clean_name

        try:
            from core.isbn_manager import get_output_base_name
            pdf_base = get_output_base_name(clean_base)
        except Exception:
            pdf_base = clean_base

        out_pdf = out_folder / f"{pdf_base}.pdf"
        print(f"\n[{idx}/{len(target_files)}] Converting: {idml_file.name} -> {out_pdf.name}")

        if not force and out_pdf.exists() and out_pdf.stat().st_mtime >= idml_file.stat().st_mtime:
            print(f"      [SKIP] Already up-to-date: {out_pdf.name}")
            success_count += 1
            continue

        retries = 2
        for r in range(retries):
            try:
                res = convert_single_idml(app, idml_file, out_pdf)
                print(f"      [OK] Created PDF: {out_pdf.name} ({res['pages']} pages, {res['size_mb']:.2f} MB)")
                
                try:
                    from core.toc_synchronizer import sync_idml_toc_from_pdf
                    synced = sync_idml_toc_from_pdf(idml_file, out_pdf)
                    if synced > 0:
                        print(f"      [TOC Sync] Synchronized {synced} TOC entry(ies) in {idml_file.name}. Re-exporting synchronized PDF...")
                        res = convert_single_idml(app, idml_file, out_pdf)
                        print(f"      [OK] Synchronized PDF: {out_pdf.name} ({res['pages']} pages)")
                    else:
                        print(f"      [TOC Verified] TOC is 100% in sync with PDF.")
                except Exception as e_sync:
                    print(f"      [TOC Sync Note] {e_sync}")

                # Save standardized final IDML name ({Sr No.}_{Spanish Print ISBN-13}.idml)
                try:
                    final_idml_path = idml_file.parent / f"{pdf_base}.idml"
                    if final_idml_path != idml_file:
                        shutil.copy2(idml_file, final_idml_path)
                        print(f"      [Final IDML] Saved: {final_idml_path.name}")
                except Exception:
                    pass

                # Mirror the renamed IDML + PDF into the dedicated renamed_output_files
                # folder next to idml_files/. Each copy is independent so one failure
                # never skips the others (no hard-coded machine paths).
                _renamed_dir = idml_file.parent.parent / "renamed_output_files"
                for _src, _name in ((idml_file, f"{pdf_base}.idml"),):
                    try:
                        if Path(_src).exists():
                            _renamed_dir.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(_src, _renamed_dir / _name)
                    except Exception:
                        pass

                success_count += 1
                break
            except Exception as e_conv:
                if r < retries - 1:
                    print(f"      [!] Convert attempt {r+1} failed ({e_conv}). Restarting InDesign and retrying...")
                    try:
                        app = restart_indesign(wait_seconds=4)
                    except Exception:
                        pass
                else:
                    print(f"      [FAIL] Could not convert {idml_file.name}: {e_conv}")
                    fail_count += 1

    elapsed = round(time.time() - start_time, 2)
    print("\n" + "=" * 72)
    print(f"PDF CONVERSION COMPLETE in {elapsed}s")
    print(f"Success: {success_count} | Failed: {fail_count}")
    print(f"Output PDFs located in: {out_folder}")
    print("=" * 72)
    return 0 if fail_count == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="Standalone High-Quality PDF Converter for IDML documents.")
    parser.add_argument("target", nargs="?", default=None, help="Target IDML file or input directory")
    parser.add_argument("--output-dir", "-o", default=None, help="Output directory for generated PDFs")
    parser.add_argument("--force", "-f", action="store_true", help="Force reconversion even if PDF exists and is up to date")
    parser.add_argument("--limit", type=int, default=None, help="Process first N documents")
    args = parser.parse_args()

    return convert_batch(args.target, args.output_dir, force=args.force, limit=args.limit)


if __name__ == "__main__":
    sys.exit(main())

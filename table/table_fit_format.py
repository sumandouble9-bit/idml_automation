import os
import sys
import time
import subprocess
from datetime import datetime

import win32com.client

JS = 1246973031

try:
    import table_scripts as ts
except ImportError:
    from . import table_scripts as ts


def _is_rpc_error(exc: Exception) -> bool:
    """True if the exception is an InDesign COM hang/crash/modal condition worth restarting for."""
    s = str(exc).lower()
    return (
        "remote procedure call" in s
        or "rpc server" in s
        or "-2147023170" in s
        or "-2147023174" in s
        or "call was rejected" in s
        or "modal dialog or alert is active" in s
        or "30486" in s
    )


def restart_indesign(wait_seconds: int = 6):
    """Force-kill InDesign, relaunch it, and return a fresh COM Application object."""
    print("  [restart] Killing InDesign.exe ...", flush=True)
    for proc in ("InDesign.exe", "Adobe Crash Processor.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True)
        except Exception:
            pass
    time.sleep(wait_seconds)
    print("  [restart] Relaunching InDesign via COM ...", flush=True)
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
            print("  [restart] InDesign is back.", flush=True)
            return app
        except Exception:
            time.sleep(5)
    raise RuntimeError("Could not restart InDesign after multiple attempts")


def _break_poem_tables(app):
    """Split poem/verse tables so they can break across pages instead of overflowing."""
    return app.DoScript(ts._break_poem_tables_js(), JS)

def _fix_tables_and_breakable(app):
    """Resize table columns/insets to fit the text and mark rows breakable across pages."""
    return app.DoScript(ts._fix_tables_and_breakable_js(), JS)

def _fix_vertical(app):
    """Reflow tables vertically so a tall table splits across pages rather than growing the frame."""
    return app.DoScript(ts._fix_vertical_js(), JS)

def _align_autogrow_cells(app):
    """Left-align and auto-grow table cells so their text stays visible."""
    return app.DoScript(ts._align_autogrow_cells_js(), JS)

def _hyphenate_overset_cells(app):
    """Enable hyphenation in overset cells so long words break and the text fits."""
    return app.DoScript(ts._hyphenate_overset_cells_js(), JS)

def _center_narrow_tables(app):
    """Center narrow left-aligned tables within the text column."""
    return app.DoScript(ts._center_narrow_tables_js(), JS)


def enforce_text_size(app, size=9.65):
    """Force NORMAL body text and TABLE text to a fixed point size (default 9.65),
    without touching headings. Sets the common body paragraph styles to `size` and
    every (non-image) table cell's text to `size`. Headings keep their own styles
    and sizes; table FIT is still handled by width/hyphenation, never by shrinking
    the font below this size. Returns the count of table cells set."""
    return app.DoScript(ts.enforce_text_size_js(size), JS)


def _collapse_empty_rows(app, const_h=4.0):
    """Remove genuinely-empty table rows (spacer rows whose every cell has no text
    and no image), from last to first so indices stay valid. A row that has text in
    ANY cell is never touched and no cell content is ever cleared - so a header row
    like ['', 'Miles.'] keeps its text instead of being blanked."""
    return app.DoScript(ts._collapse_empty_rows_js(), JS)


def _remove_all_table_borders(app):
    """Disable ALL table borders: set every cell's four edge stroke weights to 0
    across every table in the document. Requested so table rules do not print."""
    return app.DoScript(ts._remove_all_table_borders_js(), JS)


def _left_align_table_cells(app):
    """Left-align every TEXT cell in every table so content starts at the cell's
    left edge (not centred). Image cells are skipped -- their figures are centred
    separately via anchorXoffset. Returns count of cells left-aligned."""
    return app.DoScript(ts._left_align_table_cells_js(), JS)


def _split_multiline_list_cells(app):
    """Make single-column list/poem tables splittable across pages.

    Some sources cram a whole list or poem into ONE table cell, with the lines
    separated by soft returns -- producing a single very tall row that cannot
    break and overflows the page. InDesign only splits a table BETWEEN rows, so
    this expands such a 1-column table into one row per line (lossless). The
    result is an ordinary multi-row table that flows onto the next page when it
    reaches the bottom margin and reflows automatically when text above changes.
    Only single-column, text-only tables are touched. Returns count rebuilt."""
    return app.DoScript(ts._split_multiline_list_cells_js(), JS)


def _compact_cell_content(app):
    """Make data-table rows compact and tidy, without losing text.

    Many source cells carry extra blank paragraphs (leading/trailing empty
    lines) that inflate the row height, leaving big vertical gaps and overset
    'red dot' markers even though the real text is short. For every text cell
    this trims leading/trailing blank lines only (never internal content),
    top-aligns the cell so text starts at the top-left, and lets each row grow
    just to its content. Returns count of cells trimmed."""
    return app.DoScript(ts._compact_cell_content_js(), JS)


def _flow_overset_tail(app):
    """Dedicated handler for poem / single-cell table text.

    Converting a crammed single-cell list or poem into flowing text (so it can
    split across pages) EXPANDS it, which can push following text past the last
    frame of the story and overset / truncate it. The main injection reflow runs
    BEFORE the table fix, so it never sees this expansion. This pass adds threaded
    pages to every story until its last frame no longer overflows, so no poem or
    list text is lost. Returns the number of pages added."""
    return app.DoScript(ts._flow_overset_tail_js(), JS)


def convert_single_cell_tables(app):
    """Convert every single-cell (1 row x 1 col, no image) table into flowing text.

    Meant to run BEFORE the main overset reflow. A long poem/list crammed into one
    table cell is a single unbreakable row: during reflow it cannot split, so it is
    forced onto one grown page and the text after it (and its own tail) is lost. As
    flowing text it breaks across pages normally, so the reflow paginates it and
    nothing is truncated. convertToText is lossless. Returns count converted."""
    return app.DoScript(ts.convert_single_cell_tables_js(), JS)


def _fit_image_tables_to_margin(app):
    """Shrink an IMAGE table so it fits the text area, WITHOUT changing the
    paragraph indent.

    A figure table anchored in an indented paragraph (e.g. a block quote with a
    left indent) starts at margin+indent; if it is full width it then spills past
    the right margin. We cannot zero the paragraph indent (that un-indents the
    quote text that shares the paragraph), so instead we scale the table columns
    down to the available indented width. The image layout pass then re-fits the
    pictures into the smaller cells. Returns count of tables shrunk."""
    return app.DoScript(ts._fit_image_tables_to_margin_js(), JS)


def fix_tables_in_doc(app):
    """Public entry point for the pipeline, run on the already-open document.

    Fixes table CELL overset (red dots) and keeps tables within the text column by
    auto-resizing column widths and cell insets only -- the table TEXT font size is
    never changed and no word spacing is added -- makes body rows breakable, and
    centres narrow left-aligned tables.

    Run this AFTER the document is laid out (after the main reflow) so cells are
    composed and their overset state is accurate. It then re-flows vertically --
    resetting any force-grown frames so a tall table SPLITS across pages instead of
    the text frame being grown (guarded so the page count can never run away), which
    is what keeps the body text flowing normally. Returns a summary.
    """
    rS = enforce_text_size(app, 9.65)
    rE = _collapse_empty_rows(app)
    rC = _compact_cell_content(app)
    rSp = "LIST_TABLES_SPLIT=via_text_flow"
    r0 = _break_poem_tables(app)
    rA = _align_autogrow_cells(app)
    rL = _left_align_table_cells(app)
    r1 = _fix_tables_and_breakable(app)
    rI = _fit_image_tables_to_margin(app)
    r2 = _center_narrow_tables(app)
    rB = _remove_all_table_borders(app)
    r3 = _fix_vertical(app)
    rF = _flow_overset_tail(app)
    return "%s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s" % (rS, rE, rC, rSp, r0, rA, rL, r1, r2, rB, r3, rF, rI)


def _open_doc(app, idml_path):
    """Open an IDML in InDesign with user interaction and redraw disabled."""
    js = f'''
    app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
    app.scriptPreferences.enableRedraw = false;
    var doc = app.open(new File("{idml_path.replace(chr(92), '/')}"));
    try {{ doc.textPreferences.smartTextReflow = false; }} catch (e1) {{}}
    try {{ app.textPreferences.smartTextReflow = false; }} catch (e2) {{}}
    doc.pages.length + "";
    '''
    return app.DoScript(js, JS)


def _export_and_close(app, out_path):
    """Export the active document back to IDML and close it without saving."""
    js = f'''
    var outFile = new File("{out_path.replace(chr(92), '/')}");
    app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, outFile);
    app.activeDocument.close(SaveOptions.NO);
    app.scriptPreferences.enableRedraw = true;
    "ok";
    '''
    return app.DoScript(js, JS)


def _collect_targets(target):
    """Return the list of target IDML paths from a file or directory argument."""
    if os.path.isfile(target) and target.lower().endswith(".idml"):
        return [target]
    if os.path.isdir(target):
        return [os.path.join(target, f) for f in sorted(os.listdir(target))
                if f.lower().endswith(".idml")]
    return []


def main():
    """Standalone entry point: run the table-fit passes over a file or folder of IDMLs."""
    _HERE = os.path.dirname(os.path.abspath(__file__))
    default_in  = os.path.join(_HERE, "output_files", "idml_files")
    out_dir     = os.path.join(_HERE, "output_files", "table_output_file")

    target = sys.argv[1] if len(sys.argv) > 1 else default_in
    idmls = _collect_targets(target)
    if not idmls:
        print(f"No .idml files found at: {target}")
        return

    os.makedirs(out_dir, exist_ok=True)

    try:
        app = win32com.client.Dispatch("InDesign.Application")
    except Exception:
        print("Error: Ensure Adobe InDesign is installed and running.")
        return
    try:
        app.DoScript(
            "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
            JS,
        )
    except Exception:
        pass

    print(f"Found {len(idmls)} IDML file(s).")
    print(f"Writing fixed copies to: {out_dir}\n")
    log = [f"=== Table fit / visibility fix — {datetime.now():%Y-%m-%d %H:%M:%S} ===",
           f"Output folder: {out_dir}"]

    MAX_RETRIES = 3
    for idml_path in idmls:
        name = os.path.basename(idml_path)
        out_path = os.path.join(out_dir, name)
        attempts = 0
        while True:
            try:
                print(f"{'-'*56}\nProcessing: {name}")
                pages_before = _open_doc(app, idml_path)
                print(f"  Pages before: {pages_before}")

                r0 = _break_poem_tables(app)
                print(f"  Poems:  {r0}")
                log.append(f"{name}: {r0}")

                r1 = _fix_tables_and_breakable(app)
                print(f"  Tables: {r1}")
                log.append(f"{name}: {r1}")

                r2 = _fix_vertical(app)
                print(f"  Layout: {r2}")
                log.append(f"{name}: {r2}")

                pages_after = "0"
                try:
                    pages_after = app.DoScript("app.activeDocument.pages.length + '';", JS)
                except Exception:
                    pass
                print(f"  Pages after:  {pages_after}")

                _export_and_close(app, out_path)
                print(f"  Saved: table_output_file\\{name}")
                log.append(f"{name}: pages {pages_before} -> {pages_after}")
                break

            except Exception as err:
                if _is_rpc_error(err) and attempts < MAX_RETRIES:
                    attempts += 1
                    print(f"  [!] InDesign hang on {name} "
                          f"(attempt {attempts}/{MAX_RETRIES}): {err}", flush=True)
                    try:
                        app = restart_indesign()
                    except Exception as re:
                        print(f"  [!] Restart failed: {re}", flush=True)
                        log.append(f"{name}: restart failed {re}")
                        break
                    continue
                print(f"  [!] Error on {name}: {err}", flush=True)
                log.append(f"{name}: ERROR {err}")
                break

    log_path = os.path.join(out_dir, "table_fit_log.txt")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log))
    except Exception:
        pass

    print(f"\n{'-'*56}\nDone. Fixed copies in: {out_dir}\n  Log: {log_path}")


if __name__ == "__main__":
    main()

format_tables_in_doc = fix_tables_in_doc

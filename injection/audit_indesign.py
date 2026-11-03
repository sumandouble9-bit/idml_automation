import os
import re
import sys
import shutil
import time
import zipfile
import subprocess
import win32com.client
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import epub_tools

try:
    from audit_text import *
except ImportError:
    from .audit_text import *

JS = 1246973031


def _is_rpc_error(exc: Exception) -> bool:
    """Detect InDesign COM hang / crash / stuck-modal conditions worth restarting for."""
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
    """Force-kill InDesign, wait, then relaunch and return a fresh COM Application object."""
    print("  [restart] Killing InDesign.exe ...", flush=True)
    for proc in ("InDesign.exe", "Adobe Crash Processor.exe"):
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True)
        except Exception:
            pass
    time.sleep(wait_seconds)
    for _ in range(6):
        try:
            new_app = win32com.client.Dispatch("InDesign.Application")
            try:
                new_app.DoScript(
                    "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                    JS,
                )
            except Exception:
                pass
            print("  [restart] InDesign is back.", flush=True)
            return new_app
        except Exception:
            time.sleep(5)
    raise RuntimeError("Could not restart InDesign after multiple attempts")


def _find_page(app, anchor):
    """Return the page name where `anchor` (the present words just before a gap)
    appears in the open document, or "" if not found."""
    gwords = [re.sub(r"[^a-z0-9]", "", w) for w in anchor]
    gwords = [w for w in gwords if w]
    if len(gwords) < 2:
        return ""
    grep = "(?i)" + r"\s+".join(gwords)
    grep_js = grep.replace("\\", "\\\\").replace('"', '\\"')
    js = ('app.findGrepPreferences = NothingEnum.nothing;'
          'app.findGrepPreferences.findWhat = "%s";'
          'var f = app.activeDocument.findGrep();'
          'app.findGrepPreferences = NothingEnum.nothing;'
          'var pg = "";'
          'for (var i=0;i<f.length;i++){ try { var tf=f[i].parentTextFrames;'
          ' if (tf.length && tf[0].parentPage){ pg=tf[0].parentPage.name; break; } } catch(e){} }'
          'pg;') % grep_js
    try:
        return app.DoScript(js, JS) or ""
    except Exception:
        return ""


def find_missing_pages(app, spans, max_pages=8):
    """Aggregate list of page names for the biggest missing passages (for the
    one-line audit reason). `spans` is a list of (length, anchor, words)."""
    pages, seen = [], set()
    for _, anc, _ in spans or []:
        pg = _find_page(app, anc)
        if pg and pg not in seen:
            seen.add(pg)
            pages.append(pg)
        if len(pages) >= max_pages:
            break

    def _k(x):
        # Sort key: numeric when the value is an integer, else fall back to string order.
        try:
            return (0, int(x))
        except Exception:
            return (1, x)
    return sorted(pages, key=_k)


def write_missing_words_report(report_path, app, name, spans, all_words):
    """Write a per-book report of the EXACT missing words with their page numbers:
    each dropped passage (page + the missing words), then the full distinctive
    missing-word list with how many times each is missing."""
    lines = ["Missing-text report for %s" % name,
             "Generated: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "=" * 60,
             "Each dropped passage below is the run of consecutive words that are in",
             "the source but not in the output, with the page they belong on.",
             "-" * 60, ""]
    shown = 0
    for length, anchor, words in spans:
        pg = _find_page(app, anchor)
        lines.append("p.%s : %s" % (pg or "?", " ".join(words)))
        shown += 1
        if shown >= 300:
            break
    if shown == 0:
        lines.append("(nothing to locate; see the word list below)")
    lines.append("")
    lines.append("-" * 60)
    lines.append("All distinctive missing words (word  x<times missing>):")
    lines.append("-" * 60)
    for c, w in all_words:
        lines.append("  %s  x%d" % (w, c))
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

_HERE             = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR        = os.environ.get("AUDIT_OUTBASE", "").strip() or os.path.join(_HERE, "output_files")
INJECTED_DIR      = os.path.join(OUTPUT_DIR, "idml_files")
OUTPUT_PDF_DIR    = os.path.join(OUTPUT_DIR, "pdf_files")

REJECTED_DIR      = os.environ.get("AUDIT_REJBASE", "").strip() or os.path.join(_HERE, "rejected_files")
REJECTED_IDML_DIR = os.path.join(REJECTED_DIR, "idml_files")
REJECTED_PDF_DIR  = os.path.join(REJECTED_DIR, "pdf_files")

LOG_PATH          = os.path.join(OUTPUT_DIR, "audit_log.txt")
SUMMARY_PATH      = os.path.join(OUTPUT_DIR, "books_summary_report.txt")

JS = 1246973031


def export_pdf(app, pdf_path):
    # Export the active InDesign document to PDF using the High Quality Print preset.
    js = f"""
    try {{ app.pdfExportPreferences.pageRange = PageRange.ALL_PAGES; }} catch(e) {{}}
    var pdfPreset = app.pdfExportPresets.itemByName("[High Quality Print]");
    if (!pdfPreset.isValid) pdfPreset = app.pdfExportPresets[0];
    app.activeDocument.exportFile(ExportFormat.PDF_TYPE, new File("{pdf_path.replace(chr(92), '/')}"), false, pdfPreset);
    """
    app.DoScript(js, JS)


def close_doc(app):
    # Close the active document without saving.
    app.DoScript("app.activeDocument.close(SaveOptions.NO);", JS)


__all__ = ['_is_rpc_error', 'restart_indesign', '_find_page', 'find_missing_pages', 'write_missing_words_report', 'export_pdf', 'close_doc', 'JS']

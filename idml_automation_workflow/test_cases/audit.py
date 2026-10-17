import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..', 'image_inject'))
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))
import pdf_export
import check_common
import check_placeholders
import check_links
import check_image_margins
import check_overset
import check_captions
import check_tables
import check_missing_images
import check_chapter_image
import caption_center


import os
import re
import sys
import shutil
import image_refit
import time
import zipfile
import subprocess
import win32com.client
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import epub_tools  # for the EPUB caption map (caption-placement check)

EPUB_INPUT_DIR = os.environ.get("EPUB_DIR", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "epub_input_files")

NORMALIZED_DIR = os.environ.get("AUDIT_SRC", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "page_resize_output")
RAW_INPUT_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "input_files")

_IMG_TOKEN = re.compile(r"^(image|img|fig|figs|figure|plate|illustration)\d+$")
_EXT_TOKEN = {"jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "webp"}
_PH_TOKEN  = {"insert", "here", "image", "img", "fig", "figs", "figure", "figures",
              "plate", "plates", "illustration", "illustrations"}
_WORD_RE   = re.compile(r"[A-Za-z][A-Za-z0-9']*")   # hyphen = separator (avoids line-break hyphenation noise)
MISSING_RUN_LEN = 12   # a run of unique words this long, gone = a real dropped passage
MISSING_OCC_THRESHOLD = 40  # distinctive word-occurrences lost that count as text loss


def _source_idml(book):
    """Locate the un-injected source IDML for a book (normalized first, then raw)."""
    for d in (NORMALIZED_DIR, RAW_INPUT_DIR):
        p = os.path.join(d, book + ".idml")
        if os.path.exists(p):
            return p
    return None


def _idml_story_token_lists(idml_path):
    """Per-story ordered lists of lowercase word tokens from an IDML's <Content> runs.

    An IDML is a zip; the visible text lives in Stories/Story_*.xml inside <Content>
    elements. Keeping tokens grouped by story preserves reading order within a story
    so a *consecutive* run of dropped words can be spotted.
    """
    stories = []
    try:
        with zipfile.ZipFile(idml_path) as z:
            for n in sorted(z.namelist()):
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                try:
                    xml = z.read(n).decode("utf-8", "replace")
                except Exception:
                    continue
                toks = []
                for seg in re.split(r"<Br\s*/>", xml):
                    runs = re.findall(r"<Content>(.*?)</Content>", seg, re.S)
                    txt = "".join(runs)
                    txt = re.sub(r"&#x?[0-9A-Fa-f]+;", " ", txt)     # numeric char entities
                    txt = txt.replace("&amp;", " ").replace("&lt;", " ").replace("&gt;", " ")
                    for w in _WORD_RE.findall(txt):
                        toks.append(w.lower().strip("'"))
                if toks:
                    stories.append(toks)
    except Exception:
        pass
    return stories


def missing_text_reason(source_idml, injected_idml, caption_map=None):
    """Return a MISSING_TEXT reason string if the injection dropped body text.

    Compares the source IDML's words with the injected IDML's words. Words that
    legitimately disappear are ignored: the placeholder tokens (Insert / here /
    imageNNN / file extensions) and every word used in an EPUB caption (the
    original caption is removed and replaced by the EPUB caption). A hit is
    reported when EITHER a large number of distinctive word-occurrences (length
    >= 5) are missing from the output (>= MISSING_OCC_THRESHOLD) — catches a
    dropped paragraph/heading even when its words recur elsewhere — OR a
    *consecutive run* of >= MISSING_RUN_LEN source words is entirely absent from
    the output — catches a localised unique passage. Returns None when nothing
    meaningful is lost.
    """
    if not (source_idml and os.path.exists(source_idml) and os.path.exists(injected_idml)):
        return None
    src_stories = _idml_story_token_lists(source_idml)
    out_stories = _idml_story_token_lists(injected_idml)
    if not src_stories or not out_stories:
        return None
    out_tokens, out_all = set(), []
    for toks in out_stories:
        out_tokens.update(toks)
        out_all.extend(toks)

    ignore = set(_PH_TOKEN) | set(_EXT_TOKEN)
    if caption_map:
        for v in caption_map.values():
            for w in _WORD_RE.findall(v):
                ignore.add(w.lower().strip("'-"))

    def keep(w):   # a distinctive content word worth counting
        return len(w) >= 5 and w not in ignore and not _IMG_TOKEN.match(w)

    from collections import Counter
    cs = Counter(w for s in src_stories for w in s if keep(w))
    co = Counter(w for w in out_all if keep(w))
    lost_occ, lost_words = 0, []
    for w, c in cs.items():
        d = c - co.get(w, 0)
        if d > 0:
            lost_occ += d
            lost_words.append((d, w))

    def is_missing(w):
        return len(w) >= 2 and w not in ignore and not _IMG_TOKEN.match(w) and w not in out_tokens
    spans = []   # (run_length, anchor_words)
    for toks in src_stories:
        i, n = 0, len(toks)
        while i < n:
            if is_missing(toks[i]):
                j = i
                while j < n and is_missing(toks[j]):
                    j += 1
                anchor, k = [], i - 1
                while k >= 0 and len(anchor) < 3:
                    if not is_missing(toks[k]):
                        anchor.insert(0, toks[k])
                    k -= 1
                spans.append((j - i, anchor, toks[i:j]))   # length, anchor, missing words
                i = j
            else:
                i += 1
    best_run = max((L for L, _, _ in spans), default=0)

    if lost_occ >= MISSING_OCC_THRESHOLD or best_run >= MISSING_RUN_LEN:
        lost_words.sort(reverse=True)
        sample = " ".join(w for _, w in lost_words[:15]) or ""
        msg = "MISSING_TEXT=lost_occ=%d,run=%d:[%s]" % (lost_occ, best_run, sample)
        spans.sort(key=lambda x: x[0], reverse=True)
        return (msg, spans, lost_words)
    return None


def _find_page(app, anchor):
    """Return the page name where `anchor` (the present words just before a gap)
    appears in the open document, or "" if not found."""
    gwords = [re.sub(r"[^a-z0-9]", "", w) for w in anchor]
    gwords = [w for w in gwords if w]
    if len(gwords) < 2:
        return ""
    grep = "(?i)" + r"\s+".join(gwords)                  # tolerate any spacing/punctuation
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
        pg = _find_page(app, anchor)      # page the missing word(s) belong on
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
INJECTED_DIR      = os.path.join(OUTPUT_DIR, "idml_files")    # injected IDMLs (input to audit)
OUTPUT_PDF_DIR    = os.path.join(OUTPUT_DIR, "pdf_files")     # PDFs of passing documents

REJECTED_DIR      = os.environ.get("AUDIT_REJBASE", "").strip() or os.path.join(_HERE, "rejected_files")
REJECTED_IDML_DIR = os.path.join(REJECTED_DIR, "idml_files")  # rejected IDMLs
REJECTED_PDF_DIR  = os.path.join(REJECTED_DIR, "pdf_files")   # PDFs of rejected documents

LOG_PATH          = os.path.join(OUTPUT_DIR, "audit_log.txt")
SUMMARY_PATH      = os.path.join(OUTPUT_DIR, "books_summary_report.txt")  # per-book table report

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

def audit_one(app, idml_path, caption_map=None, expected=None):
    """Open an injected IDML, re-fit drifted images, and run every check module."""
    app.DoScript('app.open(new File("%s"));' % idml_path.replace(chr(92), "/"), JS)
    try:
        image_refit.run(app)
    except Exception:
        pass
    try:
        caption_center.run(app, caption_map)
    except Exception:
        pass
    reasons = []
    for module in (check_placeholders, check_links, check_image_margins,
                   check_overset, check_tables):
        reasons += module.check(app)
    reasons += check_captions.check(app, caption_map)
    reasons += check_missing_images.check(app, expected)
    reasons += check_chapter_image.check(app)
    try:
        image_refit.run(app)
    except Exception:
        pass
    reasons = [r for r in reasons if not r.startswith("IMAGE_OFF_FRAME")]
    off_frame = image_refit.offframe(app)
    if off_frame:
        reasons.append("IMAGE_OFF_FRAME=%d:%s" % (len(off_frame), ";".join(off_frame)))
    metrics = _collect_metrics(app, reasons)
    return len(reasons) == 0, reasons, metrics


def _collect_metrics(app, reasons):
    """Build the per-book summary metrics from document counts and the check results."""
    metrics = check_common.counts(app)
    def detail(prefix):
        for reason in reasons:
            if reason.startswith(prefix + "=") and ":" in reason:
                return reason.split(":", 1)[1]
        return ""
    metrics["TBL_OVER"] = detail("TABLE_CELL_OVERSET")
    metrics["IMG_OVER"] = detail("IMAGES_OUTSIDE_MARGIN")
    return metrics


def _pages_from(detail):
    """Extract unique page numbers (p.NN) from a detail string, in order."""
    pgs = re.findall(r"p\.(\w+)", detail or "")
    seen = list(dict.fromkeys(pgs))
    return ",".join(seen) if seen else "-"


def _record_summary(rows, book, metrics, result, reasons, elapsed):
    """Collect one book's metrics for the per-book summary report."""
    tables  = int(metrics.get("TABLES", "0") or 0)
    images  = int(metrics.get("IMAGES", "0") or 0)
    ph_left = int(metrics.get("PH_LEFT", "0") or 0)
    injected = ("Yes" if ph_left == 0 else "No") if images > 0 else "-"
    rows.append({
        "book":        book,
        "tables":      "Yes" if tables > 0 else "No",
        "images":      "Yes" if images > 0 else "No",
        "img_count":   str(images),
        "injected":    injected,
        "tbl_overset": _pages_from(metrics.get("TBL_OVER", "")),
        "img_overset": _pages_from(metrics.get("IMG_OVER", "")),
        "time":        "%.1f" % elapsed,
        "result":      result,
    })


def _write_summary_report(path, rows, passed, failed):
    """Write an aligned per-book table report to a new log file."""
    headers = ["Book", "Table", "Image", "ImgCount", "Injected",
               "TableOverset(pg)", "ImageOverset(pg)", "Time(s)", "Result"]
    keys = ["book", "tables", "images", "img_count", "injected",
            "tbl_overset", "img_overset", "time", "result"]
    grid = [headers] + [[str(r[k]) for k in keys] for r in rows]
    widths = [max(len(row[i]) for row in grid) for i in range(len(headers))]
    def fmt(row):
        return " | ".join(row[i].ljust(widths[i]) for i in range(len(row)))
    lines = ["=== Per-Book Summary Report ===",
             "Date: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "",
             fmt(headers),
             "-+-".join("-" * w for w in widths)]
    for row in grid[1:]:
        lines.append(fmt(row))
    lines.append("")
    lines.append("Total books: %d  |  Passed: %d  |  Rejected: %d" % (len(rows), passed, failed))
    with open(path, "w", encoding="utf-8") as f:
        f.write(chr(10).join(lines))


def main():
    for d in (INJECTED_DIR, OUTPUT_PDF_DIR, REJECTED_IDML_DIR, REJECTED_PDF_DIR):
        os.makedirs(d, exist_ok=True)

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

    idmls = [f for f in os.listdir(INJECTED_DIR)
             if f.lower().endswith("_injected.idml")]
    if not idmls:
        print(f"No *_injected.idml files in {INJECTED_DIR}")
        return

    log = ["=== IDML Audit Log ===",
           f"Date: {datetime.now():%Y-%m-%d %H:%M:%S}",
           "-" * 40]

    passed_count = 0
    failed_count = 0
    summary_rows = []   # per-book metrics for the table report

    MAX_RETRIES = 3
    for name in idmls:
        idml_path = os.path.join(INJECTED_DIR, name)
        base = os.path.splitext(name)[0]
        book = base[:-9] if base.endswith("_injected") else base
        caption_map = {}
        epub_path = os.path.join(EPUB_INPUT_DIR, book + ".epub")
        if os.path.exists(epub_path):
            try:
                caption_map = epub_tools.build_caption_map(epub_path)
            except Exception:
                caption_map = {}
        expected = check_missing_images.expected_image_names(_source_idml(book))
        if (os.path.exists(os.path.join(OUTPUT_PDF_DIR, base + ".pdf"))
                or os.path.exists(os.path.join(REJECTED_PDF_DIR, base + ".pdf"))):
            print(f"\nSKIP (already audited): {name}")
            continue

        print(f"\nAuditing: {name}")
        attempt = 0

        while True:
            attempt += 1
            try:
                _t0 = time.time()
                passed, reasons, metrics = audit_one(app, idml_path, caption_map, expected)

                try:
                    mt = missing_text_reason(_source_idml(book), idml_path, caption_map)
                    if mt:
                        msg, spans, all_words = mt
                        try:
                            pages = find_missing_pages(app, spans)  # doc still open
                            if pages:
                                msg += " pages=[%s]" % ",".join(pages)
                        except Exception:
                            pass
                        try:
                            rep = os.path.join(REJECTED_IDML_DIR, base + ".missing_words.txt")
                            write_missing_words_report(rep, app, name, spans, all_words)
                            print(f"  missing-words report -> {rep}")
                        except Exception as _erep:
                            print(f"  [warn] missing-words report failed: {_erep}")
                        reasons = list(reasons) + [msg]
                        passed = False
                except Exception as _emt:
                    print(f"  [warn] missing-text check skipped: {_emt}")

                if passed:
                    pdf_path = os.path.join(OUTPUT_PDF_DIR, base + ".pdf")
                    print(f"  PASS -> PDF: {pdf_path}")
                    pdf_export.export_pdf(app, pdf_path)
                    pdf_export.close_doc(app)
                    log.append(f"{name}: PASS -> {pdf_path}")
                    _record_summary(summary_rows, book, metrics, "PASS", reasons, time.time() - _t0)
                    passed_count += 1
                else:
                    pdf_path = os.path.join(REJECTED_PDF_DIR, base + ".pdf")
                    print(f"  FAIL: {reasons}")
                    print(f"  FAIL -> PDF: {pdf_path}")
                    pdf_export.export_pdf(app, pdf_path)          # still produce a PDF for rejected docs
                    pdf_export.close_doc(app)
                    dest = os.path.join(REJECTED_IDML_DIR, name)
                    shutil.move(idml_path, dest)        # move the IDML into rejected_files/idml_files
                    with open(dest + ".audit.txt", "w", encoding="utf-8") as f:
                        f.write("Audit failed for {}\n".format(name))
                        for r in reasons:
                            f.write(" - " + r + "\n")
                    log.append(f"{name}: FAIL -> rejected_files/  ({'; '.join(reasons)})")
                    _record_summary(summary_rows, book, metrics, "REJECT", reasons, time.time() - _t0)
                    failed_count += 1
                break  # this document is done

            except Exception as e:
                if _is_rpc_error(e) and attempt < MAX_RETRIES:
                    print(f"  [!] InDesign hang/modal on {name} "
                          f"(attempt {attempt}/{MAX_RETRIES}): {e}", flush=True)
                    log.append(f"{name}: HANG attempt {attempt} — {e}")
                    try:
                        app = restart_indesign()
                    except Exception as ridx:
                        print(f"  [!] Restart failed: {ridx}", flush=True)
                        log.append(f"{name}: RESTART_FAILED {ridx}")
                        failed_count += 1
                        break
                    for _pp in (os.path.join(OUTPUT_PDF_DIR, base + ".pdf"),
                                os.path.join(REJECTED_PDF_DIR, base + ".pdf")):
                        try:
                            if os.path.exists(_pp):
                                os.remove(_pp)
                        except Exception:
                            pass
                    continue
                else:
                    print(f"  Error on {name}: {e}")
                    log.append(f"{name}: ERROR {e}")
                    try:
                        pdf_export.close_doc(app)
                    except Exception:
                        pass
                    failed_count += 1
                    break

    log.append("-" * 40)
    log.append(f"Summary: {passed_count} passed, {failed_count} rejected")
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(log))

    print(f"\nDone. {passed_count} passed, {failed_count} rejected.")
    print(f"Log: {LOG_PATH}")

if __name__ == "__main__":
    main()

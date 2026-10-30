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

EPUB_INPUT_DIR = os.environ.get("EPUB_DIR", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "epub_input_files")

NORMALIZED_DIR = os.environ.get("AUDIT_SRC", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "page_resize_output")
RAW_INPUT_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "input_files")

_IMG_TOKEN = re.compile(r"^(image|img|fig|figs|figure|plate|illustration)\d+$")
_EXT_TOKEN = {"jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "webp"}
_PH_TOKEN  = {"insert", "here", "image", "img", "fig", "figs", "figure", "figures",
              "plate", "plates", "illustration", "illustrations"}
_WORD_RE   = re.compile(r"[A-Za-z][A-Za-z0-9']*")
MISSING_RUN_LEN = 12
MISSING_OCC_THRESHOLD = 40


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
                    txt = re.sub(r"&#x?[0-9A-Fa-f]+;", " ", txt)
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

    def keep(w):
        # Keep only meaningful words (>=5 chars, not ignored, not an image token).
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
        # A source word counts as missing when it is absent from the output tokens.
        return len(w) >= 2 and w not in ignore and not _IMG_TOKEN.match(w) and w not in out_tokens
    spans = []
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
                spans.append((j - i, anchor, toks[i:j]))
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

def audit_one(app, idml_path, caption_map=None):
    """Return (passed: bool, reasons: list[str])."""
    js_open = f'app.open(new File("{idml_path.replace(chr(92), "/")}"));'
    app.DoScript(js_open, JS)

    js_audit = r"""
    var doc = app.activeDocument;
    var problems = [];
    // Measure geometry in spread coordinates so image bounds and page/margin
    // bounds share one frame (matches the layout-fix pass).
    try { doc.viewPreferences.rulerOrigin = RulerOrigin.SPREAD_ORIGIN; } catch (eRO) {}

    // 1. Leftover placeholders
    app.findGrepPreferences = NothingEnum.nothing;
    app.findGrepPreferences.findWhat = "###Insert .*? here###";
    var leftover = doc.findGrep();
    app.findGrepPreferences = NothingEnum.nothing;
    if (leftover.length > 0) {
        var samples = [];
        for (var i = 0; i < Math.min(leftover.length, 5); i++) samples.push(leftover[i].contents);
        problems.push("LEFTOVER_PLACEHOLDERS=" + leftover.length + ":" + samples.join(","));
    }

    // 2. Broken / missing links
    var missing = 0, missingNames = [];
    for (var l = 0; l < doc.links.length; l++) {
        var lk = doc.links[l];
        if (lk.status != LinkStatus.NORMAL) {
            missing++;
            if (missingNames.length < 5) missingNames.push(lk.name + "(" + lk.status + ")");
        }
    }
    if (missing > 0) problems.push("BROKEN_LINKS=" + missing + ":" + missingNames.join(","));

    // 3. Overset text — detailed reporting done in check 6 below.

    // 4. Empty image frames (rectangle with no graphic where one seems expected).
    var emptyFrames = 0;
    for (var r = 0; r < doc.rectangles.length; r++) {
        var rc = doc.rectangles[r];
        try {
            if (rc.graphics.length === 0) {
                var gb = rc.geometricBounds;
                var h = gb[2] - gb[0], w = gb[3] - gb[1];
                if (h > 20 && w > 20) emptyFrames++;
            }
        } catch (e) {}
    }
    if (emptyFrames > 0) problems.push("EMPTY_IMAGE_FRAMES=" + emptyFrames);

    // 5. Every body image must sit INSIDE its page margin box (not spill past the
    //    margins / off the page), must fit the page, and anchored images must be
    //    centered. The logo is skipped (it lives in the header/footer). Images that
    //    the layout-fix pass detached to page-fixed frames are checked for margin
    //    containment only (their position, not anchor settings, defines centering).
    var pageBounds = doc.pages[0].bounds;
    var pageH = pageBounds[2] - pageBounds[0];
    var pageW = pageBounds[3] - pageBounds[1];
    var facing = doc.documentPreferences.facingPages;
    var offPageDetails = [], notCenteredDetails = [], outsideMarginDetails = [], overlapDetails = [], logoBadDetails = [];

    function isLogo(name) {
        if (!name) return false;
        var n = name.toUpperCase();
        return n.indexOf("LEAF-BOUND") >= 0 || n.indexOf("LOGO") >= 0;
    }
    function marginBox(pg) {
        var pb = pg.bounds, mp = pg.marginPreferences, l, r;
        if (facing && pg.side == PageSideOptions.LEFT_HAND) { l = pb[1]+mp.right; r = pb[3]-mp.left; }
        else { l = pb[1]+mp.left; r = pb[3]-mp.right; }
        return { top: pb[0]+mp.top, bottom: pb[2]-mp.bottom, left: l, right: r };
    }
    // Rectangle overlap for [top,left,bottom,right] boxes.
    function rectsOverlap(a, b) {
        return !(a[3] <= b[1] + 1 || a[1] >= b[3] - 1 || a[2] <= b[0] + 1 || a[0] >= b[2] - 1);
    }

    for (var i = 0; i < doc.allGraphics.length; i++) {
        try {
            var g    = doc.allGraphics[i];
            var name = g.itemLink ? g.itemLink.name : "?";
            if (isLogo(name)) {
                // The logo keeps its original template frame. Only flag it when it is
                // actually OFF the page (clearly broken) -- its normal template spot is
                // fine even if it slightly overlaps the bottom margin line.
                try {
                    var lfrm = g.parent, lbb = lfrm.geometricBounds, lpg = null;
                    try { lpg = lfrm.parentPage; } catch (eLp) {}
                    if (lpg) {
                        var lpb = lpg.bounds;
                        var offpage = (lbb[0] < lpb[0]-2 || lbb[2] > lpb[2]+2 || lbb[1] < lpb[1]-2 || lbb[3] > lpb[3]+2);
                        if (offpage) {
                            logoBadDetails.push(name + " (y[" + Math.round(lbb[0]) + ".." + Math.round(lbb[2]) +
                                "] pageBottom=" + Math.round(lpb[2]) + " p." + lpg.name + " off-page)");
                        }
                    } else {
                        logoBadDetails.push(name + " (no page -- off layout)");
                    }
                } catch (eLg) {}
                continue;                               // logos get only this check
            }

            var frm = g.parent;
            var bb  = frm.geometricBounds;
            var fh  = bb[2] - bb[0], fw = bb[3] - bb[1];
            var pg = null; try { pg = frm.parentPage; } catch (ePP) {}
            var pageName = pg ? pg.name : "?";

            // Oversized relative to the whole page.
            if (fh > pageH || fw > pageW) {
                offPageDetails.push(name + " (" + Math.round(fw) + "x" + Math.round(fh) + "pt on p." + pageName + ")");
                continue;
            }

            // Outside the margin box (spills past margins / off page), in either
            // dimension — too wide (crosses left/right margin) or too TALL (crosses
            // top/bottom margin). A tall figure that overflows the text area shows up
            // here via the top/bottom test.
            if (pg) {
                var mb = marginBox(pg);
                if (bb[1] < mb.left-2 || bb[3] > mb.right+2 || bb[0] < mb.top-2 || bb[2] > mb.bottom+2) {
                    outsideMarginDetails.push(name + " (x[" + Math.round(bb[1]) + ".." + Math.round(bb[3]) +
                        "] y[" + Math.round(bb[0]) + ".." + Math.round(bb[2]) +
                        "] outside margin x[" + Math.round(mb.left) + ".." + Math.round(mb.right) +
                        "] y[" + Math.round(mb.top) + ".." + Math.round(mb.bottom) + "] p." + pageName + ")");
                }
            } else {
                // No resolvable page = the image is not sitting cleanly on a page
                // (e.g. floating on the pasteboard / in an overset region). Do not
                // let it slip through unchecked.
                outsideMarginDetails.push(name + " (no page — off-layout)");
            }

            // Centering: anchored images use anchor/paragraph alignment; page-fixed
            // images were positioned by the layout-fix pass, so margin containment
            // (checked above) is the criterion for them.
            var pt = frm.parent;
            var isAnchored = false;
            try { isAnchored = (pt && pt.paragraphs && pt.paragraphs.length > 0); } catch (eIA) {}

            // Overlap check: an in-flow (anchored / table-cell) image can never sit
            // on top of text because the text makes room for it. A PAGE-FIXED image,
            // however, floats over the text — if it overlaps a text frame that holds
            // text, that is a real image-over-text overlap and must be rejected.
            var isPageFixed = false;
            try { isPageFixed = (pt && (pt.constructor.name === "Spread" || pt.constructor.name === "Page")); } catch (ePF) {}
            if (isPageFixed && pg) {
                try {
                    var tfs = pg.textFrames;
                    for (var tfi = 0; tfi < tfs.length; tfi++) {
                        var tf = tfs[tfi];
                        if (tf === frm) continue;
                        var hasText = false;
                        try { hasText = (tf.characters.length > 2); } catch (eTX) {}
                        if (hasText && rectsOverlap(bb, tf.geometricBounds)) {
                            overlapDetails.push(name + " (overlaps text on p." + pageName + ")");
                            break;
                        }
                    }
                } catch (eOv) {}
            }

            if (isAnchored) {
                var aosAlign = "n/a", paraJust = "n/a", isCentered = false;
                try {
                    var aos = frm.anchoredObjectSettings;
                    if (aos) {
                        aosAlign = String(aos.horizontalAlignment);
                        if (aos.horizontalAlignment == HorizontalAlignment.CENTER_ALIGN) isCentered = true;
                    }
                } catch (eA) {}
                if (!isCentered) {
                    try {
                        paraJust = String(pt.paragraphs[0].justification);
                        if (pt.paragraphs[0].justification == Justification.CENTER_ALIGN) isCentered = true;
                    } catch (eP) {}
                }
                if (!isCentered) {
                    notCenteredDetails.push(name + " (aos=" + aosAlign + " para=" + paraJust + " p." + pageName + ")");
                }
            }
        } catch (eG) {}
    }
    if (offPageDetails.length > 0)       problems.push("OVERSIZED_IMAGES=" + offPageDetails.length + ":" + offPageDetails.join(";"));
    if (outsideMarginDetails.length > 0) problems.push("IMAGES_OUTSIDE_MARGIN=" + outsideMarginDetails.length + ":" + outsideMarginDetails.join(";"));
    if (overlapDetails.length > 0)       problems.push("IMAGES_OVERLAP_TEXT=" + overlapDetails.length + ":" + overlapDetails.join(";"));
    if (notCenteredDetails.length > 0)   problems.push("NOT_CENTERED="   + notCenteredDetails.length + ":" + notCenteredDetails.join(";"));
    if (logoBadDetails.length > 0)       problems.push("LOGO_OUTSIDE_MARGIN=" + logoBadDetails.length + ":" + logoBadDetails.join(";"));

    // 6. Overset diagnosis — dump enough info to understand WHY reflow stopped.
    var oversetDetails = [];
    for (var s3 = 0; s3 < doc.stories.length; s3++) {
        var st = doc.stories[s3];
        if (!st.overflows) continue;
        var storyLen = 0, firstPage = "?", lastFramePage = "?";
        var containers = [];
        var lastFrameH = 0, lastFrameW = 0;
        var lastFrameEmpty = false, lastFrameNext = "none";
        var anchoredCount = 0, oversizedAnchored = 0;
        try { storyLen = st.characters.length; } catch (eL) {}
        try { containers = st.textContainers; } catch (eC0) {}
        try {
            if (containers.length > 0) {
                if (containers[0].parentPage) firstPage = containers[0].parentPage.name;
                var lf = containers[containers.length - 1];
                if (lf.parentPage) lastFramePage = lf.parentPage.name;
                var lb = lf.geometricBounds;
                lastFrameH = Math.round(lb[2] - lb[0]);
                lastFrameW = Math.round(lb[3] - lb[1]);
                try { lastFrameEmpty = (lf.characters.length === 0); } catch (eLE) {}
                try { lastFrameNext = lf.nextTextFrame ? "yes" : "no"; } catch (eN2) {}
            }
        } catch (eC) {}
        // Count anchored graphics inside this story and how many are oversized
        try {
            for (var g2 = 0; g2 < st.allPageItems.length; g2++) {
                var it = st.allPageItems[g2];
                try {
                    if (it.graphics && it.graphics.length > 0) {
                        anchoredCount++;
                        var gb = it.geometricBounds;
                        if ((gb[3] - gb[1]) > pageW || (gb[2] - gb[0]) > pageH) oversizedAnchored++;
                    }
                } catch (eIt) {}
            }
        } catch (eG3) {}

        // Roughly how many more frames of ~2000 chars we'd need
        var charsPerFrame = 2000;
        var needMore = "?";
        try {
            var used = containers.length * charsPerFrame;
            var deficit = storyLen - used;
            if (deficit > 0) needMore = String(Math.ceil(deficit / charsPerFrame));
        } catch (eD) {}

        oversetDetails.push(
            "story#" + s3 +
            " chars=" + storyLen +
            " frames=" + containers.length +
            " firstPage=" + firstPage +
            " lastPage=" + lastFramePage +
            " lastFrame(" + lastFrameW + "x" + lastFrameH + "pt empty=" + lastFrameEmpty + " threaded=" + lastFrameNext + ")" +
            " anchoredImgs=" + anchoredCount + " oversized=" + oversizedAnchored +
            " approxNeedMoreFrames=" + needMore
        );
    }
    if (oversetDetails.length > 0) problems.push("OVERSET_STORIES=" + oversetDetails.length + ":" + oversetDetails.join(";"));

    // 7. Caption placement: every image that HAS an EPUB caption must have that
    //    caption in the paragraph directly BELOW the image. Report the image name
    //    and the exact page number for any that do not.
    var CAP = __CAP__;
    function normCap(s){ return String(s).replace(/[^a-zA-Z0-9]/g, "").toLowerCase(); }
    var capMissing = [];     // EPUB caption not found below the image at all
    var capNotFig  = [];     // caption present but NOT styled as a centred 'fig caption'
    var capDup     = [];     // caption present TWICE (duplicate) for one image
    for (var ci = 0; ci < doc.allGraphics.length; ci++){
        try {
            var cg = doc.allGraphics[ci];
            var cname = cg.itemLink ? cg.itemLink.name : "";
            if (isLogo(cname)) continue;
            var want = CAP[cname];
            if (!want) continue;                       // no caption expected for this image
            var cframe = cg.parent;
            var cImgPara = cframe.parent.paragraphs[0];
            var cHost = cImgPara.parentStory;
            var cLast = cImgPara.characters[-1].index;
            var cpg = "?"; try { if (cframe.parentPage) cpg = cframe.parentPage.name; } catch (ePg) {}
            if (cLast + 1 >= cHost.characters.length){
                capMissing.push(cname + " (p." + cpg + ")"); continue;
            }
            var belowP = cHost.characters[cLast + 1].paragraphs[0];
            // Split figure / repeated image: the paragraph below is ANOTHER image,
            // so this piece's caption sits below the whole group (checked by the
            // last piece). Do not flag this piece.
            var belowIsImg = false;
            try { belowIsImg = (belowP.allPageItems.length > 0); } catch (eBI) {}
            if (belowIsImg) continue;

            var bn = normCap(belowP.contents), wn = normCap(want);
            var matched = (bn.length > 0 && (bn === wn ||
                (bn.length >= 3 && (wn.indexOf(bn) === 0 || bn.indexOf(wn) === 0)) ||
                (wn.length >= 4 && bn.indexOf(wn) !== -1)));
            if (!matched){ capMissing.push(cname + " (p." + cpg + ")"); continue; }

            // Present -> must be a centred 'fig caption' paragraph. Both the
            // paragraph style AND the actual justification must be centre (so a
            // caption styled 'fig caption' but left/right aligned still fails).
            var styleName = ""; try { styleName = belowP.appliedParagraphStyle.name; } catch (eSN) {}
            if (styleName !== "fig caption"){
                capNotFig.push(cname + " (p." + cpg + ")");
            } else {
                var bJust = null; try { bJust = belowP.justification; } catch (eBJ) {}
                if (bJust !== Justification.CENTER_ALIGN){
                    capNotFig.push(cname + " (p." + cpg + ") [left/right]");
                }
            }

            // Duplicate: the paragraph right after the caption is ANOTHER fig caption
            // with the same text.
            try {
                var bLast = belowP.characters[-1].index;
                if (bLast + 1 < cHost.characters.length){
                    var nextP = cHost.characters[bLast + 1].paragraphs[0];
                    var nImg = false; try { nImg = (nextP.allPageItems.length > 0); } catch (eNI) {}
                    var nStyle = ""; try { nStyle = nextP.appliedParagraphStyle.name; } catch (eNS) {}
                    var nn = normCap(nextP.contents);
                    if (!nImg && nStyle === "fig caption" && nn === wn){
                        capDup.push(cname + " (p." + cpg + ")");               // duplicate caption paragraph
                    } else if (!nImg && wn.length >= 4 && nn.length > wn.length && nn.indexOf(wn) === 0){
                        capDup.push(cname + " (p." + cpg + ") [body-dup]");    // caption repeated at start of body text
                    }
                }
            } catch (eDup) {}
        } catch (eCC) {}
    }
    if (capMissing.length > 0) problems.push("CAPTION_MISSING=" + capMissing.length + ":" + capMissing.join(";"));
    if (capNotFig.length  > 0) problems.push("CAPTION_NOT_CENTERED=" + capNotFig.length + ":" + capNotFig.join(";"));
    if (capDup.length     > 0) problems.push("DUPLICATE_CAPTION=" + capDup.length + ":" + capDup.join(";"));

    try { doc.recompose(); } catch(eRC){}
    function _ovf(G, FR){
        var a = G.geometricBounds, b = FR.geometricBounds;
        var x1 = Math.max(a[1], b[1]), y1 = Math.max(a[0], b[0]);
        var x2 = Math.min(a[3], b[3]), y2 = Math.min(a[2], b[2]);
        var w = x2 - x1; if (w < 0) w = 0;
        var h = y2 - y1; if (h < 0) h = 0;
        var ar = (a[3] - a[1]) * (a[2] - a[0]);
        return ar > 0 ? (w * h) / ar : 1;
    }
    var offFrame = [];
    for (var of1 = 0; of1 < doc.allGraphics.length; of1++){
        try {
            var og = doc.allGraphics[of1];
            if (!og.itemLink) continue;
            if (isLogo(og.itemLink.name)) continue;
            var ofr = og.parent;
            if (_ovf(og, ofr) < 0.5){
                var opg = "?"; try { if (ofr.parentPage) opg = ofr.parentPage.name; } catch(eop){}
                offFrame.push(og.itemLink.name + " (p." + opg + ")");
            }
        } catch(eof){}
    }
    if (offFrame.length > 0) problems.push("IMAGE_OFF_FRAME=" + offFrame.length + ":" + offFrame.join(";"));


    // 7. TABLE checks ------------------------------------------------------
    //    (a) cells whose text is overset (red dots -- text not visible)
    //    (b) a table whose width/position spills past the page margin
    var tblOverset = [], tblOutside = [];
    for (var tsi = 0; tsi < doc.stories.length; tsi++){
        var tsto = doc.stories[tsi];
        for (var tti = 0; tti < tsto.tables.length; tti++){
            var tbl = tsto.tables[tti];
            var tpg = null, tfb = null, tInset = 0;
            try {
                var tfr = tbl.storyOffset.parentTextFrames;
                if (tfr.length){
                    tpg = tfr[0].parentPage;
                    tfb = tfr[0].geometricBounds;
                    try { tInset = tfr[0].textFramePreferences.insetSpacing[0]; } catch (eIn) {}
                }
            } catch (eTF) {}
            var tpage = tpg ? tpg.name : "?";
            // (a) overset cells that actually hold content
            var oc = 0;
            try {
                for (var cci = 0; cci < tbl.cells.length; cci++){
                    try {
                        var ccell = tbl.cells[cci];
                        if (ccell.overflows) oc++;   // any red-dot overset cell counts
                    } catch (eCe) {}
                }
            } catch (eCells) {}
            if (oc > 0) tblOverset.push("tbl#" + (tti + 1) + " " + oc + " cell(s) p." + tpage);
            // (b) table spilling past the margin box
            if (tpg && tfb){
                var tmb = marginBox(tpg);
                var pLeft = 0;
                try { pLeft = tbl.storyOffset.paragraphs[0].leftIndent; } catch (ePL) {}
                var tLeft = tfb[1] + tInset + pLeft;
                var tRight = tLeft + tbl.width;
                var marginW = tmb.right - tmb.left;
                if (tRight > tmb.right + 2 || tLeft < tmb.left - 2 || tbl.width > marginW + 2){
                    tblOutside.push("tbl#" + (tti + 1) + " x[" + Math.round(tLeft) + ".." + Math.round(tRight) +
                        "] margin[" + Math.round(tmb.left) + ".." + Math.round(tmb.right) + "] p." + tpage);
                }
            }
        }
    }
    if (tblOverset.length > 0) problems.push("TABLE_CELL_OVERSET=" + tblOverset.length + ":" + tblOverset.join(";"));
    if (tblOutside.length > 0) problems.push("TABLE_OUTSIDE_MARGIN=" + tblOutside.length + ":" + tblOutside.join(";"));

    // ---- Per-book metrics for the summary report ----
    var _tables = 0, _images = 0;
    for (var ms = 0; ms < doc.stories.length; ms++){ try { _tables += doc.stories[ms].tables.length; } catch (eMs) {} }
    for (var mi = 0; mi < doc.allGraphics.length; mi++){
        try { var _g = doc.allGraphics[mi]; var _nm = _g.itemLink ? _g.itemLink.name : ""; if (!isLogo(_nm)) _images++; } catch (eMi) {}
    }
    var _phLeft = 0; try { _phLeft = leftover.length; } catch (ePH) {}
    var metricsStr = "TABLES=" + _tables + "~IMAGES=" + _images + "~PH_LEFT=" + _phLeft
        + "~TBL_OVER=" + tblOverset.join(";") + "~IMG_OVER=" + outsideMarginDetails.join(";");

    problems.join("|") + "" + metricsStr;
    """
    def _esc(s):
        # Escape a string for safe embedding inside the ExtendScript JS literal.
        return (s.replace("\\", "\\\\").replace('"', '\\"')
                 .replace("\r", " ").replace("\n", " "))
    cap_items = ",".join('"%s":"%s"' % (_esc(k), _esc(v)) for k, v in (caption_map or {}).items())
    js_audit = js_audit.replace("__CAP__", "{" + cap_items + "}")

    result = app.DoScript(js_audit, JS) or ""
    _parts = result.split("", 1)
    reasons = [r for r in _parts[0].split("|") if r]
    metrics = {}
    if len(_parts) > 1:
        for _kv in _parts[1].split("~"):
            if "=" in _kv:
                _k, _v = _kv.split("=", 1)
                metrics[_k] = _v
    passed = len(reasons) == 0
    return passed, reasons, metrics

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
        # Format one report row as padded, pipe-separated columns.
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
    # Entry point: audit every injected IDML, export PDFs, and route pass/fail to the output or rejected folders.
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
    summary_rows = []

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
                passed, reasons, metrics = audit_one(app, idml_path, caption_map)

                try:
                    mt = missing_text_reason(_source_idml(book), idml_path, caption_map)
                    if mt:
                        msg, spans, all_words = mt
                        try:
                            pages = find_missing_pages(app, spans)
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
                    export_pdf(app, pdf_path)
                    close_doc(app)
                    log.append(f"{name}: PASS -> {pdf_path}")
                    _record_summary(summary_rows, book, metrics, "PASS", reasons, time.time() - _t0)
                    passed_count += 1
                else:
                    pdf_path = os.path.join(REJECTED_PDF_DIR, base + ".pdf")
                    print(f"  FAIL: {reasons}")
                    print(f"  FAIL -> PDF: {pdf_path}")
                    export_pdf(app, pdf_path)
                    close_doc(app)
                    dest = os.path.join(REJECTED_IDML_DIR, name)
                    shutil.move(idml_path, dest)
                    with open(dest + ".audit.txt", "w", encoding="utf-8") as f:
                        f.write("Audit failed for {}\n".format(name))
                        for r in reasons:
                            f.write(" - " + r + "\n")
                    log.append(f"{name}: FAIL -> rejected_files/  ({'; '.join(reasons)})")
                    _record_summary(summary_rows, book, metrics, "REJECT", reasons, time.time() - _t0)
                    failed_count += 1
                break

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
                        close_doc(app)
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

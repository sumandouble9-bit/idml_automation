import win32com.client
import os
import sys
import time
import subprocess
import re
import shutil
from datetime import datetime

# Make same-folder modules importable regardless of the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fix_image_layout    # standalone post-injection pass (does not alter injection logic)
import logo_inject         # dedicated, isolated logo injection (never touches body images)
import fix_table_fit       # table-only fixer: cell overset (no font change) + centering
import epub_tools          # extracts EPUB images + builds image->caption map
import epub_caption_apply  # places EPUB captions below images (post-injection)

def _is_rpc_error(exc: Exception) -> bool:
    """Detect InDesign COM hang / crash / stuck-modal conditions worth restarting for."""
    s = str(exc).lower()
    return (
        "remote procedure call" in s
        or "rpc server" in s
        or "-2147023170" in s
        or "-2147023174" in s
        or "call was rejected" in s
        # A modal dialog/alert can appear mid-batch (font/plugin/recovery prompts)
        # even under NEVER_INTERACT; once up it blocks every COM call. Restarting
        # InDesign clears it so the affected document can be retried cleanly.
        or "modal dialog or alert is active" in s
        or "30486" in s
    )

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

def restart_indesign(wait_seconds: int = 6):
    """Force-kill InDesign, wait, then relaunch and return a fresh COM Application object."""
    print("  [restart] Killing InDesign.exe ...", flush=True)
    try:
        subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
    except Exception:
        pass
    try:
        subprocess.run(["taskkill", "/F", "/IM", "Adobe Crash Processor.exe"], capture_output=True)
    except Exception:
        pass
    clear_recovery_data()
    time.sleep(wait_seconds)
    print("  [restart] Relaunching InDesign via COM ...", flush=True)
    for attempt in range(6):
        try:
            new_app = win32com.client.Dispatch('InDesign.Application')
            try:
                new_app.DoScript(
                    "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
                    1246973031,
                )
            except Exception:
                pass
            print("  [restart] InDesign is back.", flush=True)
            return new_app
        except Exception:
            time.sleep(5)
    raise RuntimeError("Could not restart InDesign after multiple attempts")

PAGE_W = 396
PAGE_H = 612
COL_W  = 324
TEXT_H = PAGE_H - 36 - 54
MAX_IMG_H = int(TEXT_H * 0.85)

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

def prepare_image(src_path: str, temp_dir: str) -> str:
    """Guarantee the image fits inside column and height bounds."""
    if not _HAS_PIL:
        return src_path
    try:
        with Image.open(src_path) as im:
            w, h = im.size
            scale = 1.0
            if w > COL_W:      scale = min(scale, COL_W / w)
            if h > MAX_IMG_H:  scale = min(scale, MAX_IMG_H / h)
            if scale >= 1.0:
                return src_path
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            os.makedirs(temp_dir, exist_ok=True)
            out_path = os.path.join(temp_dir, os.path.basename(src_path))
            im2 = im.resize((new_w, new_h), Image.LANCZOS)
            if im2.mode not in ("RGB", "RGBA", "L", "CMYK"):
                im2 = im2.convert("RGB")

            im2.save(out_path, dpi=(72, 72))
            return out_path
    except Exception:
        return src_path


def source_sidebyside_pairs(source_idml):
    """Pairs of image names that share a multi-column TABLE ROW in the SOURCE
    IDML -- i.e. intended side-by-side images (e.g. image064 + image065). They
    must stay packed in ONE paragraph so placement sets them inline on one line
    instead of splitting them into stacked paragraphs."""
    import zipfile as _zip, re as _re
    pairs = set()
    try:
        with _zip.ZipFile(source_idml) as z:
            for n in z.namelist():
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                xml = z.read(n).decode("utf-8", "replace")
                for tm in _re.finditer(r"<Table\b.*?</Table>", xml, _re.S):
                    names = []
                    for c in _re.findall(r"<Cell\b.*?</Cell>", tm.group(0), _re.S):
                        mm = _re.search(r"###Insert\s+(image\d+)", c, _re.I)
                        if mm:
                            names.append(mm.group(1).lower())
                    for i in range(len(names) - 1):
                        pairs.add(frozenset((names[i], names[i + 1])))
    except Exception:
        pass
    return pairs


def set_body_image_inline_leading(app):
    js = r"""
    var d = app.activeDocument;
    var n = 0;
    function isLogoName(nm){ if(!nm) return false; var u=nm.toUpperCase(); return u.indexOf('LEAF-BOUND')>=0 || u.indexOf('LOGO')>=0; }
    for (var i = 0; i < d.allGraphics.length; i++){
        try {
            var g = d.allGraphics[i];
            if (g.itemLink && isLogoName(g.itemLink.name)) continue;
            var frm = g.parent;
            var inCell = false;
            try { inCell = (frm.parent && frm.parent.constructor.name === "Cell"); } catch (eIC){}
            if (inCell) continue;
            var bb = frm.geometricBounds;
            var imgH = bb[2] - bb[0];
            if (imgH <= 0) continue;
            try { var aos = frm.anchoredObjectSettings; aos.anchoredPosition = AnchorPosition.INLINE_POSITION; } catch (eAos){}
            try {
                var par = frm.parent.paragraphs[0];
                par.leading = imgH + 4;
                par.spaceBefore = 6;
                par.spaceAfter = 6;
                par.justification = Justification.CENTER_ALIGN;
                n++;
            } catch (ePar){}
            try { frm.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch (eTW){}
        } catch (eG){}
    }
    "INLINE_LEADING=" + n;
    """
    return app.DoScript(js, 1246973031)
# Reserves each body image's full height in the column flow: the image is set
# INLINE on its own paragraph and that paragraph's leading is set to the image
# height, so the line box is as tall as the image. Text above and below then
# makes room for it and can never render behind it. Replaces ABOVE_LINE, which
# drew a tall image UPWARD from a 12pt line and shot it off the page top onto the
# body text. Must run BEFORE the overset reflow so pagination accounts for the
# taller image lines. Skips the logo and table-cell images.


def force_body_images_inline(app):
    js = r"""
    var d = app.activeDocument;
    var n = 0;
    function isLogoName(nm){ if(!nm) return false; var u=nm.toUpperCase(); return u.indexOf('LEAF-BOUND')>=0 || u.indexOf('LOGO')>=0; }
    for (var i = 0; i < d.allGraphics.length; i++){
        try {
            var g = d.allGraphics[i];
            if (g.itemLink && isLogoName(g.itemLink.name)) continue;
            var frm = g.parent;
            var inCell = false;
            try { inCell = (frm.parent && frm.parent.constructor.name === "Cell"); } catch (eIC){}
            if (inCell) continue;
            try { var aos = frm.anchoredObjectSettings; aos.anchoredPosition = AnchorPosition.INLINE_POSITION; n++; } catch (eAos){}
            try { frm.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch (eTW){}
            try {
                if (frm.parent && frm.parent.paragraphs && frm.parent.paragraphs.length > 0){
                    frm.parent.paragraphs[0].justification = Justification.CENTER_ALIGN;
                }
            } catch (eJ){}
        } catch (eG){}
    }
    "FORCED_INLINE=" + n;
    """
    return app.DoScript(js, 1246973031)


def split_packed_placeholders(app, keep_pairs=None):
    """Split a paragraph that packs several image placeholders into one paragraph
    per placeholder, each keeping the caption that sits right before it, in
    document order. Runs BEFORE placement.

        "Morse and Semaphore Codes.###Insert image097.jpg here### Morse and
         Semaphore Codes.###Insert image098.jpg here###"   (one paragraph)
    becomes
        "Morse and Semaphore Codes.###Insert image097.jpg here###"   (paragraph)
        " Morse and Semaphore Codes.###Insert image098.jpg here###"  (paragraph)

    Without this, the placement step rewrites the whole packed paragraph and the
    images land out of order (098 before 097) with the caption duplicated. All
    images in these books are placed stacked (one per line), so splitting only
    corrects the order and gives each image exactly one caption. Returns the count
    of paragraphs split.
    """
    _kl = []
    for _pr in (keep_pairs or set()):
        _a = sorted(_pr)
        if len(_a) == 2:
            _kl.append('"%s|%s"' % (_a[0], _a[1]))
    _keep_js = "[" + ",".join(_kl) + "]"
    js = r'''
    var doc = app.activeDocument;
    var KEEP = __KEEP__;
    function countPH(s){ var c=0, re=/###Insert.*?here###/g; while(re.exec(s)!==null) c++; return c; }
    function phNames(s){ var out=[], re=/###Insert\s+(image\d+)/gi, m; while((m=re.exec(s))!==null) out.push(m[1].toLowerCase()); return out; }
    function isKeep(ns){ if(ns.length<2) return false; for(var i=0;i<ns.length-1;i++){ var k=[ns[i],ns[i+1]].sort().join("|"); for(var j=0;j<KEEP.length;j++){ if(KEEP[j]==k) return true; } } return false; }
    app.findGrepPreferences = NothingEnum.nothing;
    app.findGrepPreferences.findWhat = "###Insert.*?here###";
    var matches = doc.findGrep();
    app.findGrepPreferences = NothingEnum.nothing;
    var seen = {}, targets = [];
    for (var i = 0; i < matches.length; i++){
        try {
            var p = matches[i].paragraphs[0], st = p.parentStory;
            var key = st.id + ":" + p.characters[0].index;
            if (seen[key]) continue; seen[key] = true;
            if (countPH(p.contents) >= 2) targets.push({ sid: st.id, idx: p.characters[0].index });
        } catch (e) {}
    }
    targets.sort(function(a, b){ return b.idx - a.idx; });   // last-to-first so edits don't shift others
    var splitCount = 0;
    for (var t = 0; t < targets.length; t++){
        try {
            var story = doc.stories.itemByID(targets[t].sid);
            var para  = story.characters[targets[t].idx].paragraphs[0];
            var raw = para.contents.replace(/[\r\n]+$/, "");
            if (isKeep(phNames(raw))) {
                // Side-by-side pair: rebuild the SOURCE's borderless N-column
                // table so the images land in CELLS (which never overlap body
                // text), one placeholder per cell. Placement then fills each cell
                // and the downstream table/cell-image passes fit + centre them.
                try {
                    var phre = /###Insert.*?here###/g, mm, phs = [];
                    while ((mm = phre.exec(raw)) !== null) phs.push(mm[0]);
                    if (phs.length >= 2) {
                        var hostW = 0;
                        try {
                            var ptf = para.parentTextFrames;
                            if (ptf && ptf.length > 0) { var gbh = ptf[0].geometricBounds; hostW = gbh[3] - gbh[1]; }
                        } catch (eHW) {}
                        para.contents = phs.join("\t");
                        var fresh = story.characters[targets[t].idx].paragraphs[0];
                        var tbl = fresh.texts[0].convertToTable("\t", "\r");
                        try {
                            tbl.cells.everyItem().topEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().bottomEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().leftEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().rightEdgeStrokeWeight = 0;
                            tbl.cells.everyItem().topInset = 0;
                            tbl.cells.everyItem().bottomInset = 0;
                            tbl.cells.everyItem().leftInset = 0;
                            tbl.cells.everyItem().rightInset = 0;
                            tbl.cells.everyItem().verticalJustification = VerticalJustification.CENTER_ALIGN;
                        } catch (eB) {}
                        try {
                            if (hostW > 0 && tbl.columns.length > 0) {
                                var eachW = hostW / tbl.columns.length;
                                for (var ci = 0; ci < tbl.columns.length; ci++) tbl.columns[ci].width = eachW;
                            }
                        } catch (eCW) {}
                        splitCount++;
                    }
                } catch (eT) {}
                continue;   // side-by-side pair handled as a table
            }
            var re = /###Insert.*?here###/g, m, prev = 0, segs = [];
            while ((m = re.exec(raw)) !== null){ segs.push(raw.substring(prev, m.index) + m[0]); prev = re.lastIndex; }
            var trailing = raw.substring(prev);
            if (segs.length > 0 && trailing.replace(/\s+/g, "").length > 0) segs[segs.length - 1] += trailing;
            if (segs.length >= 2){ para.contents = segs.join("\r"); splitCount++; }
        } catch (e2) {}
    }
    splitCount.toString();
    '''
    js = js.replace("__KEEP__", _keep_js)
    return app.DoScript(js, 1246973031)


def relocate_figure_labels(app):
    """Standalone pass: normalise short figure-label paragraphs into captions.

    A figure label is a paragraph whose entire text is just a label such as
    "Fig. 1", "Fig. 2.", "Figure 1.", "Img. 1.", "img. 1.", "image 1." or
    "Image 1." (a keyword + a number). These often sit directly ABOVE the image
    placeholder. This pass:
      * moves a label found directly ABOVE an image to directly BELOW it, and
      * styles a label directly below (moved or already there) as a centred
        9pt figure caption using the shared "fig caption" paragraph style.

    Runs after image injection and before the overset reflow. Returns the count
    of labels processed (as a string).
    """
    js = r'''
    var doc = app.activeDocument;
    var LABEL = /^(figs?|figure|img|image)\.?\s*\d+\.?$/i;
    function isLogo(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf("LEAF-BOUND")>=0 || u.indexOf("LOGO")>=0; }
    function figStyle(){
        var st = doc.paragraphStyles.itemByName("fig caption");
        if (!st.isValid){
            st = doc.paragraphStyles.add({name:"fig caption"});
            try { st.justification = Justification.CENTER_ALIGN; } catch(e){}
            try { st.pointSize = 9; } catch(e){}
        }
        return st;
    }
    function styleCaption(p){
        try {
            p.appliedParagraphStyle = figStyle();
            p.justification = Justification.CENTER_ALIGN;
            // Plain regular text, no inherited character style / bold.
            try { p.appliedCharacterStyle = doc.characterStyles[0]; } catch(eC){}
            try { p.fontStyle = "Regular"; } catch(eF){}
            // Baseline 9pt; ALL-CAPS words -> 8pt.
            p.pointSize = 9;
            var ws = p.words;
            for (var i = 0; i < ws.length; i++) {
                var t = ws[i].contents;
                if ((t === t.toUpperCase()) && (t !== t.toLowerCase())) ws[i].pointSize = 8;
            }
        } catch(e){}
    }
    var count = 0;
    var graphics = doc.allGraphics;
    for (var g = 0; g < graphics.length; g++){
        try {
            var gr = graphics[g];
            if (gr.itemLink && isLogo(gr.itemLink.name)) continue;
            var frame = gr.parent;
            if (!frame || !frame.parent) continue;
            var imgPara = frame.parent.paragraphs[0];
            var host = imgPara.parentStory;
            var imgFirst = imgPara.characters[0].index;

            // 1) Label directly ABOVE the image -> move it BELOW, then style.
            if (imgFirst >= 1){
                var prevPara = host.characters[imgFirst - 1].paragraphs[0];
                var ptxt = prevPara.contents.replace(/[\r\n]+/g, "").replace(/^\s+|\s+$/g, "");
                if (LABEL.test(ptxt)){
                    prevPara.move(LocationOptions.AFTER, imgPara);
                    var ip = frame.parent.paragraphs[0];
                    var lastIdx = ip.characters[-1].index;
                    if (lastIdx + 1 < host.characters.length){
                        styleCaption(host.characters[lastIdx + 1].paragraphs[0]);
                    }
                    count++;
                    continue;
                }
            }

            // 2) Label already directly BELOW the image -> just style it.
            var lastIdx2 = imgPara.characters[-1].index;
            if (lastIdx2 + 1 < host.characters.length){
                var nextPara = host.characters[lastIdx2 + 1].paragraphs[0];
                var ntxt = nextPara.contents.replace(/[\r\n]+/g, "").replace(/^\s+|\s+$/g, "");
                if (LABEL.test(ntxt)){
                    styleCaption(nextPara);
                    count++;
                }
            }
        } catch (eG) {}
    }
    count.toString();
    '''
    return app.DoScript(js, 1246973031)

def process_batch_idmls(input_dir=None, epub_input_dir=None, output_dir=None, output_idml_dir=None, logo_path=None, target_files=None):
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _WF = os.path.dirname(_HERE)
    _REPO = os.path.dirname(_WF)

    if input_dir is None:
        _env_input = os.environ.get("INJECT_INPUT", "").strip()
        norm_cands = [
            os.path.join(_WF, "Output", "page_resize_output"),
            os.path.join(_WF, "page_resize_output"),
            os.path.join(_WF, "Output", "Formatted"),
            os.path.join(_REPO, "input_files"),
        ]
        if _env_input and os.path.isdir(_env_input):
            input_dir = _env_input
        else:
            input_dir = next(
                (c for c in norm_cands if os.path.isdir(c) and any(f.lower().endswith(".idml") for f in os.listdir(c))),
                os.path.join(_REPO, "input_files"),
            )
    print(f"Using IDMLs from input_dir: {input_dir}")

    if epub_input_dir is None:
        epub_input_dir = os.environ.get("EPUB_DIR", "").strip() or os.path.join(_REPO, "epub_input_files")
    base_image_dir = os.path.join(_HERE, "extracted_images")
    if output_dir is None:
        output_dir = os.environ.get("INJECT_OUTBASE", "").strip() or os.path.join(_WF, "final_output_files")
    if output_idml_dir is None:
        output_idml_dir = os.path.join(output_dir, "idml_files")
    if logo_path is None:
        logo_path = os.environ.get("LOGO_PATH", "").strip()
    if not logo_path or not os.path.exists(logo_path):
        for cand in [
            os.path.join(_REPO, "input_files", "logo", "LEAF-BOUND-trimmed.png"),
            os.path.join(_WF, "logo", "LEAF-BOUND-trimmed.png"),
            os.path.join(_WF, "logo", "LEAF-BOUND.png"),
        ]:
            if os.path.exists(cand):
                logo_path = cand
                break
    log_file = os.path.join(output_dir, "batch_injection_log.txt")

    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(output_idml_dir, exist_ok=True)
    os.makedirs(base_image_dir, exist_ok=True)

    clear_recovery_data()
    app = None
    for attempt in range(3):
        try:
            app = win32com.client.Dispatch('InDesign.Application')
            break
        except Exception:
            time.sleep(3)
            if attempt == 1:
                subprocess.run(["taskkill", "/F", "/IM", "InDesign.exe"], capture_output=True)
                time.sleep(3)
    if app is None:
        print("Error: Could not connect to Adobe InDesign after multiple attempts.")
        return

    try:
        app.DoScript(
            "app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;",
            1246973031,
        )
    except Exception:
        pass

    if target_files:
        idml_files = [os.path.basename(f) for f in target_files]
    else:
        idml_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.idml')]
    # Optional single/subset filter for testing (INJECT_ONLY="a.idml,b.idml").
    _only = os.environ.get("INJECT_ONLY", "").strip()
    if _only:
        wanted = {w.strip().lower() for w in _only.split(",") if w.strip()}
        idml_files = [f for f in idml_files if f.lower() in wanted]
        print(f"INJECT_ONLY set -> processing {idml_files}")
    if not idml_files:
        print(f"No IDML files found in: {input_dir}")
        return

    log_data = []
    log_data.append("=== Batch IDML Processing Log ===")
    log_data.append(f"Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_data.append("-" * 40)

    print(f"Found {len(idml_files)} IDML file(s). Starting batch process...")

    MAX_RETRIES_PER_DOC = 3
    files_to_process = list(idml_files)
    _retry_counts = {}

    for filename in files_to_process:
        _retry_counts.setdefault(filename, 0)
        while True:
            try:
                idml_path = os.path.join(input_dir, filename)
                base_name = os.path.splitext(filename)[0]

                # RESUME: if this book was already injected (e.g. a previous run was
                # killed after an InDesign hang), skip it so we continue from where
                # we stopped instead of redoing everything.
                clean_base = base_name.replace("_normalized", "").replace("_formatted", "")
                _already = os.path.join(output_idml_dir, f"{clean_base}_injected.idml")
                if not os.path.exists(_already):
                    _already = os.path.join(output_idml_dir, f"{base_name}_injected.idml")
                force_inject = os.environ.get("INJECT_FORCE", "0") == "1"
                if not force_inject and os.path.exists(_already):
                    if os.path.getmtime(_already) >= os.path.getmtime(idml_path):
                        print(f"SKIP (already injected): {filename}", flush=True)
                        log_data.append(f"SKIP already injected: {filename}")
                        break

                # Extract this book's images AND caption map straight from its EPUB.
                current_image_folder = os.path.join(base_image_dir, clean_base)
                caption_map = {}
                epub_path = os.path.join(epub_input_dir, clean_base + ".epub")
                if not os.path.exists(epub_path):
                    epub_path = os.path.join(epub_input_dir, base_name + ".epub")
                if os.path.exists(epub_path):
                    try:
                        n_imgs, caption_map = epub_tools.extract_epub(epub_path, current_image_folder)
                        print(f"EPUB: extracted {n_imgs} image(s), {len(caption_map)} caption(s) from {os.path.basename(epub_path)}")
                        log_data.append(f"EPUB: {n_imgs} images, {len(caption_map)} captions from {os.path.basename(epub_path)}")
                    except Exception as e_epub:
                        print(f"EPUB extraction failed for {clean_base}: {e_epub}")
                        log_data.append(f"EPUB extraction failed for {clean_base}: {e_epub}")
                else:
                    print(f"WARNING: no EPUB at {epub_path}")
                    log_data.append(f"WARNING: no EPUB for {clean_base}")

                output_idml = os.path.join(output_idml_dir, f"{clean_base}_injected.idml")

                doc_temp_dir = os.path.join(output_dir, "_resized", clean_base)
                if os.path.exists(doc_temp_dir):
                    shutil.rmtree(doc_temp_dir, ignore_errors=True)
                os.makedirs(doc_temp_dir, exist_ok=True)

                print(f"\n{'-'*50}")
                print(f"Processing Document: {filename}")
                print(f"Using Image Folder: {current_image_folder}")
                log_data.append(f"\n--- Document: {filename} ---")
                log_data.append(f"Image Folder: {current_image_folder}")

                clean_idml_path = idml_path.replace(chr(92), "/")
                js_open_doc = f"""
                app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT;
                app.scriptPreferences.enableRedraw = false;
                var idmlPath = "{clean_idml_path}";
                var doc = app.open(new File(idmlPath));

                try {{ doc.textPreferences.smartTextReflow = false; }} catch (eSTR) {{}}
                try {{ app.textPreferences.smartTextReflow = false; }} catch (eSTRa) {{}}
                """
                app.DoScript(js_open_doc, 1246973031)

                input_pages = 0
                try:
                    input_pages = int(app.DoScript("app.activeDocument.pages.length + '';", 1246973031))
                except Exception:
                    pass
                print(f"Input pages: {input_pages}")
                log_data.append(f"Input pages: {input_pages}")

                # NOTE: the logo is handled entirely by the dedicated logo_inject
                # pass at the very end (relink + size + position), isolated from the
                # body-image injection below.

                # Split packed multi-image paragraphs so images land in document
                # order (097 before 098) with one caption each.
                try:
                    _src_orig = os.path.join(_REPO, "input_files", f"{clean_base}.idml")
                    _keep = source_sidebyside_pairs(_src_orig) if os.path.exists(_src_orig) else set()
                    if _keep:
                        print(f"Side-by-side pairs kept packed: {sorted(sorted(x) for x in _keep)}")
                        log_data.append(f"Side-by-side pairs kept packed: {sorted(sorted(x) for x in _keep)}")
                    n_split = split_packed_placeholders(app, keep_pairs=_keep)
                    print(f"Packed paragraphs split: {n_split}")
                    log_data.append(f"Packed paragraphs split: {n_split}")
                except Exception as e_split:
                    print(f"Packed split skipped: {e_split}")
                    log_data.append(f"Packed split skipped: {e_split}")

                js_find_all = """
                app.findGrepPreferences = NothingEnum.nothing;
                app.findGrepPreferences.findWhat = "###Insert[\\\\s~s]+.*?[\\\\s~s]+here###";
                var matches = app.activeDocument.findGrep();
                var results = [];
                for (var i = 0; i < matches.length; i++) {
                    results.push(matches[i].contents);
                }
                app.findGrepPreferences = NothingEnum.nothing;
                results.join("|||");
                """

                match_data = app.DoScript(js_find_all, 1246973031)

                if match_data:
                    placeholders = match_data.split("|||")
                    total = len(placeholders)
                    print(f"Found {total} placeholders. Injecting images...")

                    success_count = 0
                    fail_count = 0
                    failed_images = []

                    for i in range(total - 1, -1, -1):
                        content = placeholders[i]
                        img_name = re.sub(r'[\r\n\t\u00a0\u200b]+', ' ', content)
                        img_name = img_name.replace("###Insert", "").replace("here###", "").strip()
                        
                        img_path = os.path.join(current_image_folder, img_name)
                        iteration = total - i

                        if not os.path.exists(img_path) and os.path.exists(current_image_folder):
                            clean_target = img_name.strip().lower()
                            for f_on_disk in os.listdir(current_image_folder):
                                if f_on_disk.strip().lower() == clean_target:
                                    img_path = os.path.join(current_image_folder, f_on_disk)
                                    img_name = f_on_disk
                                    break

                        if os.path.exists(img_path):
                            final_img_path = prepare_image(img_path, doc_temp_dir)
                            # JS-string-safe literal for substring matching (indexOf), not a regex.
                            js_name = img_name.replace('\\', '\\\\').replace('"', '\\"')
                            clean_img_path = final_img_path.replace(chr(92), "/")

                            js_place = f"""
                            var __result = "false";
                            var __name = "{js_name}";
                            // Robust placeholder finder: the literal image name cannot be embedded
                            // directly in the GREP because InDesign findGrep fails to anchor a
                            // literal token across a <Content> run boundary (some placeholders are
                            // split into two runs, e.g. "###Insert " + "imageNNN.jpg here###").
                            // Instead we match the whole "###Insert ... here###" span (which does
                            // cross run boundaries) and filter by name via indexOf.
                            function findPH() {{
                                app.findGrepPreferences = NothingEnum.nothing;
                                app.findGrepPreferences.findWhat = "###Insert.*?here###";
                                var all = app.activeDocument.findGrep();
                                app.findGrepPreferences = NothingEnum.nothing;
                                for (var k = 0; k < all.length; k++) {{
                                    if (all[k].contents.indexOf(__name) !== -1) return all[k];
                                }}
                                return null;
                            }}
                            try {{
                                var match = findPH();

                                if (match !== null) {{
                                    var matchStr = match.contents;

                                    // Side-by-side detection: step1 flattens a 2-column image
                                    // table into ONE paragraph holding two "###Insert" tokens
                                    // (e.g. image064 + image065). Such images must sit on one
                                    // line, not stacked. A paragraph with >=2 placeholders, or
                                    // whose sibling image is already placed while a placeholder
                                    // remains, is a side-by-side group.
                                    var _phPara0 = "";
                                    try {{ _phPara0 = match.paragraphs[0].contents; }} catch (ePP0) {{}}
                                    var _phCount = (_phPara0.match(/###Insert/g) || []).length;
                                    var _sibGraphics = 0;
                                    try {{ _sibGraphics = match.paragraphs[0].allGraphics.length; }} catch (eSG0) {{}}
                                    var sideBySide = (_phCount >= 2) || (_sibGraphics >= 1 && _phPara0.indexOf("###Insert") !== -1);

                                    var maxAllowedWidth = 324;
                                    try {{
                                        if (match.parentTextFrames && match.parentTextFrames.length > 0) {{
                                            var tfBounds = match.parentTextFrames[0].geometricBounds;
                                            maxAllowedWidth = tfBounds[3] - tfBounds[1];
                                        }}
                                    }} catch (eWidth) {{}}

                                    var captionText = "";
                                    try {{
                                        var paraTxt = match.paragraphs[0].contents;
                                        captionText = paraTxt.replace(matchStr, "")
                                                             .replace(/[\\r\\n\\t\\u00A0\\u2028\\uFEFF]/g, " ")
                                                             .replace(/\\s+/g, " ")
                                                             .replace(/^\\s+|\\s+$/g, "");
                                        if (/^(chapter|cap[íi]tulo|book|libro|part|parte|[ivxlcdm0-9]+[\\s\\.\\:\\-])/i.test(captionText)) {{
                                            captionText = "";
                                        }}
                                    }} catch (eCap) {{}}
                                    // A side-by-side sibling placeholder is NOT a caption.
                                    if (sideBySide) {{ captionText = ""; }}

                                    try {{
                                        if (captionText.length > 0) {{
                                            match.paragraphs[0].contents = matchStr + "\\r" + captionText + "\\r";
                                            match = findPH();
                                        }}
                                    }} catch (eRew) {{}}

                                    if (match === null) {{
                                        app.findGrepPreferences = NothingEnum.nothing;
                                        __result = "false";
                                    }} else {{
                                        var _story = match.parentStory;
                                        var _pIdx = match.paragraphs[0].index;

                                        var targetFile = new File("{clean_img_path}");
                                        var placedItems = match.place(targetFile);

                                        if (placedItems && placedItems.length > 0) {{
                                            try {{
                                                var frame = placedItems[0].parent;
                                                frame.fit(FitOptions.FRAME_TO_CONTENT);

                                                try {{ frame.textWrapPreferences.textWrapMode = TextWrapModes.NONE; }} catch (eTW) {{}}

                                                try {{
                                                    var aos = frame.anchoredObjectSettings;
                                                    if (sideBySide) {{
                                                        // Inline so both images flow on the SAME
                                                        // (centered) line, side by side.
                                                        aos.anchoredPosition = AnchorPosition.INLINE_POSITION;
                                                    }} else {{
                                                        // ABOVE_LINE places the image as a block above its anchor
                                                        // line, taking its full height with no baseline/leading
                                                        // interaction (the proven, no-crop placement). spaceBefore/
                                                        // spaceAfter give a small gap; centring is via the anchored
                                                        // object settings below.
                                                        aos.anchoredPosition         = AnchorPosition.ABOVE_LINE;
                                                        aos.spaceBefore              = 6;
                                                        aos.spaceAfter               = 6;
                                                        aos.horizontalAlignment      = HorizontalAlignment.CENTER_ALIGN;
                                                        aos.horizontalReferencePoint = AnchoredRelativeTo.COLUMN_EDGE;
                                                    }}
                                                }} catch (eAnc) {{}}

                                                try {{
                                                    // Leave a 4pt gap on the left and right of every image so it
                                                    // never touches the column margins (max width = column - 8pt).
                                                    var SIDE_PAD = 4;
                                                    var hostTF = (match.parentTextFrames && match.parentTextFrames.length > 0) ? match.parentTextFrames[0] : null;
                                                    var maxW = maxAllowedWidth - 2 * SIDE_PAD;
                                                    var maxH = 450;
                                                    if (hostTF) {{
                                                        var tb = hostTF.geometricBounds;
                                                        maxW = (tb[3] - tb[1]) - 2 * SIDE_PAD;
                                                        maxH = (tb[2] - tb[0]) * 0.90;
                                                    }}
                                                    // Each side-by-side image gets half the column
                                                    // (minus a 10pt inter-image gap) so the pair fits.
                                                    if (sideBySide) {{ maxW = (maxW - 10) / 2; }}
                                                    var gb = frame.geometricBounds;
                                                    var fw = gb[3] - gb[1];
                                                    var fh = gb[2] - gb[0];
                                                    var scale = 1.0;
                                                    if (fw > maxW) scale = Math.min(scale, maxW / fw);
                                                    if (fh > maxH) scale = Math.min(scale, maxH / fh);
                                                    if (scale < 1.0) {{
                                                        frame.geometricBounds = [gb[0], gb[1], gb[0] + fh * scale, gb[1] + fw * scale];
                                                        frame.fit(FitOptions.CONTENT_TO_FRAME);
                                                    }}
                                                }} catch (eFit) {{}}

                                                try {{ frame.parent.paragraphs[0].justification = Justification.CENTER_ALIGN; }} catch (eP1) {{}}

                                                // Figure caption = the inline text that was moved BELOW the
                                                // image. It only exists when the placeholder had image + text
                                                // (captionText.length > 0). Such a paragraph gets the dedicated
                                                // "fig caption" paragraph style (created once per doc: centred,
                                                // 9pt base). ALL-CAPS words are then overridden to 8pt (per-word
                                                // sizing cannot live in a paragraph style).
                                                try {{
                                                    if (captionText.length > 0) {{
                                                        var _doc = app.activeDocument;
                                                        // Re-derive the caption paragraph AFTER placement from the
                                                        // anchored image frame. NOTE: paragraph.index is a CHARACTER
                                                        // offset (not a paragraph ordinal), so paragraphs[idx+1] is
                                                        // wrong; instead we step one character past the image
                                                        // paragraph's end and read that paragraph.
                                                        var _imgPara = frame.parent.paragraphs[0];
                                                        var _host = _imgPara.parentStory;
                                                        var _lastChar = _imgPara.characters[-1].index;
                                                        if ((_lastChar + 1) < _host.characters.length) {{
                                                            var figStyle = _doc.paragraphStyles.itemByName("fig caption");
                                                            if (!figStyle.isValid) {{
                                                                figStyle = _doc.paragraphStyles.add({{name: "fig caption"}});
                                                                try {{ figStyle.justification = Justification.CENTER_ALIGN; }} catch (eFJ) {{}}
                                                                try {{ figStyle.pointSize = 9; }} catch (eFS) {{}}
                                                            }}

                                                            var capPara = _host.characters[_lastChar + 1].paragraphs[0];
                                                            var sName = capPara.appliedParagraphStyle.name.toLowerCase();
                                                            var isHeading = (sName.indexOf("chapter") !== -1 || sName.indexOf("chap") !== -1 || sName.indexOf("sub-heading") !== -1);
                                                            if (!isHeading) {{
                                                                capPara.appliedParagraphStyle = figStyle;
                                                                capPara.justification = Justification.CENTER_ALIGN;
                                                                // Strip any inherited character style / bold so the
                                                                // whole caption is plain regular text (the source often
                                                                // has the title in a "boldtext" character style).
                                                                try {{ capPara.appliedCharacterStyle = _doc.characterStyles[0]; }} catch (eCS) {{}}
                                                                try {{ capPara.fontStyle = "Regular"; }} catch (eFSr) {{}}
                                                                // Baseline 9pt (covers spaces/punctuation), then bump
                                                                // ALL-CAPS words to 8pt.
                                                                capPara.pointSize = 9;
                                                                var capWords = capPara.words;
                                                                for (var cw = 0; cw < capWords.length; cw++) {{
                                                                    var wtext = capWords[cw].contents;
                                                                    var isAllCaps = (wtext === wtext.toUpperCase()) && (wtext !== wtext.toLowerCase());
                                                                    if (isAllCaps) capWords[cw].pointSize = 8;
                                                                }}
                                                            }}
                                                        }}
                                                    }}
                                                }} catch (eP2) {{}}
                                            }} catch (ePost) {{}}
                                        }}
                                        app.findGrepPreferences = NothingEnum.nothing;
                                        __result = "true";
                                    }}
                                }} else {{
                                    app.findGrepPreferences = NothingEnum.nothing;
                                    __result = "false";
                                }}
                            }} catch (topErr) {{
                                try {{ app.findGrepPreferences = NothingEnum.nothing; }} catch (e){{}}
                                __result = "err:" + topErr.message;
                            }}
                            __result;
                            """
                            try:
                                res = app.DoScript(js_place, 1246973031)
                                if res == "true":
                                    success_count += 1
                                elif isinstance(res, str) and res.startswith("err:"):
                                    fail_count += 1
                                    failed_images.append(f"{img_name} (JS: {res[4:]})")
                                else:
                                    fail_count += 1
                                    failed_images.append(f"{img_name} (Placeholder Not Found)")
                            except Exception as e:
                                fail_count += 1
                                failed_images.append(f"{img_name} (Py Error: {str(e).strip()})")
                        else:
                            fail_count += 1
                            failed_images.append(f"{img_name} (File Not Found in '{current_image_folder}')")

                        percent = int(100 * (iteration / float(total)))
                        filled = int(30 * iteration // total)
                        bar = '#' * filled + '.' * (30 - filled)
                        sys.stdout.write(f"\rProgress: [{bar}] {percent}% | Processing: {img_name}".ljust(80))
                        sys.stdout.flush()

                    print(f"\nImage Injection: {success_count} Injected | {fail_count} Failed")
                    log_data.append(f"Images: {success_count} Injected, {fail_count} Failed")
                    if failed_images:
                        log_data.append("Failed Images List:")
                        for fi in failed_images:
                            log_data.append(f"  - {fi}")
                else:
                    print("No image placeholders found in this document.")
                    log_data.append("Images: 0 placeholders found.")

                # EPUB caption pass: put each image's EPUB <figcaption> BELOW the
                # image and remove the original caption (above / inline / interleaved)
                # so nothing is duplicated. Runs before the reflow so pagination
                # accounts for the caption paragraphs.
                try:
                    caps_applied = epub_caption_apply.apply_captions(app, caption_map)
                    print(f"EPUB captions placed below images: {caps_applied}")
                    log_data.append(f"EPUB captions placed: {caps_applied}")
                except Exception as e_cap:
                    print(f"EPUB caption pass skipped: {e_cap}")
                    log_data.append(f"EPUB caption pass skipped: {e_cap}")

                # Separate pass: give the FIRST half of a split figure its caption
                # too (when it is directly followed by the second image).
                try:
                    caps_split = epub_caption_apply.ensure_split_figure_captions(app, caption_map)
                    print(f"Split-figure captions inserted: {caps_split}")
                    log_data.append(f"Split-figure captions inserted: {caps_split}")
                except Exception as e_csf:
                    print(f"Split-figure caption pass skipped: {e_csf}")
                    log_data.append(f"Split-figure caption pass skipped: {e_csf}")

                # Separate cleanup pass: remove any duplicate caption and fix a
                # caption that got fused onto the following body paragraph.
                try:
                    caps_clean = epub_caption_apply.cleanup_caption_artifacts(app, caption_map)
                    print(f"Caption artifacts cleaned: {caps_clean}")
                    log_data.append(f"Caption artifacts cleaned: {caps_clean}")
                except Exception as e_ccl:
                    print(f"Caption cleanup pass skipped: {e_ccl}")
                    log_data.append(f"Caption cleanup pass skipped: {e_ccl}")

                # DISABLED: normalize_captions_below_images ran AFTER cleanup_caption_artifacts,
                # so any duplicate caption it re-inserted on a split figure (two images
                # sharing one caption) was never deduped and the book was rejected with
                # CAPTION_DUP. The proven reference runs only apply_captions +
                # ensure_split_figure_captions + cleanup_caption_artifacts, so this
                # extra normalise pass is intentionally not run.

                # Reserve each body image's full height in the flow (INLINE + leading =
                # image height) so a tall image never overlaps the text above it. Runs
                # before the overset reflow so pagination accounts for the taller lines.
                try:
                    inl = set_body_image_inline_leading(app)
                    print(f"Body image inline-leading set: {inl}")
                    log_data.append(f"Body image inline-leading: {inl}")
                except Exception as e_inl:
                    print(f"Inline-leading pass skipped: {e_inl}")
                    log_data.append(f"Inline-leading pass skipped: {e_inl}")

                # Convert non-breaking spaces to regular spaces BEFORE reflow.
                # After the page-resize normalization narrowed the columns, any line
                # joined entirely by non-breaking spaces (~S / ~s) that is wider than
                # the column becomes unbreakable: InDesign cannot place a single
                # character, a freshly added frame accepts 0 characters, and the
                # reflow loop's safeguard then abandons ALL remaining text as overset.
                # Normalizing them to breakable spaces lets the text reflow correctly.
                js_fix_nbsp = """
                var doc = app.activeDocument;
                app.findGrepPreferences = NothingEnum.nothing;
                app.changeGrepPreferences = NothingEnum.nothing;
                app.findGrepPreferences.findWhat = "~S|~s";
                app.changeGrepPreferences.changeTo = " ";
                var changed = doc.changeGrep();
                app.findGrepPreferences = NothingEnum.nothing;
                app.changeGrepPreferences = NothingEnum.nothing;
                changed.length + "";
                """
                try:
                    nbsp_fixed = app.DoScript(js_fix_nbsp, 1246973031)
                    print(f"Non-breaking spaces normalized: {nbsp_fixed}")
                    log_data.append(f"Non-breaking spaces normalized: {nbsp_fixed}")
                except Exception as e_nbsp:
                    print(f"Non-breaking space normalization skipped: {e_nbsp}")
                    log_data.append(f"NBSP normalization skipped: {e_nbsp}")

                # Convert single-cell poem/list tables to flowing text BEFORE the
                # reflow so they can break across pages (a 1-cell table is one
                # unbreakable row that would otherwise be forced onto one page and
                # truncate itself and the text after it).
                try:
                    sc_conv = fix_table_fit.convert_single_cell_tables(app)
                    print(f"Single-cell tables -> text (pre-reflow): {sc_conv}")
                    log_data.append(f"Single-cell tables -> text (pre-reflow): {sc_conv}")
                except Exception as e_sc:
                    print(f"Pre-reflow single-cell conversion skipped: {e_sc}")
                    log_data.append(f"Pre-reflow single-cell conversion skipped: {e_sc}")

                # Overset reflow loop: dynamic page addition + cause-agnostic jam escape.
                #
                # PROBLEM this solves generally (works for ANY file, not just known cases):
                # A freshly added, full-size text frame can accept 0 characters yet still
                # overflow. That happens whenever the next content unit cannot fit a page
                # AND cannot break: a table row taller than the page, an anchored image
                # taller than the page, an unbreakable line wider than the column, a huge
                # word, etc. The old logic simply `break`-ed on that condition, silently
                # abandoning ALL remaining text as overset.
                #
                # NEW LOGIC (no per-cause special handling):
                #   1. Add pages while the story overflows (as before).
                #   2. If a fresh frame accepts 0 chars but overflows (a "jam"), GROW that
                #      frame (height first, then a little width) until it accepts the stuck
                #      element. This forces the oversized element onto the page so the flow
                #      continues and NO text is lost. The oversized frame is intentionally
                #      left larger than the page so it is easy to spot and fix by hand.
                #   3. Every jam is RECORDED (page, style, text snippet, forced size). If an
                #      element is so large it cannot be placed even after max growth, it is
                #      recorded as UNRESOLVED together with the remaining overset text.
                #   4. The full report is written to <name>_overset_report.txt so problems
                #      can be fixed step by step.
                # Enable hyphenation on the body text too (same hyphen rule as the
                # tables): long words break with a hyphen, which also tightens
                # justified lines so no extra space is added between words. Done
                # BEFORE the reflow so pagination accounts for it.
                js_hyphenate_body = r"""
                var doc = app.activeDocument;
                var styles = doc.allParagraphStyles;
                var n = 0;
                for (var i = 0; i < styles.length; i++){
                    try { styles[i].hyphenation = true; } catch(e){}
                    try { styles[i].hyphenateCapitalizedWords = true; } catch(e){}
                    var sName = styles[i].name.toLowerCase();
                    if ((sName.indexOf("chapter") !== -1 || sName.indexOf("chap") !== -1) && sName.indexOf("after") === -1) {
                        try { styles[i].startParagraph = StartParagraph.NEXT_PAGE; } catch(e1){
                            try { styles[i].startParagraph = StartParagraph.nextPage; } catch(e2){}
                        }
                        try { styles[i].keepAllLinesTogether = true; } catch(e){}
                        try { styles[i].keepLinesTogether = true; } catch(e){}
                        try { styles[i].keepWithNext = 2; } catch(e){}
                    }
                    if (sName.indexOf("after") !== -1) {
                        try { styles[i].startParagraph = StartParagraph.ANYWHERE; } catch(e1){
                            try { styles[i].startParagraph = StartParagraph.anywhere; } catch(e2){}
                        }
                    }
                    if (sName.indexOf("sub-heading") !== -1 || sName.indexOf("heading") !== -1) {
                        try { styles[i].keepWithNext = 2; } catch(e){}
                        try { styles[i].keepLinesTogether = true; } catch(e){}
                    }
                    if (sName.indexOf("body") !== -1 || sName.indexOf("normal") !== -1 || sName.indexOf("basic") !== -1 || sName.indexOf("noindent") !== -1) {
                        try { styles[i].keepLinesTogether = true; } catch(e){}
                        try { styles[i].keepAllLinesTogether = false; } catch(e){}
                        try { styles[i].keepFirstAndLastLines = true; } catch(e){}
                        try { styles[i].minLinesAtStart = 2; } catch(e){}
                        try { styles[i].minLinesAtEnd = 2; } catch(e){}
                    }
                    n++;
                }


                n + "";
                """
                try:
                    hy = app.DoScript(js_hyphenate_body, 1246973031)
                    print(f"Hyphenation enabled on {hy} paragraph styles")
                    log_data.append(f"Hyphenation enabled: {hy} styles")
                except Exception as e_hy:
                    print(f"Hyphenation enable skipped: {e_hy}")
                    log_data.append(f"Hyphenation enable skipped: {e_hy}")

                print("Resolving overset text frames dynamically...")
                js_resolve_overset = """
                var doc = app.activeDocument;
                var oldRuler = doc.viewPreferences.rulerOrigin;
                doc.viewPreferences.rulerOrigin = RulerOrigin.PAGE_ORIGIN;
                var pageH = doc.documentPreferences.pageHeight;
                var pageW = doc.documentPreferences.pageWidth;
                var pagesAdded = 0;
                var jams = [];

                var HEIGHT_STEP = 72;   // grow ~1 line-block per step
                var WIDTH_STEP  = 12;   // gentle width relief for over-wide unbreakable lines
                var MAX_STEPS   = 40;   // up to ~40 * 72pt (~5 pages) of forced growth

                function frameGeom(page) {
                    var top = page.marginPreferences.top;
                    var bottom = pageH - page.marginPreferences.bottom;
                    var left, right;
                    if (doc.documentPreferences.facingPages && page.side == PageSideOptions.LEFT_HAND) {
                        left  = page.marginPreferences.right;
                        right = pageW - page.marginPreferences.left;
                    } else {
                        left  = page.marginPreferences.left;
                        right = pageW - page.marginPreferences.right;
                    }
                    return [top, left, bottom, right];
                }

                function describeStuck(frame, story) {
                    var info = { idx: -1, style: "", text: "" };
                    try {
                        var prev = frame.previousTextFrame;
                        info.idx = prev.characters[-1].index + 1;
                        var par = story.characters[info.idx].paragraphs[0];
                        info.style = par.appliedParagraphStyle.name;
                        var t = par.contents.replace(/[\\r\\n\\t]+/g, " ");
                        info.text = (t.length > 140) ? t.substring(0, 140) + "..." : t;
                    } catch (e) {}
                    return info;
                }

                for (var i = 0; i < doc.stories.length; i++) {
                    var s = doc.stories[i];
                    s.recompose();
                    if (s.textContainers.length === 0) continue;
                    var lastFrame = s.textContainers[s.textContainers.length - 1];
                    if (lastFrame.constructor.name !== "TextFrame") continue;

                    // Standalone front-matter stories (Title on Page 1, Copyright on Page 2)
                    // must NEVER have pages added at the end of the document.
                    // Only the flowing body text story should spawn pages.
                    try {
                        var firstContainer = s.textContainers[0];
                        if (firstContainer.parentPage) {
                            var pNum = parseInt(firstContainer.parentPage.name, 10);
                            if (pNum === 1 || pNum === 2) continue;
                            if (s.textContainers.length === 1 && (pNum <= 6 || s.characters.length < 2000)) continue;
                        }
                    } catch (eFm) {}

                    var guard = 0;
                    while (lastFrame.overflows) {
                        guard++;
                        if (guard > 30000) { jams.push("ABORT|story " + i + "|guard limit reached"); break; }

                        var newPage = doc.pages.add();
                        pagesAdded++;
                        var newFrame = newPage.textFrames.add();
                        newFrame.geometricBounds = frameGeom(newPage);
                        lastFrame.nextTextFrame = newFrame;
                        lastFrame = newFrame;
                        s.recompose();

                        if (lastFrame.characters.length === 0 && lastFrame.overflows) {
                            // JAM: the next content unit cannot fit or break on a normal page.
                            var stuck = describeStuck(lastFrame, s);

                            // GENERAL ESCAPE: grow the frame until it accepts the stuck unit.
                            var steps = 0;
                            while (lastFrame.characters.length === 0 && lastFrame.overflows && steps < MAX_STEPS) {
                                var gb = lastFrame.geometricBounds;
                                var newBottom = gb[2] + HEIGHT_STEP;
                                var newRight  = Math.min(gb[3] + WIDTH_STEP, pageW - 6);
                                lastFrame.geometricBounds = [gb[0], gb[1], newBottom, newRight];
                                steps++;
                                s.recompose();
                            }
                            var fh = (lastFrame.geometricBounds[2] - lastFrame.geometricBounds[0]);

                            if (lastFrame.characters.length === 0 && lastFrame.overflows) {
                                // Still unplaceable after max growth: capture the remaining overset text.
                                var remaining = "";
                                try {
                                    var start = lastFrame.previousTextFrame.characters[-1].index + 1;
                                    remaining = s.contents.substring(start);
                                    if (remaining.length > 4000) remaining = remaining.substring(0, 4000) + " ...[truncated]";
                                    remaining = remaining.replace(/[\\r\\n\\t]+/g, " ");
                                } catch (e) {}
                                jams.push("UNRESOLVED|page~" + doc.pages.length + "|storyIdx=" + stuck.idx +
                                          "|style=" + stuck.style + "|stuck=[" + stuck.text + "]|REMAINING_TEXT=[" + remaining + "]");
                                break; // cannot proceed on this thread; stop to avoid an infinite loop
                            } else {
                                jams.push("FORCED|page~" + doc.pages.length + "|storyIdx=" + stuck.idx +
                                          "|style=" + stuck.style + "|frameHeight=" + fh.toFixed(0) + "pt|content=[" + stuck.text + "]");
                            }
                        }
                    }
                }
                doc.viewPreferences.rulerOrigin = oldRuler;

                var oversetLeft = 0;
                for (var q = 0; q < doc.stories.length; q++) {
                    var cs = doc.stories[q].textContainers;
                    for (var j = 0; j < cs.length; j++) { if (cs[j].overflows) oversetLeft++; }
                }
                "PAGES=" + pagesAdded + "|OVERSET=" + oversetLeft + "|JAMS=" + jams.length + "\\n" + jams.join("\\n");
                """
                try:
                    reflow_report = app.DoScript(js_resolve_overset, 1246973031)
                    # First line is the summary; the rest are per-jam report lines.
                    report_lines = str(reflow_report).split("\n")
                    summary_line = report_lines[0] if report_lines else ""
                    jam_lines = [ln for ln in report_lines[1:] if ln.strip()]

                    # Parse summary for logging/printing.
                    added_str = "0"
                    overset_left = "0"
                    try:
                        parts = dict(p.split("=", 1) for p in summary_line.split("|") if "=" in p)
                        added_str = parts.get("PAGES", "0")
                        overset_left = parts.get("OVERSET", "0")
                    except Exception:
                        pass

                    print(f"Overset reflow: added {added_str} page(s) | remaining overset frames: {overset_left} | issues flagged: {len(jam_lines)}")
                    log_data.append(f"Overset reflow: added {added_str} page(s), remaining overset frames {overset_left}, issues flagged {len(jam_lines)}")

                    # Write a per-document report so each problem can be fixed step by step.
                    if jam_lines:
                        report_path = os.path.join(output_dir, f"{base_name}_overset_report.txt")
                        with open(report_path, "w", encoding="utf-8") as rf:
                            rf.write(f"Overset / oversized-content report for {filename}\n")
                            rf.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                            rf.write(f"{summary_line}\n")
                            rf.write("-" * 60 + "\n")
                            rf.write("FORCED  = oversized element auto-placed on a grown frame (fix layout by hand).\n")
                            rf.write("UNRESOLVED = element too large even after growth; remaining text captured below.\n")
                            rf.write("-" * 60 + "\n\n")
                            for ln in jam_lines:
                                rf.write(ln + "\n\n")
                        print(f"  Report written: {report_path}")
                        log_data.append(f"Overset report: {report_path}")
                        for ln in jam_lines:
                            log_data.append(f"  {ln[:200]}")
                except Exception as e_over_outer:
                    added_str = "0"
                    print(f"Error resolving overset: {e_over_outer}")
                    log_data.append(f"Error resolving overset: {e_over_outer}")

                # Table fix — AFTER the main reflow so table cells are composed and
                # their overset state is accurate. Makes each table's text visible by
                # auto-resizing columns/insets only (no font change, no word spacing),
                # keeps tables within the text column, centres narrow left-aligned
                # tables, and re-flows vertically so a tall table SPLITS across pages
                # (instead of growing the text frame) -- keeping the body text flowing.
                try:
                    tbl_res = fix_table_fit.fix_tables_in_doc(app)
                    print(f"Tables fixed: {tbl_res}")
                    log_data.append(f"Tables fixed: {tbl_res}")
                except Exception as e_tbl:
                    print(f"Table fix pass skipped: {e_tbl}")
                    log_data.append(f"Table fix pass skipped: {e_tbl}")

                js_center_all = """
                var d = app.activeDocument;
                var fixed = 0;
                function isLogoName(n){ if(!n) return false; var u=n.toUpperCase(); return u.indexOf('LEAF-BOUND')>=0 || u.indexOf('LOGO')>=0; }
                for (var i = 0; i < d.allGraphics.length; i++) {
                    try {
                        var g = d.allGraphics[i];
                        if (g.itemLink && isLogoName(g.itemLink.name)) continue;
                        var frm = g.parent;
                        var _skipFloat = false;
                        try { if (frm.label == "INLINE_SINGLE_IMG") _skipFloat = true; } catch (eLbl) {}
                        var _inCellSweep = false;
                        try { _inCellSweep = (frm.parent && frm.parent.constructor.name === "Cell"); } catch (eIC2) {}
                        try {
                            var aosChk = frm.anchoredObjectSettings;
                            if (!_inCellSweep && aosChk.anchoredPosition == AnchorPosition.INLINE_POSITION) _skipFloat = true;
                        } catch (ePos) {}
                        if (!_skipFloat) {
                            try {
                                var aos = frm.anchoredObjectSettings;
                                aos.horizontalAlignment      = HorizontalAlignment.CENTER_ALIGN;
                                aos.horizontalReferencePoint = AnchoredRelativeTo.COLUMN_EDGE;
                            } catch (eA) {}
                            try { frm.textWrapPreferences.textWrapMode = TextWrapModes.NONE; } catch (eTW) {}
                        }
                        try {
                            if (frm.parent && frm.parent.paragraphs && frm.parent.paragraphs.length > 0) {
                                frm.parent.paragraphs[0].justification = Justification.CENTER_ALIGN;
                                fixed++;
                            }
                        } catch (eP) {}
                    } catch (eG) {}
                }
                "centered " + fixed + " graphics";
                """
                try:
                    res_c = app.DoScript(js_center_all, 1246973031)
                    log_data.append(f"Center sweep: {res_c}")
                except Exception as e:
                    log_data.append(f"Center sweep failed: {e}")

                output_pages = 0
                try:
                    output_pages = int(app.DoScript("app.activeDocument.pages.length + '';", 1246973031))
                except Exception:
                    pass
                page_delta = output_pages - input_pages
                summary = f"Output pages: {output_pages} (added {page_delta} pages after injection)"
                print(summary)
                log_data.append(summary)

                # Standalone pass: fix any images that overflow the margin box
                # (side-by-side above-line groups, or oversized images). Runs after
                # pagination is final and before export; does not touch well-placed images.
                try:
                    imgs_fixed = fix_image_layout.fix_image_layout(app)
                    print(f"Image layout fixed: {imgs_fixed} image(s) re-fitted within margins")
                    log_data.append(f"Image layout fixed: {imgs_fixed}")
                except Exception as e_fil:
                    print(f"Image layout pass skipped: {e_fil}")
                    log_data.append(f"Image layout pass skipped: {e_fil}")

                # Separate pass: centre images anchored inside table cells within
                # their column (removes the uniform rightward offset that pushes a
                # side-by-side figure's outer image past the page margin).
                try:
                    centered = fix_image_layout.center_images_in_cells(app)
                    print(f"Cell images centered: {centered}")
                    log_data.append(f"Cell images centered: {centered}")
                except Exception as e_cic:
                    print(f"Cell-centering pass skipped: {e_cic}")
                    log_data.append(f"Cell-centering pass skipped: {e_cic}")

                # Separate pass: remove the black border (cell strokes) from figure
                # tables that hold side-by-side images, and any image-frame stroke.
                try:
                    borders_cleared = fix_image_layout.remove_image_table_borders(app)
                    print(f"Image table borders cleared: {borders_cleared}")
                    log_data.append(f"Image table borders cleared: {borders_cleared}")
                except Exception as e_brd:
                    print(f"Border removal pass skipped: {e_brd}")
                    log_data.append(f"Border removal pass skipped: {e_brd}")

                # Dedicated, isolated logo pass: relink + size + centre + place the
                # logo ABOVE the bottom margin, fully visible. Touches ONLY the logo;
                # never affects any body image's injection or position.
                try:
                    logo_done = logo_inject.inject_logo(app, logo_path)
                    print(f"Logo relinked + fitted in original frame: {logo_done}")
                    log_data.append(f"Logo injected: {logo_done}")
                except Exception as e_logo:
                    print(f"Logo injection pass skipped: {e_logo}")
                    log_data.append(f"Logo injection pass skipped: {e_logo}")

                # Dynamic TOC Synchronization with actual layout pages
                try:
                    scripts_core_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Scripts")
                    if scripts_core_dir not in sys.path:
                        sys.path.insert(0, scripts_core_dir)
                    from core.toc_synchronizer import sync_toc_via_indesign
                    toc_sync_count = sync_toc_via_indesign(app)
                    print(f"Live InDesign TOC Sync: {toc_sync_count} entry(ies) synchronized with layout")
                    log_data.append(f"TOC sync: {toc_sync_count} entries synchronized")
                except Exception as e_toc:
                    print(f"TOC sync pass skipped: {e_toc}")
                    log_data.append(f"TOC sync pass skipped: {e_toc}")

                # DISABLED: force_body_images_inline flipped every single body image
                # from the proven ABOVE_LINE block anchoring to INLINE_POSITION on the
                # text baseline, so a tall image overlapped the lines above it. The
                # proven reference keeps body images ABOVE_LINE (no overlap), so this
                # pass is intentionally not run.

                print("Exporting processed IDML to output folder...")
                if locals().get("fail_count", 0) > 0:
                    rejection_dir = os.path.join(os.path.dirname(output_idml_dir), "rejection_folder")
                    os.makedirs(rejection_dir, exist_ok=True)
                    output_idml = os.path.join(rejection_dir, os.path.basename(output_idml))
                    print(f"MISSING IMAGES DETECTED. Exporting to REJECTION FOLDER: {output_idml}")
                    log_data.append(f"REJECTED due to missing images. Exported to: {output_idml}")

                clean_output_idml = output_idml.replace(chr(92), "/")
                js_export = f"""
                var outFile = new File("{clean_output_idml}");
                app.activeDocument.exportFile(ExportFormat.INDESIGN_MARKUP, outFile);
                app.activeDocument.close(SaveOptions.NO);
                app.scriptPreferences.enableRedraw = true;
                """
                app.DoScript(js_export, 1246973031)
                log_data.append(f"Exported To: {output_idml}")
                break

            except Exception as _doc_err:
                if _is_rpc_error(_doc_err):
                    _retry_counts[filename] += 1
                    msg = f"[!] InDesign hung/crashed on {filename} (attempt {_retry_counts[filename]}/{MAX_RETRIES_PER_DOC}): {_doc_err}"
                    print(msg, flush=True)
                    log_data.append(f"HANG on {filename}: attempt {_retry_counts[filename]} — {_doc_err}")

                    try:
                        app = restart_indesign()
                    except Exception as _ridx:
                        print(f"[!] Restart failed: {_ridx}", flush=True)
                        log_data.append(f"Restart failed for {filename}: {_ridx}")
                        break

                    try:
                        _partial = os.path.join(output_dir, f"{os.path.splitext(filename)[0]}_injected.idml")
                        if os.path.exists(_partial):
                            os.remove(_partial)
                    except Exception:
                        pass

                    if _retry_counts[filename] < MAX_RETRIES_PER_DOC:
                        print(f"    Retrying {filename} from the start ...", flush=True)
                        continue
                    else:
                        print(f"    Giving up on {filename} after {MAX_RETRIES_PER_DOC} attempts.", flush=True)
                        log_data.append(f"GAVE UP on {filename} after {MAX_RETRIES_PER_DOC} hangs.")
                        break
                else:
                    print(f"[!] Error processing {filename}: {_doc_err}", flush=True)
                    log_data.append(f"ERROR on {filename}: {_doc_err}")
                    break

    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_data))

    print(f"\n{'-'*50}")
    print(f"Batch processing complete! Log saved to: {log_file}")

if __name__ == "__main__":
    process_batch_idmls()
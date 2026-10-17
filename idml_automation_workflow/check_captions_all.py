# -*- coding: utf-8 -*-
# Static caption verifier (no InDesign). For every injected IDML it finds, and for
# every image that has an EPUB caption, it checks whether the paragraph directly
# below the image is a centred "fig caption" paragraph that contains the caption.
#
# Reports, per book:  OK (fig caption) / NOT-CENTERED / MISSING / DUPLICATE
# plus a roll-up across all books.
#
# Usage:
#   python check_captions_all.py                 # every injected IDML found
#   python check_captions_all.py 9789358718041   # one book
import os, re, sys, html, glob, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "image_inject"))
import epub_tools  # noqa: E402

EPUB_DIR = os.environ.get("EPUB_DIR", "").strip() or os.path.join(os.path.dirname(HERE), "epub_input_files")
SEARCH_GLOBS = [
    os.path.join(HERE, "final_output_files", "idml_files", "*_injected.idml"),
    os.path.join(HERE, "final_output_files", "rejected_files", "idml_files", "*_injected.idml"),
    os.path.join(HERE, "image_injection", "idml_files", "*_injected.idml"),
]

ONLY = sys.argv[1].strip() if len(sys.argv) > 1 else ""
if ONLY.lower().endswith(".idml"): ONLY = ONLY[:-5]
if ONLY.endswith("_injected"): ONLY = ONLY[:-len("_injected")]

def norm(s): return re.sub(r"[^a-zA-Z0-9]", "", str(s)).lower()
def para_style(attrs):
    m = re.search(r'AppliedParagraphStyle="([^"]*)"', attrs)
    return m.group(1).split("/")[-1] if m else ""
def para_text(block):
    return html.unescape("".join(re.findall(r"<Content>(.*?)</Content>", block, re.S)))
PSR = re.compile(r'<ParagraphStyleRange\b([^>]*)>(.*?)</ParagraphStyleRange>', re.S)

def matched(below_text, want):
    bn, wn = norm(below_text), norm(want)
    if not bn: return False
    if bn == wn: return True
    if len(bn) >= 3 and (wn.startswith(bn) or bn.startswith(wn)): return True
    if len(wn) >= 4 and wn in bn: return True
    return False

def check_story(xml, cap_by_img):
    results = []
    paras = [(m.start(), m.end(), para_style(m.group(1)), m.group(2)) for m in PSR.finditer(xml)]
    for i, (ps, pe, style, block) in enumerate(paras):
        for lm in re.finditer(r'LinkResourceURI="[^"]*/(image\d+\.[a-zA-Z]+)"', block):
            img = lm.group(1)
            want = cap_by_img.get(img)
            if not want: continue
            if i + 1 >= len(paras):
                results.append((img, "MISSING")); continue
            nstyle, nblock = paras[i + 1][2], paras[i + 1][3]
            if re.search(r'LinkResourceURI="[^"]*/image\d+\.', nblock):
                continue
            btext = para_text(nblock)
            if not matched(btext, want):
                results.append((img, "MISSING")); continue
            if nstyle != "fig caption":
                results.append((img, "NOT-CENTERED")); continue
            dup = False
            if i + 2 < len(paras):
                s2, b2 = paras[i + 2][2], paras[i + 2][3]
                if s2 == "fig caption" and norm(para_text(b2)) == norm(want) \
                        and not re.search(r'LinkResourceURI="[^"]*/image\d+\.', b2):
                    dup = True
            results.append((img, "DUPLICATE" if dup else "OK"))
    return results

def check_book(idml_path):
    base = os.path.basename(idml_path)[:-len("_injected.idml")]
    epub = os.path.join(EPUB_DIR, base + ".epub")
    if not os.path.exists(epub): return base, None, "no EPUB"
    try: cap_by_img = epub_tools.build_caption_map(epub)
    except Exception as e: return base, None, "caption-map error: %s" % e
    z = zipfile.ZipFile(idml_path)
    all_res = []
    for n in z.namelist():
        if not n.startswith("Stories/"): continue
        xml = z.read(n).decode("utf-8", "replace")
        if "LinkResourceURI" not in xml: continue
        all_res.extend(check_story(xml, cap_by_img))
    return base, all_res, None

def main():
    files = []
    for g in SEARCH_GLOBS: files.extend(glob.glob(g))
    by_base = {}
    for f in files:
        base = os.path.basename(f)
        rejected = "rejected_files" in f.replace("\\", "/")
        if base not in by_base or (by_base[base][1] and not rejected):
            by_base[base] = (f, rejected)
    files = [v[0] for v in by_base.values()]
    if ONLY: files = [f for f in files if os.path.basename(f).startswith(ONLY)]
    files.sort()
    if not files:
        print("No *_injected.idml found. Run the inject step first, e.g.:")
        print('  "%s" %s' % (sys.executable, os.path.join(HERE, "image_inject", "inject_with_epub_captions.py")))
        for g in SEARCH_GLOBS: print("   ", g)
        return
    tot = {"OK": 0, "NOT-CENTERED": 0, "MISSING": 0, "DUPLICATE": 0}
    report = ["=" * 78,
              "CAPTION CHECK  (every EPUB caption must be a centred 'fig caption' below its image)",
              "=" * 78]
    books_all_ok, books_bad = [], []
    for f in files:
        base, res, err = check_book(f)
        if err:
            report.append("\n%-16s  -- %s" % (base, err)); continue
        c = {"OK": 0, "NOT-CENTERED": 0, "MISSING": 0, "DUPLICATE": 0}
        bad = []
        for img, st in res:
            c[st] += 1; tot[st] += 1
            if st != "OK": bad.append((img, st))
        total = sum(c.values())
        flag = "ALL OK" if (c["NOT-CENTERED"] == 0 and c["MISSING"] == 0 and c["DUPLICATE"] == 0) else "** ISSUES **"
        report.append("\n%-16s captions=%-4d OK=%-4d NOT-CENTERED=%-3d MISSING=%-3d DUP=%-3d  %s"
                      % (base, total, c["OK"], c["NOT-CENTERED"], c["MISSING"], c["DUPLICATE"], flag))
        for img, st in bad[:60]:
            report.append("        %-16s %s" % (img, st))
        if len(bad) > 60: report.append("        ... and %d more" % (len(bad) - 60))
        (books_all_ok if not bad else books_bad).append(base)
    report.append("\n" + "=" * 78)
    report.append("ROLL-UP across %d book(s): OK=%d  NOT-CENTERED=%d  MISSING=%d  DUPLICATE=%d"
                  % (len(files), tot["OK"], tot["NOT-CENTERED"], tot["MISSING"], tot["DUPLICATE"]))
    report.append("Books all-OK (%d): %s" % (len(books_all_ok), ", ".join(books_all_ok) or "-"))
    report.append("Books with issues (%d): %s" % (len(books_bad), ", ".join(books_bad) or "-"))
    report.append("=" * 78)
    text = "\n".join(report)
    print(text)
    out = os.path.join(HERE, "caption_check_report.txt")
    with open(out, "w", encoding="utf-8") as fh: fh.write(text)
    print("\nSaved:", out)

if __name__ == "__main__":
    main()

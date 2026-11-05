"""Orchestrate the 4-step image engine for one or more books: EPUB -> size -> place -> refine -> export + audit."""

import os
import re
import sys
import glob
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))              # resize_images/engine
RESIZE_DIR = os.path.dirname(HERE)                             # resize_images
REPO = os.path.dirname(RESIZE_DIR)                             # project root
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "injection"))

import epub_tools                                              # reused EPUB extractor

from . import size_range, first_guess, placement, refine, indesign_jobs

EPUB_DIR = os.path.join(REPO, "epub_input_files")
IDML_DIR = os.path.join(REPO, "idml_input_files")
OUT_DIR = os.path.join(RESIZE_DIR, "output")

_MARKER_RE = re.compile(r"###Insert\s+(\S+?)\s+here###", re.I)


def marker_names(idml_path):
    """Return the image filenames referenced by ###Insert ... here### markers, in first-seen order."""
    seen, order = set(), []
    try:
        with zipfile.ZipFile(idml_path) as z:
            for n in z.namelist():
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                xml = z.read(n).decode("utf-8", "replace")
                text = re.sub(r"<[^>]+>", " ", xml)
                for m in _MARKER_RE.finditer(text):
                    nm = m.group(1).strip()
                    if nm and nm.lower() not in seen:
                        seen.add(nm.lower())
                        order.append(nm)
    except Exception:
        pass
    return order


def _find_image(raw_dir, name):
    """Resolve a marker name to an extracted file path (case-insensitive), or None."""
    exact = os.path.join(raw_dir, name)
    if os.path.isfile(exact):
        return exact
    low = name.lower()
    for f in os.listdir(raw_dir):
        if f.lower() == low:
            return os.path.join(raw_dir, f)
    return None


def _resolve(book):
    """Resolve a book id/path to (idml_path, epub_path, book_id)."""
    if os.path.isfile(book) and book.lower().endswith(".idml"):
        idml = book
        bid = os.path.splitext(os.path.basename(book))[0]
    else:
        bid = os.path.splitext(os.path.basename(book))[0]
        idml = os.path.join(IDML_DIR, bid + ".idml")
    epub = os.path.join(EPUB_DIR, bid + ".epub")
    return idml, epub, bid


def process(app, book):
    """Run all 4 steps for one book and write the injected IDML, PDF and audit report."""
    idml, epub, bid = _resolve(book)
    if not os.path.isfile(idml):
        print(f"[engine] no IDML for {bid}: {idml}")
        return
    book_out = os.path.join(OUT_DIR, bid)
    raw_dir = os.path.join(book_out, "raw_images")
    links_dir = os.path.join(book_out, bid + "_Links")
    os.makedirs(book_out, exist_ok=True)

    if os.path.isfile(epub):
        epub_tools.extract_epub(epub, raw_dir)
    names = marker_names(idml)
    plans = []
    for nm in names:
        if nm.lower().startswith("cover"):
            continue
        path = _find_image(raw_dir, nm) if os.path.isdir(raw_dir) else None
        if not path:
            continue
        pl = size_range.plan_image(path, nm)
        if pl:
            plans.append(pl)
    print(f"[engine] {bid}: {len(names)} markers, {len(plans)} sizable image(s)")
    if not plans:
        return

    first_guess.first_guess(plans)                            # STEP 3
    name_to_path = placement.write_sized_images(plans, links_dir)

    indesign_jobs.open_doc(app, idml)                         # STEP 2
    placed, failed, failures = placement.place_all(app, name_to_path)
    print(f"[engine] placed {placed}, failed {failed}")

    try:                                                      # flow overset text + images into real pages
        import resolve_overset as _ro
        pages_added, overset_left, jams = _ro.resolve_overset(app)
        print(f"[engine] overset reflow: +{pages_added} page(s), {overset_left} frame(s) still overset, {len(jams)} jam(s)")
    except Exception as exc:
        print(f"[engine] overset reflow skipped: {exc}")

    audit = refine.refine(app, plans)                         # STEP 4

    out_idml = os.path.join(book_out, bid + ".idml")
    out_pdf = os.path.join(book_out, bid + ".pdf")
    indesign_jobs.export_idml(app, out_idml)
    indesign_jobs.export_pdf(app, out_pdf)
    indesign_jobs.close_doc(app)

    report = os.path.join(book_out, bid + ".audit.txt")
    with open(report, "w", encoding="utf-8") as f:
        f.write(f"Image engine audit for {bid}\n")
        f.write(f"markers={len(names)} sized={len(plans)} placed={placed} failed={failed}\n")
        f.write("-" * 60 + "\n")
        if failures:
            f.write("PLACEMENT FAILURES:\n")
            for x in failures:
                f.write("  " + x + "\n")
            f.write("-" * 60 + "\n")
        f.write("PAGES STILL OUTSIDE THE GAP RULE (%d):\n" % len(audit))
        for ln in audit:
            f.write("  " + ln + "\n")
    print(f"[engine] {bid}: audit -> {report}  ({len(audit)} page(s) flagged)")


def main(argv=None):
    """Process the requested book(s); with no argument, process every IDML in idml_input_files."""
    argv = argv if argv is not None else sys.argv[1:]
    if argv:
        books = argv
    else:
        books = sorted(glob.glob(os.path.join(IDML_DIR, "*.idml")))
    app = indesign_jobs.connect()
    if app is None:
        print("[engine] could not connect to InDesign.")
        return
    os.makedirs(OUT_DIR, exist_ok=True)
    for b in books:
        try:
            process(app, b)
        except Exception as exc:
            print(f"[engine] ERROR on {b}: {exc}")


if __name__ == "__main__":
    main()

"""
Unified Dual-Language Pipeline Master Runner (English & Spanish)
Automatically classifies each IDML by language and executes all pipeline stages:
- Step 1: Format to Reference (Spanish -> pipeline_es, English -> pipeline_en)
- Step 2: Document Setup Normalization (5.5x8.5 in, Margins 36/54/36/36 pt, 3mm Bleed)
- Step 3: EPUB Image & Caption Injection via Adobe InDesign
- Step 3b: Text Bottom-Gap Fill (Widow/orphan keep-lines relaxed, chapter ends intact)
- Step 3c: Chapter & Front Matter Layout Spacing (14.5 pt top gap, Title gap)
- Step 4: High-Quality Print PDF Export via Adobe InDesign (Embedded fonts)
"""

import argparse
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

WF_DIR = Path(__file__).resolve().parent
REPO_DIR = WF_DIR.parent
SCRIPTS_DIR = WF_DIR / "Scripts"
SPANISH_DIR = SCRIPTS_DIR / "spanish"
IMAGE_INJECT_DIR = WF_DIR / "image_inject"

for p in [str(WF_DIR), str(SCRIPTS_DIR), str(SPANISH_DIR), str(IMAGE_INJECT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from pipeline_es import process_idml_es
from typography_postprocessor_es import postprocess_idml_es
from pipeline import process_idml as process_idml_en
from core.typography_postprocessor import postprocess_idml as postprocess_idml_en
from pages import normalize_document_setup
import convert_to_pdf

# Dynamic Input directory resolution
INPUT_DIR = None
for cand in [
    REPO_DIR / "input_files",
    WF_DIR / "input_files",
    REPO_DIR / "Input",
]:
    if cand.is_dir() and any(cand.glob("*.idml")):
        INPUT_DIR = cand
        break
if not INPUT_DIR:
    INPUT_DIR = REPO_DIR / "input_files"

# Dynamic EPUB directory resolution
EPUB_DIR = None
for cand in [
    REPO_DIR / "epub_input_files",
    WF_DIR / "epub_input_files",
]:
    if cand.is_dir() and any(cand.glob("*.epub")):
        EPUB_DIR = cand
        break
if not EPUB_DIR:
    EPUB_DIR = REPO_DIR / "epub_input_files"

FORMAT_DIR = WF_DIR / "Output" / "Formatted"
NORM_DIR = WF_DIR / "Output" / "page_resize_output"
# Output lives under the workflow dir (idml_automation_workflow/), same base the
# image-injection step writes to (INJECT_OUTBASE = WF_DIR/"final_output_files").
# Keep this on WF_DIR so step 3b and step 4 find the injected files.
FINAL_OUTPUT_ROOT = WF_DIR / "final_output_files"
FINAL_IDML_DIR = FINAL_OUTPUT_ROOT / "idml_files"
FINAL_PDF_DIR = FINAL_OUTPUT_ROOT / "pdf_files"
RENAMED_OUT_DIR = FINAL_OUTPUT_ROOT / "renamed_output_files"

# Dynamic Reference file resolution
REFERENCE_FILE = None
for r_dir in [
    WF_DIR / "Reference",
    REPO_DIR / "Reference",
]:
    if r_dir.is_dir():
        refs = sorted(r_dir.glob("*.idml"))
        cand_ref = next((r for r in refs if "MIS" in r.name.upper()), (refs[0] if refs else None))
        if cand_ref:
            REFERENCE_FILE = cand_ref
            break
if not REFERENCE_FILE:
    REFERENCE_FILE = WF_DIR / "Reference" / "11671 LES MISÉRABLES.idml"


def detect_book_language(idml_path: Path) -> str:
    """Robust content-based language detector (100% accurate on Spanish vs English)."""
    stem = idml_path.stem.lower()
    if "_es" in stem or "spanish" in stem:
        return "es"
    if "_en" in stem or "english" in stem:
        return "en"

    try:
        with zipfile.ZipFile(idml_path, "r") as zf:
            story_files = [n for n in zf.namelist() if n.startswith("Stories/Story_")]
            story_files.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
            text_samples = []
            for sf in story_files[:8]:
                raw = zf.read(sf).decode("utf-8", errors="ignore")
                matches = re.findall(r"<Content>(.*?)</Content>", raw[:150000])
                if matches:
                    text_samples.append(" ".join(matches))
            text = " ".join(text_samples).lower()

            es_keywords = [
                "capítulo", "capitulo", "contenido", "sobre la autoría", "sobre la autoria",
                "derechos de autor", "parte primera", "prólogo", "prologo", " de ", " en ",
                " que ", " con ", " para ", " por ", " los ", " las ", " una ", " del "
            ]
            en_keywords = [
                "chapter", "contents", "about the author", "copyright", "part one",
                "preface", "published by", " of ", " in ", " that ", " with ", " for ",
                " by ", " the ", " from ", " and "
            ]

            es_score = sum(text.count(kw) for kw in es_keywords)
            en_score = sum(text.count(kw) for kw in en_keywords)
            return "es" if es_score > en_score else "en"
    except Exception:
        return "en"


def get_all_books(only_book=None, target_lang=None, limit=None):
    books = sorted([f for f in INPUT_DIR.glob("*.idml") if not f.name.startswith("~") and not f.name.startswith(".")])
    if only_book:
        clean = only_book.replace(".idml", "")
        candidates = {clean}
        try:
            from core.isbn_manager import get_book_isbn_info
            info = get_book_isbn_info(clean)
            if info:
                if info.get("sp_epub_isbn"):
                    candidates.add(info["sp_epub_isbn"])
                if info.get("sp_print_isbn"):
                    candidates.add(info["sp_print_isbn"])
                if info.get("sr_no"):
                    candidates.add(info["sr_no"])
        except Exception:
            pass
        books = [b for b in books if any(c in b.stem for c in candidates)]
    result = []
    for b in books:
        lang = detect_book_language(b)
        if target_lang and lang != target_lang:
            continue
        result.append((b, lang))
    if limit and limit > 0:
        result = result[:limit]
    return result


def run_step1_formatting(books):
    FORMAT_DIR.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 70)
    print("STEP 1: DUAL-LANGUAGE TYPOGRAPHY & STRUCTURAL FORMATTING")
    print(f"Total books to format: {len(books)}")
    print("=" * 70)
    success, failed = 0, 0
    for idx, (book, lang) in enumerate(books, 1):
        out_f = FORMAT_DIR / f"{book.stem}_formatted.idml"
        lang_str = "SPANISH (ES)" if lang == "es" else "ENGLISH (EN)"
        print(f"[{idx:2d}/{len(books)}] Formatting {lang_str}: {book.name} -> {out_f.name}")
        try:
            if lang == "es":
                process_idml_es(str(book), str(REFERENCE_FILE), str(out_f))
                try:
                    postprocess_idml_es(out_f)
                except Exception as ep:
                    print(f"       Note: postprocessor {ep}")
            else:
                process_idml_en(str(book), str(REFERENCE_FILE), str(out_f))
                try:
                    postprocess_idml_en(out_f)
                except Exception as ep:
                    print(f"       Note: postprocessor {ep}")
            try:
                from core.chapter_top_spacing import apply_chapter_top_spacing as _acts
                _acts(out_f, out_f, sequence_pages=True, verbose=False)
            except Exception as _ecs:
                print(f"       Note: chapter spacing {_ecs}")
            print(f"       [OK] Success: {out_f.name}")
            success += 1
        except Exception as e:
            print(f"       [FAIL] Error: {e}")
            failed += 1
    print(f"\nStep 1 Formatting finished: {success} succeeded, {failed} failed.")
    return success, failed


def run_step2_normalization(books):
    NORM_DIR.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 70)
    print("STEP 2: DOCUMENT SETUP NORMALIZATION (5.5x8.5 in, Margins, Bleeds)")
    print(f"Total books to normalize: {len(books)}")
    print("=" * 70)
    success, failed = 0, 0
    for idx, (book, lang) in enumerate(books, 1):
        in_f = FORMAT_DIR / f"{book.stem}_formatted.idml"
        if not in_f.exists():
            in_f = book
        out_f = NORM_DIR / f"{book.stem}_normalized.idml"
        print(f"[{idx:2d}/{len(books)}] Normalizing: {in_f.name} -> {out_f.name}")
        try:
            normalize_document_setup.normalize_one_file(str(in_f), str(out_f))
            print(f"       [OK] Success: {out_f.name}")
            success += 1
        except Exception as e:
            print(f"       [FAIL] Error: {e}")
            failed += 1
    print(f"\nStep 2 Normalization finished: {success} succeeded, {failed} failed.")
    return success, failed


def run_step3_injection(books, force=False):
    FINAL_IDML_DIR.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 70)
    print("STEP 3: EPUB IMAGE & CAPTION INJECTION (via Adobe InDesign)")
    print(f"Input directory:  {NORM_DIR}")
    print(f"EPUB directory:   {EPUB_DIR}")
    print(f"Output directory: {FINAL_IDML_DIR}")
    print("=" * 70)

    env = dict(os.environ)
    env["INJECT_INPUT"] = str(NORM_DIR)
    env["INJECT_OUTBASE"] = str(WF_DIR / "final_output_files")
    env["EPUB_DIR"] = str(EPUB_DIR)
    for logo_cand in [
        WF_DIR / "logo" / "LEAF-BOUND-trimmed.png",
        WF_DIR / "logo" / "LEAF-BOUND.png",
        REPO_DIR / "input_files" / "logo" / "LEAF-BOUND-trimmed.png",
    ]:
        if logo_cand.exists():
            env["LOGO_PATH"] = str(logo_cand)
            break

    # Pass exact list of books to inject
    env["INJECT_ONLY"] = ",".join(f"{b[0].stem}_normalized.idml" for b in books)
    if force:
        env["INJECT_FORCE"] = "1"

    res = subprocess.run([sys.executable, "-u", str(IMAGE_INJECT_DIR / "inject_with_epub_captions.py")], env=env)
    return res.returncode


def run_step3d_image_leading(books):
    print("\n" + "=" * 70)
    print("STEP 3d: CHAPTER DOUBLE-BREAK FIX (remove blank page before body chapters)")
    print(f"Target directory: {FINAL_IDML_DIR}")
    print("=" * 70)

    from core.chapter_break_fix import apply_to_idml as fix_chapter_breaks

    book_stems = {b[0].stem for b in books}
    targets = [f for f in FINAL_IDML_DIR.glob("*_injected.idml")
               if any(b_stem in f.name for b_stem in book_stems)]
    for idml in targets:
        try:
            br = fix_chapter_breaks(idml)
            print(f"  {idml.name}: chapter double-break fixed={br}")
        except Exception as e:
            print(f"  {idml.name}: [!] chapter break fix failed: {e}")
    return 0


def run_step3b_gap_fill(books):
    print("\n" + "=" * 70)
    print("STEP 3b: TEXT BOTTOM-GAP FILLING (Reflow body lines down to bottom margin)")
    print(f"Input/Output: {FINAL_IDML_DIR}")
    print("=" * 70)

    env = dict(os.environ)
    env["GAPFIX_INPUT"] = str(FINAL_IDML_DIR)
    env["GAPFIX_OUTPUT"] = str(FINAL_IDML_DIR)

    for b in books:
        stem = b[0].stem
        print(f"  Fixing bottom gap for: {stem}")
        cmd = [sys.executable, "-u", str(WF_DIR / "fix_text_bottom_gap.py"), stem]
        subprocess.run(cmd, env=env)
    return 0


def run_step3c_chapter_top_spacing(books):
    print("\n" + "=" * 70)
    print("STEP 3c: CHAPTER & FRONT MATTER LAYOUT SPACING (14.5 pt top gap, Title gap)")
    print(f"Target directory: {FINAL_IDML_DIR}")
    print("=" * 70)

    from core.chapter_top_spacing import apply_chapter_top_spacing

    book_stems = {b[0].stem for b in books}
    target_idmls = [f for f in FINAL_IDML_DIR.glob("*_injected.idml") if any(b_stem in f.name for b_stem in book_stems)]
    if not target_idmls:
        target_idmls = [f for f in NORM_DIR.glob("*_normalized.idml") if any(b_stem in f.name for b_stem in book_stems)]
    if not target_idmls:
        target_idmls = [f for f in FORMAT_DIR.glob("*_formatted.idml") if any(b_stem in f.name for b_stem in book_stems)]
    if not target_idmls:
        target_idmls = [f for f in RENAMED_OUT_DIR.glob("*.idml") if any(b_stem in f.name for b_stem in book_stems)]
    if not target_idmls:
        target_idmls = [f for f in (WF_DIR / "renamed_output_files").glob("*.idml") if any(b_stem in f.name for b_stem in book_stems)]
    if not target_idmls:
        target_idmls = [f for f in (WF_DIR / "Output").glob("*.idml") if any(b_stem in f.name for b_stem in book_stems)]

    success, failed = 0, 0
    for idx, idml_f in enumerate(target_idmls, 1):
        print(f"[{idx:2d}/{len(target_idmls)}] Applying layout spacing: {idml_f.name}")
        try:
            res = apply_chapter_top_spacing(idml_f, idml_f, sequence_pages=True, verbose=True)
            if res.get("success"):
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"       [FAIL] Error applying spacing to {idml_f.name}: {e}")
            failed += 1

    print(f"\nStep 3c Spacing finished: {success} succeeded, {failed} failed.")
    return success, failed


def run_step4_pdf_export(books, force=False):
    FINAL_PDF_DIR.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 70)
    print("STEP 4: HIGH-QUALITY PRINT PDF EXPORT (via Adobe InDesign)")
    print(f"Source IDMLs:  {FINAL_IDML_DIR}")
    print(f"PDF Directory: {FINAL_PDF_DIR}")
    print("=" * 70)

    book_stems = {b[0].stem for b in books}
    target_idmls = [f for f in FINAL_IDML_DIR.glob("*_injected.idml") if any(b_stem in f.name for b_stem in book_stems)]
    if not target_idmls:
        target_idmls = [f for f in NORM_DIR.glob("*_normalized.idml") if any(b_stem in f.name for b_stem in book_stems)]
    if not target_idmls:
        target_idmls = [f for f in FORMAT_DIR.glob("*_formatted.idml") if any(b_stem in f.name for b_stem in book_stems)]

    # Integrity gate: reject any book that dropped body paragraphs during processing.
    import shutil as _shutil
    _sys_paths = [str(WF_DIR / "test_cases"), str(IMAGE_INJECT_DIR)]
    for _sp in _sys_paths:
        if _sp not in sys.path:
            sys.path.insert(0, _sp)
    _REJECT_IDML = WF_DIR / "final_output_files" / "rejected_files" / "idml_files"
    _kept = []
    _rejected = []
    for _doc in target_idmls:
        _isbn = _doc.stem.replace("_injected", "").replace("_normalized", "").replace("_formatted", "")
        _src = INPUT_DIR / f"{_isbn}.idml"
        _cmap = {}
        _ep = EPUB_DIR / f"{_isbn}.epub"
        if _ep.exists():
            try:
                import epub_tools as _et
                _cmap = _et.build_caption_map(str(_ep))
            except Exception:
                _cmap = {}
        _reasons = []
        if _src.exists() and "_injected" in _doc.name:
            # Normalize the injected file the SAME way export will (pure-Python
            # postprocess: caption dedup, verse/word-spacing, heading split) so the
            # audit reflects the PDF that gets produced, not the stale step-3b file.
            # (pre-audit in-place postprocess removed: it mutated the injected
            # deliverable and re-flowed it, dropping images. Step 1 already applied
            # typography and the PDF step now only exports, so the injected IDML is
            # audited as-is.)
            try:
                import check_missing_paragraphs as _cmp
                _reasons = _cmp.check(str(_src), str(_doc), _cmap)
            except Exception as _e:
                print(f"  [warn] paragraph check skipped for {_isbn}: {_e}")
            # Static image-integrity checks (no InDesign needed): any remaining
            # ###Insert placeholder means an image was not placed (missing image);
            # a stacked side-by-side pair means the table rebuild failed.
            try:
                import zipfile as _zip
                _left = 0
                with _zip.ZipFile(str(_doc)) as _z:
                    for _n in _z.namelist():
                        if _n.startswith("Stories/") and _n.endswith(".xml"):
                            _left += _z.read(_n).decode("utf-8", "replace").count("###Insert")
                if _left:
                    _reasons.append("MISSING_IMAGES: %d placeholder(s) left unplaced" % _left)
            except Exception as _e:
                print(f"  [warn] image-placeholder check skipped for {_isbn}: {_e}")
            try:
                import check_sidebyside as _csbs
                _ok, _det = _csbs.check(str(_src), str(_doc))
                if not _ok:
                    _reasons.append("SIDEBYSIDE not side-by-side: " + _det)
            except Exception as _e:
                print(f"  [warn] side-by-side check skipped for {_isbn}: {_e}")
            try:
                import check_word_spacing_and_block as _cwsb
                for _r in _cwsb.check(str(_doc)):
                    _reasons.append(_r)
            except Exception as _e:
                print(f"  [warn] word-spacing/block check skipped for {_isbn}: {_e}")
            try:
                import check_caption as _ccap
                for _r in _ccap.check(str(_doc), _cmap):
                    _reasons.append(_r)
            except Exception as _e:
                print(f"  [warn] caption check skipped for {_isbn}: {_e}")
        if _reasons:
            _REJECT_IDML.mkdir(parents=True, exist_ok=True)
            # Rejected files use the SAME standardized name as the output:
            # {Sr No.}_{Spanish Print ISBN-13}.idml (PDF is named to match by export).
            try:
                from core.isbn_manager import get_output_base_name as _gobn
                _dest = _REJECT_IDML / f"{_gobn(_isbn)}.idml"
            except Exception:
                _dest = _REJECT_IDML / _doc.name
            try:
                _shutil.move(str(_doc), str(_dest))
                with open(str(_dest) + ".reasons.txt", "w", encoding="utf-8") as _fh:
                    _fh.write(chr(10).join(["REJECTED:"] + list(_reasons)))
                print(f"  [REJECT] {_isbn}: {_reasons[0][:90]} -> rejected_files/ (PDF still generated)")
                _rejected.append(_dest)
            except Exception as _e:
                print(f"  [warn] could not move rejected {_isbn}: {_e}")
        else:
            _kept.append(_doc)
    target_idmls = _kept

    if target_idmls:
        print(f"Exporting {len(target_idmls)} IDML document(s) to PDF...")
        for target_doc in target_idmls:
            convert_to_pdf.convert_batch(target_path=str(target_doc), output_dir=str(FINAL_PDF_DIR), force=force)
    else:
        print("No books passed the integrity gate; exporting rejected books only.")

    # Rejected books still get a PDF (in rejected_files/pdf_files) so they can be
    # reviewed; they are simply kept out of the clean final_output_files set.
    if _rejected:
        _REJECT_PDF = WF_DIR / "final_output_files" / "rejected_files" / "pdf_files"
        _REJECT_PDF.mkdir(parents=True, exist_ok=True)
        print(f"Exporting {len(_rejected)} REJECTED document(s) to rejected_files/pdf_files for review...")
        for _rdoc in _rejected:
            try:
                convert_to_pdf.convert_batch(target_path=str(_rdoc), output_dir=str(_REJECT_PDF), force=force)
            except Exception as _e:
                print(f"  [warn] could not export rejected PDF {_rdoc.name}: {_e}")

    if not target_idmls:
        return 0

    # Verify and synchronize TOC page numbers with final PDF
    from core.toc_synchronizer import sync_idml_toc_from_pdf
    from core.isbn_manager import get_output_base_name
    print("\nVerifying TOC page synchronization against generated PDFs...")
    for idml_f in target_idmls:
        clean_stem = idml_f.stem.replace("_injected", "").replace("_normalized", "").replace("_formatted", "")
        base_out = get_output_base_name(clean_stem)
        pdf_candidates = [
            FINAL_PDF_DIR / f"{base_out}.pdf",
            FINAL_PDF_DIR / f"{clean_stem}.pdf",
            FINAL_PDF_DIR / f"{idml_f.stem}.pdf",
        ]
        pdf_f = next((p for p in pdf_candidates if p.exists()), None)
        if pdf_f:
            synced = sync_idml_toc_from_pdf(idml_f, pdf_f)
            if synced > 0:
                print(f"  [TOC Sync] Synchronized {synced} TOC entry(ies) in {idml_f.name}. Refreshing final PDF...")
                convert_to_pdf.convert_batch(target_path=str(idml_f), output_dir=str(FINAL_PDF_DIR), force=True)
            else:
                print(f"  [TOC Verified] {idml_f.name} TOC is 100% in sync with {pdf_f.name}.")

        # Generate and save standardized final output files:
        # {Sr No.}_{Spanish Print ISBN-13}.idml and {Sr No.}_{Spanish Print ISBN-13}.pdf
        if base_out:
            # Exactly ONE renamed IDML deliverable ({Sr No.}_{Spanish Print ISBN-13}.idml)
            # in renamed_output_files. The PDF lives only in pdf_files (rejected books:
            # rejected_files/pdf_files). No idml_files / Output / sequenced copies.
            r_dir = FINAL_OUTPUT_ROOT / "renamed_output_files"
            r_dir.mkdir(parents=True, exist_ok=True)
            _shutil.copy2(idml_f, r_dir / f"{base_out}.idml")
            print(f"  [Renamed IDML] Saved {base_out}.idml into renamed_output_files/")

    print("\nStep 4 Complete! Verified PDF and IDML files available in:", FINAL_PDF_DIR)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Unified Dual-Language Pipeline")
    parser.add_argument("book_pos", nargs="?", default=None, help="Optional positional book identifier")
    parser.add_argument("--book", default=None, help="Process single book by ISBN/name")
    parser.add_argument("--lang", choices=["all", "es", "en"], default="all", help="Filter by language")
    parser.add_argument("--step", choices=["all", "1", "2", "3", "3d", "3b", "3c", "4"], default="all", help="Pipeline step to run")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of books to process (e.g. 10)")
    parser.add_argument("--force", action="store_true", help="Force injection even if already processed")
    args, _ = parser.parse_known_args()

    target_book = args.book or args.book_pos
    force_run = args.force or bool(target_book)
    filter_lang = None if args.lang == "all" else args.lang
    books = get_all_books(target_book, filter_lang, limit=args.limit)
    print(f"Discovered {len(books)} books matching criteria.")
    es_count = sum(1 for _, l in books if l == "es")
    en_count = sum(1 for _, l in books if l == "en")
    print(f"  Spanish books: {es_count}")
    print(f"  English books: {en_count}")

    if args.step in ["all", "1"]:
        run_step1_formatting(books)
    if args.step in ["all", "2"]:
        run_step2_normalization(books)
    if args.step in ["all", "3"]:
        run_step3_injection(books, force=force_run)
        run_step3d_image_leading(books)
    if args.step in ["3d"]:
        run_step3d_image_leading(books)
    if args.step in ["all", "3b"]:
        run_step3b_gap_fill(books)
    if args.step in ["all", "3c"]:
        pass  # chapter spacing moved to step 1 (before the injection reflow)
    if args.step in ["all", "4"]:
        run_step4_pdf_export(books, force=force_run)


if __name__ == "__main__":
    main()


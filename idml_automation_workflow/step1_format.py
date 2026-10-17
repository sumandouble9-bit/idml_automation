"""
Step 1 Runner: Typography and Structural Formatting
Processes raw IDML files from input_files/ and outputs formatted IDML to Output/Formatted/.
Supports Spanish (pipeline_es) and English (pipeline).
"""

import argparse
import sys
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT_DIR / "Scripts"
SPANISH_DIR = SCRIPTS_DIR / "spanish"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(SPANISH_DIR) not in sys.path:
    sys.path.insert(0, str(SPANISH_DIR))

from pipeline_es import process_idml_es
from typography_postprocessor_es import postprocess_idml_es
from pipeline import process_idml as process_idml_en


def detect_language(idml_path: Path) -> str:
    stem = idml_path.stem.lower()
    if "_es" in stem or "spanish" in stem:
        return "es"
    if "_en" in stem or "english" in stem:
        return "en"
    try:
        import re
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
        pass
    return "en"


def run_step1(input_target=None, lang=None, reference_path=None, limit=None):
    input_dir = ROOT_DIR / "input_files"
    if not input_dir.is_dir() or not any(input_dir.glob("*.idml")):
        if (ROOT_DIR.parent / "input_files").is_dir():
            input_dir = ROOT_DIR.parent / "input_files"

    output_dir = ROOT_DIR / "Output" / "Formatted"
    output_dir.mkdir(parents=True, exist_ok=True)

    if input_target:
        p = Path(input_target).resolve()
        files = [p] if p.is_file() else sorted(p.glob("*.idml"))
    else:
        files = sorted(input_dir.glob("*.idml"))

    files = [f for f in files if not f.name.startswith("~") and not f.name.startswith(".")]
    if limit and limit > 0:
        files = files[:limit]

    if not files:
        print(f"[!] No IDML files found in {input_dir}")
        return 1

    ref_dir = ROOT_DIR / "Reference"
    if reference_path:
        ref_file = Path(reference_path).resolve()
    else:
        ref_files = list(ref_dir.glob("*.idml"))
        ref_file = ref_files[0] if ref_files else None

    print("=" * 70)
    print("STEP 1: Typography & Structural Formatting")
    print(f"Files to process: {len(files)}")
    print(f"Output folder:    {output_dir}")
    print("=" * 70)

    success, failed = 0, 0
    for idx, f in enumerate(files, 1):
        target_lang = lang if lang else detect_language(f)
        out_f = output_dir / f"{f.stem}_formatted.idml"
        print(f"\n[{idx}/{len(files)}] Formatting ({target_lang.upper()}): {f.name} -> {out_f.name}")
        try:
            if target_lang == "es":
                process_idml_es(str(f), str(ref_file) if ref_file else "", str(out_f))
                try:
                    postprocess_idml_es(out_f)
                except Exception as e_p:
                    print(f"     [!] Postprocessor note: {e_p}")
            else:
                process_idml_en(str(f), str(ref_file) if ref_file else "", str(out_f))
                try:
                    from core.typography_postprocessor import postprocess_idml
                    postprocess_idml(out_f)
                except Exception as e_pen:
                    pass
            print(f"     [OK] Formatted: {out_f.name}")
            success += 1
        except Exception as e:
            print(f"     [FAIL] Error formatting {f.name}: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print(f"Step 1 Complete: {success} succeeded, {failed} failed.")
    print("=" * 70)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 1: Typography & Formatting")
    parser.add_argument("input", nargs="?", default=None, help="Target IDML or folder (default: input_files/)")
    parser.add_argument("--lang", choices=["es", "en"], default=None, help="Force language (es or en)")
    parser.add_argument("--reference", default=None, help="Reference IDML file")
    parser.add_argument("--limit", type=int, default=None, help="Process first N books")
    args = parser.parse_args()
    sys.exit(run_step1(args.input, args.lang, args.reference, args.limit))

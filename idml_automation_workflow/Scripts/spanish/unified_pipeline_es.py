"""
Unified Master Pipeline Runner for Spanish IDML Books (Workflow V2):
Integrates modules in the requested order:
  1. Spanish Formatting Module under Scripts/spanish/ (Title page 'Por' italic, Spanish Copyright,
     Spanish TOC 'Contenido' dot leaders, Sobre la autoría + blank page, 16pt Gill Sans MT
     headings with 1-space sinkage, Palatino Linotype 9.65pt body text, footnotes, table protection)
  2. Document Setup Normalization (Page size 5.5x8.5 in, Margins 36/54/36/36 pt, Bleeds)
  3. EPUB Image & Caption Map Injection (extracts from epub_input_files/ via epub_tools,
     injects in InDesign, places captions below images, reflows oversets, centers graphics,
     fits within margins, injects logo)
  4. Comprehensive InDesign Audit & High-Quality PDF Export
"""

import argparse
import os
import sys
import time
from pathlib import Path

SPANISH_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SPANISH_DIR.parent
WORKFLOW_DIR = SCRIPTS_DIR.parent
REPO_DIR = WORKFLOW_DIR.parent

# Check for image injection modules (epub_image_map_inject or image_inject)
if (WORKFLOW_DIR / "epub_image_map_inject").is_dir():
    EPUB_MODULE_DIR = WORKFLOW_DIR / "epub_image_map_inject"
elif (WORKFLOW_DIR / "image_inject").is_dir():
    EPUB_MODULE_DIR = WORKFLOW_DIR / "image_inject"
elif (REPO_DIR / "epub_image_map_inject").is_dir():
    EPUB_MODULE_DIR = REPO_DIR / "epub_image_map_inject"
else:
    EPUB_MODULE_DIR = WORKFLOW_DIR / "epub_image_map_inject"

if str(SPANISH_DIR) not in sys.path:
    sys.path.insert(0, str(SPANISH_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(WORKFLOW_DIR) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_DIR))
if str(EPUB_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(EPUB_MODULE_DIR))

from pages import normalize_document_setup
from pipeline_es import process_idml_es as run_typography_pipeline_es
import inject_with_epub_captions
import audit_epub


def run_pipeline_e2e_es(
    input_path: str = None,
    output_dir: str = None,
    reference_path: str = None,
    stage: int = None,
    skip_formatting: bool = False,
    skip_normalize: bool = False,
    skip_inject: bool = False,
    skip_audit: bool = False,
) -> int:
    start_total = time.time()
    workflow_dir = Path(WORKFLOW_DIR)

    # 1. Resolve directories (Standard clean architecture)
    raw_input_dir = None
    for cand in [
        workflow_dir / "input_files",
        workflow_dir.parent / "input_files",
        workflow_dir / "Input_Spanish",
        workflow_dir / "Input",
    ]:
        if cand.is_dir() and any(cand.glob("*.idml")):
            raw_input_dir = cand
            break
    if not raw_input_dir:
        raw_input_dir = workflow_dir.parent / "input_files" if (workflow_dir.parent / "input_files").is_dir() else workflow_dir / "input_files"

    epub_input_dir = None
    for cand in [
        workflow_dir / "epub_input_files",
        workflow_dir.parent / "epub_input_files",
        workflow_dir / "epub_input_files_Spanish",
    ]:
        if cand.is_dir() and any(cand.glob("*.epub")):
            epub_input_dir = cand
            break
    if not epub_input_dir:
        epub_input_dir = workflow_dir.parent / "epub_input_files" if (workflow_dir.parent / "epub_input_files").is_dir() else workflow_dir / "epub_input_files"

    if output_dir:
        out_p = Path(output_dir).resolve()
        final_output_dir = out_p.parent if out_p.suffix.lower() == ".idml" else out_p
    else:
        final_output_dir = workflow_dir / "Output"

    formatted_dir = final_output_dir / "Formatted"
    norm_output_dir = final_output_dir / "page_resize_output"
    injected_dir = final_output_dir / "injected_idml_files"
    final_pdf_dir = final_output_dir / "pdf_files"
    desktop_dir = Path.home() / "Desktop"
    desktop_pdf_dir = desktop_dir / "PDF_Spanish" if desktop_dir.is_dir() else final_pdf_dir
    ref_dir = workflow_dir / "Reference"

    formatted_dir.mkdir(parents=True, exist_ok=True)
    norm_output_dir.mkdir(parents=True, exist_ok=True)
    injected_dir.mkdir(parents=True, exist_ok=True)
    final_output_dir.mkdir(parents=True, exist_ok=True)
    final_pdf_dir.mkdir(parents=True, exist_ok=True)
    try:
        desktop_pdf_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        desktop_pdf_dir = final_pdf_dir

    # Resolve Reference IDML
    if reference_path:
        ref_file = Path(reference_path).resolve()
    else:
        ref_files = list(ref_dir.glob("*.idml"))
        ref_file = ref_files[0] if ref_files else None

    if not ref_file or not ref_file.exists():
        print(f"[!] Warning: Reference IDML not found in {ref_dir}. Some style copying may be skipped.")

    # Determine files to process
    if input_path:
        p = Path(input_path).resolve()
        if p.is_file():
            target_files = [p]
        elif p.is_dir():
            target_files = sorted(p.glob("*.idml"))
        else:
            print(f"[!] Error: Specified input path does not exist: {input_path}")
            return 1
    else:
        target_files = sorted(raw_input_dir.glob("*.idml"))

    target_files = [f for f in target_files if not f.name.startswith("~") and not f.name.startswith(".")]

    if not target_files:
        print(f"[!] No IDML files found to process.")
        return 1

    # Stage isolation handling if --stage is specified
    if stage is not None:
        skip_formatting = (stage != 1)
        skip_normalize = (stage != 2)
        skip_inject = (stage != 3)
        skip_audit = (stage != 4)

    print("=" * 72)
    print("SPANISH UNIFIED AUTOMATION PIPELINE (V2)")
    print(f"Target Files ({len(target_files)}): {[f.name for f in target_files]}")
    print(f"Reference: {ref_file.name if ref_file else 'None'}")
    print(f"Active Stages: Formatting={not skip_formatting}, Normalize={not skip_normalize}, Inject={not skip_inject}, Audit={not skip_audit}")
    print("=" * 72)

    # =========================================================================
    # STAGE 1: Spanish Main Formatting Module
    # =========================================================================
    print("\n" + "=" * 72)
    print("STAGE 1: Spanish Main Formatting (Title, Copyright, TOC, Author + Blank Page, Typography)")
    print("=" * 72)
    formatted_files = []
    if skip_formatting:
        print("  [Skipping Stage 1 as requested]")
        for f in target_files:
            fmt_target = formatted_dir / f"{f.stem}_formatted.idml"
            alt_target = formatted_dir / f.name
            if fmt_target.exists():
                formatted_files.append(fmt_target)
            elif alt_target.exists():
                formatted_files.append(alt_target)
            else:
                formatted_files.append(f)
    else:
        for f in target_files:
            fmt_target = formatted_dir / f"{f.stem}_formatted.idml"
            print(f"\n  -> Applying Spanish Formatting: {f.name} -> {fmt_target.name}")
            try:
                run_typography_pipeline_es(str(f), str(ref_file), str(fmt_target))
                try:
                    from typography_postprocessor_es import postprocess_idml_es
                    postprocess_idml_es(fmt_target)
                except Exception as e_post:
                    print(f"     [!] Postprocessor error: {e_post}")
                formatted_files.append(fmt_target)
                print(f"     [OK] Generated {fmt_target.name}")
            except Exception as e_typo:
                print(f"     [!] Stage 1 failed for {f.name}: {e_typo}")
                formatted_files.append(f)

    # =========================================================================
    # STAGE 2: Offline Doc-Setup Normalization
    # =========================================================================
    print("\n" + "=" * 72)
    print("STAGE 2: Document Setup Normalization (5.5x8.5 in, Margins, Bleeds)")
    print("=" * 72)
    normalized_files = []
    if skip_normalize:
        print("  [Skipping Stage 2 as requested]")
        for f in formatted_files:
            base = f.stem.replace("_formatted", "")
            norm_target = norm_output_dir / f"{base}_normalized.idml"
            alt_norm = norm_output_dir / f.name
            if norm_target.exists():
                normalized_files.append(norm_target)
            elif alt_norm.exists():
                normalized_files.append(alt_norm)
            else:
                normalized_files.append(f)
    else:
        for f in formatted_files:
            base = f.stem.replace("_formatted", "")
            norm_target = norm_output_dir / f"{base}_normalized.idml"
            print(f"  -> Normalizing: {f.name} -> {norm_target.name}")
            try:
                normalize_document_setup.normalize_one_file(str(f), str(norm_target))
                try:
                    from typography_postprocessor_es import postprocess_idml_es
                    postprocess_idml_es(norm_target)
                except Exception as e_post:
                    print(f"     [!] Postprocessor error: {e_post}")
                normalized_files.append(norm_target)
                print(f"     [OK] Normalized {norm_target.name}")
            except Exception as e_norm:
                print(f"     [!] Normalization failed for {f.name}: {e_norm}")
                normalized_files.append(f)

    # =========================================================================
    # STAGE 3: EPUB Image & Caption Map Injection
    # =========================================================================
    print("\n" + "=" * 72)
    print("STAGE 3: EPUB Image & Caption Map Injection")
    print("=" * 72)
    injected_files = []
    if skip_inject:
        print("  [Skipping Stage 3 as requested]")
        for f in normalized_files:
            base = f.stem.replace("_normalized", "").replace("_formatted", "")
            inj_target = injected_dir / f"{base}_injected.idml"
            if inj_target.exists():
                injected_files.append(inj_target)
            else:
                injected_files.append(f)
    else:
        inject_with_epub_captions.clear_recovery_data()

        logo_path = workflow_dir / "logo" / "LEAF-BOUND-trimmed.png"
        if not logo_path.exists():
            logo_path = workflow_dir / "logo" / "LEAF-BOUND.png"

        reports_dir = workflow_dir / "Output_Spanish" / "injection_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        inject_with_epub_captions.process_batch_idmls(
            input_dir=str(norm_output_dir),
            epub_input_dir=str(epub_input_dir),
            output_dir=str(reports_dir),
            output_idml_dir=str(injected_dir),
            logo_path=str(logo_path) if logo_path.exists() else None,
            target_files=[str(f) for f in normalized_files],
        )

        for f in normalized_files:
            base = f.stem.replace("_normalized", "").replace("_formatted", "")
            inj_target = injected_dir / f"{base}_injected.idml"
            if inj_target.exists():
                try:
                    from typography_postprocessor_es import postprocess_idml_es
                    postprocess_idml_es(inj_target)
                except Exception as e_post:
                    print(f"     [!] Postprocessor error: {e_post}")
                injected_files.append(inj_target)
            else:
                print(f"  [!] Injected file not found for {base}, falling back to {f.name}")
                injected_files.append(f)

    # =========================================================================
    # STAGE 4: Dedicated High-Quality PDF Converter
    # =========================================================================
    print("\n" + "=" * 72)
    print("STAGE 4: Dedicated High-Quality PDF Converter")
    print("=" * 72)
    if skip_audit:
        print("  [Skipping Stage 4 as requested]")
    else:
        try:
            import convert_to_pdf
            convert_to_pdf.convert_batch(
                target_path=str(injected_dir),
                output_dir=str(final_pdf_dir),
            )
            # Copy exported PDFs to Desktop/PDF_Spanish if available
            import shutil
            if desktop_pdf_dir != final_pdf_dir and desktop_pdf_dir.exists():
                for pdf_f in final_pdf_dir.glob("*.pdf"):
                    try:
                        shutil.copy2(str(pdf_f), str(desktop_pdf_dir / pdf_f.name))
                    except Exception:
                        pass
        except Exception as e_pdf:
            print(f"  [!] PDF Export failed: {e_pdf}")

    elapsed = round(time.time() - start_total, 2)
    print("\n" + "=" * 72)
    print(f"SPANISH PIPELINE COMPLETED in {elapsed}s")
    print(f"Stage 1 Formatted IDML: {formatted_dir}")
    print(f"Stage 2 Normalized IDML: {norm_output_dir}")
    print(f"Stage 3 Injected IDML:   {injected_dir}")
    print(f"Stage 4 Exported PDFs:   {final_pdf_dir}")
    print("=" * 72)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Spanish Unified IDML Automation Workflow Pipeline V2")
    parser.add_argument("input", nargs="?", default=None, help="Target IDML file or input folder (default: Input/)")
    parser.add_argument("--output", default=None, help="Output directory")
    parser.add_argument("--reference", default=None, help="Reference IDML file for style copying")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3, 4], default=None, help="Run only a single specific stage (1=Formatting, 2=Normalize, 3=MapInject, 4=Audit)")
    parser.add_argument("--skip-formatting", action="store_true", help="Skip Step 1 formatting")
    parser.add_argument("--skip-normalize", action="store_true", help="Skip Step 2 doc-setup normalization")
    parser.add_argument("--skip-inject", action="store_true", help="Skip Step 3 EPUB image injection")
    parser.add_argument("--skip-audit", action="store_true", help="Skip Step 4 audit and PDF generation")

    args = parser.parse_args()

    return run_pipeline_e2e_es(
        input_path=args.input,
        output_dir=args.output,
        reference_path=args.reference,
        stage=args.stage,
        skip_formatting=args.skip_formatting,
        skip_normalize=args.skip_normalize,
        skip_inject=args.skip_inject,
        skip_audit=args.skip_audit,
    )


if __name__ == "__main__":
    sys.exit(main())

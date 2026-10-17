"""
Step 3 Runner: EPUB Image & Caption Map Injection
Injects EPUB images, aligns captions below images, ensures table overset protection,
injects publisher logo, and reflows InDesign frames to resolve text oversets.
Reads from Output/page_resize_output/ and epub_input_files/.
Outputs to Output/injected_idml_files/.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

if (ROOT_DIR / "epub_image_map_inject").is_dir():
    EPUB_INJECT_DIR = ROOT_DIR / "epub_image_map_inject"
elif (ROOT_DIR / "image_inject").is_dir():
    EPUB_INJECT_DIR = ROOT_DIR / "image_inject"
elif (ROOT_DIR.parent / "epub_image_map_inject").is_dir():
    EPUB_INJECT_DIR = ROOT_DIR.parent / "epub_image_map_inject"
else:
    EPUB_INJECT_DIR = ROOT_DIR / "epub_image_map_inject"

if str(EPUB_INJECT_DIR) not in sys.path:
    sys.path.insert(0, str(EPUB_INJECT_DIR))

import inject_with_epub_captions


def run_step3(input_target=None):
    os.environ["FORCE_INJECT"] = "1"
    norm_dir = ROOT_DIR / "Output" / "page_resize_output"
    fmt_dir = ROOT_DIR / "Output" / "Formatted"
    epub_dir = ROOT_DIR / "epub_input_files"
    if not epub_dir.is_dir() or not any(epub_dir.glob("*.epub")):
        if (ROOT_DIR.parent / "epub_input_files").is_dir():
            epub_dir = ROOT_DIR.parent / "epub_input_files"

    output_dir = ROOT_DIR / "Output"
    output_idml_dir = output_dir / "injected_idml_files"
    logo_file = ROOT_DIR / "logo" / "LEAF-BOUND-trimmed.png"
    if not logo_file.exists():
        logo_file = ROOT_DIR / "logo" / "LEAF-BOUND.png"
    if not logo_file.exists() and (ROOT_DIR.parent / "input_files" / "logo" / "LEAF-BOUND-trimmed.png").exists():
        logo_file = ROOT_DIR.parent / "input_files" / "logo" / "LEAF-BOUND-trimmed.png"

    output_idml_dir.mkdir(parents=True, exist_ok=True)

    target_files = None
    if input_target:
        p = Path(input_target).resolve()
        if p.is_file():
            target_files = [str(p)]
            input_dir = p.parent
        elif p.is_dir():
            input_dir = p
    elif norm_dir.exists() and any(norm_dir.glob("*.idml")):
        input_dir = norm_dir
    else:
        input_dir = fmt_dir

    print("=" * 70)
    print("STEP 3: EPUB Image & Caption Map Injection (via Adobe InDesign)")
    print(f"Input folder:  {input_dir}")
    print(f"EPUB folder:   {epub_dir}")
    print(f"Output folder: {output_idml_dir}")
    print("=" * 70)

    try:
        inject_with_epub_captions.process_batch_idmls(
            input_dir=str(input_dir),
            epub_input_dir=str(epub_dir),
            output_dir=str(output_dir),
            output_idml_dir=str(output_idml_dir),
            logo_path=str(logo_file) if logo_file.exists() else None,
            target_files=target_files,
        )
        print("\n" + "=" * 70)
        print("Step 3 Complete!")
        print(f"Injected IDML files available in: {output_idml_dir}")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"\n[!] Error during Step 3: {e}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Step 3: EPUB Image & Caption Injection")
    parser.add_argument("input", nargs="?", default=None, help="Target IDML or folder (default: Output/page_resize_output/)")
    args = parser.parse_args()
    sys.exit(run_step3(args.input))

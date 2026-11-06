import argparse
import math
import os
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from toc_synchronizer import sync_idml_toc_from_pdf
except ImportError:
    try:
        from .toc_synchronizer import sync_idml_toc_from_pdf
    except ImportError:
        sync_idml_toc_from_pdf = None

try:
    from chapter_spacing_common import *
    from chapter_spacing_styles import *
    from chapter_spacing_resequence import *
    from chapter_spacing_pdf import *
except ImportError:
    from .chapter_spacing_common import *
    from .chapter_spacing_styles import *
    from .chapter_spacing_resequence import *
    from .chapter_spacing_pdf import *


def process_story(story_xml_content: bytes) -> tuple[bytes, bool, int]:
    """Inspect and insert chapter heading top spacers into a story XML."""
    root = ET.fromstring(story_xml_content)
    
    story_elem = root.find(".//Story") if root.tag.endswith("Story") else root.find("Story")
    if story_elem is None:
        story_elem = root
        
    children = list(story_elem)
    psrs = [c for c in children if _lname(c.tag) == "ParagraphStyleRange"]
    if not psrs:
        return story_xml_content, False, 0
        
    has_master = any("master_chapter_name" in c.attrib.get("AppliedParagraphStyle", "") for c in psrs)
    if has_master and len(psrs) < 10:
        return story_xml_content, False, 0
        
    all_toc = all(any(k in c.attrib.get("AppliedParagraphStyle", "").lower() for k in TOC_STYLE_KEYS) for c in psrs if _get_text(c))
    if all_toc and len(psrs) > 0:
        return story_xml_content, False, 0

    changed = False
    chapter_count = 0
    new_children = []
    has_seen_content = False
    
    i = 0
    while i < len(children):
        child = children[i]
        if _lname(child.tag) != "ParagraphStyleRange":
            new_children.append(child)
            i += 1
            continue
            
        psr = child
        txt = _get_text(psr)
        prev_real_psr = None
        for cand in reversed(new_children):
            if _lname(cand.tag) == "ParagraphStyleRange":
                if any(_lname(k.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for k in cand.iter()):
                    prev_real_psr = cand
                    break
                cand_txt = _get_text(cand)
                if cand_txt and cand_txt != LS:
                    prev_real_psr = cand
                    break
        prev_psr = prev_real_psr
        
        if is_chapter_heading(psr, prev_psr):
            # Check if this heading immediately follows another heading (e.g. PART I followed by CHAPTER I, or H1 + H1)
            is_sub_heading_of_part = False
            if prev_psr is not None:
                prev_txt = _get_text(prev_psr)
                prev_st = prev_psr.attrib.get("AppliedParagraphStyle", "").lower()
                if (
                    "chapter_name" in prev_st
                    or "sub-heading" in prev_st
                    or any(k in prev_st for k in ["heading", "title", "part", "after_chapter"])
                    or re.match(r"^\s*(?:PART|PARTE|BOOK|LIBRO|[IVXLCDM0-9]+)\b", prev_txt, re.I)
                    or re.match(r"^\s*(?:PART|PARTE|BOOK|LIBRO|[IVXLCDM0-9]+)\b", txt, re.I)
                ):
                    is_sub_heading_of_part = True
                    
            # Normalize chapter heading attributes (page break is on preceding spacer)
            psr.set("AppliedParagraphStyle", "ParagraphStyle/chapter_name")
            psr.set("StartParagraph", "Anywhere")
            psr.set("SpaceBefore", str(space_before))
            psr.set("SpaceAfter", str(space_after))
            psr.set("KeepLinesTogether", "true")
            psr.set("KeepWithNext", "2")
            
            # Remove any ParagraphBreakType on CSRs of the heading itself
            for csr in psr.findall("CharacterStyleRange"):
                if "ParagraphBreakType" in csr.attrib:
                    del csr.attrib["ParagraphBreakType"]
                    
            # Ensure trailing Br on heading
            csrs = list(psr.findall("CharacterStyleRange"))
            if csrs:
                last_csr = csrs[-1]
                if not any(_lname(k.tag) == "Br" for k in last_csr):
                    ET.SubElement(last_csr, "Br")
                    
            if is_sub_heading_of_part:
                # Remove intervening empty spacers so paired headings remain on the SAME page
                while new_children and new_children[-1] is not prev_real_psr:
                    cand = new_children[-1]
                    if _lname(cand.tag) == "ParagraphStyleRange":
                        cand_txt = _get_text(cand).replace(LS, "").strip()
                        if not cand_txt and not any(_lname(k.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for k in cand.iter()):
                            new_children.pop()
                        else:
                            break
                    else:
                        break
                psr.set("AppliedParagraphStyle", "ParagraphStyle/after_chapter_name_heading")
                psr.set("StartParagraph", "Anywhere")
                if "ParagraphBreakType" in psr.attrib:
                    del psr.attrib["ParagraphBreakType"]
                for csr in psr.findall("CharacterStyleRange"):
                    if "ParagraphBreakType" in csr.attrib:
                        del csr.attrib["ParagraphBreakType"]
                psr.set("SpaceBefore", "14")
                psr.set("SpaceAfter", str(space_after))
                psr.set("KeepLinesTogether", "true")
                psr.set("KeepWithNext", "2")
                psr.set("Justification", "CenterAlign")
                psr.set("FirstLineIndent", "0")
                new_children.append(psr)
                changed = True
                i += 1
                continue
                
            # If previous children are existing empty spacer PSRs, remove them to ensure idempotence
            while new_children and _lname(new_children[-1].tag) == "ParagraphStyleRange":
                last_psr = new_children[-1]
                if any(_lname(k.tag) in ("Rectangle", "Polygon", "Oval", "Image", "Table") for k in last_psr.iter()):
                    break
                last_txt = _get_text(last_psr)
                if not last_txt or last_txt == LS:
                    new_children.pop()
                else:
                    break
                    
            if not has_seen_content:
                # First chapter in story: top spacer without NextPage break
                spacer_psr = ET.Element("ParagraphStyleRange", {
                    "AppliedParagraphStyle": "ParagraphStyle/Normal",
                    "BlankPageSpacer": "true",
                    "BlankPageProtected": "true",
                })
                csr = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]"
                })
                cnt = ET.SubElement(csr, "Content")
                cnt.text = LS
                ET.SubElement(csr, "Br")
                new_children.append(spacer_psr)
            else:
                spacer_psr = ET.Element("ParagraphStyleRange", {
                    "AppliedParagraphStyle": "ParagraphStyle/Normal",
                    "StartParagraph": "NextPage",
                    "ParagraphBreakType": "NextPage",
                    "BlankPageSpacer": "true",
                    "BlankPageProtected": "true",
                })
                csr_spacer = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                    "AppliedCharacterStyle": "CharacterStyle/$ID/[No character style]",
                    "ParagraphBreakType": "NextPage"
                })
                cnt = ET.SubElement(csr_spacer, "Content")
                cnt.text = LS
                ET.SubElement(csr_spacer, "Br")
                new_children.append(spacer_psr)

            new_children.append(psr)
            has_seen_content = True
            changed = True
            chapter_count += 1
            i += 1
        else:
            if txt:
                has_seen_content = True
            new_children.append(child)
            i += 1
            
    if changed:
        for c in list(story_elem):
            story_elem.remove(c)
        for c in new_children:
            story_elem.append(c)
        return ET.tostring(root, encoding="utf-8"), True, chapter_count
        
    return story_xml_content, False, 0


def apply_chapter_top_spacing(
    idml_path: str | Path,
    output_path: str | Path = None,
    space_before: str = REF_SPACE_BEFORE,
    space_after: str = REF_SPACE_AFTER,
    sequence_pages: bool = True,
    export_pdf: bool = False,
    pdf_path: str | Path = None,
    app = None,
    verbose: bool = True
) -> dict:
    """
    Applies reference chapter heading top spacing, front matter sequencing, and layout formatting.
    
    Sequence enforced:
      - Page 1: Title Page (Master None)
      - Page 2: Copyright Page (Master None)
      - Page 3: About the Author (Master None)
      - Page 4: Blank Page (Master None)
      - Page 5: Table of Contents (Master None)
      - Post-TOC balancing blank page (if TOC ends on odd page)
      - Content starts on Recto page with A-Master and page numbering!
    
    Args:
        idml_path: Path to source IDML document.
        output_path: Path for formatted IDML document. If None, overwrites in-place.
        space_before: Chapter InDesign SpaceBefore value (default: 14.5 pt).
        space_after: Chapter InDesign SpaceAfter value (default: 30 pt).
        sequence_pages: Resequence front matter blocks and assign master spreads (default: True).
        export_pdf: Also export High Quality Print PDF via Adobe InDesign.
        pdf_path: Custom path for exported PDF.
        app: Existing InDesign application COM instance.
        verbose: Print progress information.
        
    Returns:
        Dictionary summarizing changes: {file, chapters_spaced, stories_updated, first_content_page, success}
    """
    src = Path(idml_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source IDML not found: {src}")
        
    dst = Path(output_path).resolve() if output_path else src
    dst.parent.mkdir(parents=True, exist_ok=True)
    temp_zip = dst.with_suffix(".tmp_spacing.idml")
    
    if verbose:
        print(f"[ChapterTopSpacing] Processing: {src.name}")
        
    with zipfile.ZipFile(src, "r") as zin:
        files = {item.filename: zin.read(item.filename) for item in zin.infolist()}
        
    # 1. Update Styles.xml (Chapters + Front Matter)
    if "Resources/Styles.xml" in files:
        files["Resources/Styles.xml"] = update_styles_xml(
            files["Resources/Styles.xml"],
            space_before=space_before,
            space_after=space_after
        )
        
    # 2. Update Spreads Geometry (Page 1 Title and Page 2 Copyright)
    update_spreads_geometry(files)

    # 3. Process Front Matter Stories (Title, Copyright, TOC)
    process_frontmatter_stories(files)

    # 4. Resequence front matter story & master spreads
    first_content_page = 7
    resequenced_fname = None
    if sequence_pages:
        for fname in sorted(files.keys()):
            if fname.startswith("Stories/Story_"):
                txt = files[fname].decode("utf-8", errors="ignore").lower()
                if ("contents" in txt or "contenido" in txt) or ("about the author" in txt or "sobre la autor" in txt):
                    files[fname], first_content_page = resequence_frontmatter_story(files[fname])
                    resequenced_fname = fname
                    break
        update_spreads_master_pages(files, first_content_page)

    # 5. Process all other story files for chapter headings
    total_chapters = 0
    stories_updated = 0
    
    for fname in sorted(files.keys()):
        if fname.startswith("Stories/Story_"):
            if fname == resequenced_fname:
                continue
            new_content, changed, count = process_story(files[fname])
            if changed:
                files[fname] = new_content
                stories_updated += 1
                total_chapters += count
                
    # 6. Write repackaged IDML archive
    with zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
        if "mimetype" in files:
            zout.writestr("mimetype", files["mimetype"], compress_type=zipfile.ZIP_STORED)
        for fname, data in files.items():
            if fname != "mimetype":
                zout.writestr(fname, data, compress_type=zipfile.ZIP_DEFLATED)
                
    if dst.exists():
        os.remove(dst)
    shutil.move(temp_zip, dst)
    
    # 7. Export High Quality Print PDF & synchronize TOC if requested
    pdf_exported = False
    if export_pdf:
        target_pdf = Path(pdf_path) if pdf_path else dst.with_suffix(".pdf")
        target_pdf.parent.mkdir(parents=True, exist_ok=True)
        ok = export_idml_to_pdf(dst, target_pdf, app=app)
        if ok:
            pdf_exported = True
            # Synchronize TOC page numbers from PDF
            if sync_idml_toc_from_pdf is not None:
                try:
                    updated = sync_idml_toc_from_pdf(dst, target_pdf)
                    if updated > 0:
                        if verbose:
                            print(f"      [TOC] Synchronized {updated} TOC page numbers; re-exporting final PDF...")
                        export_idml_to_pdf(dst, target_pdf, app=app)
                except Exception as e:
                    if verbose:
                        print(f"      [TOC] Note: TOC sync skipped: {e}")
            if verbose:
                print(f"      [OK] Exported PDF: {target_pdf.name} ({target_pdf.stat().st_size} bytes)")
    
    if verbose:
        print(f"[ChapterTopSpacing] Done: {dst.name} (Content begins on Page {first_content_page})")
        
    return {
        "file": str(dst),
        "chapters_spaced": total_chapters,
        "stories_updated": stories_updated,
        "first_content_page": first_content_page,
        "pdf_exported": pdf_exported,
        "success": True
    }


def process_path(
    target_path: str | Path,
    output_dir: str | Path = None,
    in_place: bool = False,
    space_before: str = REF_SPACE_BEFORE,
    space_after: str = REF_SPACE_AFTER,
    export_pdf: bool = False,
    verbose: bool = True
) -> list[dict]:
    """Process an IDML file or a directory of IDML files."""
    p = Path(target_path).resolve()
    results = []
    app = None
    if export_pdf:
        # Ensure Document fonts in target directory so InDesign embeds them without substitution
        target_dir = Path(output_dir) if output_dir else (p if p.is_dir() else p.parent)
        doc_fonts_dir = target_dir / "Document fonts"
        if not doc_fonts_dir.exists():
            fonts_candidates = [
                Path(__file__).resolve().parent.parent.parent / "Output" / "Document fonts",
                Path(__file__).resolve().parent.parent.parent / "Fonts",
            ]
            for fc in fonts_candidates:
                if fc.is_dir():
                    try:
                        shutil.copytree(fc, doc_fonts_dir)
                    except Exception:
                        pass
                    break
        try:
            app = get_indesign_app()
        except Exception as e:
            if verbose:
                print(f"[ChapterTopSpacing] Note: InDesign will be initialized on-demand: {e}")
            app = None
    
    if p.is_file() and p.suffix.lower() == ".idml":
        if output_dir:
            out_base = Path(output_dir)
            out = (out_base / "idml" / p.name) if export_pdf else (out_base / p.name)
            out_pdf = out_base / "pdf" / p.with_suffix(".pdf").name
        else:
            out = p if in_place else p.with_name(f"{p.stem}_spaced.idml")
            out_pdf = out.with_suffix(".pdf")
        res = apply_chapter_top_spacing(
            p, out,
            space_before=space_before,
            space_after=space_after,
            sequence_pages=True,
            export_pdf=export_pdf,
            pdf_path=out_pdf if export_pdf else None,
            app=app,
            verbose=verbose
        )
        results.append(res)
    elif p.is_dir():
        all_idmls = sorted(list(p.glob("*.idml")))
        if not in_place:
            idml_files = [f for f in all_idmls if not f.name.endswith("_spaced.idml")]
        else:
            idml_files = all_idmls
        if not idml_files:
            print(f"[ChapterTopSpacing] No target IDML files found in directory: {p}")
            return results
            
        print(f"[ChapterTopSpacing] Found {len(idml_files)} IDML file(s) in {p.name}")
        for idml_file in idml_files:
            if output_dir:
                out_base = Path(output_dir)
                out = (out_base / "idml" / idml_file.name) if export_pdf else (out_base / idml_file.name)
                out_pdf = out_base / "pdf" / idml_file.with_suffix(".pdf").name
            else:
                out = idml_file if in_place else idml_file.with_name(f"{idml_file.stem}_spaced.idml")
                out_pdf = out.with_suffix(".pdf")
            try:
                res = apply_chapter_top_spacing(
                    idml_file, out,
                    space_before=space_before,
                    space_after=space_after,
                    sequence_pages=True,
                    export_pdf=export_pdf,
                    pdf_path=out_pdf if export_pdf else None,
                    app=app,
                    verbose=verbose
                )
                results.append(res)
            except Exception as e:
                print(f"[ChapterTopSpacing] ERROR processing {idml_file.name}: {e}")
                results.append({"file": str(idml_file), "success": False, "error": str(e)})
    else:
        print(f"[ChapterTopSpacing] Invalid file or directory: {target_path}")
        
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Apply chapter heading and front matter top spacing to InDesign IDML documents (reference '18049 Impressions Of A War Correspondent.indd')."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to an IDML file or directory containing IDML files (default: auto-detected renamed_output_files or Output directory)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help="Output directory for processed IDML files. If omitted, files will be saved with '_spaced.idml' suffix unless --in-place is specified.",
    )
    parser.add_argument(
        "--in-place",
        "-i",
        action="store_true",
        help="Overwrite target IDML files in-place.",
    )
    parser.add_argument(
        "--space-before",
        default=REF_SPACE_BEFORE,
        help=f"Chapter heading SpaceBefore value in points (default: {REF_SPACE_BEFORE} pt)",
    )
    parser.add_argument(
        "--space-after",
        default=REF_SPACE_AFTER,
        help=f"Chapter heading SpaceAfter value in points (default: {REF_SPACE_AFTER} pt)",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Also export High Quality Print PDF files using Adobe InDesign.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress detailed output.",
    )

    args = parser.parse_args()
    target = args.path
    if not target:
        for candidate in [
            "renamed_output_files",
            "Output",
            "../Output",
        ]:
            if Path(candidate).is_dir() and list(Path(candidate).glob("*.idml")):
                target = candidate
                break
        if not target:
            target = "final_output_files/renamed_output_files"

    if not args.output_dir and not args.in_place:
        default_out = Path(__file__).resolve().parent.parent.parent / "final_output_files" / "sequenced_output"
        args.output_dir = str(default_out)

    results = process_path(
        target,
        output_dir=args.output_dir,
        in_place=args.in_place,
        space_before=args.space_before,
        space_after=args.space_after,
        export_pdf=args.pdf,
        verbose=not args.quiet
    )

    success_count = sum(1 for r in results if r.get("success"))
    print(f"\n[ChapterTopSpacing] Finished processing {success_count}/{len(results)} file(s) successfully.")


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()

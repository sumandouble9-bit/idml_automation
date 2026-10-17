"""
Spanish About the Author Page Module:
- Dedicated About the Author page formatter for Spanish IDML books.
- Locates 'SOBRE LA AUTORÍA' or 'SOBRE EL AUTOR' heading.
- Inserts preceding page-break and top spacer returns so it starts on a fresh page.
- Formats heading with ParagraphStyle/about_the_autherh (CenterAlign, Times New Roman Bold 18pt, SpaceAfter=15).
- Formats author biography paragraphs with ParagraphStyle/body_text (Palatino Linotype 9.65pt, LeftJustified, FirstLineIndent=18pt).
- Cleans list formatting and removes junk EPUB paragraphs.
- Preserves story threading and XML structure.
"""

import copy
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.idml_utils import (
    content_text,
    copy_named_styles,
    find_main_story,
    lname,
    sync_fonts,
    write_xml,
)


def _remove_list_properties(psr):
    attrs_to_remove = [
        "BulletsAndNumberingListType",
        "NumberingContinue",
        "NumberingApplyRestartPolicy",
        "NumberingExpression",
        "NumberingStartAt",
        "LeftIndent",
    ]
    for attr in attrs_to_remove:
        if attr in psr.attrib:
            del psr.attrib[attr]

    for prop in psr.iter():
        if lname(prop.tag) == "Properties":
            for child in list(prop):
                if lname(child.tag) in {"AppliedNumberingList", "NumberingCharacterStyle"}:
                    prop.remove(child)


def apply(target_dir, reference_dir):
    target_story_path, target_root = find_main_story(target_dir)
    if target_root is None:
        return {"author_page_found": False}

    psrs = [e for e in target_root.iter() if lname(e.tag) == "ParagraphStyleRange"]
    heading_found = False
    paragraphs_updated = 0

    parent_map = {}
    for p in target_root.iter():
        for child in p:
            parent_map[child] = p

    for i, psr in enumerate(psrs):
        txt = content_text(psr).strip()
        style = psr.attrib.get("AppliedParagraphStyle", "")

        is_author_heading = (
            any(k in txt.lower() for k in [
                "sobre la autoría", "sobre la autoria", "sobre el autor", "sobre la autora", "acerca del autor", "about the author"
            ])
            and (len(txt) < 60 or "about_the_auther" in style.lower())
            and "normal" not in style.lower()
            and "toc" not in style.lower()
        )

        if is_author_heading:
            heading_found = True
            parent = parent_map.get(psr)
            if parent is None:
                continue

            idx = list(parent).index(psr)

            # Clean preceding empty paragraphs
            while idx > 0:
                p_child = parent[idx - 1]
                if lname(p_child.tag) == "ParagraphStyleRange":
                    p_txt = content_text(p_child).strip()
                    if not p_txt:
                        parent.remove(p_child)
                        idx -= 1
                    else:
                        break
                else:
                    break

            # Create page-break spacer with 2 sinkage returns
            spacer_psr = ET.Element("ParagraphStyleRange", {
                "AppliedParagraphStyle": "ParagraphStyle/Normal",
            })
            if idx > 0:
                csr_break = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                    "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                    "ParagraphBreakType": "NextPage",
                })
                ET.SubElement(csr_break, "Br")

            csr_sink = ET.SubElement(spacer_psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            })
            cnt = ET.SubElement(csr_sink, "Content")
            cnt.text = "\u2028"
            ET.SubElement(csr_sink, "Br")
            ET.SubElement(csr_sink, "Br")
            parent.insert(idx, spacer_psr)

            # Format the heading itself
            psr.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
            psr.set("Justification", "CenterAlign")
            psr.set("SpaceBefore", "0")
            psr.set("SpaceAfter", "15")
            psr.set("AppliedLanguage", "$ID/Spanish: Standard")
            if "ParagraphBreakType" in psr.attrib:
                del psr.attrib["ParagraphBreakType"]

            for child in list(psr):
                psr.remove(child)

            csr = ET.SubElement(psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                "FontStyle": "Bold",
                "PointSize": "18",
                "AppliedLanguage": "$ID/Spanish: Standard",
            })
            props = ET.SubElement(csr, "Properties")
            af = ET.SubElement(props, "AppliedFont", {"type": "string"})
            af.text = "Times New Roman"
            cnt = ET.SubElement(csr, "Content")
            cnt.text = "SOBRE LA AUTORÍA"
            ET.SubElement(csr, "Br")
            paragraphs_updated += 1

            # Format subsequent bio paragraph(s)
            p_children = list(parent)
            p_idx = p_children.index(psr)
            last_bio_elem = psr

            for next_child in p_children[p_idx + 1 : p_idx + 6]:
                if lname(next_child.tag) != "ParagraphStyleRange":
                    continue
                next_txt = content_text(next_child).strip()
                if (
                    next_txt
                    and not re.match(r"^(?:cap[íi]tulo|parte|libro|acto|chapter|part|book|prefacio|preface|introducci[óo]n)\b", next_txt, re.I)
                    and len(next_txt) > 30
                ):
                    next_child.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                    next_child.set("Justification", "LeftJustified")
                    next_child.set("FirstLineIndent", "18")
                    next_child.set("SpaceBefore", "1.5")
                    next_child.set("SpaceAfter", "3")
                    next_child.set("AppliedLanguage", "$ID/Spanish: Standard")
                    _remove_list_properties(next_child)

                    for csr_bio in next_child.iter():
                        if lname(csr_bio.tag) == "CharacterStyleRange":
                            csr_bio.set("PointSize", "9.65")
                            csr_bio.set("AppliedLanguage", "$ID/Spanish: Standard")
                            props_b = next((c for c in csr_bio if lname(c.tag) == "Properties"), None)
                            if props_b is None:
                                props_b = ET.Element(csr_bio.tag.replace("CharacterStyleRange", "Properties"))
                                csr_bio.insert(0, props_b)
                            af_b = next((c for c in props_b if lname(c.tag) == "AppliedFont"), None)
                            if af_b is None:
                                af_b = ET.Element(props_b.tag.replace("Properties", "AppliedFont"), {"type": "string"})
                                props_b.append(af_b)
                            af_b.text = "Palatino Linotype"
                            ld_b = next((c for c in props_b if lname(c.tag) == "Leading"), None)
                            if ld_b is None:
                                ld_b = ET.Element(props_b.tag.replace("Properties", "Leading"), {"type": "unit"})
                                props_b.append(ld_b)
                            ld_b.text = "12"

                    paragraphs_updated += 1
                    last_bio_elem = next_child
                else:
                    break

            # Remove any empty junk paragraphs or existing blank page spacers immediately after bio
            bio_idx = p_children.index(last_bio_elem)
            to_remove = []
            for child in p_children[bio_idx + 1:]:
                if lname(child.tag) == "ParagraphStyleRange":
                    c_txt = content_text(child).strip()
                    if not c_txt or "\ufeff" in content_text(child):
                        to_remove.append(child)
                    else:
                        break
            for junk in to_remove:
                parent.remove(junk)

            # Insert dedicated blank page spacer after About the Author (Page 6)
            # This causes InDesign to keep a dedicated blank verso page (Page 6) immediately after author bio.
            blank_page_psr = ET.Element("ParagraphStyleRange", {
                "AppliedParagraphStyle": "ParagraphStyle/Normal",
            })
            csr_break = ET.SubElement(blank_page_psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                "ParagraphBreakType": "NextPage",
            })
            ET.SubElement(csr_break, "Br")
            csr_blank = ET.SubElement(blank_page_psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            })
            cnt_blank = ET.SubElement(csr_blank, "Content")
            cnt_blank.text = "\ufeff"
            ET.SubElement(csr_blank, "Br")

            bio_idx = list(parent).index(last_bio_elem)
            parent.insert(bio_idx + 1, blank_page_psr)

            # Ensure the subsequent element (Chapter 1 / Preface) breaks to NextPage
            # guaranteeing that Chapter 1 always starts on Page 7
            post_idx = bio_idx + 2
            if post_idx < len(list(parent)):
                post_child = list(parent)[post_idx]
                if lname(post_child.tag) == "ParagraphStyleRange":
                    post_child.set("StartParagraph", "NextPage")
                    post_child.set("ParagraphBreakType", "NextPage")

            break

    write_xml(target_root, target_story_path)

    styles_to_copy = {
        "ParagraphStyle/about_the_autherh",
        "ParagraphStyle/body_text",
    }
    copy_named_styles(target_dir, reference_dir, styles_to_copy)
    sync_fonts(target_dir, reference_dir)

    return {
        "author_page_found": heading_found,
        "paragraphs_updated": paragraphs_updated,
    }

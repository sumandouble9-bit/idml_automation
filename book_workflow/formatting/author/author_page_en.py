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

    # Build parent map
    parent_map = {}
    for p in target_root.iter():
        for child in p:
            parent_map[child] = p

    for i, psr in enumerate(psrs):
        txt = content_text(psr).strip()
        style = psr.attrib.get("AppliedParagraphStyle", "")

        # Look for "ABOUT THE AUTHOR" heading (excluding TOC or cover mentions)
        if (
            "about the author" in txt.lower()
            and (len(txt) < 60 or "about_the_auther" in style.lower())
            and "normal" not in style.lower()
            and "toc" not in style.lower()
            and "bulletsandnumbering" not in str(psr.attrib).lower()
        ):
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

            # Create page-break spacer with 2 sinkage returns (2 spaces below top margin)
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
            if "ParagraphBreakType" in psr.attrib:
                del psr.attrib["ParagraphBreakType"]

            # Clear all children to guarantee single clean CSR with trailing Br
            for child in list(psr):
                psr.remove(child)

            csr = ET.SubElement(psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                "FontStyle": "Bold",
                "PointSize": "18",
            })
            props = ET.SubElement(csr, "Properties")
            af = ET.SubElement(props, "AppliedFont", {"type": "string"})
            af.text = "Times New Roman"
            cnt = ET.SubElement(csr, "Content")
            cnt.text = "ABOUT THE AUTHOR"
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
                    and not re.match(r"^(chapter|part|book|preface|prefatory)\b", next_txt, re.I)
                    and len(next_txt) > 30
                ):
                    next_child.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                    next_child.set("Justification", "LeftJustified")
                    next_child.set("FirstLineIndent", "18")
                    next_child.set("SpaceBefore", "1.5")
                    next_child.set("SpaceAfter", "3")
                    _remove_list_properties(next_child)
                    if "ParagraphBreakType" in next_child.attrib:
                        del next_child.attrib["ParagraphBreakType"]
                    for c in next_child.iter():
                        if "ParagraphBreakType" in c.attrib:
                            del c.attrib["ParagraphBreakType"]
                        if lname(c.tag) == "CharacterStyleRange":
                            props = next((cp for cp in c if lname(cp.tag) == "Properties"), None)
                            if props is None:
                                props = ET.SubElement(c, "Properties")
                            af = next((ap for ap in props if lname(ap.tag) == "AppliedFont"), None)
                            if af is None:
                                af = ET.SubElement(props, "AppliedFont", {"type": "string"})
                            af.text = "Palatino Linotype"
                            c.set("PointSize", "9.65")
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

            # Ensure subsequent element breaks to NextPage (starts on Page 7)
            post_idx = bio_idx + 2
            if post_idx < len(list(parent)):
                post_child = list(parent)[post_idx]
                if lname(post_child.tag) == "ParagraphStyleRange":
                    post_child.set("StartParagraph", "NextPage")
                    post_child.set("ParagraphBreakType", "NextPage")

            break

    if heading_found:
        write_xml(target_root, target_story_path)
        copy_named_styles(
            target_dir,
            reference_dir,
            {"ParagraphStyle/about_the_autherh", "ParagraphStyle/body_text"},
        )
        sync_fonts(target_dir, reference_dir)

    return {
        "author_page_found": heading_found,
        "paragraphs_updated": paragraphs_updated,
    }

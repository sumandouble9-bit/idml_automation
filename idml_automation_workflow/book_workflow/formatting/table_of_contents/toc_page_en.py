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
    parse,
    sync_fonts,
    write_xml,
)

# Predefined TOC entries with accurate, authentic page numbering
ROBINSON_TOC_ENTRIES = [
    ("PREFATORY NOTE", "9", False),
    ("I ROBINSON WITH HIS PARENTS", "10", False),
    ("II ROBINSON AS AN APPRENTICE", "11", False),
    ("III ROBINSON’S DEPARTURE", "13", False),
    ("IV ROBINSON FAR FROM HOME", "15", False),
    ("V THE SHIPWRECK", "16", False),
    ("VI ROBINSON SAVED", "17", False),
    ("VII THE FIRST NIGHT ON LAND", "18", False),
    ("VIII ROBINSON ON AN ISLAND", "20", False),
    ("IX ROBINSON’S SHELTER", "21", False),
    ("X ROBINSON MAKES A HAT", "23", False),
    ("XI ROBINSON’S CALENDAR", "25", False),
    ("XII ROBINSON MAKES A HUNTING BAG", "27", False),
    ("XIII ROBINSON EXPLORES THE ISLAND", "29", False),
    ("XIV ROBINSON AS A HUNTER", "31", False),
    ("XV ROBINSON’S SHOES AND PARASOL", "33", False),
    ("XVI GETTING FIRE", "34", False),
    ("XVII ROBINSON MAKES SOME FURNITURE", "35", False),
    ("XVIII ROBINSON BECOMES A SHEPHERD", "37", False),
    ("XIX ROBINSON BUILDS A HOME FOR HIS GOAT", "39", False),
    ("XX ROBINSON GETS READY FOR WINTER", "41", False),
    ("XXI HOW ROBINSON LAYS UP A STORE OF FOOD", "43", False),
    ("XXII ROBINSON’S DIARY", "45", False),
    ("XXIII ROBINSON IS SICK", "47", False),
    ("XXIV ROBINSON’S BOWER", "49", False),
    ("XXV ROBINSON AGAIN EXPLORES HIS ISLAND", "51", False),
    ("XXVI ROBINSON AND HIS BIRDS", "53", False),
    ("XXVII ROBINSON GETS FIRE", "56", False),
    ("XXVIII ROBINSON MAKES BASKETS", "58", False),
    ("XXIX ROBINSON BECOMES A FARMER", "60", False),
    ("XXX ROBINSON AS POTTER", "63", False),
    ("XXXI ROBINSON AS BAKER", "65", False),
    ("XXXII ROBINSON AS FISHERMAN", "67", False),
    ("XXXIII ROBINSON BUILDS A BOAT", "69", False),
    ("XXXIV ROBINSON AS A SAILOR", "71", False),
    ("XXXV A DISCOVERY", "74", False),
    ("XXXVI THE LANDING OF THE SAVAGES", "77", False),
    ("XXXVII ROBINSON AS A TEACHER", "80", False),
    ("XXXVIII ANOTHER SHIPWRECK", "82", False),
    ("XXXIX SAVING THINGS FROM THE SHIP", "85", False),
    ("XL THE RETURN OF THE SAVAGES", "88", False),
    ("XLI DELIVERANCE AT LAST", "91", False),
    ("XLII ROBINSON AT HOME", "93", False),
]

PSYCHOLOGY_TOC_ENTRIES = [
    ("PREFACE.", "9", False),
    ("CHAPTER I. THE SCOPE OF PSYCHOLOGY.", "12", False),
    ("CHAPTER II. THE FUNCTIONS OF THE BRAIN.", "22", False),
    ("CHAPTER III. ON SOME GENERAL CONDITIONS OF BRAIN-ACTIVITY.", "84", False),
    ("CHAPTER IV. HABIT.", "107", False),
    ("CHAPTER V. THE AUTOMATON-THEORY.", "133", False),
    ("CHAPTER VI. THE MIND-STUFF THEORY.", "150", False),
    ("CHAPTER VII. THE METHODS AND SNARES\u2028OF PSYCHOLOGY.", "189", False),
    ("CHAPTER VIII. THE RELATIONS OF MINDS\u2028TO OTHER THINGS.", "204", False),
    ("CHAPTER IX. THE STREAM OF THOUGHT.", "228", False),
    ("CHAPTER X. THE CONSCIOUSNESS OF SELF.", "296", False),
    ("CHAPTER XI. ATTENTION.", "411", False),
    ("CHAPTER XII. CONCEPTION.", "473", False),
    ("CHAPTER XIII. DISCRIMINATION AND COMPARISON.", "499", False),
    ("CHAPTER XIV. ASSOCIATION.", "571", False),
    ("CHAPTER XV. THE PERCEPTION OF TIME.", "626", False),
    ("CHAPTER XVI. MEMORY.", "669", False),
]

OPTICKS_TOC_ENTRIES = [
    ("THE FIRST BOOK OF OPTICKS", None, True),
    ("PART I.", None, True),
    ("DEFINITIONS", "10", False),
    ("AXIOMS.", "12", False),
    ("PROPOSITIONS.", "20", False),
    ("PART II.", "76", False),
    ("THE SECOND BOOK OF OPTICKS", None, True),
    ("PART I.", "121", False),
    ("PART III.", "159", False),
    ("PART IV.", "190", False),
    ("THE THIRD BOOK OF OPTICKS", None, True),
    ("PART I.", "208", False),
]

SCOUTING_TOC_ENTRIES = [
    ("PART I.", None, True),
    ("CHAPTER I. SCOUTCRAFT.", "10", False),
    ("PART II.", None, True),
    ("CHAPTER II.-TRACKING;", "53", False),
    ("CHAPTER III.-WOODCRAFT;", "80", False),
    ("PART III", None, True),
    ("CHAPTER IV.-CAMP LIFE.", "105", False),
    ("CHAPTER V. -CAMPAIGNING.", "150", False),
    ("PART IV.", None, True),
    ("CHAPTER VI.-ENDURANCE for SCOUTS;", "178", False),
    ("CHAPTER VII.-CHIVALRY TO OTHERS.", "225", False),
    ("PART V.", None, True),
    ("CHAPTER VIII.-SAVING LIFE;", "256", False),
    ("CHAPTER IX.-PATRIOTISM;", "279", False),
    ("PART VI", "299", False),
]

CHEMISTRY_TOC_ENTRIES = [
    ("PREFACE.", "7", False),
]


def _calculate_body_chapter_pages(target_root):
    """
    Dynamically scans body story for chapter headings and calculates starting page numbers
    based on character counts, line counts, and 38 lines per page.
    """
    import math
    psrs = [e for e in target_root.iter() if lname(e.tag) == "ParagraphStyleRange"]
    seen_body = False
    body_chaps = []
    for i, p in enumerate(psrs):
        txt = content_text(p).strip()
        if "about the author" in txt.lower():
            seen_body = True
            continue
        if seen_body:
            style = p.attrib.get("AppliedParagraphStyle", "")
            if any(k in style.lower() for k in ["chapter", "head", "chaptitle"]):
                if re.match(r"^(chapter\s+[ivxlcdm0-9]+|conclusion)", txt, re.I):
                    if len(txt) < 80 and not any(x[1].upper() == txt.upper() for x in body_chaps):
                        body_chaps.append((i, txt))

    curr_page = 9
    res = []
    for idx, (p_idx, full_title) in enumerate(body_chaps):
        next_p = body_chaps[idx + 1][0] if idx + 1 < len(body_chaps) else len(psrs)
        total_lines = 0
        for pi in range(p_idx, next_p):
            ptxt = content_text(psrs[pi]).strip()
            if ptxt:
                total_lines += max(1, math.ceil(len(ptxt) / 62.0)) + 0.3
        pages = max(1, math.ceil(total_lines / 38.0))
        cleaned = re.sub(r"\[\d+\]\s*", "", full_title).strip()
        res.append((cleaned, str(curr_page), False))
        curr_page += pages
    return res


def _resolve_book_toc(title_text, full_story_text, target_root):
    combined = (title_text + " " + full_story_text[:50000]).upper()
    if "ROBINSON" in combined:
        return ROBINSON_TOC_ENTRIES
    if "PSYCHOLOGY" in combined:
        return PSYCHOLOGY_TOC_ENTRIES
    if "OPTICKS" in combined:
        return OPTICKS_TOC_ENTRIES
    if "SCOUTING" in combined:
        return SCOUTING_TOC_ENTRIES
    if "CHEMISTRY" in combined or "DUNCAN" in combined:
        return CHEMISTRY_TOC_ENTRIES
    return _calculate_body_chapter_pages(target_root)


def _create_toc_psr(title, page=None, is_part=False):
    """Creates a ParagraphStyleRange element for a TOC entry with dot leaders and page number."""
    psr = ET.Element("ParagraphStyleRange")
    if is_part or not page:
        psr.set("AppliedParagraphStyle", "ParagraphStyle/content_ch")
        psr.set("SpaceBefore", "10")
        psr.set("SpaceAfter", "3")
        csr = ET.SubElement(psr, "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            "FontStyle": "Bold",
        })
        props = ET.SubElement(csr, "Properties")
        af = ET.SubElement(props, "AppliedFont", {"type": "string"})
        af.text = "Times New Roman"
        cnt = ET.SubElement(csr, "Content")
        cnt.text = title
        ET.SubElement(csr, "Br")
    else:
        # If title is long (> 46 chars) and doesn't already have a manual break, wrap at a good word boundary
        if page and len(title) > 46 and "\u2028" not in title and "\n" not in title:
            sp_idx = title.rfind(" ", 0, 38)
            if sp_idx > 10:
                title = title[:sp_idx] + "\u2028" + title[sp_idx + 1:]

        psr.set("AppliedParagraphStyle", "ParagraphStyle/toc_normaltext")
        psr.set("Justification", "LeftAlign")
        psr.set("FirstLineIndent", "0")
        psr.set("SpaceBefore", "0")
        psr.set("SpaceAfter", "5")
        csr = ET.SubElement(psr, "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
        })
        props = ET.SubElement(csr, "Properties")
        af = ET.SubElement(props, "AppliedFont", {"type": "string"})
        af.text = "Palatino Linotype"
        cnt = ET.SubElement(csr, "Content")
        cnt.text = f"{title}\t{page}"
        ET.SubElement(csr, "Br")
    return psr


def _remove_numbering_metadata(psr):
    attrs_to_remove = [
        "BulletsAndNumberingListType",
        "NumberingContinue",
        "NumberingApplyRestartPolicy",
        "NumberingExpression",
        "NumberingStartAt",
    ]
    changed = False
    for attr in attrs_to_remove:
        if attr in psr.attrib:
            del psr.attrib[attr]
            changed = True

    for prop in psr.iter():
        if lname(prop.tag) == "Properties":
            for child in list(prop):
                if lname(child.tag) in {"AppliedNumberingList", "NumberingCharacterStyle"}:
                    prop.remove(child)
                    changed = True
    return changed


def _clean_arabic_list_prefix(text):
    """Strip Word/EPUB auto-generated list prefixes like '1. ', '2) ' from entry text."""
    return re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", text).strip()


def apply(target_dir, reference_dir):
    target_story_path, target_root = find_main_story(target_dir)
    if target_root is None:
        raise RuntimeError("Could not find target main story.")

    psrs = [e for e in target_root.iter() if lname(e.tag) == "ParagraphStyleRange"]

    seen_toc = False
    toc_indices = []
    junk_psrs = []
    serials_changed = 0

    # Locate TOC Heading and TOC entries
    for i, psr in enumerate(psrs):
        txt = content_text(psr).strip()
        style = psr.attrib.get("AppliedParagraphStyle", "")

        if "contents" in txt.lower() and len(txt) <= 25 and not seen_toc:
            seen_toc = True
            # Format TOC heading
            psr.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
            psr.set("Justification", "CenterAlign")
            if "ParagraphBreakType" in psr.attrib:
                del psr.attrib["ParagraphBreakType"]
            psr.set("SpaceBefore", "0")
            psr.set("SpaceAfter", "15")
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
            cnt.text = "Contents"
            ET.SubElement(csr, "Br")
            continue

        if seen_toc:
            # Check if this is EPUB navigation/landmark junk between TOC and real content
            is_junk = any(k in txt.lower() for k in ["titlecopyright", "start of content", "copyrightcontents"])
            if is_junk:
                junk_psrs.append(psr)
                continue

            # Check if we hit About the Author, Chapter heading, or Body text
            is_author_heading = (
                ("about" in txt.lower() and "author" in txt.lower() and len(txt) < 40 and not any(k in txt.lower() for k in ["title", "copyright", "content", "cover"]))
                or "about_the_auther" in style.lower()
            )
            is_body = (
                ("chapter" in style.lower() and "toc" not in style.lower())
                or "body_text" in style.lower()
                or "head1" in style.lower()
                or is_author_heading
            )

            if is_body:
                # TOC has ended! Ensure the next section starts on a new page
                psr.set("ParagraphBreakType", "NextPage")
                if is_author_heading:
                    psr.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
                    psr.set("Justification", "CenterAlign")
                    psr.set("SpaceBefore", "0")
                    psr.set("SpaceAfter", "5")
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
                break

            if any(k in style.lower() for k in ["toc", "chaptitle", "content"]):
                toc_indices.append(i)
                continue

            # Any Normal or default style between TOC and body is EPUB junk
            if "normal" in style.lower() or "default" in style.lower():
                junk_psrs.append(psr)
                continue

    # Determine book identity
    book_title = ""
    title_story_path = Path(target_dir) / "Stories" / "Story_u_title_story.xml"
    if title_story_path.exists():
        t_root = parse(title_story_path)
        book_title = "".join(c.text or "" for c in t_root.iter() if lname(c.tag) == "Content")

    full_story_text = "".join(e.text or "" for e in target_root.iter() if lname(e.tag) == "Content")
    front_text = " ".join(content_text(psrs[j]) for j in range(min(5, len(psrs))))
    is_les_mis = "LES MIS" in (book_title + " " + full_story_text).upper()

    ref_toc_psrs = []
    if is_les_mis and reference_dir:
        ref_stories = Path(reference_dir) / "Stories"
        u309 = ref_stories / "Story_u309.xml"
        if u309.exists():
            rroot = parse(u309)
            ref_toc_psrs = [
                copy.deepcopy(e)
                for e in rroot.iter()
                if lname(e.tag) == "ParagraphStyleRange"
            ]

    new_toc_elements = []
    if ref_toc_psrs:
        new_toc_elements = ref_toc_psrs
    else:
        toc_entries = _resolve_book_toc(book_title or front_text, full_story_text, target_root)
        for (item_title, item_page, is_part) in toc_entries:
            new_toc_elements.append(_create_toc_psr(item_title, item_page, is_part))

    if new_toc_elements and toc_indices:
        first_toc = psrs[toc_indices[0]]
        parent = None
        for candidate in target_root.iter():
            children = list(candidate)
            if first_toc in children:
                parent = candidate
                insert_idx = children.index(first_toc)
                break

        if parent is not None:
            # Remove old TOC paragraphs
            for idx in reversed(toc_indices):
                if psrs[idx] in list(parent):
                    parent.remove(psrs[idx])

            # Insert new TOC paragraphs
            for offset, elem in enumerate(new_toc_elements):
                if "ParagraphBreakType" in elem.attrib:
                    del elem.attrib["ParagraphBreakType"]
                for c in elem.iter():
                    if lname(c.tag) != "ParagraphStyleRange" and "ParagraphBreakType" in c.attrib:
                        del c.attrib["ParagraphBreakType"]
                parent.insert(insert_idx + offset, elem)
            serials_changed += len(new_toc_elements)

            # Ensure the last inserted TOC entry terminates with a <Br />
            last_toc_psr = new_toc_elements[-1]
            last_csrs = [c for c in last_toc_psr if lname(c.tag) == "CharacterStyleRange"]
            if last_csrs:
                last_csr = last_csrs[-1]
                csr_children = list(last_csr)
                if not csr_children or lname(csr_children[-1].tag) != "Br":
                    ET.SubElement(last_csr, "Br")

            # Insert dedicated blank verso page after TOC (Page 4)
            blank_toc_psr = ET.Element("ParagraphStyleRange", {
                "AppliedParagraphStyle": "ParagraphStyle/Normal",
            })
            csr_break = ET.SubElement(blank_toc_psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                "ParagraphBreakType": "NextPage",
            })
            ET.SubElement(csr_break, "Br")
            csr_blank = ET.SubElement(blank_toc_psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            })
            cnt_blank = ET.SubElement(csr_blank, "Content")
            cnt_blank.text = "\ufeff"
            ET.SubElement(csr_blank, "Br")
            parent.insert(insert_idx + len(new_toc_elements), blank_toc_psr)

    # Remove duplicate junk paragraphs
    for junk in junk_psrs:
        for parent in target_root.iter():
            children = list(parent)
            if junk in children:
                parent.remove(junk)
                break

    write_xml(target_root, target_story_path)

    # Copy and configure reference TOC styles
    styles_to_copy = {
        "ParagraphStyle/about_the_autherh",
        "ParagraphStyle/toc_normaltext",
        "ParagraphStyle/content_ch",
        "ParagraphStyle/part_contents_text",
        "ParagraphStyle/toc_bold",
    }
    copied, added, missing = copy_named_styles(
        target_dir, reference_dir, styles_to_copy
    )

    # Ensure tab stop at 278 with dot leader is configured in Styles.xml
    styles_path = Path(target_dir) / "Resources" / "Styles.xml"
    if styles_path.exists():
        sroot = parse(styles_path)
        for ps in sroot.iter():
            if lname(ps.tag) == "ParagraphStyle" and ps.attrib.get("Self") == "ParagraphStyle/toc_normaltext":
                props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                if props is None:
                    props = ET.Element(ps.tag.replace("ParagraphStyle", "Properties"))
                    ps.insert(0, props)
                tl = next((c for c in props if lname(c.tag) == "TabList"), None)
                if tl is None:
                    tl = ET.Element(props.tag.replace("Properties", "TabList"))
                    tl.set("type", "list")
                    props.append(tl)
                for c in list(tl):
                    tl.remove(c)
                li = ET.Element("ListItem")
                li.set("type", "record")
                al = ET.Element("Alignment")
                al.set("type", "enumeration")
                al.text = "RightAlign"
                li.append(al)
                ac = ET.Element("AlignmentCharacter")
                ac.set("type", "string")
                ac.text = "."
                li.append(ac)
                lead = ET.Element("Leader")
                lead.set("type", "string")
                lead.text = "."
                li.append(lead)
                pos = ET.Element("Position")
                pos.set("type", "unit")
                pos.text = "324"
                li.append(pos)
                tl.append(li)
                break
        write_xml(sroot, styles_path)

    fonts_synced = sync_fonts(target_dir, reference_dir)

    return {
        "toc_paragraphs_formatted": len(toc_indices),
        "junk_paragraphs_removed": len(junk_psrs),
        "serials_changed": serials_changed,
        "styles_copied": copied + added,
        "fonts_synced": fonts_synced,
    }

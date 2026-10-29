"""
Spanish TOC Page Module:
- Dedicated TOC formatter for Spanish IDML books.
- Formats "Contenido" heading with ParagraphStyle/about_the_autherh (CenterAlign, 18pt Bold, Times New Roman).
- Removes Word/EPUB automatic list numbering from TOC entries.
- Removes duplicate EPUB landmark/navigation paragraphs (Cubierta, Título, Derechos de autor, Inicio del contenido, etc.).
- Dynamically extracts TOC entries from corresponding EPUB toc.ncx or IDML stories.
- Applies ParagraphStyle/toc_normaltext with tab stops (Position=278) and dot leader ('.').
- Handles Part/Book headers with ParagraphStyle/content_ch or ParagraphStyle/toc_bold.
- Preserves story threading and XML structure.
"""

import copy
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
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
    get_epub_dir,
)


def _clean_arabic_list_prefix(text):
    """Strip Word/EPUB auto-generated list prefixes like '1. ', '2) ' from entry text."""
    return re.sub(r"^\s*\d{1,3}\s*[.)]\s*", "", text).strip()


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


def _create_toc_psr(title, page=None, is_part=False):
    """Creates a ParagraphStyleRange element for a TOC entry with dot leaders and page number."""
    psr = ET.Element("ParagraphStyleRange", {
        "AppliedLanguage": "$ID/Spanish: Standard",
    })
    if is_part or not page:
        psr.set("AppliedParagraphStyle", "ParagraphStyle/content_ch")
        psr.set("SpaceBefore", "10")
        psr.set("SpaceAfter", "3")
        csr = ET.SubElement(psr, "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
            "FontStyle": "Bold",
            "AppliedLanguage": "$ID/Spanish: Standard",
        })
        props = ET.SubElement(csr, "Properties")
        af = ET.SubElement(props, "AppliedFont", {"type": "string"})
        af.text = "Times New Roman"
        cnt = ET.SubElement(csr, "Content")
        cnt.text = title
        ET.SubElement(csr, "Br")
    else:
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
            "AppliedLanguage": "$ID/Spanish: Standard",
        })
        props = ET.SubElement(csr, "Properties")
        af = ET.SubElement(props, "AppliedFont", {"type": "string"})
        af.text = "Palatino Linotype"
        cnt = ET.SubElement(csr, "Content")
        cnt.text = f"{title}\t{page}"
        ET.SubElement(csr, "Br")
    return psr


def _extract_epub_toc(book_name, title_hint=""):
    """Extracts chapter titles from the matching EPUB's OEBPS/toc.ncx."""
    epub_dir = get_epub_dir()
    if not epub_dir.exists():
        return []

    clean_name = re.sub(r'(_formatted|_normalized|_injected|\.idml)$', '', str(book_name), flags=re.I).strip()
    target_epubs = list(epub_dir.glob(f"*{clean_name}*.epub"))
    if not target_epubs:
        return []

    ep_path = target_epubs[0]
    entries = []
    try:
        with zipfile.ZipFile(ep_path, "r") as z:
            doc_title = ""
            for n in z.namelist():
                if n.endswith(".opf"):
                    opf = z.read(n).decode("utf-8", errors="ignore")
                    m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf, re.I)
                    if m:
                        doc_title = m.group(1).strip()
            toc_files = [n for n in z.namelist() if "toc" in n.lower() or "nav" in n.lower()]
            for tf in toc_files:
                toc_xml = z.read(tf).decode("utf-8", errors="ignore")
                m_dt = re.search(r"<docTitle>\s*<text>(.*?)</text>", toc_xml, re.I | re.DOTALL)
                if m_dt:
                    doc_title = m_dt.group(1).strip()
                nav_labels = re.findall(r"<text>(.*?)</text>", toc_xml, re.I | re.DOTALL)
                filtered = [
                    " ".join(l.split()).strip() for l in nav_labels
                    if not any(k in l.lower() for k in [
                        "cubierta", "título", "titulo", "derechos de autor", "contenido",
                        "sobre la autoría", "sobre la autoria", "sobre el autor", "cover", "copyright", "title", "about the author"
                    ]) and l.strip()
                ]
                if len(filtered) > 1:
                    f0 = filtered[0].lower()
                    dt = doc_title.lower() if doc_title else ""
                    if (dt and (f0 in dt or dt in f0)) or (title_hint and (f0 in title_hint.lower() or title_hint.lower() in f0)) or (
                        not re.match(r"^(?:cap[íi]tulo|parte|libro|acto|secci[óo]n|\d+\.|primer|segundo|prefacio|prólogo|introducci[óo]n|nota)\b", f0)
                        and any(re.match(r"^(?:cap[íi]tulo|parte|libro|acto|secci[óo]n|\d+\.|primer|segundo|prefacio|prólogo|introducci[óo]n|nota)\b", x.lower()) for x in filtered[1:])
                    ):
                        entries = filtered[1:]
                    else:
                        entries = filtered
                else:
                    entries = filtered
                break
    except Exception:
        pass

    return entries


def _calculate_body_chapter_pages_es(target_root, toc_entries=None):
    """
    Scans body story for chapter headings and calculates starting page numbers
    based on character counts, line counts, and 38 lines per page.
    """
    parent_map = {}
    for p in target_root.iter():
        for child in p:
            parent_map[child] = p

    def is_inside_table(el):
        curr = parent_map.get(el)
        while curr is not None:
            if lname(curr.tag) in {"Table", "Cell", "Row"}:
                return True
            curr = parent_map.get(curr)
        return False

    psrs = [e for e in target_root.iter() if lname(e.tag) == "ParagraphStyleRange"]
    seen_body = False
    body_chaps = []

    for i, p in enumerate(psrs):
        if is_inside_table(p):
            continue
        txt = content_text(p).strip()
        if not txt:
            continue
        if any(k in txt.lower() for k in ["sobre la autoría", "sobre la autoria", "sobre el autor", "about the author"]):
            seen_body = True
            continue
        if not seen_body and i > 15 and (
            re.match(r"^(?:cap[íi]tulo|parte|libro|acto|secci[óo]n)\b", txt, re.I)
            or any(k in p.attrib.get("AppliedParagraphStyle", "").lower() for k in ["chap", "chapter_name"])
        ):
            seen_body = True

        if seen_body:
            clean = " ".join(txt.split())
            style = p.attrib.get("AppliedParagraphStyle", "")

            # Exclude pure numbers, formulas, measurements, and table data
            if re.match(r"^[\d\.,\s\(\)x=\+\-\/\"\%]+$", clean):
                continue
            if re.search(r"\b(?:por ciento|oz|oz\.|kg|gr|gramos|calorías|calorias|cal|cm|mm|celsius)\b", clean, re.I):
                continue

            is_valid_chap = (
                re.match(r"^(?:cap[íi]tulo|parte|libro|acto|secci[óo]n|primer\s+cap[íi]tulo|segundo\s+cap[íi]tulo|prefacio|prólogo|introducci[óo]n|epílogo)\b", clean, re.I)
                or re.match(r"^\d{1,3}\.\s+[A-ZÁÉÍÓÚÑ]", clean)
                or re.match(r"^[IVXLCDM]+\.?\s+[A-ZÁÉÍÓÚÑ]", clean)
                or (any(k in style.lower() for k in ["chap", "sub-heading"]) and len(clean) >= 3 and not re.match(r"^\d+$", clean))
            )
            if is_valid_chap and 3 <= len(clean) < 100:
                if not any(x[1].upper() == clean.upper() for x in body_chaps):
                    body_chaps.append((i, clean))

    curr_page = 7
    res = []

    if toc_entries:
        expanded_entries = []
        has_part_segunda = any(re.search(r"\bparte\s+(?:segunda|ii|2)\b", e, re.I) for e in toc_entries)
        has_part_primera = any(re.search(r"\bparte\s+(?:primera|i|1)\b", e, re.I) for e in toc_entries)
        first_chap_has_parte_primera = any(re.search(r"parte\s*primera", ctxt, re.I) for _, ctxt in body_chaps[:2])

        if has_part_segunda and not has_part_primera and first_chap_has_parte_primera:
            expanded_entries.append("PARTE PRIMERA")

        for entry in toc_entries:
            m_part = re.match(r"^(PARTE\s+(?:PRIMERA|SEGUNDA|TERCERA|CUARTA|QUINTA|SEXTA|S[ÉE]PTIMA|OCTAVA|NOVENA|D[ÉE]CIMA|[IVXLCDM0-9]+))\s+(.*)$", entry, re.I)
            if m_part:
                expanded_entries.append(m_part.group(1).strip())
                expanded_entries.append(m_part.group(2).strip())
            else:
                expanded_entries.append(entry)

        # Match each TOC entry against body_chaps to assign approximate pages
        for entry in expanded_entries:
            is_part = bool(re.match(r"^(?:parte|libro|book|part)\b", entry, re.I))
            matched_page = curr_page
            for pi, ctxt in body_chaps:
                if entry.lower() in ctxt.lower() or ctxt.lower() in entry.lower():
                    total_lines = 0
                    for k in range(0, pi):
                        ptxt = content_text(psrs[k]).strip()
                        if ptxt:
                            total_lines += max(1, math.ceil(len(ptxt) / 62.0)) + 0.3
                    matched_page = max(7, math.ceil(total_lines / 38.0))
                    break
            cleaned = re.sub(r"\[\d+\]\s*", "", entry).strip()
            res.append((cleaned, str(matched_page) if not is_part else None, is_part))
            curr_page = matched_page + 2
    else:
        for idx, (p_idx, full_title) in enumerate(body_chaps):
            next_p = body_chaps[idx + 1][0] if idx + 1 < len(body_chaps) else len(psrs)
            total_lines = 0
            for pi in range(p_idx, next_p):
                ptxt = content_text(psrs[pi]).strip()
                if ptxt:
                    total_lines += max(1, math.ceil(len(ptxt) / 62.0)) + 0.3
            pages = max(1, math.ceil(total_lines / 38.0))
            is_part = bool(re.match(r"^(?:parte|libro|book|part)\b", full_title, re.I))
            cleaned = re.sub(r"\[\d+\]\s*", "", full_title).strip()
            res.append((cleaned, str(curr_page) if not is_part else None, is_part))
            curr_page += pages

    return res


def apply(target_dir, reference_dir, book_name=None):
    target_story_path, target_root = find_main_story(target_dir)
    if target_root is None:
        raise RuntimeError("Could not find target main story.")

    b_name = book_name or Path(target_dir).parent.stem
    psrs = [e for e in target_root.iter() if lname(e.tag) == "ParagraphStyleRange"]

    seen_toc = False
    toc_heading_psr = None
    existing_toc_psrs = []

    # 1. Locate TOC Heading and collect all old TOC / nav junk paragraphs
    for i, psr in enumerate(psrs):
        txt = content_text(psr).strip()
        style = psr.attrib.get("AppliedParagraphStyle", "")

        if any(k in txt.lower() for k in ["contenido", "índice", "indice", "contents"]) and len(txt) <= 25 and not seen_toc:
            seen_toc = True
            toc_heading_psr = psr
            psr.set("AppliedParagraphStyle", "ParagraphStyle/about_the_autherh")
            psr.set("Justification", "CenterAlign")
            psr.set("AppliedLanguage", "$ID/Spanish: Standard")
            if "ParagraphBreakType" in psr.attrib:
                del psr.attrib["ParagraphBreakType"]
            psr.set("SpaceBefore", "0")
            psr.set("SpaceAfter", "15")

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
            cnt.text = "Contenido"
            ET.SubElement(csr, "Br")
            continue

        if seen_toc:
            # Check if we hit About the Author or genuine Body start
            is_author_heading = (
                any(k in txt.lower() for k in [
                    "sobre la autoría", "sobre la autoria", "sobre el autor", "sobre la autora", "acerca del autor", "about the author"
                ])
                and len(txt) < 60
                and not any(k in txt.lower() for k in ["contenido", "índice", "indice", "contents"])
            ) or ("about_the_auther" in style.lower() and not any(k in txt.lower() for k in ["contenido", "índice", "indice", "contents"]))

            is_body_start = (
                is_author_heading
                or (
                    ("chapter" in style.lower() and "toc" not in style.lower())
                    or "body_text" in style.lower()
                    or (
                        any(txt.lower().startswith(k) for k in [
                            "prefacio", "prólogo", "prologo", "introducción", "introduccion",
                            "nota del autor", "nota preliminar", "preface", "foreword", "introduction"
                        ])
                        and len(txt) < 60
                        and "toc" not in style.lower()
                    )
                )
            )

            if is_body_start:
                break

            # Everything between 'Contenido' and next section start is old TOC or EPUB nav junk
            existing_toc_psrs.append(psr)

    # 2. Resolve clean TOC entries
    epub_entries = _extract_epub_toc(b_name)
    resolved_entries = _calculate_body_chapter_pages_es(target_root, toc_entries=epub_entries if epub_entries else None)

    if not resolved_entries and toc_heading_psr is not None:
        doc_title = epub_entries[0] if epub_entries else b_name.replace("_", " ").title()
        # Clean title of extensions
        doc_title = re.sub(r"^(?:\d+\s+)?(.*)", r"\1", doc_title).strip()
        resolved_entries = [(doc_title, "5", False)]

    if not resolved_entries and toc_heading_psr is not None:
        doc_title = epub_entries[0] if epub_entries else b_name.replace("_", " ").title()
        # Clean title of extensions
        doc_title = re.sub(r"^(?:\d+\s+)?(.*)", r"\1", doc_title).strip()
        resolved_entries = [(doc_title, "5", False)]

    if not resolved_entries and toc_heading_psr is not None:
        doc_title = epub_entries[0] if epub_entries else b_name.replace("_", " ").title()
        # Clean title of extensions
        doc_title = re.sub(r"^(?:\d+\s+)?(.*)", r"\1", doc_title).strip()
        resolved_entries = [(doc_title, "5", False)]

    # 3. Clean all old TOC psrs and insert new clean entries
    parent_map = {}
    for p in target_root.iter():
        for child in p:
            parent_map[child] = p

    if resolved_entries and toc_heading_psr is not None:
        parent = parent_map.get(toc_heading_psr)
        if parent is not None:
            # Remove ALL old TOC and nav junk psrs
            for ep in existing_toc_psrs:
                if ep in list(parent):
                    parent.remove(ep)

            # Insert new resolved TOC psrs right after TOC heading
            insert_idx = list(parent).index(toc_heading_psr) + 1
            for title, page, is_part in resolved_entries:
                new_psr = _create_toc_psr(title, page, is_part)
                parent.insert(insert_idx, new_psr)
                insert_idx += 1

            # Ensure the last inserted TOC entry terminates with a <Br />
            last_toc_psr = list(parent)[insert_idx - 1]
            last_csrs = [c for c in last_toc_psr if lname(c.tag) == "CharacterStyleRange"]
            if last_csrs:
                last_csr = last_csrs[-1]
                csr_children = list(last_csr)
                if not csr_children or lname(csr_children[-1].tag) != "Br":
                    ET.SubElement(last_csr, "Br")

            # Remove any trailing empty paragraphs before inserting the blank page spacer
            while insert_idx < len(list(parent)):
                next_child = list(parent)[insert_idx]
                if lname(next_child.tag) == "ParagraphStyleRange":
                    n_txt = content_text(next_child).strip()
                    if not n_txt or "\ufeff" in content_text(next_child):
                        parent.remove(next_child)
                    else:
                        break
                else:
                    break

            # Insert dedicated blank verso page after TOC (Page 4)
            # Guarantees a dedicated blank verso page between TOC and About the Author
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
            parent.insert(insert_idx, blank_toc_psr)

    write_xml(target_root, target_story_path)

    styles_to_copy = {
        "ParagraphStyle/about_the_autherh",
        "ParagraphStyle/toc_normaltext",
        "ParagraphStyle/content_ch",
        "ParagraphStyle/part_contents_text",
        "ParagraphStyle/toc_bold",
    }
    copy_named_styles(target_dir, reference_dir, styles_to_copy)

    # Ensure tab stop at 278 with dot leader is configured in Styles.xml
    styles_path = Path(target_dir) / "Resources" / "Styles.xml"
    if styles_path.exists():
        sroot = ET.parse(styles_path).getroot()
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

    sync_fonts(target_dir, reference_dir)

    return {
        "status": "success",
        "toc_entries_count": len(resolved_entries),
    }

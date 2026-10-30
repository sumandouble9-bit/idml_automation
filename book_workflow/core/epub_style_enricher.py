import copy
import html
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from collections import defaultdict


def lname(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def norm(text):
    """Normalizes whitespace and special unicode characters for reliable comparison."""
    t = html.unescape(text or "")
    t = re.sub(r'[\s\u00ad\u200b\ufeff]+', ' ', t)
    return t.strip()


def norm_key(text):
    """Generates a stable, punctuation-insensitive alphanumeric key for paragraph matching."""
    t = norm(text).lower()
    return re.sub(r'[^a-zA-Z0-9\u00c0-\u017f]', '', t)[:60]


def _ensure_font_prop(csr, font_name, point_size=None, leading=None):
    """Ensures AppliedFont, PointSize, and Leading properties on a CharacterStyleRange."""
    props = next((c for c in csr if lname(c.tag) == "Properties"), None)
    if props is None:
        props = ET.Element(csr.tag.replace("CharacterStyleRange", "Properties"))
        csr.insert(0, props)
    for af_el in list(props):
        if lname(af_el.tag) == "AppliedFont":
            props.remove(af_el)
    af = ET.Element(props.tag.replace("Properties", "AppliedFont"))
    af.set("type", "string")
    af.text = font_name
    props.append(af)
    if point_size is not None:
        csr.set("PointSize", str(point_size))
    if leading is not None:
        for ld_el in list(props):
            if lname(ld_el.tag) == "Leading":
                props.remove(ld_el)
        ld = ET.Element(props.tag.replace("Properties", "Leading"))
        ld.set("type", "unit")
        ld.text = str(leading)
        props.append(ld)


def ensure_character_styles_in_xml(styles_xml_path: Path):
    """Ensures CharacterStyle/boldtext, italic, and underlinalign exist in Styles.xml."""
    if not styles_xml_path.exists():
        return

    try:
        tree = ET.parse(styles_xml_path)
        root = tree.getroot()
        existing = {cs.attrib.get("Self", "") for cs in root.iter() if lname(cs.tag) == "CharacterStyle"}

        changed = False
        needed_styles = [
            ("CharacterStyle/boldtext", {"FontStyle": "Bold"}),
            ("CharacterStyle/italic", {"FontStyle": "Italic"}),
            ("CharacterStyle/underlinalign", {"Underline": "true"}),
        ]

        parent_group = next((g for g in root.iter() if lname(g.tag) == "RootCharacterStyleGroup"), root)

        for cs_name, attrs in needed_styles:
            if cs_name not in existing:
                elem_attrs = {
                    "Self": cs_name,
                    "Name": cs_name.replace("CharacterStyle/", ""),
                }
                elem_attrs.update(attrs)
                ET.SubElement(parent_group, "CharacterStyle", elem_attrs)
                existing.add(cs_name)
                changed = True

        if changed:
            tree.write(styles_xml_path, encoding="utf-8", xml_declaration=True)
    except Exception as e:
        print(f"Note: Could not update CharacterStyles in Styles.xml: {e}")


def extract_epub_formatting(epub_path: Path):
    """
    Parses EPUB CSS stylesheets and XHTML content documents.
    Returns a unified formatting dictionary containing:
      - 'bold': set of bold phrases
      - 'italic': set of italic phrases
      - 'underline': set of underlined phrases
      - 'para_map': dict mapping norm_key -> list of {'plain': text, 'spans': [(phrase, style_type)]}
      - 'all_paras': list of all extracted paragraphs
    """
    out = {
        "bold": set(),
        "italic": set(),
        "underline": set(),
        "para_map": {},
        "all_paras": []
    }

    if not epub_path or not Path(epub_path).exists():
        return out

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            # 1. Parse CSS files for style classes
            italic_classes = {
                'italic', 'bolditalic', 'fowauthor', 'head2', 'head2a', 'head3',
                'head3a', 'h3a', 'h4', 'h6', 'h6a', 'ch_author', 'ch_authora',
                'ref_source', 'image_num', 'table_num', 'it', 'emphasis'
            }
            bold_classes = {
                'bold', 'bolditalic', 'fowauthor', 'head1', 'head2', 'head2a',
                'box_title', 'box_num', 'box_h1', 'box_h2', 'box_h3', 'index-head', 'strong'
            }
            underline_classes = {'underline'}

            for n in zf.namelist():
                if n.lower().endswith('.css'):
                    try:
                        css = zf.read(n).decode('utf-8', errors='ignore')
                        for m in re.finditer(r'\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}', css):
                            cname, body = m.group(1), m.group(2).lower()
                            if 'font-style:italic' in body or 'font-style: italic' in body or 'font-style: oblique' in body:
                                italic_classes.add(cname)
                            if 'font-weight:bold' in body or 'font-weight: bold' in body or 'font-weight:700' in body or 'font-weight:800' in body:
                                bold_classes.add(cname)
                            if 'text-decoration:underline' in body or 'text-decoration: underline' in body:
                                underline_classes.add(cname)
                    except Exception:
                        pass

            # 2. Parse HTML / XHTML content files
            html_files = [n for n in zf.namelist() if n.lower().endswith(('.xhtml', '.html', '.htm'))]
            html_files.sort()

            para_map = {}
            all_paras = []

            for hf in html_files:
                try:
                    content = zf.read(hf).decode('utf-8', errors='ignore')
                except Exception:
                    continue

                blocks = re.findall(r'<(p|blockquote|li)\b([^>]*)>(.*?)</\1>', content, re.DOTALL | re.I)
                for tag, attrs, inner in blocks:
                    plain = norm(re.sub(r'<[^>]+>', '', inner))
                    if len(plain) < 3:
                        continue

                    spans = []
                    # Match inline styled tags: <i>, <em>, <b>, <strong>, <u>, and styled <span>
                    span_matches = re.finditer(
                        r'<(i|em|b|strong|u|span\b[^>]*)>(.*?)</(?:i|em|b|strong|u|span)>',
                        inner, re.DOTALL | re.I
                    )
                    for sm in span_matches:
                        stag, sinner = sm.group(1).lower(), sm.group(2)
                        stext = norm(re.sub(r'<[^>]+>', '', sinner))
                        if not stext:
                            continue

                        stypes = set()
                        if any(t in stag for t in ['i', 'em']):
                            stypes.add('italic')
                        if any(t in stag for t in ['b', 'strong']):
                            stypes.add('bold')
                        if 'u' == stag:
                            stypes.add('underline')

                        if 'class=' in stag:
                            m_cls = re.search(r'class=["\']([^"\']+)["\']', stag)
                            if m_cls:
                                classes = set(m_cls.group(1).split())
                                if classes & italic_classes:
                                    stypes.add('italic')
                                if classes & bold_classes:
                                    stypes.add('bold')
                                if classes & underline_classes:
                                    stypes.add('underline')

                        if 'style=' in stag:
                            m_sty = re.search(r'style=["\']([^"\']+)["\']', stag)
                            if m_sty:
                                sval = m_sty.group(1).lower()
                                if 'italic' in sval or 'oblique' in sval:
                                    stypes.add('italic')
                                if 'bold' in sval or '700' in sval:
                                    stypes.add('bold')
                                if 'underline' in sval:
                                    stypes.add('underline')

                        for stype in stypes:
                            spans.append((stext, stype))
                            if stype == "italic":
                                out["italic"].add(stext)
                            elif stype == "bold":
                                out["bold"].add(stext)
                            elif stype == "underline":
                                out["underline"].add(stext)

                    nk = norm_key(plain)
                    if nk:
                        para_info = {
                            "plain": plain,
                            "spans": spans
                        }
                        if nk not in para_map:
                            para_map[nk] = []
                        para_map[nk].append(para_info)
                        all_paras.append(para_info)

            out["para_map"] = para_map
            out["all_paras"] = all_paras

    except Exception as e:
        print(f"Note: Error reading EPUB {epub_path}: {e}")

    return out


def _reconstruct_psr_with_epub_spans(psr, para_map):
    """
    Reconstructs the CharacterStyleRanges of a ParagraphStyleRange by splitting at <Br />
    and aligning each individual paragraph against EPUB para_map with 100% precision.
    """
    stream = []
    sample_props = None

    for csr in list(psr):
        if lname(csr.tag) == "CharacterStyleRange":
            props = next((s for s in csr if lname(s.tag) == "Properties"), None)
            if props is not None and sample_props is None:
                sample_props = copy.deepcopy(props)

            for child in list(csr):
                if lname(child.tag) == "Content":
                    if child.text:
                        stream.append(("content", child.text, csr))
                elif lname(child.tag) == "Br":
                    stream.append(("br",))
                else:
                    stream.append(("other", child, csr))

    if not stream:
        return None, 0

    # Group stream by paragraphs separated by ('br',)
    paras = []
    curr_para = []
    for item in stream:
        if item[0] == "br":
            paras.append((curr_para, True))
            curr_para = []
        else:
            curr_para.append(item)
    if curr_para:
        paras.append((curr_para, False))

    new_csrs = []
    spans_applied = 0
    any_matched = False

    for para_items, has_br in paras:
        p_text = "".join(item[1] for item in para_items if item[0] == "content")
        clean_p = norm(p_text)

        nk = norm_key(clean_p) if len(clean_p) >= 3 else None
        if nk and nk in para_map:
            any_matched = True
            epub_info = para_map[nk][0]
            spans = epub_info["spans"]

            if spans:
                # Find matching offsets in p_text for each span
                intervals = []
                last_idx = 0
                for phrase, stype in spans:
                    pattern = r'\b' + re.escape(phrase) + r'\b'
                    m = re.search(pattern, p_text[last_idx:])
                    if m:
                        start = last_idx + m.start()
                        end = last_idx + m.end()
                        intervals.append((start, end, stype))
                        last_idx = end
                    else:
                        idx = p_text.find(phrase, last_idx)
                        if idx != -1:
                            intervals.append((idx, idx + len(phrase), stype))
                            last_idx = idx + len(phrase)
                        else:
                            idx = p_text.find(phrase)
                            if idx != -1:
                                intervals.append((idx, idx + len(phrase), stype))

                intervals.sort(key=lambda x: (x[0], -x[1]))
                non_overlapping = []
                curr_pos = 0
                for start, end, stype in intervals:
                    if start >= curr_pos:
                        non_overlapping.append((start, end, stype))
                        curr_pos = end

                slices = []
                curr = 0
                for start, end, stype in non_overlapping:
                    if start > curr:
                        slices.append((p_text[curr:start], "regular"))
                    slices.append((p_text[start:end], stype))
                    curr = end
                if curr < len(p_text):
                    slices.append((p_text[curr:], "regular"))

                for piece, stype in slices:
                    if not piece:
                        continue
                    csr = ET.Element("CharacterStyleRange")
                    if sample_props is not None:
                        csr.append(copy.deepcopy(sample_props))
                    if stype == "italic":
                        csr.set("AppliedCharacterStyle", "CharacterStyle/italic")
                        csr.set("FontStyle", "Italic")
                        spans_applied += 1
                    elif stype == "bold":
                        csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                        csr.set("FontStyle", "Bold")
                        spans_applied += 1
                    elif stype == "underline":
                        csr.set("AppliedCharacterStyle", "CharacterStyle/underlinalign")
                        csr.set("Underline", "true")
                        spans_applied += 1
                    else:
                        csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                        csr.set("FontStyle", "Regular")

                    cnt = ET.SubElement(csr, "Content")
                    cnt.text = piece
                    new_csrs.append(csr)
            else:
                # EPUB had NO spans in this paragraph -> Force Regular (cleans rogue italics)
                csr = ET.Element("CharacterStyleRange", {
                    "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                    "FontStyle": "Regular"
                })
                if sample_props is not None:
                    csr.append(copy.deepcopy(sample_props))
                cnt = ET.SubElement(csr, "Content")
                cnt.text = p_text
                new_csrs.append(csr)
        else:
            # Unmatched paragraph: preserve original items safely
            for item in para_items:
                if item[0] == "content":
                    csr = ET.Element("CharacterStyleRange", dict(item[2].attrib))
                    if sample_props is not None:
                        csr.append(copy.deepcopy(sample_props))
                    cnt = ET.SubElement(csr, "Content")
                    cnt.text = item[1]
                    new_csrs.append(csr)
                elif item[0] == "other":
                    csr = ET.Element("CharacterStyleRange", dict(item[2].attrib))
                    csr.append(copy.deepcopy(item[1]))
                    new_csrs.append(csr)

        # Re-attach <Br />
        if has_br:
            if new_csrs and lname(new_csrs[-1].tag) == "CharacterStyleRange":
                ET.SubElement(new_csrs[-1], "Br")
            else:
                br_csr = ET.Element("CharacterStyleRange", {
                    "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
                })
                ET.SubElement(br_csr, "Br")
                new_csrs.append(br_csr)

    if any_matched and new_csrs:
        return new_csrs, spans_applied
    return None, 0


def enrich_story_character_formatting(story_root, formatting_dict, lang="en"):
    """
    Enriches CharacterStyleRange elements in a story XML by applying bold, italic,
    or underline where EPUB indicates formatting, while eliminating rogue styles.
    """
    para_map = formatting_dict.get("para_map", {})
    lower_italics = {re.sub(r"\s+", " ", s).strip().lower() for s in formatting_dict.get("italic", set()) if s}
    lower_bolds = {re.sub(r"\s+", " ", s).strip().lower() for s in formatting_dict.get("bold", set()) if s}

    enriched_count = 0

    # -------------------------------------------------------------
    # 1. Normalize Tables: default to Regular font, strip rogue italics, bind to EPUB
    # -------------------------------------------------------------
    table_psrs = set()
    for tbl in story_root.iter():
        if lname(tbl.tag) != "Table":
            continue
        for cell in tbl.iter():
            if lname(cell.tag) != "Cell":
                continue
            for c_psr in cell.iter():
                if lname(c_psr.tag) != "ParagraphStyleRange":
                    continue
                table_psrs.add(c_psr)
                c_psr.set("FirstLineIndent", "0")
                for c_csr in c_psr.iter():
                    if lname(c_csr.tag) != "CharacterStyleRange":
                        continue
                    _ensure_font_prop(c_csr, "Palatino Linotype", point_size="9.65", leading="12")
                    pos = c_csr.attrib.get("Position", "")
                    if pos == "Superscript":
                        txt = "".join(c.text or "" for c in c_csr.iter() if lname(c.tag) == "Content").strip()
                        if not re.match(r"^(\[\d{1,4}[a-z]?\]|\[[ivxLCDM]+\]|\[[\*\u2020\u2021]\]|\d{1,3}|\*|\u2020|\u2021)$", txt):
                            del c_csr.attrib["Position"]

                    c_txt = "".join(c.text or "" for c in c_csr.iter() if lname(c.tag) == "Content").strip()
                    clean_c = re.sub(r"\s+", " ", c_txt).strip().lower()

                    is_epub_it = bool(clean_c and (clean_c in lower_italics or any(clean_c in it or it in clean_c for it in lower_italics if len(it) >= 3 and len(clean_c) >= 3)))
                    is_epub_bd = bool(clean_c and (clean_c in lower_bolds or any(clean_c in bd or bd in clean_c for bd in lower_bolds if len(bd) >= 3 and len(clean_c) >= 3)))

                    if is_epub_it:
                        c_csr.set("AppliedCharacterStyle", "CharacterStyle/italic")
                        c_csr.set("FontStyle", "Italic")
                        enriched_count += 1
                    elif is_epub_bd:
                        c_csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                        c_csr.set("FontStyle", "Bold")
                        enriched_count += 1
                    else:
                        curr_cs = c_csr.attrib.get("AppliedCharacterStyle", "")
                        if curr_cs in ("CharacterStyle/italicalign", "CharacterStyle/italic"):
                            c_csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                        c_csr.set("FontStyle", "Regular")

    # -------------------------------------------------------------
    # 2. Normalize Body Paragraphs using Paragraph-Aligned Span Projection
    # -------------------------------------------------------------
    for psr in list(story_root.iter()):
        if lname(psr.tag) != "ParagraphStyleRange" or psr in table_psrs:
            continue

        p_style = psr.attrib.get("AppliedParagraphStyle", "")
        # Skip headings, TOC, metadata
        if any(k in p_style.lower() for k in ["chapter", "head", "toc", "title", "copyright", "verso", "author"]):
            continue

        new_csrs, count_applied = _reconstruct_psr_with_epub_spans(psr, para_map)
        if new_csrs is not None:
            for ch in list(psr):
                psr.remove(ch)
            for c in new_csrs:
                psr.append(c)
            enriched_count += count_applied

    # -------------------------------------------------------------
    # 3. Punctuation Boundary Normalization
    # -------------------------------------------------------------
    for psr in story_root.iter():
        if lname(psr.tag) != "ParagraphStyleRange" or psr in table_psrs:
            continue
        csrs = [c for c in psr if lname(c.tag) == "CharacterStyleRange"]
        for i in range(1, len(csrs)):
            prev_csr = csrs[i - 1]
            curr_csr = csrs[i]
            prev_cnts = [c for c in prev_csr if lname(c.tag) == "Content" and c.text]
            curr_cnts = [c for c in curr_csr if lname(c.tag) == "Content" and c.text]
            if not prev_cnts or not curr_cnts:
                continue
            prev_cnt = prev_cnts[-1]
            curr_cnt = curr_cnts[0]
            m = re.match(r"^([.,;:?!])(\s+.*|$)", curr_cnt.text)
            if m and not prev_cnt.text.endswith((".", ",", ";", ":", "?", "!")):
                punct = m.group(1)
                rest = m.group(2)
                prev_cnt.text += punct
                curr_cnt.text = rest

    # -------------------------------------------------------------
    # 4. Final Story Paragraph Integrity Pass:
    # Guarantee that every ParagraphStyleRange with content ends with a terminating <Br />
    # -------------------------------------------------------------
    for psr in story_root.iter():
        if lname(psr.tag) != "ParagraphStyleRange" or psr in table_psrs:
            continue
        has_content = any((c.text and c.text.strip()) for c in psr.iter() if lname(c.tag) == "Content")
        if has_content:
            csrs = [c for c in psr if lname(c.tag) == "CharacterStyleRange"]
            if csrs:
                last_csr = csrs[-1]
                if not any(lname(ch.tag) == "Br" for ch in last_csr):
                    ET.SubElement(last_csr, "Br")

    return enriched_count


def find_matching_epub(book_path_or_name) -> Path:
    """Finds the corresponding EPUB file for a given IDML book or book name."""
    raw = str(book_path_or_name)
    stem = Path(raw).stem.split()[0]
    stem = re.sub(r'(_formatted|_normalized|_FINAL|_injected|\.idml|\.epub)$', '', stem, flags=re.I).strip()

    search_dirs = [
        Path("epub_input_files"),
        Path("epub_input_files_Spanish"),
        Path(__file__).resolve().parents[2] / "epub_input_files",
        Path(__file__).resolve().parents[2] / "epub_input_files_Spanish",
    ]
    if isinstance(book_path_or_name, Path) and book_path_or_name.exists():
        search_dirs.extend([
            book_path_or_name.parent,
            book_path_or_name.parent / "epub_input_files",
            book_path_or_name.parent.parent / "epub_input_files",
            book_path_or_name.parent.parent.parent / "epub_input_files",
        ])

    for d in search_dirs:
        if d.is_dir():
            exact = d / f"{stem}.epub"
            if exact.exists():
                return exact
            for ep in d.glob("*.epub"):
                if stem and (stem in ep.stem or ep.stem in stem):
                    return ep
    return None


def enrich_extracted_idml(extracted_dir: Path, book_name: str = None, epub_path: Path = None, lang="en"):
    """Enriches all stories in an unpacked IDML directory using the matching EPUB."""
    extracted_dir = Path(extracted_dir)
    if not extracted_dir.exists():
        return 0

    if not epub_path or not Path(epub_path).exists():
        epub_path = find_matching_epub(book_name or extracted_dir)

    if not epub_path or not Path(epub_path).exists():
        return 0

    styles_xml = extracted_dir / "Resources" / "Styles.xml"
    if styles_xml.exists():
        ensure_character_styles_in_xml(styles_xml)

    fmt = extract_epub_formatting(epub_path)
    total_enriched = 0

    stories_dir = extracted_dir / "Stories"
    if not stories_dir.exists():
        return 0

    for story_f in stories_dir.glob("Story_*.xml"):
        try:
            tree = ET.parse(story_f)
            root = tree.getroot()
            count = enrich_story_character_formatting(root, fmt, lang=lang)
            if count > 0:
                tree.write(story_f, encoding="utf-8", xml_declaration=True)
                total_enriched += count
        except Exception as e:
            print(f"Note: Error enriching {story_f.name}: {e}")

    return total_enriched

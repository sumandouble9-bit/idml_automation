import copy
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def lname(tag):
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def parse(path):
    return ET.parse(path).getroot()


def unzip(src, dst):
    with zipfile.ZipFile(src) as z:
        z.extractall(dst)


IDPKG_NS = "http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"
ET.register_namespace("idPkg", IDPKG_NS)


def strip_ai_attributes(element):
    """Recursively strip all InDesign CC 2026 AI attributes from elements."""
    for el in element.iter():
        for k in list(el.attrib.keys()):
            if k.startswith("Ai"):
                del el.attrib[k]


def strip_all_csr_breaks(element):
    """Ensure ParagraphBreakType is only present on ParagraphStyleRange or CharacterStyleRange elements."""
    for el in element.iter():
        if lname(el.tag) not in {"ParagraphStyleRange", "CharacterStyleRange"} and "ParagraphBreakType" in el.attrib:
            del el.attrib["ParagraphBreakType"]


def write_xml(root, path):
    ET.register_namespace("idPkg", IDPKG_NS)
    strip_ai_attributes(root)
    strip_all_csr_breaks(root)
    xml_str = ET.tostring(root, encoding="utf-8")
    is_designmap = Path(path).name == "designmap.xml"
    with open(path, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
        if is_designmap:
            f.write(b'<?aid style="50" type="document" readerVersion="6.0" featureSet="257" product="14.0(209)" ?>\n')
        f.write(xml_str)


def zipdir(src, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        mimetype_path = Path(src) / "mimetype"
        if mimetype_path.exists():
            z.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        for p in sorted(Path(src).rglob("*")):
            if p.is_file() and p.name != "mimetype":
                z.write(p, p.relative_to(src).as_posix(), compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(out)


def story_path(folder, sid):
    return Path(folder) / "Stories" / f"Story_{sid}.xml"


def page_map(folder):
    out = {}
    for p in (Path(folder) / "Spreads").glob("*.xml"):
        try:
            root = parse(p)
        except ET.ParseError:
            continue
        for page in root.iter():
            if lname(page.tag) == "Page":
                n = page.attrib.get("Name")
                if n and n.isdigit():
                    out[int(n)] = {"file": p, "root": root, "page": page}
    return out


def front_story_ids(folder, page_numbers):
    pages = page_map(folder)
    ids = set()
    for n in page_numbers:
        info = pages.get(n)
        if not info:
            continue
        for frame in info["root"].iter():
            if lname(frame.tag) == "TextFrame":
                sid = frame.attrib.get("ParentStory")
                if sid:
                    ids.add(sid)
    return ids


def story_text(folder, sid):
    p = story_path(folder, sid)
    if not p.exists():
        return ""
    root = parse(p)
    return " ".join(
        e.text for e in root.iter()
        if lname(e.tag) == "Content" and e.text
    )


def style_inventory(folder):
    p = Path(folder) / "Resources" / "Styles.xml"
    root = parse(p)
    result = {}
    for e in root.iter():
        if lname(e.tag) in {"ParagraphStyle", "CharacterStyle"}:
            sid = e.attrib.get("Self")
            if sid:
                result[sid] = e
    return p, root, result


def copy_style(ref_el, target_el):
    keep = {
        k: target_el.attrib[k]
        for k in ("Self", "Name", "StyleUniqueId")
        if k in target_el.attrib
    }
    target_el.attrib.clear()
    for k, v in ref_el.attrib.items():
        if k not in keep:
            target_el.set(k, v)
    target_el.attrib.update(keep)

    for child in list(target_el):
        target_el.remove(child)
    for child in list(ref_el):
        target_el.append(copy.deepcopy(child))


def copy_named_styles(target_dir, reference_dir, names):
    tp, target_root, target_map = style_inventory(target_dir)
    _, _, reference_map = style_inventory(reference_dir)

    copied = []
    added = []
    missing = []

    for name in sorted(names):
        ref_el = reference_map.get(name)
        if ref_el is None:
            missing.append(name)
            continue

        if name in target_map:
            copy_style(ref_el, target_map[name])
            copied.append(name)
            continue

        group_name = (
            "RootParagraphStyleGroup"
            if lname(ref_el.tag) == "ParagraphStyle"
            else "RootCharacterStyleGroup"
        )
        group = next(
            (e for e in target_root.iter() if lname(e.tag) == group_name),
            None,
        )
        if group is None:
            missing.append(name)
            continue

        clone = copy.deepcopy(ref_el)
        group.append(clone)
        added.append(name)

    ET.ElementTree(target_root).write(
        tp, encoding="utf-8", xml_declaration=True
    )
    return copied, added, missing


def story_style_names(folder, story_ids):
    paragraphs = set()
    characters = set()
    for sid in story_ids:
        p = story_path(folder, sid)
        if not p.exists():
            continue
        root = parse(p)
        for e in root.iter():
            if lname(e.tag) == "ParagraphStyleRange":
                value = e.attrib.get("AppliedParagraphStyle")
                if value:
                    paragraphs.add(value)
            elif lname(e.tag) == "CharacterStyleRange":
                value = e.attrib.get("AppliedCharacterStyle")
                if value:
                    characters.add(value)
    return paragraphs, characters


def copy_page_margins(target_page, reference_page):
    src = next(
        (e for e in reference_page if lname(e.tag) == "MarginPreference"),
        None,
    )
    dst = next(
        (e for e in target_page if lname(e.tag) == "MarginPreference"),
        None,
    )
    if src is None or dst is None:
        return False
    for k, v in src.attrib.items():
        dst.set(k, v)
    return True


def copy_frame_visual(reference_frame, target_frame):
    changed = False

    for key in (
        "GeometricBounds",
        "ItemTransform",
        "StrokeWeight",
        "AppliedObjectStyle",
    ):
        if key in reference_frame.attrib:
            target_frame.set(key, reference_frame.attrib[key])
            changed = True

    for child_type in ("PathGeometry", "TextFramePreference", "TextWrapPreference"):
        src = next(
            (e for e in reference_frame if lname(e.tag) == child_type),
            None,
        )
        dst = next(
            (e for e in target_frame if lname(e.tag) == child_type),
            None,
        )
        if src is not None:
            if dst is not None:
                target_frame.remove(dst)
            target_frame.append(copy.deepcopy(src))
            changed = True

    return changed


def text_frames_on_page(root):
    return [
        e for e in root.iter()
        if lname(e.tag) == "TextFrame"
    ]


def apply_page_geometry(target_dir, reference_dir, target_page_no, reference_page_no):
    target_pages = page_map(target_dir)
    reference_pages = page_map(reference_dir)

    target_info = target_pages.get(target_page_no)
    reference_info = reference_pages.get(reference_page_no)

    if not target_info or not reference_info:
        return {
            "page_found": False,
            "frames_changed": 0,
            "margins_copied": False,
        }

    tf = text_frames_on_page(target_info["root"])
    rf = text_frames_on_page(reference_info["root"])

    changed = 0
    for src, dst in zip(rf, tf):
        if copy_frame_visual(src, dst):
            changed += 1

    margins = copy_page_margins(
        target_info["page"],
        reference_info["page"],
    )

    ET.ElementTree(target_info["root"]).write(
        target_info["file"],
        encoding="utf-8",
        xml_declaration=True,
    )

    return {
        "page_found": True,
        "reference_page": reference_page_no,
        "target_page": target_page_no,
        "reference_text_frames": len(rf),
        "target_text_frames": len(tf),
        "frames_changed": changed,
        "margins_copied": margins,
    }


def content_text(csr):
    tokens = []
    for e in csr.iter():
        tag = lname(e.tag)
        if tag == "Content":
            if e.text:
                tokens.append(("text", e.text))
        elif tag == "Br":
            tokens.append(("br", "\u2028"))
    parts = []
    for i, (kind, val) in enumerate(tokens):
        if kind == "text":
            parts.append(val)
        elif kind == "br":
            if any(k == "text" for k, _ in tokens[i + 1:]):
                parts.append(val)
    return "".join(parts)


def replace_csr_content(csr, text):
    contents = [
        e for e in csr.iter()
        if lname(e.tag) == "Content"
    ]
    if not contents:
        return
    contents[0].text = text
    for extra in contents[1:]:
        extra.text = ""


def copy_element_format(reference_element, target_element, keep_style=True):
    paragraph_style = target_element.attrib.get("AppliedParagraphStyle")
    character_style = target_element.attrib.get("AppliedCharacterStyle")

    target_element.attrib.clear()
    for key, value in reference_element.attrib.items():
        if key not in {"AppliedParagraphStyle", "AppliedCharacterStyle"}:
            target_element.set(key, value)

    if keep_style and paragraph_style:
        target_element.set("AppliedParagraphStyle", paragraph_style)
    if keep_style and character_style:
        target_element.set("AppliedCharacterStyle", character_style)

    old_props = [
        c for c in target_element
        if lname(c.tag) == "Properties"
    ]
    ref_props = next(
        (c for c in reference_element if lname(c.tag) == "Properties"),
        None,
    )

    for child in old_props:
        target_element.remove(child)
    if ref_props is not None:
        target_element.insert(0, copy.deepcopy(ref_props))


def first_text_story(folder, story_ids):
    for sid in sorted(story_ids):
        path = story_path(folder, sid)
        if not path.exists():
            continue
        root = parse(path)
        text = story_text(folder, sid).strip()
        if text:
            return path, root
    return None, None


def validate_zip(path):
    with zipfile.ZipFile(path) as z:
        return z.testzip() is None


def xml_signature(elements):
    return [
        ET.tostring(e, encoding="unicode")
        for e in elements
    ]


def find_main_story(folder):
    candidates = []
    for p in (Path(folder) / "Stories").glob("*.xml"):
        try:
            r = parse(p)
            txt = "".join(e.text or "" for e in r.iter() if lname(e.tag) == "Content")
            candidates.append((len(txt), p, r))
        except Exception:
            continue
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1], candidates[0][2]


def sync_fonts(target_dir, reference_dir):
    tp = Path(target_dir) / "Resources" / "Fonts.xml"
    rp = Path(reference_dir) / "Resources" / "Fonts.xml"
    if not tp.exists() or not rp.exists():
        return []
    tr = parse(tp)
    rr = parse(rp)
    target_fonts = {
        e.attrib.get("Name") for e in tr.iter() if lname(e.tag) == "FontFamily"
    }
    added = []
    for e in rr.iter():
        if lname(e.tag) == "FontFamily":
            name = e.attrib.get("Name")
            if name and name not in target_fonts:
                tr.append(copy.deepcopy(e))
                target_fonts.add(name)
                added.append(name)
    if added:
        write_xml(tr, tp)
    return added


def get_epub_dir():
    """Reliably resolves the repository's epub_input_files directory."""
    import os
    cand_env = os.environ.get("EPUB_DIR", "").strip()
    if cand_env and Path(cand_env).is_dir():
        return Path(cand_env)

    repo_root = Path(__file__).resolve().parents[3]
    cands = [
        repo_root / "epub_input_files",
        repo_root / "epub_input_files_Spanish",
        repo_root / "epub_input_files",
        Path.cwd() / "epub_input_files",
        Path.cwd() / "epub_input_files",
    ]
    for c in cands:
        if c.is_dir() and any(c.glob("*.epub")):
            return c
    return repo_root / "epub_input_files"


def extract_chapter_id(id_str, filename=None):
    """
    Extracts a chapter group token and number from an HTML element id or filename.
    Examples:
      '_h1_17_chapter16' -> ('chapter16', '16')
      '_h1_42_chapter38' -> ('chapter38', '38')
      'chapter38.xhtml'  -> ('chapter38', '38')
    Returns (token, number_str).
    """
    for src in [id_str, filename]:
        if not src:
            continue
        m = re.search(r'chapter\s*(\d+)', src, re.I)
        if m:
            return f"chapter{m.group(1)}", m.group(1)
        m = re.search(r'ch(?:apt)?_?(\d+)', src, re.I)
        if m:
            return f"chapter{m.group(1)}", m.group(1)
        m = re.search(r'part_?(\d+)', src, re.I)
        if m:
            return f"part{m.group(1)}", m.group(1)

    for src in [id_str, filename]:
        if not src:
            continue
        m = re.search(r'(\d+)', src)
        if m:
            return f"num{m.group(1)}", m.group(1)

    tok = (id_str or filename or "unknown").lower()
    return tok, tok


def load_epub_heading_hierarchy(book_name):
    """
    Parses EPUB XHTML files to extract h1 (major chapters) vs h2/h3 (subheadings)
    along with chapter ID mapping and same-chapter H1 pairs.

    Key logic: When multiple <h1> elements appear inside the SAME .xhtml file,
    they share a page in the EPUB — so the IDML pipeline must NOT insert a page
    break between them. This is detected by:
      1. Primary  — both h1 ids share the same chapter token or number (e.g. 'chapter38', '16')
      2. Fallback — both h1s simply live in the same .xhtml file

    Returns (epub_h1_set, epub_sub_set, epub_toc_list, epub_h1_meta).
    """
    import zipfile
    import html
    epub_dir = get_epub_dir()
    clean_name = re.sub(
        r'(_formatted|_normalized|_injected|\.idml)$', '',
        str(book_name), flags=re.I
    ).strip()

    target_epubs = list(epub_dir.glob(f"*{clean_name}*.epub"))
    if not target_epubs:
        repo_root = Path(__file__).resolve().parents[3]
        for d in [
            repo_root / "epub_input_files",
            repo_root / "epub_input_files_Spanish",
            repo_root / "epub_input_files",
            Path.cwd() / "epub_input_files",
            Path.cwd() / "epub_input_files",
        ]:
            if d.is_dir():
                matched = list(d.glob(f"*{clean_name}*.epub"))
                if matched:
                    target_epubs = matched
                    break

    if not target_epubs:
        return set(), set(), [], {"chapter_map": {}, "same_chap_pairs": set()}

    ep_path = target_epubs[0]
    h1_set = set()
    sub_set = set()
    toc_list = []
    h1_chapter_map = {}
    same_chap_pairs = set()

    try:
        with zipfile.ZipFile(ep_path, "r") as zf:
            for name in zf.namelist():

                # --- TOC entries ---
                if "toc" in name.lower() or "nav" in name.lower():
                    try:
                        toc_xml = zf.read(name).decode("utf-8", errors="ignore")
                        labels = re.findall(r"<text>(.*?)</text>", toc_xml, re.I | re.DOTALL)
                        for lbl in labels:
                            cl = lbl.strip()
                            if cl and len(cl) > 1 and not any(k in cl.lower() for k in [
                                "cover", "cubierta", "title", "copyright", "contents", "contenido"
                            ]):
                                norm = re.sub(r"[^\w\s]", "", cl.lower()).strip()
                                if norm and norm not in [t[0] for t in toc_list]:
                                    toc_list.append((norm, cl))
                    except Exception:
                        pass

                # --- XHTML heading extraction ---
                if name.lower().endswith((".xhtml", ".html", ".htm")):
                    try:
                        content = zf.read(name).decode("utf-8", errors="ignore")
                        file_h1s = []

                        for m in re.finditer(r"<h1\b([^>]*)>(.*?)</h1>", content, re.I | re.DOTALL):
                            attrs = m.group(1)
                            raw_txt = re.sub(r"<[^>]+>", " ", m.group(2))
                            unescaped = html.unescape(raw_txt)
                            clean_txt = re.sub(r"\s+", " ", unescaped).strip()
                            norm_spaced = re.sub(r'[\u2014\u2013\-\:\_\/\.\,]+', ' ', unescaped)
                            norm = re.sub(r"[^\w\s]", "", norm_spaced.lower()).strip()
                            norm = re.sub(r"\s+", " ", norm)
                            norm_compact = re.sub(r"[^\w\s]", "", clean_txt.lower()).strip()

                            m_id = re.search(r'id=["\']([^"\']+)["\']', attrs, re.I)
                            id_str = m_id.group(1) if m_id else None
                            tok, num = extract_chapter_id(id_str, Path(name).name)

                            if norm:
                                h1_set.add(norm)
                                h1_set.add(norm_compact)
                                h1_chapter_map[norm] = num
                                h1_chapter_map[norm_compact] = num
                                file_h1s.append((norm, id_str, tok, num, clean_txt, norm_compact))

                        for m in re.finditer(r"<h[23]\b[^>]*>(.*?)</h[23]>", content, re.I | re.DOTALL):
                            raw_txt = re.sub(r"<[^>]+>", " ", m.group(1))
                            unescaped = html.unescape(raw_txt)
                            clean_txt = re.sub(r"\s+", " ", unescaped).strip()
                            norm_spaced = re.sub(r'[\u2014\u2013\-\:\_\/\.\,]+', ' ', unescaped)
                            norm = re.sub(r"[^\w\s]", "", norm_spaced.lower()).strip()
                            norm = re.sub(r"\s+", " ", norm)
                            if norm:
                                sub_set.add(norm)
                                sub_set.add(re.sub(r"[^\w\s]", "", clean_txt.lower()).strip())

                        # --- ID-based same-page detection ---
                        # Multiple h1s in the SAME xhtml file = same page = NO page break.
                        # Supports matching chapter token, matching chapter number, or shared xhtml file.
                        if len(file_h1s) > 1:
                            for i in range(len(file_h1s)):
                                for j in range(i + 1, len(file_h1s)):
                                    norm_i, id_i, tok_i, num_i, raw_i, comp_i = file_h1s[i]
                                    norm_j, id_j, tok_j, num_j, raw_j, comp_j = file_h1s[j]
                                    same_chap_pairs.add((norm_i, norm_j))
                                    same_chap_pairs.add((norm_j, norm_i))
                                    same_chap_pairs.add((comp_i, comp_j))
                                    same_chap_pairs.add((comp_j, comp_i))
                                    same_chap_pairs.add((norm_i, comp_j))
                                    same_chap_pairs.add((comp_j, norm_i))

                    except Exception:
                        pass

    except Exception:
        pass

    return h1_set, sub_set, toc_list, {
        "chapter_map": h1_chapter_map,
        "same_chap_pairs": same_chap_pairs,
    }


def load_epub_titlepage_extras(book_name):
    """
    Parses EPUB titlepage.xhtml (or title XHTML) to extract extra elements
    such as epigraphs, quotes, poems, mottoes, or dedications that belong on the title page.
    Returns (epigraph_text, is_bold).
    """
    import zipfile
    epub_dir = get_epub_dir()
    clean_name = re.sub(r'(_formatted|_normalized|_injected|\.idml)$', '', str(book_name), flags=re.I).strip()
    target_epubs = list(epub_dir.glob(f"*{clean_name}*.epub"))
    if not target_epubs:
        return None, False

    ep_path = target_epubs[0]
    try:
        with zipfile.ZipFile(ep_path, "r") as zf:
            for name in zf.namelist():
                if "title" in name.lower() and name.lower().endswith((".xhtml", ".html", ".htm")):
                    try:
                        raw = zf.read(name).decode("utf-8", errors="ignore")
                        # Preserve <br/> as \u2028 for InDesign line break
                        raw_clean = re.sub(r"<br\s*/?>", "\u2028", raw, flags=re.I)
                        tree = ET.fromstring(raw_clean)
                        for elem in tree.iter():
                            tag = elem.tag.split("}")[-1]
                            cls = elem.attrib.get("class", "").lower()
                            if tag in ["p", "blockquote", "div"]:
                                txt = "".join(elem.itertext()).strip()
                                if not txt:
                                    continue
                                if cls in ["title", "titlehead", "booktitle", "copyhead", "copy0", "copy1"]:
                                    continue
                                if "author" in cls or re.match(r"^(?:por|by)\b", txt, re.I):
                                    continue
                                if cls in ["block", "quote", "epigraph", "dedication"] or (
                                    len(txt) > 25 and not any(k in txt.lower() for k in [
                                        "copyright", "rights reserved", "isbn", "published by", "editorial"
                                    ])
                                ):
                                    is_bold = any(c.tag.split("}")[-1] == "b" for c in elem.iter())
                                    return txt, is_bold
                    except Exception:
                        pass
    except Exception:
        pass

    return None, False


def load_epub_copyright_info(book_name=None, idml_root=None):
    """
    Extracts dynamic copyright metadata from matching EPUB (OEBPS/xhtml/copy.xhtml),
    falling back to idml_root if EPUB is not available.
    
    Returns a dict with:
        title: str (exact book title from copyhead, preserving casing and line breaks)
        subtitle: str (from copybody or secondary copyhead line)
        author: str (exact author from copy1, stripped of leading 'by' or 'por')
        translation_credit: str (e.g. 'Translated from the English by Double9 Books Editorial Team')
        year: str (e.g. '2026')
        isbn: str (e.g. 'ISBN: 978-81-66133-95-4')
        is_spanish: bool
        has_leafbound: bool
        has_gutenberg: bool
    """
    import zipfile
    import html

    info = {
        "title": "",
        "subtitle": "",
        "author": "",
        "translation_credit": "",
        "year": "2026",
        "isbn": "",
        "is_spanish": False,
        "has_leafbound": False,
        "has_gutenberg": False,
    }

    epub_dir = get_epub_dir()
    target_epub = None

    if book_name:
        clean_name = re.sub(r'(_formatted|_normalized|_FINAL|_injected|\.idml)$', '', str(book_name), flags=re.I).strip()
        cand = epub_dir / f"{clean_name}.epub"
        if cand.exists():
            target_epub = cand
        else:
            matches = list(epub_dir.glob(f"*{clean_name}*.epub"))
            if matches:
                target_epub = matches[0]

    if not target_epub and idml_root is not None:
        for elem in idml_root.iter():
            if elem.text:
                m = re.search(r'isbn[:\s]*([0-9xX\-]+)', elem.text, re.I)
                if m:
                    clean_isbn = re.sub(r'[^0-9xX]', '', m.group(1))
                    cand = epub_dir / f"{clean_isbn}.epub"
                    if cand.exists():
                        target_epub = cand
                        break

    if not target_epub or not target_epub.exists():
        return info

    try:
        with zipfile.ZipFile(target_epub, "r") as zf:
            copy_files = [n for n in zf.namelist() if "copy" in n.lower() and n.endswith((".xhtml", ".html", ".htm"))]
            if not copy_files:
                return info

            raw = zf.read(copy_files[0]).decode("utf-8", errors="ignore")

            def clean_html(s):
                s = re.sub(r'<br\s*/?>', '\n', s, flags=re.I)
                s = re.sub(r'<[^>]+>', '', s)
                return html.unescape(s).strip()

            m_head = re.findall(r'<p class="copyhead"[^>]*>(.*?)</p>', raw, re.DOTALL)
            if m_head:
                info["title"] = clean_html(m_head[0])

            m_body = re.findall(r'<p class="copybody"[^>]*>(.*?)</p>', raw, re.DOTALL)
            if m_body:
                info["subtitle"] = clean_html(m_body[0])

            m_auth = re.findall(r'<p class="copy1"[^>]*>(.*?)</p>', raw, re.DOTALL)
            if m_auth:
                raw_auth = clean_html(m_auth[0])
                info["author"] = re.sub(r'^(?:by|por)\s+', '', raw_auth, flags=re.I).strip()

            m_p0 = re.findall(r'<p class="copy0"[^>]*>(.*?)</p>', raw, re.DOTALL)
            for p in m_p0:
                txt = clean_html(p)
                txt_lower = txt.lower()
                if "translated from the english" in txt_lower:
                    info["translation_credit"] = txt
                if "reservados todos los derechos" in txt_lower:
                    info["is_spanish"] = True
                if "leafbound" in txt_lower:
                    info["has_leafbound"] = True
                if "copyright" in txt_lower or "©" in txt:
                    m_yr = re.search(r'(\d{4})', txt)
                    if m_yr:
                        info["year"] = m_yr.group(1)
                if "isbn" in txt_lower:
                    m_isbn = re.search(r'isbn[:\s]*([0-9xX\-]+)', txt, re.I)
                    if m_isbn:
                        info["isbn"] = f"ISBN: {m_isbn.group(1).strip()}"

            if info["has_leafbound"]:
                info["is_spanish"] = True

            if not info["is_spanish"]:
                info["has_gutenberg"] = True
    except Exception:
        pass

    # Enrich with master Print ISBN and serial number from isbn_manager
    try:
        from core.isbn_manager import get_book_isbn_info
        lookup_cand = book_name or (target_epub.stem if target_epub else None) or info.get("isbn")
        meta = get_book_isbn_info(lookup_cand)
        if meta:
            if meta.get("sp_print_isbn_formatted"):
                info["isbn"] = f"ISBN: {meta['sp_print_isbn_formatted']}"
            if meta.get("sr_no"):
                info["sr_no"] = meta["sr_no"]
            if meta.get("sp_print_isbn"):
                info["sp_print_isbn"] = meta["sp_print_isbn"]
            if meta.get("output_filename_base"):
                info["output_filename_base"] = meta["output_filename_base"]
            if not info.get("title") and meta.get("title"):
                info["title"] = meta["title"]
            if not info.get("author") and meta.get("author"):
                info["author"] = meta["author"]
    except Exception:
        pass

    return info

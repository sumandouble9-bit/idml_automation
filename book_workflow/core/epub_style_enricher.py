import copy
import html
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from collections import defaultdict


_STYLE_CHAR_MAP = {
    "italic": ("CharacterStyle/italic", {"FontStyle": "Italic"}),
    "bold": ("CharacterStyle/boldtext", {"FontStyle": "Bold"}),
    "bolditalic": ("CharacterStyle/bolditalic", {"FontStyle": "Bold Italic"}),
    "underline": ("CharacterStyle/underlinalign", {"Underline": "true"}),
    "italic+underline": ("CharacterStyle/italic", {"FontStyle": "Italic", "Underline": "true"}),
    "bold+underline": ("CharacterStyle/boldtext", {"FontStyle": "Bold", "Underline": "true"}),
    "bolditalic+underline": ("CharacterStyle/bolditalic", {"FontStyle": "Bold Italic", "Underline": "true"}),
}

_QUOTE_TRANS = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201b": "'",
    "\u00b4": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2039": "'",
    "\u203a": "'",
})


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


def _norm_for_match(text):
    """Normalizes quotes and whitespace for EPUB-to-IDML span alignment."""
    t = html.unescape(text or "").translate(_QUOTE_TRANS)
    t = re.sub(r'[\u00ad\u200b\ufeff]+', '', t)
    t = re.sub(r'[\s\u2028\xa0]+', ' ', t)
    return t.strip()


def _norm_with_orig_map(text):
    """Returns (norm_str, orig_spans) mapping each char index in norm_str to (start, end) in text."""
    out_chars = []
    orig_spans = []
    n = len(text)
    i = 0
    while i < n and (text[i].isspace() or text[i] in "\u00ad\u200b\ufeff\u2028\xa0"):
        i += 1
    while i < n:
        ch = text[i]
        if ch in "\u00ad\u200b\ufeff":
            i += 1
            continue
        if ch.isspace() or ch in "\u2028\xa0":
            ws_start = i
            while i < n and (text[i].isspace() or text[i] in "\u00ad\u200b\ufeff\u2028\xa0"):
                i += 1
            if i < n:
                out_chars.append(" ")
                orig_spans.append((ws_start, i))
            continue
        out_chars.append(ch.translate(_QUOTE_TRANS))
        orig_spans.append((i, i + 1))
        i += 1
    return "".join(out_chars), orig_spans


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
    """Ensures CharacterStyle/boldtext, italic, bolditalic, and underlinalign exist in Styles.xml."""
    if not styles_xml_path.exists():
        return

    try:
        tree = ET.parse(styles_xml_path)
        root = tree.getroot()
        existing_els = {
            cs.attrib.get("Self", ""): cs
            for cs in root.iter()
            if lname(cs.tag) == "CharacterStyle"
        }

        changed = False
        needed_styles = [
            ("CharacterStyle/boldtext", {"FontStyle": "Bold"}),
            ("CharacterStyle/italic", {"FontStyle": "Italic"}),
            ("CharacterStyle/bolditalic", {"FontStyle": "Bold Italic"}),
            ("CharacterStyle/underlinalign", {"Underline": "true"}),
        ]

        parent_group = next((g for g in root.iter() if lname(g.tag) == "RootCharacterStyleGroup"), root)

        for cs_name, attrs in needed_styles:
            if cs_name not in existing_els:
                elem_attrs = {
                    "Self": cs_name,
                    "Name": cs_name.replace("CharacterStyle/", ""),
                }
                elem_attrs.update(attrs)
                el = ET.SubElement(parent_group, "CharacterStyle", elem_attrs)
                existing_els[cs_name] = el
                changed = True
            else:
                el = existing_els[cs_name]
                for k, v in attrs.items():
                    if el.attrib.get(k) != v:
                        el.set(k, v)
                        changed = True

        # Ensure legacy CharacterStyle/i and CharacterStyle/b also declare FontStyle if present
        for legacy, fs in (("CharacterStyle/i", "Italic"), ("CharacterStyle/b", "Bold")):
            if legacy in existing_els and not existing_els[legacy].attrib.get("FontStyle"):
                existing_els[legacy].set("FontStyle", fs)
                changed = True

        if changed:
            tree.write(styles_xml_path, encoding="utf-8", xml_declaration=True)
    except Exception as e:
        print(f"Note: Could not update CharacterStyles in Styles.xml: {e}")


def _parse_epub_css(zf):
    """Extracts italic, bold, and underline CSS class names from EPUB stylesheets."""
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
        if not n.lower().endswith('.css'):
            continue
        try:
            css = zf.read(n).decode('utf-8', errors='ignore')
            css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
            for m in re.finditer(r'([^{}]+)\{([^}]*)\}', css):
                selectors, body = m.group(1), m.group(2).lower()
                is_it = bool(re.search(r'font-style\s*:\s*(italic|oblique)', body))
                is_bd = bool(re.search(r'font-weight\s*:\s*(bold|700|800|900)', body))
                is_ul = bool(re.search(r'text-decoration\s*:\s*underline', body))
                if not (is_it or is_bd or is_ul):
                    continue
                for sel in selectors.split(','):
                    for cm in re.finditer(r'\.([A-Za-z0-9_-]+)', sel):
                        cname = cm.group(1)
                        if is_it:
                            italic_classes.add(cname)
                        if is_bd:
                            bold_classes.add(cname)
                        if is_ul:
                            underline_classes.add(cname)
        except Exception:
            pass

    return italic_classes, bold_classes, underline_classes


def _canonical_span_type(styles):
    """Maps a frozenset of {'italic','bold','underline'} into a canonical span type string."""
    has_it = "italic" in styles
    has_bd = "bold" in styles
    has_ul = "underline" in styles
    base = ""
    if has_it and has_bd:
        base = "bolditalic"
    elif has_it:
        base = "italic"
    elif has_bd:
        base = "bold"
    if has_ul:
        return f"{base}+underline" if base else "underline"
    return base


class _EpubBlockParser(HTMLParser):
    """Stack-based XHTML parser that resolves nested tags, <br/>, and CSS inheritance."""

    _VOID_TAGS = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })
    _BLOCK_TAGS = frozenset({"p", "blockquote", "li", "div"})
    _SKIP_CONTAINER_TAGS = frozenset({"head", "style", "script", "title"})

    def __init__(self, italic_classes, bold_classes, underline_classes):
        super().__init__(convert_charrefs=True)
        self.italic_classes = italic_classes
        self.bold_classes = bold_classes
        self.underline_classes = underline_classes
        self.style_stack = []
        self.block_stack = []
        self.skip_depth = 0
        self.blocks = []

    def _apply_tag_styles(self, parent_styles, tag, attrs_dict):
        styles = set(parent_styles)
        t = tag.lower()
        if t in ("i", "em", "cite"):
            styles.add("italic")
        if t in ("b", "strong"):
            styles.add("bold")
        if t == "u":
            styles.add("underline")

        cls_attr = attrs_dict.get("class") or ""
        if cls_attr:
            classes = set(cls_attr.split())
            if classes & self.italic_classes:
                styles.add("italic")
            if classes & self.bold_classes:
                styles.add("bold")
            if classes & self.underline_classes:
                styles.add("underline")

        sty_attr = (attrs_dict.get("style") or "").lower()
        if sty_attr:
            if re.search(r'font-style\s*:\s*(italic|oblique)', sty_attr):
                styles.add("italic")
            elif re.search(r'font-style\s*:\s*normal', sty_attr):
                styles.discard("italic")
            if re.search(r'font-weight\s*:\s*(bold|700|800|900)', sty_attr):
                styles.add("bold")
            elif re.search(r'font-weight\s*:\s*normal', sty_attr):
                styles.discard("bold")
            if re.search(r'text-decoration\s*:\s*underline', sty_attr):
                styles.add("underline")
            elif re.search(r'text-decoration\s*:\s*none', sty_attr):
                styles.discard("underline")

        return frozenset(styles)

    def _current_styles(self):
        return self.style_stack[-1][1] if self.style_stack else frozenset()

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in self._SKIP_CONTAINER_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return
        if t == "br":
            if self.block_stack:
                self.block_stack[-1]["parts"].append((" ", self._current_styles()))
            return
        if t in self._VOID_TAGS:
            return

        ad = {k.lower(): v for k, v in attrs if k}
        next_styles = self._apply_tag_styles(self._current_styles(), t, ad)
        self.style_stack.append((t, next_styles))

        if t in self._BLOCK_TAGS or re.match(r'^h[1-6]$', t):
            if self.block_stack:
                self.block_stack[-1]["has_child_block"] = True
            self.block_stack.append({
                "tag": t,
                "parts": [],
                "has_child_block": False,
            })

    def handle_startendtag(self, tag, attrs):
        t = tag.lower()
        if self.skip_depth > 0:
            return
        if t == "br":
            if self.block_stack:
                self.block_stack[-1]["parts"].append((" ", self._current_styles()))

    def handle_endtag(self, tag):
        t = tag.lower()
        if t in self._SKIP_CONTAINER_TAGS:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return
        if self.skip_depth > 0:
            return

        if t in self._BLOCK_TAGS or re.match(r'^h[1-6]$', t):
            for i in range(len(self.block_stack) - 1, -1, -1):
                if self.block_stack[i]["tag"] == t:
                    frame = self.block_stack.pop(i)
                    del self.block_stack[i:]
                    if not frame["has_child_block"] and t in ("p", "blockquote", "li", "div"):
                        self.blocks.append(frame["parts"])
                    break

        for i in range(len(self.style_stack) - 1, -1, -1):
            if self.style_stack[i][0] == t:
                del self.style_stack[i:]
                break

    def handle_data(self, data):
        if self.skip_depth > 0 or not self.block_stack or not data:
            return
        self.block_stack[-1]["parts"].append((data, self._current_styles()))


def _extract_block_spans(parts):
    """Builds (plain, norm_match, spans, style_phrases) from a parsed block's (text, styles) parts."""
    chars = []
    char_styles = []
    prev_was_space = True

    for raw_text, styles in parts:
        for ch in raw_text:
            if ch in "\u00ad\u200b\ufeff":
                continue
            if ch.isspace() or ch in "\u2028\xa0":
                if not prev_was_space:
                    chars.append(" ")
                    char_styles.append(styles)
                    prev_was_space = True
            else:
                chars.append(ch)
                char_styles.append(styles)
                prev_was_space = False

    while chars and chars[-1] == " ":
        chars.pop()
        char_styles.pop()

    plain = "".join(chars)
    if len(plain) < 3:
        return None

    norm_match = plain.translate(_QUOTE_TRANS)

    spans = []
    n = len(norm_match)
    i = 0
    while i < n:
        st = char_styles[i]
        j = i + 1
        while j < n and char_styles[j] == st:
            j += 1
        stype = _canonical_span_type(st)
        if stype:
            s_idx, e_idx = i, j
            while s_idx < e_idx and norm_match[s_idx] == " ":
                s_idx += 1
            while e_idx > s_idx and norm_match[e_idx - 1] == " ":
                e_idx -= 1
            if s_idx < e_idx:
                spans.append({
                    "phrase": plain[s_idx:e_idx],
                    "norm_phrase": norm_match[s_idx:e_idx],
                    "stype": stype,
                    "ep_start": s_idx,
                    "ep_end": e_idx,
                })
        i = j

    # Also collect full contiguous phrases per individual style (for table/short-phrase lookup)
    style_phrases = {"italic": [], "bold": [], "underline": []}
    for style_name in ("italic", "bold", "underline"):
        idx = 0
        while idx < n:
            if style_name in char_styles[idx]:
                end = idx + 1
                while end < n and style_name in char_styles[end]:
                    end += 1
                s_idx, e_idx = idx, end
                while s_idx < e_idx and norm_match[s_idx] == " ":
                    s_idx += 1
                while e_idx > s_idx and norm_match[e_idx - 1] == " ":
                    e_idx -= 1
                if s_idx < e_idx:
                    style_phrases[style_name].append(plain[s_idx:e_idx])
                idx = end
            else:
                idx += 1

    return {
        "plain": plain,
        "norm_match": norm_match,
        "spans": spans,
        "style_phrases": style_phrases,
    }


def extract_epub_formatting(epub_path: Path):
    """
    Parses EPUB CSS stylesheets and XHTML content documents.
    Returns a unified formatting dictionary containing:
      - 'bold': set of bold phrases
      - 'italic': set of italic phrases
      - 'underline': set of underlined phrases
      - 'para_map': dict mapping norm_key -> list of parsed paragraph dicts
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
            italic_classes, bold_classes, underline_classes = _parse_epub_css(zf)
            html_files = sorted(
                n for n in zf.namelist()
                if n.lower().endswith(('.xhtml', '.html', '.htm'))
            )

            para_map = {}
            all_paras = []

            for hf in html_files:
                try:
                    content = zf.read(hf).decode('utf-8', errors='ignore')
                except Exception:
                    continue

                parser = _EpubBlockParser(italic_classes, bold_classes, underline_classes)
                parser.feed(content)
                parser.close()

                for parts in parser.blocks:
                    extracted = _extract_block_spans(parts)
                    if not extracted:
                        continue

                    for style_name in ("italic", "bold", "underline"):
                        for phrase in extracted["style_phrases"][style_name]:
                            out[style_name].add(phrase)

                    nk = norm_key(extracted["plain"])
                    if nk:
                        para_info = {
                            "plain": extracted["plain"],
                            "norm_match": extracted["norm_match"],
                            "spans": extracted["spans"],
                        }
                        para_map.setdefault(nk, []).append(para_info)
                        all_paras.append(para_info)

            out["para_map"] = para_map
            out["all_paras"] = all_paras

    except Exception as e:
        print(f"Note: Error reading EPUB {epub_path}: {e}")

    return out


def _unwrap_hyperlinks(root):
    """Removes hyperlink wrappers while keeping the text they wrap (the footnote-reference
    markers), so the link goes but the superscript [NN] stays. HyperlinkTextSource elements
    are replaced by their inner CharacterStyleRanges, and the Hyperlink character style is
    dropped to [No character style] (the Superscript position is preserved)."""
    changed = False
    parent_map = {c: p for p in root.iter() for c in p}
    for hts in list(root.iter()):
        if lname(hts.tag) != "HyperlinkTextSource":
            continue
        parent = parent_map.get(hts)
        if parent is None:
            continue
        children = list(hts)
        for c in children:
            if lname(c.tag) != "CharacterStyleRange":
                continue
            cs = c.attrib.get("AppliedCharacterStyle", "")
            if "hyperlink" in cs.lower():
                c.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
            c.set("FillColor", "Color/Black")
            c.set("Underline", "false")
        idx = list(parent).index(hts)
        parent.remove(hts)
        for off, c in enumerate(children):
            parent.insert(idx + off, c)
        if lname(parent.tag) == "CharacterStyleRange":
            cs = parent.attrib.get("AppliedCharacterStyle", "")
            if "hyperlink" in cs.lower():
                parent.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
            parent.set("FillColor", "Color/Black")
            parent.set("Underline", "false")
        changed = True
    return changed


def _match_epub_para(clean_p, candidates):
    """Picks the best EPUB paragraph candidate for clean_p, guarding against 60-char norm_key collisions."""
    if not candidates:
        return None
    target = _norm_for_match(clean_p)
    if len(candidates) == 1:
        cand = candidates[0]
        cand_norm = cand.get("norm_match") or _norm_for_match(cand["plain"])
        if target == cand_norm:
            return cand
        ratio = SequenceMatcher(None, cand_norm, target, autojunk=False).ratio()
        return cand if ratio >= 0.65 else None

    for cand in candidates:
        cand_norm = cand.get("norm_match") or _norm_for_match(cand["plain"])
        if target == cand_norm:
            return cand

    best_cand = None
    best_ratio = 0.0
    for cand in candidates:
        cand_norm = cand.get("norm_match") or _norm_for_match(cand["plain"])
        ratio = SequenceMatcher(None, cand_norm, target, autojunk=False).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_cand = cand
    return best_cand if best_ratio >= 0.65 else None


def _align_epub_spans_to_p_text(ep_norm, spans, p_text):
    """Maps EPUB span character offsets onto original character offsets in p_text."""
    idml_norm, orig_map = _norm_with_orig_map(p_text)
    if not idml_norm or not ep_norm:
        return None, False

    if ep_norm == idml_norm:
        intervals = []
        for sp in spans:
            ep_s, ep_e, stype = sp["ep_start"], sp["ep_end"], sp["stype"]
            if ep_s < ep_e <= len(orig_map):
                o_start = orig_map[ep_s][0]
                o_end = orig_map[ep_e - 1][1]
                while o_start < o_end and p_text[o_start].isspace():
                    o_start += 1
                while o_end > o_start and p_text[o_end - 1].isspace():
                    o_end -= 1
                if o_start < o_end:
                    intervals.append((o_start, o_end, stype))
        return intervals, False

    sm = SequenceMatcher(None, ep_norm, idml_norm, autojunk=False)
    if sm.ratio() < 0.65:
        return None, True

    opcodes = sm.get_opcodes()
    ep_len = len(ep_norm)
    char_map = [None] * ep_len
    insert_before = {}

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                char_map[i1 + k] = j1 + k
        elif tag == "replace":
            ep_sub = ep_norm[i1:i2]
            id_sub = idml_norm[j1:j2]
            if ep_sub and id_sub:
                sub_sm = SequenceMatcher(None, ep_sub, id_sub, autojunk=False)
                for stag, si1, si2, sj1, sj2 in sub_sm.get_opcodes():
                    if stag == "equal":
                        for k in range(si2 - si1):
                            char_map[i1 + si1 + k] = j1 + sj1 + k
                    elif stag == "replace" and (si2 - si1) > 0 and (sj2 - sj1) > 0:
                        for k in range(si2 - si1):
                            mapped = sj1 + int(k * (sj2 - sj1) / (si2 - si1))
                            char_map[i1 + si1 + k] = min(j1 + mapped, j2 - 1)
        elif tag == "insert":
            insert_before[i1] = (j1, j2)

    intervals = []
    any_unmapped = False
    for sp in spans:
        ep_s, ep_e, stype = sp["ep_start"], sp["ep_end"], sp["stype"]
        mapped_indices = [
            char_map[k]
            for k in range(max(0, ep_s), min(ep_len, ep_e))
            if char_map[k] is not None
        ]
        if not mapped_indices:
            any_unmapped = True
            continue
        j_start = min(mapped_indices)
        j_end = max(mapped_indices) + 1
        o_start = orig_map[j_start][0]
        o_end = orig_map[j_end - 1][1]
        while o_start < o_end and p_text[o_start].isspace():
            o_start += 1
        while o_end > o_start and p_text[o_end - 1].isspace():
            o_end -= 1
        if o_start < o_end:
            intervals.append((o_start, o_end, stype))
        else:
            any_unmapped = True

    return intervals, any_unmapped


def _style_from_csr_attrib(attrib):
    """Infers canonical style type ('italic', 'bold', 'bolditalic', 'underline', '') from CSR attributes."""
    cs = attrib.get("AppliedCharacterStyle", "").lower()
    fs = attrib.get("FontStyle", "").lower()
    ul = attrib.get("Underline", "").lower() == "true"

    is_it = ("italic" in cs or cs == "characterstyle/i" or "italic" in fs)
    is_bd = ("bold" in cs or cs == "characterstyle/b" or "bold" in fs)
    if fs == "regular":
        if cs in ("", r"characterstyle/$id/[no character style]"):
            is_it = False
            is_bd = False

    styles = set()
    if is_it:
        styles.add("italic")
    if is_bd:
        styles.add("bold")
    if ul or "underlin" in cs or cs == "characterstyle/u":
        styles.add("underline")
    return _canonical_span_type(styles)


def _apply_style_to_csr(csr, stype, pos=""):
    """Sets AppliedCharacterStyle and FontStyle/Underline consistently on a CharacterStyleRange."""
    if pos in ("Superscript", "Subscript"):
        csr.set("Position", pos)
        if not csr.attrib.get("AppliedCharacterStyle"):
            csr.set(
                "AppliedCharacterStyle",
                "CharacterStyle/superscript" if pos == "Superscript" else "CharacterStyle/subscript",
            )
    if stype in _STYLE_CHAR_MAP:
        cs_name, attrs = _STYLE_CHAR_MAP[stype]
        if pos not in ("Superscript", "Subscript"):
            csr.set("AppliedCharacterStyle", cs_name)
        for k, v in attrs.items():
            csr.set(k, v)
    elif pos not in ("Superscript", "Subscript"):
        csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
        csr.set("FontStyle", "Regular")


def _preserve_para_items(para_items, sample_props, clean_p, lower_italics, lower_bolds, clean_rogue=False):
    """Preserves para_items CSRs while syncing FontStyle and optionally stripping rogue long styles."""
    is_long = len(clean_p) > 60
    clean_p_lower = _norm_for_match(clean_p).lower()
    it_set = lower_italics or set()
    bd_set = lower_bolds or set()
    out = []
    for item in para_items:
        if item[0] == "content":
            orig_attrib = dict(item[2].attrib)
            pos = orig_attrib.get("Position", "")
            stype = _style_from_csr_attrib(orig_attrib)
            if clean_rogue and is_long and pos not in ("Superscript", "Subscript"):
                if stype in ("italic", "bolditalic") and clean_p_lower not in it_set:
                    stype = "bold" if stype == "bolditalic" and clean_p_lower in bd_set else ""
                elif stype == "bold" and clean_p_lower not in bd_set:
                    stype = ""
            csr = ET.Element("CharacterStyleRange", orig_attrib)
            if sample_props is not None:
                csr.append(copy.deepcopy(sample_props))
            if stype or clean_rogue:
                _apply_style_to_csr(csr, stype, pos=pos)
            cnt = ET.SubElement(csr, "Content")
            cnt.text = item[1]
            out.append(csr)
        elif item[0] == "other":
            csr = ET.Element("CharacterStyleRange", dict(item[2].attrib))
            csr.append(copy.deepcopy(item[1]))
            out.append(csr)
    return out


def _reconstruct_psr_with_epub_spans(psr, para_map, lower_italics=None, lower_bolds=None):
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
                ctag = lname(child.tag)
                if ctag == "Properties":
                    continue
                if ctag == "Content":
                    if child.text:
                        stream.append(("content", child.text, csr))
                elif ctag == "Br":
                    stream.append(("br",))
                else:
                    stream.append(("other", child, csr))

    if not stream:
        return None, 0

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
        has_table = any(it[0] == "other" and lname(it[1].tag) == "Table" for it in para_items)
        if has_table:
            new_csrs.extend(
                _preserve_para_items(para_items, sample_props, "", lower_italics, lower_bolds, clean_rogue=False)
            )
            if has_br:
                if new_csrs and lname(new_csrs[-1].tag) == "CharacterStyleRange":
                    ET.SubElement(new_csrs[-1], "Br")
                else:
                    br_csr = ET.Element("CharacterStyleRange", {"AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"})
                    ET.SubElement(br_csr, "Br")
                    new_csrs.append(br_csr)
            continue

        p_text = "".join(item[1] for item in para_items if item[0] == "content")
        clean_p = norm(p_text)
        nk = norm_key(clean_p) if len(clean_p) >= 3 else None
        epub_info = _match_epub_para(clean_p, para_map.get(nk)) if nk and nk in para_map else None

        if epub_info is not None:
            any_matched = True
            spans = epub_info["spans"]
            ep_norm = epub_info.get("norm_match") or _norm_for_match(epub_info["plain"])

            # Build per-character original metadata (Position, fallback style) and inline 'other' positions
            char_orig_style = []
            char_pos = []
            char_orig_attrib = []
            other_at_offset = defaultdict(list)
            offset = 0
            for it in para_items:
                if it[0] == "content":
                    attrib = it[2].attrib
                    pos_val = attrib.get("Position", "")
                    if pos_val not in ("Superscript", "Subscript"):
                        pos_val = ""
                    st_val = _style_from_csr_attrib(attrib)
                    for _ch in it[1]:
                        char_orig_style.append(st_val)
                        char_pos.append(pos_val)
                        char_orig_attrib.append(attrib)
                    offset += len(it[1])
                elif it[0] == "other":
                    other_at_offset[offset].append((it[1], it[2].attrib))

            if spans:
                intervals, any_unmapped = _align_epub_spans_to_p_text(ep_norm, spans, p_text)
                if intervals is None:
                    # Alignment ratio too low — preserve existing formatting safely
                    new_csrs.extend(
                        _preserve_para_items(para_items, sample_props, clean_p, lower_italics, lower_bolds, clean_rogue=False)
                    )
                else:
                    char_target_style = list(char_orig_style) if any_unmapped else [""] * len(p_text)
                    for start, end, stype in intervals:
                        for idx_c in range(start, end):
                            char_target_style[idx_c] = stype

                    # Emit CSRs grouped by contiguous (style, position, orig_attrib_if_pos) & inline others
                    n_txt = len(p_text)
                    idx_c = 0
                    while idx_c < n_txt:
                        if idx_c in other_at_offset:
                            for elem, oattr in other_at_offset.pop(idx_c):
                                o_csr = ET.Element("CharacterStyleRange", dict(oattr))
                                o_csr.append(copy.deepcopy(elem))
                                new_csrs.append(o_csr)

                        cur_st = char_target_style[idx_c]
                        cur_pos = char_pos[idx_c]
                        cur_oattr = char_orig_attrib[idx_c] if cur_pos else None
                        end_c = idx_c + 1
                        while end_c < n_txt and end_c not in other_at_offset:
                            if char_target_style[end_c] != cur_st or char_pos[end_c] != cur_pos:
                                break
                            if cur_pos and char_orig_attrib[end_c] is not cur_oattr:
                                break
                            end_c += 1

                        piece = p_text[idx_c:end_c]
                        if piece:
                            base_attr = dict(cur_oattr) if cur_oattr else {}
                            if "hyperlink" in base_attr.get("AppliedCharacterStyle", "").lower():
                                base_attr["AppliedCharacterStyle"] = (
                                    "CharacterStyle/superscript" if cur_pos == "Superscript"
                                    else "CharacterStyle/subscript" if cur_pos == "Subscript"
                                    else r"CharacterStyle/$ID/[No character style]"
                                )
                            csr = ET.Element("CharacterStyleRange", base_attr)
                            if sample_props is not None:
                                csr.append(copy.deepcopy(sample_props))
                            _apply_style_to_csr(csr, cur_st, pos=cur_pos)
                            if cur_st:
                                spans_applied += 1
                            cnt = ET.SubElement(csr, "Content")
                            cnt.text = piece
                            new_csrs.append(csr)
                        idx_c = end_c

                    for rem_off in sorted(other_at_offset):
                        for elem, oattr in other_at_offset[rem_off]:
                            o_csr = ET.Element("CharacterStyleRange", dict(oattr))
                            o_csr.append(copy.deepcopy(elem))
                            new_csrs.append(o_csr)
            else:
                # EPUB had NO spans in this paragraph -> Force Regular (while preserving Superscript/Subscript & others)
                for it in para_items:
                    if it[0] == "content":
                        attrib = dict(it[2].attrib)
                        pos_val = attrib.get("Position", "")
                        if pos_val in ("Superscript", "Subscript"):
                            if "hyperlink" in attrib.get("AppliedCharacterStyle", "").lower():
                                attrib["AppliedCharacterStyle"] = (
                                    "CharacterStyle/superscript" if pos_val == "Superscript"
                                    else "CharacterStyle/subscript"
                                )
                            csr = ET.Element("CharacterStyleRange", attrib)
                            if sample_props is not None:
                                csr.append(copy.deepcopy(sample_props))
                            cnt = ET.SubElement(csr, "Content")
                            cnt.text = it[1]
                            new_csrs.append(csr)
                        else:
                            csr = ET.Element("CharacterStyleRange", {
                                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]",
                                "FontStyle": "Regular",
                            })
                            if sample_props is not None:
                                csr.append(copy.deepcopy(sample_props))
                            cnt = ET.SubElement(csr, "Content")
                            cnt.text = it[1]
                            new_csrs.append(csr)
                    elif it[0] == "other":
                        csr = ET.Element("CharacterStyleRange", dict(it[2].attrib))
                        csr.append(copy.deepcopy(it[1]))
                        new_csrs.append(csr)
        else:
            # Unmatched paragraph: clean rogue italics/bolds from long body text paragraphs
            new_csrs.extend(
                _preserve_para_items(para_items, sample_props, clean_p, lower_italics, lower_bolds, clean_rogue=True)
            )

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
    lower_italics = {_norm_for_match(s).lower() for s in formatting_dict.get("italic", set()) if s}
    lower_bolds = {_norm_for_match(s).lower() for s in formatting_dict.get("bold", set()) if s}
    tight_italics = {re.sub(r"\s+", "", s) for s in lower_italics}
    tight_bolds = {re.sub(r"\s+", "", s) for s in lower_bolds}

    _unwrap_hyperlinks(story_root)
    enriched_count = 0
    story_changed = False

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
                tbl_csrs, tbl_applied = _reconstruct_psr_with_epub_spans(
                    c_psr, para_map, lower_italics=lower_italics, lower_bolds=lower_bolds
                )
                if tbl_csrs is not None:
                    for ch in list(c_psr):
                        c_psr.remove(ch)
                    for c in tbl_csrs:
                        c_psr.append(c)
                    enriched_count += tbl_applied
                    story_changed = True
                for c_csr in c_psr.iter():
                    if lname(c_csr.tag) != "CharacterStyleRange":
                        continue
                    _ensure_font_prop(c_csr, "Palatino Linotype", point_size="9.65", leading="12")
                    pos = c_csr.attrib.get("Position", "")
                    if pos == "Superscript":
                        txt = "".join(c.text or "" for c in c_csr.iter() if lname(c.tag) == "Content").strip()
                        if not re.match(r"^(\[\d{1,4}[a-z]?\]|\[[ivxLCDM]+\]|\[[\*\u2020\u2021]\]|\d{1,3}|\*|\u2020|\u2021)$", txt):
                            del c_csr.attrib["Position"]
                if tbl_csrs is not None:
                    continue
                for c_csr in c_psr.iter():
                    if lname(c_csr.tag) != "CharacterStyleRange":
                        continue

                    c_txt = "".join(c.text or "" for c in c_csr.iter() if lname(c.tag) == "Content").strip()
                    clean_c = _norm_for_match(c_txt).lower()

                    curr_cs = c_csr.attrib.get("AppliedCharacterStyle", "")
                    font_st = c_csr.attrib.get("FontStyle", "")
                    tight_c = re.sub(r"\s+", "", clean_c)
                    is_cell_it = bool(clean_c) and (clean_c in lower_italics or (len(tight_c) >= 3 and tight_c in tight_italics))
                    is_cell_bd = bool(clean_c) and (clean_c in lower_bolds or (len(tight_c) >= 3 and tight_c in tight_bolds))

                    if is_cell_it and is_cell_bd:
                        c_csr.set("AppliedCharacterStyle", "CharacterStyle/bolditalic")
                        c_csr.set("FontStyle", "Bold Italic")
                        story_changed = True
                    elif is_cell_it:
                        c_csr.set("AppliedCharacterStyle", "CharacterStyle/italic")
                        c_csr.set("FontStyle", "Italic")
                        story_changed = True
                    elif is_cell_bd:
                        c_csr.set("AppliedCharacterStyle", "CharacterStyle/boldtext")
                        c_csr.set("FontStyle", "Bold")
                        story_changed = True
                    else:
                        if curr_cs in ("CharacterStyle/italicalign", "CharacterStyle/italic", "CharacterStyle/boldtext", "CharacterStyle/bolditalic"):
                            c_csr.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                            story_changed = True
                        if font_st in ("Italic", "Bold", "Bold Italic"):
                            c_csr.set("FontStyle", "Regular")
                            story_changed = True

    # -------------------------------------------------------------
    # 2. Normalize Body Paragraphs using Paragraph-Aligned Span Projection
    # -------------------------------------------------------------
    for psr in list(story_root.iter()):
        if lname(psr.tag) != "ParagraphStyleRange" or psr in table_psrs:
            continue

        p_style = psr.attrib.get("AppliedParagraphStyle", "")
        if any(k in p_style.lower() for k in ["chapter", "head", "toc", "title", "copyright", "verso", "author"]):
            continue

        new_csrs, count_applied = _reconstruct_psr_with_epub_spans(psr, para_map, lower_italics=lower_italics, lower_bolds=lower_bolds)
        if new_csrs is not None:
            for ch in list(psr):
                psr.remove(ch)
            for c in new_csrs:
                psr.append(c)
            enriched_count += count_applied
            story_changed = True

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
            if prev_csr.attrib.get("Position") in ("Superscript", "Subscript"):
                continue
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

    return enriched_count, story_changed


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


def unwrap_hyperlinks_in_extracted(extracted_dir):
    """Unwraps every HyperlinkTextSource in an unpacked IDML's stories BEFORE the
    typography pass runs. Footnote-reference markers wrapped as a direct child of a
    ParagraphStyleRange would otherwise be discarded when the paragraph is rebuilt;
    flattening them to plain superscript CharacterStyleRanges here keeps the marker
    text (as black, unlinked superscript) all the way through to the PDF."""
    extracted_dir = Path(extracted_dir)
    stories_dir = extracted_dir / "Stories"
    if not stories_dir.exists():
        return 0
    changed_count = 0
    for story_f in stories_dir.glob("Story_*.xml"):
        try:
            tree = ET.parse(story_f)
            root = tree.getroot()
            if _unwrap_hyperlinks(root):
                tree.write(story_f, encoding="utf-8", xml_declaration=True)
                changed_count += 1
        except Exception as e:
            print(f"Note: Error unwrapping hyperlinks in {story_f.name}: {e}")
    return changed_count


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
            count, changed = enrich_story_character_formatting(root, fmt, lang=lang)
            if count > 0 or changed:
                tree.write(story_f, encoding="utf-8", xml_declaration=True)
                total_enriched += count
        except Exception as e:
            print(f"Note: Error enriching {story_f.name}: {e}")

    return total_enriched

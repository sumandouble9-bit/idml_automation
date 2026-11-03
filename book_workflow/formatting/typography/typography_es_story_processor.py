"""Per-story / per-paragraph Spanish typography processor: classifies and restyles every ParagraphStyleRange in a story."""

import copy
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from core.idml_utils import content_text, lname, write_xml, load_epub_heading_hierarchy
from core.heading_classifier import (
    normalize_heading_str,
    is_part_or_book_heading,
    is_chapter_heading,
    extract_heading_number,
    split_runon_heading,
    should_pair_headings,
    apply_paired_heading_format,
)

try:
    from .typography_es_common import (
        _normalize_table_content, _is_page_break_spacer, _is_blank_page_spacer,
        _apply_heading_page_break, _apply_preface_page_break, _clean_subheading_page_break,
        _split_soft_lines, _is_true_verse, _ensure_font_prop, _format_clean_heading,
        _format_clean_subheading, _normalize_heading_str, _extract_doc_toc_entries_es,
        _load_epub_underlines_es,
    )
    from . import typography_es_ops as es_ops
except ImportError:
    from typography_es_common import (
        _normalize_table_content, _is_page_break_spacer, _is_blank_page_spacer,
        _apply_heading_page_break, _apply_preface_page_break, _clean_subheading_page_break,
        _split_soft_lines, _is_true_verse, _ensure_font_prop, _format_clean_heading,
        _format_clean_subheading, _normalize_heading_str, _extract_doc_toc_entries_es,
        _load_epub_underlines_es,
    )
    import typography_es_ops as es_ops


class _EsStoryProcessor:
    """Loads EPUB/TOC context once, then restyles every Spanish story XML under a target IDML directory."""

    def __init__(self, target_dir, book_name=None):
        """Resolve the stories dir and load EPUB underline, heading hierarchy, TOC and formatting references."""
        self.target_dir = target_dir
        self.book_name = book_name
        self.stories_dir = Path(target_dir) / "Stories"

        self.stats = {
            "bold_fixed": 0, "italic_fixed": 0, "underline_fixed": 0,
            "chapters_separated": 0, "body_styled": 0, "footnotes_formatted": 0,
        }

        self.epub_underlines = _load_epub_underlines_es(target_dir, book_name=book_name)
        res = load_epub_heading_hierarchy(book_name or Path(target_dir).parent.stem)
        if len(res) == 4:
            self.epub_h1_set, self.epub_sub_set, epub_toc, epub_h1_meta = res
        else:
            self.epub_h1_set, self.epub_sub_set, epub_toc = res
            epub_h1_meta = {"chapter_map": {}, "same_chap_pairs": set()}
        self.epub_h1_map = epub_h1_meta.get("chapter_map", {})
        self.same_chap_pairs = epub_h1_meta.get("same_chap_pairs", set())
        self.toc_raw, self.toc_norms, self.toc_chaps = _extract_doc_toc_entries_es(target_dir, book_name=book_name)
        for norm_e, raw_e in epub_toc:
            self.toc_norms.add(norm_e)

        self.epub_fmt = None
        try:
            from core.epub_style_enricher import extract_epub_formatting, find_matching_epub
            epub_f = find_matching_epub(book_name or target_dir)
            if epub_f:
                self.epub_fmt = extract_epub_formatting(epub_f)
        except Exception:
            pass

    def run(self):
        """Process every story XML file and return the aggregated fix counters."""
        for sp in sorted(self.stories_dir.glob("*.xml")):
            if (
                sp.name in ["Story_u_title_story.xml", "Story_u_copyright_story.xml"]
                or "copyright" in sp.name.lower()
                or "title_story" in sp.name.lower()
            ):
                continue
            try:
                root = ET.parse(sp).getroot()
            except Exception:
                continue
            if not self._process_story(root):
                continue
            write_xml(root, sp)
        return dict(self.stats)

    def _build_parent_map(self, root):
        """Return a child->parent map for every element under root."""
        pm = {}
        for p in root.iter():
            for child in p:
                pm[child] = p
        return pm

    def _process_story(self, root):
        """Restyle one story root in place; return True if the story should be written out."""
        psrs = [e for e in root.iter() if lname(e.tag) == "ParagraphStyleRange"]
        if len(psrs) < 5:
            return False

        for tbl in root.iter():
            if lname(tbl.tag) == "Table":
                _normalize_table_content(tbl, epub_fmt=self.epub_fmt)

        self.parent_map = self._build_parent_map(root)

        es_ops.presplit_compound_tables(root, self.epub_fmt)

        self.parent_map = self._build_parent_map(root)
        psrs = [e for e in root.iter() if lname(e.tag) == "ParagraphStyleRange"]

        self.in_preface = False
        self.in_footnotes = False
        self.in_index = False
        self.last_h1_norm = None
        self.last_h1_text = None
        self.last_h1_num = None
        self.seen_body_since_h1 = False

        for psr in psrs:
            self._process_psr(psr)

        es_ops.cleanup_character_styles(root, self.epub_underlines, self.stats)
        return True

    def _in_cell_or_table(self, psr):
        """True when the paragraph is nested inside a Table or Cell."""
        cur_node = self.parent_map.get(psr)
        while cur_node is not None:
            if lname(cur_node.tag) in ("Cell", "Table"):
                return True
            cur_node = self.parent_map.get(cur_node)
        return False

    def _process_psr(self, psr):
        """Run the full ordered phase pipeline on one ParagraphStyleRange."""
        ptxt = content_text(psr).strip()
        pstyle = psr.attrib.get("AppliedParagraphStyle", "")
        has_table = any(lname(c.tag) == "Table" for c in psr.iter())
        in_cell_or_table = self._in_cell_or_table(psr)

        if has_table:
            es_ops.split_table_csrs(psr, self.epub_fmt)
            return

        if in_cell_or_table:
            self._style_cell(psr)
            return

        if self._skip_frontmatter(pstyle, ptxt, psr):
            return

        if "###Insert" in ptxt:
            self._handle_image_placeholder(psr, ptxt)
            return

        if self._handle_preface_heading(psr, ptxt, has_table):
            return
        if self._handle_backmatter(psr, ptxt, has_table):
            return
        if self._handle_heading(psr, pstyle, ptxt, has_table, in_cell_or_table):
            return
        if self._handle_preface_body(psr, ptxt):
            return
        if self._handle_index_body(psr, ptxt):
            return

        is_fn = self.in_footnotes or "footnote" in pstyle.lower() or ptxt.startswith("{Nota ") or ptxt.startswith("[Nota")
        is_quote = any(k in pstyle.lower() for k in ["quote", "block", "verse", "poem"])
        _soft_lines = _split_soft_lines(psr)
        has_soft_break = _is_true_verse(psr)

        if self._handle_footnote_quote(psr, ptxt, is_fn, is_quote, has_soft_break):
            return

        self._handle_body_text(psr, pstyle, ptxt, has_soft_break)

        if len(ptxt) > 15 and not any(k in pstyle.lower() for k in ["head", "chap", "sub"]):
            self.seen_body_since_h1 = True

    def _style_cell(self, psr):
        """Restyle a paragraph nested inside a Table/Cell (headings become body; blocks keep a ragged indent)."""
        _cell_style = psr.attrib.get("AppliedParagraphStyle", "").lower()
        _cell_lines = _split_soft_lines(psr)
        _is_verse_cell = _is_true_verse(psr)
        if any(k in _cell_style for k in ["chapter", "sub-heading", "head"]):
            psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
        elif any(k in _cell_style for k in ["block", "quote", "verse", "poem"]) or _is_verse_cell:
            psr.set("LeftIndent", "39.68503937007875")
            psr.set("RightIndent", "39.68503937007875")
            psr.set("FirstLineIndent", "0")
            psr.set("Justification", "LeftAlign")
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)

    def _skip_frontmatter(self, pstyle, ptxt, psr):
        """True for front-matter (title/copyright/TOC/author) and spacer paragraphs that are left untouched."""
        if any(k in pstyle.lower() for k in ["verso", "copyright", "doublenine", "main_page_title", "toc", "content_ch", "about_the_auther"]):
            return True
        if _is_blank_page_spacer(psr) or _is_page_break_spacer(psr):
            return True
        if any(k in ptxt.lower() for k in ["double 9 books", "cubierta", "títuloderechos", "iniciodelcontenido"]):
            return True
        return False

    def _handle_image_placeholder(self, psr, ptxt):
        """Isolate a '###Insert ... ###' image placeholder into its own centered paragraph."""
        if "ParagraphBreakType" in psr.attrib:
            del psr.attrib["ParagraphBreakType"]
        if "StartParagraph" in psr.attrib:
            del psr.attrib["StartParagraph"]
        for c in list(psr.iter()):
            if "ParagraphBreakType" in c.attrib:
                del c.attrib["ParagraphBreakType"]

        m_ph = re.search(r"(###Insert\s+.*?###)", ptxt)
        ph_str = m_ph.group(1).strip() if m_ph else ptxt.strip()

        for child in list(psr):
            psr.remove(child)

        psr.set("AppliedParagraphStyle", "ParagraphStyle/Normal")
        psr.set("Justification", "CenterAlign")
        psr.set("FirstLineIndent", "0")
        psr.set("SpaceBefore", "6")
        psr.set("SpaceAfter", "6")

        new_csr = ET.SubElement(psr, "CharacterStyleRange", {
            "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
        })
        cnt = ET.SubElement(new_csr, "Content")
        cnt.text = ph_str
        ET.SubElement(new_csr, "Br")

    def _handle_preface_heading(self, psr, ptxt, has_table):
        """Format a Spanish/English preface heading on a fresh page and enter preface mode; True if handled."""
        is_preface = (
            not has_table
            and any(ptxt.lower().startswith(k) for k in [
                "prefacio", "prólogo", "prologo", "introducción", "introduccion",
                "nota del autor", "nota preliminar", "advertencia", "estudio preliminar",
                "preface", "foreword", "introduction"
            ])
            and len(ptxt) < 60
        )
        if not is_preface:
            return False
        self.in_preface = True
        self.in_footnotes = False
        parent = self.parent_map.get(psr)
        _apply_preface_page_break(psr, parent)
        clean_hd = ptxt.upper()
        _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
        return True

    def _handle_backmatter(self, psr, ptxt, has_table):
        """Format a NOTAS/APÉNDICE/ÍNDICE-style back-matter heading on a fresh page; True if handled."""
        is_backmatter = (
            not has_table
            and re.match(
                r"^(NOTAS(\s+AL\s+PIE)?|AP[ÉE]NDICE|EP[ÍI]LOGO|GLOSARIO|[ÍI]NDICE|BIBLIOGRAF[ÍI]A|CONCLUSI[ÓO]N|FOOT-?NOTES?|NOTES?|APPENDIX|EPILOGUE|GLOSSARY|INDEX|BIBLIOGRAPHY)\b:?\.?$",
                ptxt,
                re.I,
            )
            and len(ptxt) < 40
        )
        if not is_backmatter:
            return False
        self.in_footnotes = bool(re.search(r"^(NOTAS|FOOT-?NOTES?|NOTES?)\b", ptxt, re.I))
        self.in_index = bool(re.search(r"^([ÍI]NDICE|INDEX)\b", ptxt, re.I))
        self.in_preface = False
        parent = self.parent_map.get(psr)
        _apply_preface_page_break(psr, parent)
        clean_hd = re.sub(r"[:.]+$", "", ptxt).strip()
        _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
        return True

    def _handle_heading(self, psr, pstyle, ptxt, has_table, in_cell_or_table):
        """Classify a chapter/sub-heading, separate run-ons, and apply page breaks or same-page pairing; True if handled."""
        is_heading_cand = (
            not has_table
            and not in_cell_or_table
            and (
                (
                    any(k in pstyle.lower() for k in ["chap", "head", "sub-heading"])
                    and not any(k in pstyle.lower() for k in ["toc", "verso", "copy", "main_page", "author", "caption"])
                ) or (
                    re.match(r"^(cap[íi]tulo|libro|parte|acto|escena|secci[óo]n|chapter|book|part|act|scene)\b", ptxt, re.I)
                    and len(ptxt) < 120
                ) or (
                    re.match(r"^(?:primer|segundo|tercer|cuarto|quinto|sexto|s[ée]ptimo|octavo|noveno|d[ée]cimo)\s+cap[íi]tulo\b", ptxt, re.I)
                    and len(ptxt) < 120
                ) or (
                    re.match(r"^\d+\.\s+[A-ZÁÉÍÓÚÑ]", ptxt)
                    and len(ptxt) < 80
                ) or (
                    re.match(r"^(?:[IVXLCDM]+\b\.?\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{2,})", ptxt)
                    and len(ptxt) < 80
                )
            )
        )
        if not is_heading_cand:
            return False

        book_part, chap_part, was_separated = split_runon_heading(ptxt, lang="es")
        effective_txt = chap_part if was_separated else ptxt
        norm_p = normalize_heading_str(effective_txt)
        norm_p_clean = re.sub(r'[\s\.\-_]+', '', norm_p)
        toc_clean_map = {re.sub(r'[\s\.\-_]+', '', t): t for t in self.toc_norms}
        epub_h1_clean_map = {re.sub(r'[\s\.\-_]+', '', h): h for h in self.epub_h1_set}
        c_num = extract_heading_number(effective_txt, lang="es")

        is_main = False
        if norm_p in self.epub_h1_set or norm_p_clean in epub_h1_clean_map:
            is_main = True
        elif norm_p in self.epub_sub_set and norm_p not in self.epub_h1_set and norm_p_clean not in epub_h1_clean_map:
            is_main = False
        elif len(self.toc_norms) > 1:
            if norm_p in self.toc_norms or norm_p_clean in toc_clean_map:
                is_main = True
            elif c_num is not None and c_num in self.toc_chaps and (
                is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt)
            ):
                is_main = True
            elif any(norm_p.startswith(t) for t in self.toc_norms if len(t) > 6 and len(norm_p) > 6):
                is_main = True
            elif any(norm_p_clean.startswith(tc) for tc in toc_clean_map if len(tc) > 6 and len(norm_p_clean) > 6):
                is_main = True
        else:
            if is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt):
                is_main = True

        if not is_main and any(k in pstyle.lower() for k in ["chapter_name", "chapter"]) and len(ptxt) < 60:
            is_main = True

        if was_separated and book_part:
            self.in_preface = False
            self.in_footnotes = False
            self.in_index = False
            parent = self.parent_map.get(psr)
            self.stats["chapters_separated"] += 1

            _apply_heading_page_break(psr, parent)

            if parent is not None:
                idx = list(parent).index(psr)
                book_psr = ET.Element("ParagraphStyleRange")
                _format_clean_heading(book_psr, "ParagraphStyle/Sub-heading", "Gill Sans MT", book_part, space_after="20")
                book_psr.set("StartParagraph", "NextPage")
                parent.insert(idx, book_psr)

            apply_paired_heading_format(psr, chap_part, font_name="Gill Sans MT", space_before="14", space_after="30", language="es")

            self.last_h1_norm = normalize_heading_str(chap_part)
            self.last_h1_text = chap_part
            self.last_h1_num = c_num
            self.seen_body_since_h1 = False
            return True

        if is_main:
            self.in_preface = False
            self.in_footnotes = False
            self.in_index = False
            parent = self.parent_map.get(psr)

            curr_h1_num = self.epub_h1_map.get(norm_p)
            if curr_h1_num is None:
                for k, v in self.epub_h1_map.items():
                    if (len(k) > 6 and len(norm_p) > 6) and (k.startswith(norm_p) or norm_p.startswith(k)):
                        curr_h1_num = v
                        break

            is_same_page_h1 = should_pair_headings(
                prev_norm=self.last_h1_norm,
                curr_norm=norm_p,
                prev_text=self.last_h1_text,
                curr_text=effective_txt,
                seen_body_since_prev=self.seen_body_since_h1,
                same_chap_pairs=self.same_chap_pairs,
                prev_num=self.last_h1_num,
                curr_num=curr_h1_num,
            )

            if is_same_page_h1:
                _clean_subheading_page_break(psr, parent)
                apply_paired_heading_format(psr, effective_txt, font_name="Gill Sans MT", space_before="14", space_after="30", language="es")
                self.last_h1_norm = norm_p
                self.last_h1_text = effective_txt
                if curr_h1_num is not None:
                    self.last_h1_num = curr_h1_num
                self.seen_body_since_h1 = False
            else:
                _apply_heading_page_break(psr, parent)
                heading_text = effective_txt
                style_to_use = "ParagraphStyle/Sub-heading" if (
                    ("sub-heading" in pstyle.lower() or is_part_or_book_heading(heading_text))
                    and not heading_text.lower().startswith("cap")
                    and norm_p not in self.toc_norms
                ) else "ParagraphStyle/chapter_name"
                space_aft = "20" if style_to_use == "ParagraphStyle/Sub-heading" else "30"
                _format_clean_heading(psr, style_to_use, "Gill Sans MT", heading_text, space_after=space_aft)
                psr.set("StartParagraph", "NextPage")

                self.last_h1_norm = norm_p
                self.last_h1_text = heading_text
                self.last_h1_num = curr_h1_num
                self.seen_body_since_h1 = False

            self.stats["chapters_separated"] += 1
            return True

        parent = self.parent_map.get(psr)
        _clean_subheading_page_break(psr, parent)
        _format_clean_subheading(psr, "Gill Sans MT", ptxt, space_before="18", space_after="12", point_size=14)
        return True

    def _handle_preface_body(self, psr, ptxt):
        """Style a preface body paragraph; True if handled."""
        if not (self.in_preface and ptxt):
            return False
        psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
        psr.set("FirstLineIndent", "18")
        psr.set("Justification", "LeftAlign" if " " in ptxt else "LeftJustified")
        psr.set("SpaceBefore", "1.5")
        psr.set("SpaceAfter", "3")
        psr.set("AppliedLanguage", "$ID/Spanish: Standard")
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
        self.stats["body_styled"] += 1
        return True

    def _handle_index_body(self, psr, ptxt):
        """Style a tight index-entry paragraph; True if handled."""
        if not (self.in_index and ptxt):
            return False
        psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
        psr.set("Justification", "LeftAlign")
        psr.set("FirstLineIndent", "0")
        psr.set("SpaceBefore", "1")
        psr.set("SpaceAfter", "1")
        psr.set("AppliedLanguage", "$ID/Spanish: Standard")
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
        return True

    def _handle_footnote_quote(self, psr, ptxt, is_fn, is_quote, has_soft_break):
        """Style footnote and quote/verse paragraphs; True if handled."""
        if is_fn and ptxt:
            psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
            psr.set("LeftIndent", "39.68503937007875")
            psr.set("RightIndent", "39.68503937007875")
            psr.set("FirstLineIndent", "0")
            psr.set("SpaceBefore", "1.5")
            psr.set("SpaceAfter", "3")
            psr.set("Justification", "LeftAlign" if has_soft_break else "LeftJustified")
            psr.set("AppliedLanguage", "$ID/Spanish: Standard")
            for csr in psr.iter():
                if lname(csr.tag) == "CharacterStyleRange":
                    _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
            self.stats["footnotes_formatted"] += 1
            return True
        if is_quote or has_soft_break:
            psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
            psr.set("Justification", "LeftAlign")
            psr.set("LeftIndent", "39.68503937007875")
            psr.set("RightIndent", "39.68503937007875")
            psr.set("FirstLineIndent", "0")
            psr.set("SpaceBefore", "2")
            psr.set("SpaceAfter", "3")
            psr.set("AppliedLanguage", "$ID/Spanish: Standard")
            for csr in psr.iter():
                if lname(csr.tag) == "CharacterStyleRange":
                    _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
            return True
        return False

    def _handle_body_text(self, psr, pstyle, ptxt, has_soft_break):
        """Style ordinary body paragraphs (including chapter-styled paragraphs that are really narrative text)."""
        has_chap_kw = bool(re.match(r"^(?:cap[íi]tulo|chapter|parte|part|libro|book|acto|[íi]ndice|indice|index|prefacio|preface|pr[óo]logo|prologue|introducci[óo]n|introduction|conclusi[óo]n|conclusion|ep[íi]logo|epilogue|ap[ée]ndice|appendix|glosario|glossary|bibliograf[íi]a|bibliography|notas|notes|[IVXLCDM]+\b|\d+\b)\b", ptxt.strip(), re.I))
        is_mistaken_chap = (
            any(k in pstyle.lower() for k in ["chapter_name", "sub-heading"])
            and not has_chap_kw
            and (len(ptxt) > 120 or (len(ptxt) > 50 and "." in ptxt))
            and _normalize_heading_str(ptxt) not in self.toc_norms
            and not any(_normalize_heading_str(ptxt).startswith(t) for t in self.toc_norms if len(t) > 6)
        )

        if (
            is_mistaken_chap
            or (
                any(k in pstyle.lower() for k in ["noindent", "body", "normal", "msonormal", "basic paragraph", "text", "style", "paragraph", "para"])
                and not any(k in pstyle.lower() for k in ["chapter_name", "sub-heading", "heading", "toc", "verso", "copy", "author", "caption", "quote"])
            )
        ):
            if ptxt.strip() and not ptxt.strip().startswith("###Insert"):
                if "StartParagraph" in psr.attrib:
                    del psr.attrib["StartParagraph"]
                if "ParagraphBreakType" in psr.attrib:
                    del psr.attrib["ParagraphBreakType"]
                _is_sep = ptxt.strip() in ("*", "* * *", "***", "•", "• • •", "♦", "♦ ♦ ♦", "—", "——", "§")
                _cur_j = psr.attrib.get("Justification")
                _is_cent = _cur_j == "CenterAlign" or any(k in pstyle.lower() for k in ["center", "centre"]) or _is_sep
                _is_rt = _cur_j == "RightAlign" or any(k in pstyle.lower() for k in ["right", "signature", "signed"])
                _has_soft = " " in ptxt or has_soft_break

                psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                if _is_cent:
                    psr.set("Justification", "CenterAlign")
                    psr.set("FirstLineIndent", "0")
                elif _is_rt:
                    psr.set("Justification", "RightAlign")
                    psr.set("FirstLineIndent", "0")
                elif _has_soft or self.in_index:
                    psr.set("Justification", "LeftAlign")
                    psr.set("FirstLineIndent", "0")
                else:
                    psr.set("Justification", "LeftJustified")
                    psr.set("FirstLineIndent", "18")
                psr.set("SpaceBefore", "1.5")
                psr.set("SpaceAfter", "3")
                psr.set("KeepLinesTogether", "true")
                psr.set("KeepFirstAndLastLines", "true")
                psr.set("MinLinesAtStart", "2")
                psr.set("MinLinesAtEnd", "2")
                psr.set("AppliedLanguage", "$ID/Spanish: Standard")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                        if csr.attrib.get("FontStyle") == "Bold" and "bold" not in csr.attrib.get("AppliedCharacterStyle", "").lower():
                            csr.set("FontStyle", "Regular")
                self.stats["body_styled"] += 1


def process_stories(target_dir, book_name=None):
    """Restyle all Spanish story XML under target_dir via _EsStoryProcessor and return the fix counters."""
    return _EsStoryProcessor(target_dir, book_name=book_name).run()

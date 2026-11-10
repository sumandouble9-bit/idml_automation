"""Per-story / per-paragraph typography processor: classifies and restyles every ParagraphStyleRange in a story."""

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
    from .typography_common import (
        _apply_heading_page_break, _apply_preface_page_break, _ensure_font_prop,
        _split_soft_lines, _is_true_verse, _format_clean_heading, _clean_subheading_page_break,
        _normalize_table_content, _format_clean_subheading, _is_blank_page_spacer,
        _is_page_break_spacer, _normalize_heading_str, _extract_doc_toc_entries,
        _load_epub_underlines, _load_epub_tables,
    )
    from . import typography_char_ops as char_ops
except ImportError:
    from typography_common import (
        _apply_heading_page_break, _apply_preface_page_break, _ensure_font_prop,
        _split_soft_lines, _is_true_verse, _format_clean_heading, _clean_subheading_page_break,
        _normalize_table_content, _format_clean_subheading, _is_blank_page_spacer,
        _is_page_break_spacer, _normalize_heading_str, _extract_doc_toc_entries,
        _load_epub_underlines, _load_epub_tables,
    )
    import typography_char_ops as char_ops


class _StoryProcessor:
    """Loads EPUB/TOC context once, then restyles every story XML under a target IDML directory."""

    def __init__(self, target_dir, book_name=None):
        """Resolve the stories dir and load EPUB formatting, underline, table, heading and TOC references."""
        self.target_dir = target_dir
        self.book_name = book_name
        self.stories_dir = Path(target_dir) / "Stories"

        self.stats = {
            "bold_fixed": 0, "italic_fixed": 0, "underline_fixed": 0,
            "caps_fixed": 0, "super_fixed": 0, "sub_fixed": 0,
        }
        self.chapters_separated = 0
        self.body_styled = 0
        self.footnotes_formatted = 0

        self.epub_underlines = _load_epub_underlines(target_dir, book_name=book_name)
        self.epub_tables = _load_epub_tables(target_dir, book_name=book_name)

        res = load_epub_heading_hierarchy(book_name or Path(target_dir).parent.stem)
        if len(res) == 4:
            self.epub_h1_set, self.epub_sub_set, epub_toc, epub_h1_meta = res
        else:
            self.epub_h1_set, self.epub_sub_set, epub_toc = res
            epub_h1_meta = {"chapter_map": {}, "same_chap_pairs": set()}
        self.epub_h1_map = epub_h1_meta.get("chapter_map", {})
        self.same_chap_pairs = epub_h1_meta.get("same_chap_pairs", set())

        self.toc_raw, self.toc_norms, self.toc_chaps = _extract_doc_toc_entries(target_dir)
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

        self.lower_italics = set()
        self.lower_bolds = set()
        if self.epub_fmt:
            self.lower_italics = {re.sub(r"\s+", " ", s).strip().lower() for s in self.epub_fmt.get("italic", set()) if s}
            self.lower_bolds = {re.sub(r"\s+", " ", s).strip().lower() for s in self.epub_fmt.get("bold", set()) if s}

    def run(self):
        """Process every story XML file and return the aggregated fix counters."""
        for sp in sorted(self.stories_dir.glob("*.xml")):
            # NEVER touch dedicated Title Page or Copyright Page stories!
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
            if self._process_story(root):
                write_xml(root, sp)

        return {
            "bold_fixed": self.stats["bold_fixed"],
            "italic_fixed": self.stats["italic_fixed"],
            "underline_fixed": self.stats["underline_fixed"],
            "caps_fixed": self.stats["caps_fixed"],
            "super_fixed": self.stats["super_fixed"],
            "sub_fixed": self.stats["sub_fixed"],
            "chapters_separated": self.chapters_separated,
            "body_styled": self.body_styled,
            "footnotes_formatted": self.footnotes_formatted,
        }

    def _process_story(self, root):
        """Restyle one story root in place; return True if anything changed."""
        self.changed = False
        psrs = [e for e in root.iter() if lname(e.tag) == "ParagraphStyleRange"]
        if len(psrs) < 5:
            return False

        # Normalize all tables in the story against EPUB
        for tbl in root.iter():
            if lname(tbl.tag) == "Table":
                _normalize_table_content(tbl, epub_fmt=self.epub_fmt)

        self.parent_map = {}
        for p in root.iter():
            for child in p:
                self.parent_map[child] = p

        self.in_preface = False
        self.preface_para_count = 0
        self.needs_page_break_after_preface = False
        self.in_footnotes = False
        self.in_index = False
        self.last_h1_norm = None
        self.last_h1_text = None
        self.last_h1_num = None
        self.seen_body_since_h1 = False

        for psr in list(psrs):
            self._process_psr(psr)

        self._cleanup_soft_breaks(root)
        return self.changed

    def _process_psr(self, psr):
        """Run the full ordered phase pipeline on one ParagraphStyleRange."""
        pstyle = psr.attrib.get("AppliedParagraphStyle", "")
        ptxt = content_text(psr).strip()
        has_table = any(lname(c.tag) == "Table" for c in psr.iter())

        if has_table and self._split_table_text_para(psr):
            return
        if self._style_in_cell_para(psr):
            return
        if self._handle_backmatter_heading(psr, ptxt, has_table):
            return
        if self._skip_frontmatter(psr, pstyle, ptxt):
            return
        if self._handle_image_placeholder(psr, ptxt):
            return
        if self._handle_preface_heading(psr, ptxt, has_table):
            return
        if self._handle_backmatter2(psr, ptxt, has_table):
            return
        if self._handle_heading(psr, pstyle, ptxt, has_table):
            return

        if self.needs_page_break_after_preface and ptxt:
            self.needs_page_break_after_preface = False

        self._handle_preface_body(psr, ptxt)

        if has_table:
            # Table paragraph: clean alignment, zero indent, preserve internal table cell structures
            psr.set("FirstLineIndent", "0")
            psr.set("Justification", "LeftAlign")
            self.changed = True
            return

        if self._handle_index_body(psr, ptxt):
            return

        is_fn_style, is_quote_style, has_soft_break = self._body_style_pass(psr, pstyle, ptxt)

        # Safety: genuine verse / quote paragraphs must never be LeftJustified (footnotes stay justified)
        if (has_soft_break or is_quote_style) and not (is_fn_style or self.in_footnotes) and psr.attrib.get("Justification") == "LeftJustified":
            psr.set("Justification", "LeftAlign")
            self.changed = True

        if len(ptxt) > 15 and not any(k in pstyle.lower() for k in ["head", "chap", "sub"]):
            self.seen_body_since_h1 = True

        if char_ops.unpack_multichild_csrs(psr):
            self.changed = True
        if char_ops.merge_and_split_ref_markers(psr, self.in_footnotes, is_fn_style, self.stats):
            self.changed = True
        if char_ops.handle_chem_and_subscript(psr, self.stats):
            self.changed = True
        if char_ops.apply_char_styles(psr, self.epub_fmt, self.lower_italics, self.lower_bolds, self.epub_underlines, self.stats):
            self.changed = True
        if (self.in_footnotes or is_fn_style or "quote" in psr.attrib.get("AppliedParagraphStyle", "").lower()) and char_ops.unsuperscript_entry_marker(psr):
            self.changed = True

    def _split_table_text_para(self, psr):
        """Split a paragraph holding both a Table and body text into separate table/text PSRs; True if split."""
        if char_ops.split_table_and_text(psr, self.parent_map, self.epub_fmt):
            self.changed = True
            return True
        return False

    def _style_in_cell_para(self, psr):
        """Restyle a paragraph nested inside a Table/Cell and stop further processing; True if in a cell/table."""
        in_cell_or_table = False
        cur_node = self.parent_map.get(psr)
        while cur_node is not None:
            if lname(cur_node.tag) in ("Cell", "Table"):
                in_cell_or_table = True
                break
            cur_node = self.parent_map.get(cur_node)
        if not in_cell_or_table:
            return False

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
        return True

    def _handle_backmatter_heading(self, psr, ptxt, has_table):
        """Format a FOOTNOTES/NOTES/APPENDIX-style back-matter heading on a fresh page; True if handled."""
        is_backmatter_heading = (
            not has_table
            and re.match(r"^(FOOT-?NOTES?|END-?NOTES?|NOTES?|APPENDIX|EPILOGUE|GLOSSARY|INDEX|BIBLIOGRAPHY)\b:?\.?$", ptxt, re.I)
            and len(ptxt) < 40
        )
        if not is_backmatter_heading:
            return False
        self.in_footnotes = bool(re.search(r"^(FOOT-?NOTES?|END-?NOTES?|NOTES?)\b", ptxt, re.I))
        self.in_preface = False
        self.needs_page_break_after_preface = False
        parent = self.parent_map.get(psr)
        _apply_preface_page_break(psr, parent)
        clean_hd = re.sub(r"[:.]+$", "", ptxt).strip()
        _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
        self.changed = True
        return True

    def _skip_frontmatter(self, psr, pstyle, ptxt):
        """Skip title/copyright/TOC/author front-matter and spacer paragraphs; True if this psr is skipped."""
        if any(k in pstyle.lower() for k in ["verso", "copyright", "doublenine", "main_page_title", "toc", "content_ch", "about_the_auther"]):
            return True
        if _is_blank_page_spacer(psr) or _is_page_break_spacer(psr):
            return True
        if "double 9 books" in ptxt.lower():
            return True
        if any(k in ptxt.lower() for k in ["titlecopyright", "start of content", "copyrightcontents"]):
            return True
        return False

    def _handle_image_placeholder(self, psr, ptxt):
        """Isolate '###Insert ... ###' image placeholders into their own centered paragraph; True if handled."""
        if "###Insert" not in ptxt:
            return False

        # 1. Strip any forced page breaks so images flow naturally below text
        if "ParagraphBreakType" in psr.attrib:
            del psr.attrib["ParagraphBreakType"]
        if "StartParagraph" in psr.attrib:
            del psr.attrib["StartParagraph"]
        for c in list(psr.iter()):
            if "ParagraphBreakType" in c.attrib:
                del c.attrib["ParagraphBreakType"]

        # 2. Extract the placeholder tag(s): ###Insert ... ###
        matches = re.findall(r"(###Insert\s+.*?###)", ptxt)
        ph_str = " ".join([m.strip() for m in matches]) if matches else ptxt.strip()

        _non_ph = re.sub(r"###Insert\s+.*?###", "", ptxt)
        _non_ph = re.sub(r"[\s ﻿ ]+", "", _non_ph)
        _img_parent = self.parent_map.get(psr)
        if matches and len(_non_ph) >= 5 and _img_parent is not None:
            for _c in psr.iter():
                if lname(_c.tag) == "Content" and _c.text and "###Insert" in _c.text:
                    _c.text = re.sub(r"###Insert\s+.*?###", "", _c.text)
            _ph_psr = ET.Element("ParagraphStyleRange", {
                "AppliedParagraphStyle": "ParagraphStyle/Normal",
                "Justification": "CenterAlign",
                "FirstLineIndent": "0",
                "SpaceBefore": "6",
                "SpaceAfter": "6",
            })
            _ph_csr = ET.SubElement(_ph_psr, "CharacterStyleRange", {
                "AppliedCharacterStyle": r"CharacterStyle/$ID/[No character style]"
            })
            _pc = ET.SubElement(_ph_csr, "Content")
            _pc.text = ph_str
            ET.SubElement(_ph_csr, "Br")
            try:
                _idx = list(_img_parent).index(psr)
                _img_parent.insert(_idx + 1, _ph_psr)
            except ValueError:
                pass
            self.changed = True
            return True

        # 3. Placeholder-only paragraph: clean children and rebuild a single CSR.
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
        self.changed = True
        return True

    def _handle_preface_heading(self, psr, ptxt, has_table):
        """Format a PREFACE/FOREWORD/INTRODUCTION heading on a fresh page and enter preface mode; True if handled."""
        is_preface = (
            not has_table
            and any(ptxt.lower().startswith(k) for k in [
                "preface", "prefatory note", "foreword", "introduction", "prologue", "memoir", "biographical sketch"
            ])
            and len(ptxt) < 60
        )
        if not is_preface:
            return False
        self.in_preface = True
        self.in_footnotes = False
        self.preface_para_count = 0
        parent = self.parent_map.get(psr)
        _apply_preface_page_break(psr, parent)
        clean_heading = ptxt.upper()
        if "preface" in ptxt.lower():
            clean_heading = "PREFACE"
        elif "prefatory note" in ptxt.lower():
            clean_heading = "PREFATORY NOTE"
        _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_heading, space_after="30")
        self.changed = True
        return True

    def _handle_backmatter2(self, psr, ptxt, has_table):
        """Format a CONCLUSION/EPILOGUE/APPENDIX/NOTES/INDEX back-matter heading on a fresh page; True if handled."""
        is_backmatter = (
            not has_table
            and re.match(
                r"^(CONCLUSION|EPILOGUE|APPENDIX|NOTES?|FOOT-?NOTES?|GLOSSARY|INDEX|BIBLIOGRAPHY|AFTERWORD)\b:?\.?$",
                ptxt,
                re.I,
            )
            and len(ptxt) < 40
        )
        if not is_backmatter:
            return False
        self.in_footnotes = bool(re.search(r"^(NOTAS|FOOT-?NOTES?|NOTES?)\b", ptxt, re.I))
        self.in_index = bool(re.search(r"^INDEX\b", ptxt, re.I))
        self.in_preface = False
        parent = self.parent_map.get(psr)
        _apply_preface_page_break(psr, parent)
        clean_hd = re.sub(r"[:.]+$", "", ptxt).strip().upper()
        _format_clean_heading(psr, "ParagraphStyle/chapter_name", "Gill Sans MT", clean_hd, space_after="30")
        self.changed = True
        return True

    def _handle_heading(self, psr, pstyle, ptxt, has_table):
        """Classify a chapter/sub-heading, separate run-ons, and apply page breaks or same-page pairing; True if handled."""
        in_cell_or_table = False  # headings are only reached after the cell handler returned False
        is_heading_candidate = (
            not has_table
            and not in_cell_or_table
            and (
                (
                    any(k in pstyle.lower() for k in ["chap", "head", "sub-heading"])
                    and not any(k in pstyle.lower() for k in ["toc", "verso", "copy", "main_page", "author", "caption"])
                ) or (
                    re.match(r"^(chapter|book|part|act|scene)\b", ptxt, re.I)
                    and len(ptxt) < 120
                ) or (
                    re.match(r"^(definitions?|axioms?|propositions?|theory|experiment|questions?)\b:?\.?$", ptxt, re.I)
                    and len(ptxt) < 60
                ) or (
                    (
                        re.match(r"^(?:[IVXLCDM]+\b\.?\s+[A-Z][A-Z\s]{3,})", ptxt)
                        or re.match(
                            r"^(XLII|XLI|XL|XXXIX|XXXVIII|XXXVII|XXXVI|XXXV|XXXIV|XXXIII|XXXII|XXXI|XXX|XXIX|XXVIII|XXVII|XXVI|XXV|XXIV|XXIII|XXII|XXI|XX|XIX|XVIII|XVII|XVI|XV|XIV|XIII|XII|XI|X|IX|VIII|VII|VI|V|IV|III|II|I)(ROBINSON|THE|ANOTHER|DELIVERANCE|GETTING|SAVING|A\s+|HOW\s+)",
                            ptxt,
                        )
                    )
                    and len(ptxt) < 80
                ) or (
                    "book of opticks" in ptxt.lower()
                    and len(ptxt) < 80
                ) or (
                    re.match(r"^(camp\s*fire\s*yarn|yarn\s*no|section\b|axiom\b|prop\b|defin\b)", ptxt, re.I)
                    and len(ptxt) < 100
                )
            )
        )
        if not is_heading_candidate:
            return False

        book_part, chap_part, was_separated = split_runon_heading(ptxt, lang="en")
        effective_txt = chap_part if was_separated else ptxt
        norm_p = normalize_heading_str(effective_txt)
        norm_p_clean = re.sub(r'[\s\.\-_]+', '', norm_p)
        toc_clean_map = {re.sub(r'[\s\.\-_]+', '', t): t for t in self.toc_norms}
        epub_h1_clean_map = {re.sub(r'[\s\.\-_]+', '', h): h for h in self.epub_h1_set}
        c_num = extract_heading_number(effective_txt, lang="en")

        m_chap_sub = re.match(
            r"^(CHAPTER\s+[IVXLCDM0-9]+(?:[\.\:\-\s]+[A-Za-z\s]+?)?[\.\:\-])\s*(CAMP\s*FIRE\s*YARN.*)$",
            effective_txt.strip().replace("\r", " ").replace("\n", " "),
            re.I,
        )
        sub_trailing_text = None
        if m_chap_sub:
            effective_txt = m_chap_sub.group(1).strip()
            sub_trailing_text = m_chap_sub.group(2).strip()
            norm_p = normalize_heading_str(effective_txt)
            norm_p_clean = re.sub(r'[\s\.\-_]+', '', norm_p)
            c_num = extract_heading_number(effective_txt, lang="en")

        is_main = False
        if norm_p in self.epub_h1_set or norm_p_clean in epub_h1_clean_map:
            is_main = True
        elif norm_p in self.epub_sub_set and norm_p not in self.epub_h1_set and norm_p_clean not in epub_h1_clean_map:
            is_main = False
        elif len(self.toc_norms) > 1:
            if norm_p in self.toc_norms or norm_p_clean in toc_clean_map:
                is_main = True
            elif c_num is not None and c_num in self.toc_chaps and (is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt)):
                is_main = True
            elif any(norm_p.startswith(t) for t in self.toc_norms if len(t) > 6 and len(norm_p) > 6 and (is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt))):
                is_main = True
            elif any(norm_p_clean.startswith(tc) for tc in toc_clean_map if len(tc) > 6 and len(norm_p_clean) > 6 and (is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt))):
                is_main = True
        else:
            if is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt):
                is_main = True
            elif any(effective_txt.lower().startswith(k) for k in ["conclusion", "epilogue"]):
                is_main = True

        if (not is_main and any(k in pstyle.lower() for k in ["chapter_name", "chapter"]) and len(ptxt) < 60
                and (is_chapter_heading(effective_txt) or is_part_or_book_heading(effective_txt)
                     or norm_p in self.epub_h1_set or norm_p_clean in epub_h1_clean_map)):
            is_main = True

        if was_separated and book_part:
            self.in_preface = False
            self.in_footnotes = False
            self.needs_page_break_after_preface = False
            parent = self.parent_map.get(psr)
            self.chapters_separated += 1
            self.changed = True

            _apply_heading_page_break(psr, parent)

            if parent is not None:
                idx = list(parent).index(psr)
                book_psr = ET.Element("ParagraphStyleRange")
                _format_clean_heading(book_psr, "ParagraphStyle/Sub-heading", "Gill Sans MT", book_part, space_after="20")
                book_psr.set("StartParagraph", "NextPage")
                parent.insert(idx, book_psr)

            apply_paired_heading_format(psr, chap_part, font_name="Gill Sans MT", space_before="14", space_after="30", language="en")

            if sub_trailing_text and parent is not None:
                idx = list(parent).index(psr)
                sub_psr = ET.Element("ParagraphStyleRange")
                _format_clean_subheading(sub_psr, "Gill Sans MT", sub_trailing_text, space_before="18", space_after="12", point_size=14)
                parent.insert(idx + 1, sub_psr)

            self.last_h1_norm = normalize_heading_str(chap_part)
            self.last_h1_text = chap_part
            self.last_h1_num = c_num
            self.seen_body_since_h1 = False
            return True

        if is_main:
            self.in_preface = False
            self.in_footnotes = False
            self.needs_page_break_after_preface = False
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
                apply_paired_heading_format(psr, effective_txt, font_name="Gill Sans MT", space_before="14", space_after="30", language="en")
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
                    and not heading_text.lower().startswith("chapter")
                    and norm_p not in self.toc_norms
                ) else "ParagraphStyle/chapter_name"
                space_aft = "20" if style_to_use == "ParagraphStyle/Sub-heading" else "30"
                _format_clean_heading(psr, style_to_use, "Gill Sans MT", heading_text, space_after=space_aft)
                psr.set("StartParagraph", "NextPage")

                self.last_h1_norm = norm_p
                self.last_h1_text = heading_text
                self.last_h1_num = curr_h1_num
                self.seen_body_since_h1 = False

            if sub_trailing_text and parent is not None:
                idx = list(parent).index(psr)
                sub_psr = ET.Element("ParagraphStyleRange")
                _format_clean_subheading(sub_psr, "Gill Sans MT", sub_trailing_text, space_before="18", space_after="12", point_size=14)
                parent.insert(idx + 1, sub_psr)

            self.changed = True
            return True

        # SUBHEADING: MUST NOT HAVE A PAGE BREAK; flows on the SAME PAGE
        parent = self.parent_map.get(psr)
        _clean_subheading_page_break(psr, parent)
        _format_clean_subheading(psr, "Gill Sans MT", ptxt, space_before="18", space_after="12", point_size=14)
        self.changed = True
        return True

    def _handle_preface_body(self, psr, ptxt):
        """Style preface body paragraphs and signatures; falls through to later passes (no early return)."""
        if not (self.in_preface and ptxt):
            return
        self.preface_para_count += 1
        is_signature = (
            len(ptxt) < 60
            and (
                bool(re.search(r"([A-Z]\.){2,}", ptxt))
                or bool(re.search(r"\b(18\d\d|19\d\d|[A-Z]{2,4})\b", ptxt))
                or "house" in ptxt.lower()
                or bool(re.match(r"^[A-Z\.\s]{2,15}$", ptxt))
            )
        )
        psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
        psr.set("FirstLineIndent", "18")
        if is_signature:
            psr.set("SpaceBefore", "6")
            psr.set("SpaceAfter", "12")
            self.needs_page_break_after_preface = True
            self.in_preface = False
        else:
            psr.set("Justification", "LeftAlign" if " " in ptxt else "LeftJustified")
            psr.set("SpaceBefore", "1.5")
            psr.set("SpaceAfter", "3")
            if self.preface_para_count > 10:
                self.in_preface = False

        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
        self.changed = True

    def _handle_index_body(self, psr, ptxt):
        """Style tight index-entry paragraphs; True if handled."""
        if not (self.in_index and ptxt):
            return False
        psr.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
        psr.set("Justification", "LeftAlign")
        psr.set("FirstLineIndent", "0")
        psr.set("SpaceBefore", "1")
        psr.set("SpaceAfter", "1")
        for csr in psr.iter():
            if lname(csr.tag) == "CharacterStyleRange":
                _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
        self.changed = True
        return True

    def _body_style_pass(self, psr, pstyle, ptxt):
        """Style footnotes, quotes/verse, body and centered paragraphs; return (is_fn_style, is_quote_style, has_soft_break)."""
        is_fn_style = "footnote" in pstyle.lower() or ptxt.startswith("FOOTNOTES:")
        is_quote_style = any(k in pstyle.lower() for k in ["quote", "block", "verse", "poem"])
        _soft_lines = _split_soft_lines(psr)
        has_soft_break = _is_true_verse(psr)

        if (self.in_footnotes or is_fn_style) and ptxt:
            psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
            psr.set("LeftIndent", "39.68503937007875")
            psr.set("RightIndent", "39.68503937007875")
            psr.set("FirstLineIndent", "0")
            psr.set("SpaceBefore", "1.5")
            psr.set("SpaceAfter", "3")
            psr.set("Justification", "LeftJustified")
            for csr in psr.iter():
                if lname(csr.tag) == "CharacterStyleRange":
                    _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
            self.footnotes_formatted += 1
            self.changed = True
        elif is_quote_style or has_soft_break:
            psr.set("AppliedParagraphStyle", "ParagraphStyle/quotes_normal")
            if any(k in pstyle.lower() for k in ["right", "signature", "signed"]) or psr.attrib.get("Justification") == "RightAlign":
                psr.set("Justification", "RightAlign")
            elif any(k in pstyle.lower() for k in ["center", "centre"]) or psr.attrib.get("Justification") == "CenterAlign":
                psr.set("Justification", "CenterAlign")
            else:
                psr.set("Justification", "LeftAlign")
            psr.set("LeftIndent", "39.68503937007875")
            psr.set("RightIndent", "39.68503937007875")
            psr.set("FirstLineIndent", "0")
            psr.set("SpaceBefore", "2")
            psr.set("SpaceAfter", "3")
            for csr in psr.iter():
                if lname(csr.tag) == "CharacterStyleRange":
                    _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
            self.changed = True
        elif (
            (
                any(k in pstyle.lower() for k in ["chapter_name", "sub-heading"])
                and (len(ptxt) > 80 or (len(ptxt) > 40 and "." in ptxt and not re.match(r"^(?:chapter|book|part|act)\b", ptxt, re.I)))
                and _normalize_heading_str(ptxt) not in self.toc_norms
                and not any(_normalize_heading_str(ptxt).startswith(t) for t in self.toc_norms if len(t) > 6)
            )
            or (
                any(k in pstyle.lower() for k in ["noindent", "body", "normal", "msonormal", "basic paragraph", "text", "style", "paragraph", "para"])
                and not any(k in pstyle.lower() for k in ["chapter_name", "sub-heading", "heading", "toc", "verso", "copy", "author", "caption", "quote", "block", "verse", "poem", "fig caption", "right", "center", "centre"])
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
                has_tbl = any(lname(c.tag) == "Table" for c in psr.iter())
                if not has_tbl:
                    psr.set("KeepLinesTogether", "true")
                    psr.set("KeepFirstAndLastLines", "true")
                    psr.set("MinLinesAtStart", "2")
                    psr.set("MinLinesAtEnd", "2")
                else:
                    if "KeepLinesTogether" in psr.attrib:
                        del psr.attrib["KeepLinesTogether"]
                    if "KeepFirstAndLastLines" in psr.attrib:
                        del psr.attrib["KeepFirstAndLastLines"]
                    psr.set("FirstLineIndent", "0")
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                        if csr.attrib.get("FontStyle") == "Bold" and "bold" not in csr.attrib.get("AppliedCharacterStyle", "").lower():
                            csr.set("FontStyle", "Regular")
                self.body_styled += 1
                self.changed = True
        elif any(k in pstyle.lower() for k in ["centre", "center"]) and not any(k in pstyle.lower() for k in ["chapter_name", "sub-heading", "heading", "author", "title", "toc"]):
            if ptxt.strip() and not ptxt.strip().startswith("###Insert"):
                for csr in psr.iter():
                    if lname(csr.tag) == "CharacterStyleRange":
                        _ensure_font_prop(csr, "Palatino Linotype", point_size=9.65, leading=12)
                self.changed = True

        return is_fn_style, is_quote_style, has_soft_break

    def _cleanup_soft_breaks(self, root):
        """Trim stray soft breaks at paragraph edges and keep verse/block paragraphs ragged-left."""
        for psr in root.iter():
            if lname(psr.tag) == "ParagraphStyleRange":
                if psr.attrib.get("AppliedParagraphStyle") == "ParagraphStyle/Normal":
                    continue
                for c_elem in psr.iter():
                    if lname(c_elem.tag) == "Content" and c_elem.text:
                        if " " in c_elem.text:
                            cleaned_t = re.sub(r"^ +", "", c_elem.text)
                            cleaned_t = re.sub(r" +$", "", cleaned_t)
                            if cleaned_t != c_elem.text:
                                c_elem.text = cleaned_t
                                self.changed = True
                _pstyle_l = psr.attrib.get("AppliedParagraphStyle", "").lower()
                _is_block_sty = any(k in _pstyle_l for k in ("block", "quote", "verse", "poem"))
                _is_verse_p = _is_true_verse(psr)
                if _is_verse_p or _is_block_sty:
                    _eff_just = psr.attrib.get("Justification")
                    if _eff_just in ("LeftJustified", None):
                        psr.set("Justification", "LeftAlign")
                        self.changed = True


def process_stories(target_dir, book_name=None):
    """Restyle all story XML under target_dir via _StoryProcessor and return the fix counters."""
    return _StoryProcessor(target_dir, book_name=book_name).run()

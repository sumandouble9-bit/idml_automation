import copy
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from typography_postprocessor_helpers import *
except ImportError:
    from .typography_postprocessor_helpers import *


def enforce_styles_xml(tmp_dir, stats):
    """Enforce canonical fonts and paragraph/character-style attributes in Resources/Styles.xml."""
    styles_xml = tmp_dir / "Resources" / "Styles.xml"
    if styles_xml.exists():
        sroot = ET.parse(styles_xml).getroot()
        for ps in sroot.iter():
            if lname(ps.tag) == "ParagraphStyle":
                sid = ps.attrib.get("Self", "")
                ps.set("SingleWordJustification", "AlignLeft")
                if sid in (
                    "ParagraphStyle/body_text",
                    "ParagraphStyle/Normal",
                    "ParagraphStyle/$ID/[Basic Paragraph]",
                    "ParagraphStyle/$ID/NormalParagraphStyle",
                    "ParagraphStyle/$ID/[Normal Paragraph Style]",
                    "ParagraphStyle/Normal (Web)",
                    "ParagraphStyle/noindent",
                    "ParagraphStyle/noindentj",
                    "ParagraphStyle/noindent1",
                    "ParagraphStyle/bodytext_noendent",
                    "ParagraphStyle/bodytext_Noendent",
                    "ParagraphStyle/copybody",
                    "ParagraphStyle/centre_align",
                    "ParagraphStyle/center",
                    "ParagraphStyle/center1",
                ) or (
                    any(k in sid.lower() for k in ["body", "normal", "basic", "noindent"])
                    and not any(k in sid.lower() for k in [
                        "quote", "chapter", "sub-heading", "heading", "toc", "author", "title", "caption", "copy"
                    ])
                ):
                    _ensure_pstyle_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                    ps.set("KeepLinesTogether", "true")
                    ps.set("KeepFirstAndLastLines", "true")
                    ps.set("MinLinesAtStart", "2")
                    ps.set("MinLinesAtEnd", "2")
                    if sid in ("ParagraphStyle/body_text", "ParagraphStyle/Normal"):
                        ps.set("Justification", "LeftJustified")
                        ps.set("FirstLineIndent", "18")
                        ps.set("SpaceBefore", "1.5")
                        ps.set("SpaceAfter", "3")
                        ps.set("MinimumWordSpacing", "80")
                        ps.set("DesiredWordSpacing", "100")
                        ps.set("MaximumWordSpacing", "120")
                        ps.set("MinimumLetterSpacing", "0")
                        ps.set("DesiredLetterSpacing", "0")
                        ps.set("MaximumLetterSpacing", "0")
                        ps.set("Hyphenation", "true")
                    stats["styles_updated"] += 1
                elif sid == "ParagraphStyle/fig caption":
                    _ensure_pstyle_font(ps, "Palatino Linotype", point_size="9", leading="11")
                    ps.set("Justification", "CenterAlign")
                    stats["styles_updated"] += 1
                elif sid == "ParagraphStyle/chapter_name":
                    _ensure_pstyle_font(ps, "Gill Sans MT", point_size="16", leading="20")
                    ps.set("Hyphenation", "false")
                    ps.set("FontStyle", "Bold")
                    ps.set("Justification", "CenterAlign")
                    ps.set("StartParagraph", "NextPage")
                    ps.set("KeepAllLinesTogether", "true")
                    ps.set("KeepLinesTogether", "true")
                    ps.set("KeepWithNext", "2")
                    ps.set("RuleAbove", "true")
                    ps.set("RuleAboveLineWeight", "0")
                    ps.set("RuleAboveOffset", "14.5")
                    ps.set("KeepRuleAboveInFrame", "true")
                    props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                    if props is not None:
                        rac = next((c for c in props if lname(c.tag) == "RuleAboveColor"), None)
                        if rac is None:
                            rac = ET.SubElement(props, ps.tag.replace("ParagraphStyle", "RuleAboveColor"), {"type": "string"})
                            rac.text = "Text Color"
                elif sid == "ParagraphStyle/after_chapter_name_heading":
                    _ensure_pstyle_font(ps, "Gill Sans MT", point_size="16", leading="20")
                    ps.set("FontStyle", "Bold")
                    ps.set("Justification", "CenterAlign")
                    ps.set("StartParagraph", "Anywhere")
                    ps.set("ParagraphBreakType", "Anywhere")
                    ps.set("FirstLineIndent", "0")
                    ps.set("SpaceBefore", "14")
                    ps.set("SpaceAfter", "30")
                    ps.set("KeepWithNext", "2")
                    ps.set("KeepAllLinesTogether", "true")
                    ps.set("KeepLinesTogether", "true")
                elif sid == "ParagraphStyle/Sub-heading":
                    _ensure_pstyle_font(ps, "Gill Sans MT", point_size="14", leading="18")
                    ps.set("Hyphenation", "false")
                    ps.set("FontStyle", "Bold")
                    ps.set("Justification", "CenterAlign")
                    ps.set("SpaceBefore", "18")
                    ps.set("SpaceAfter", "12")
                    ps.set("KeepWithNext", "2")
                    ps.set("KeepLinesTogether", "true")
                    if "ParagraphBreakType" in ps.attrib:
                        del ps.attrib["ParagraphBreakType"]
                elif sid == "ParagraphStyle/quotes_normal":
                    _ensure_pstyle_font(ps, "Palatino Linotype", point_size="9.65", leading="12")
                    ps.set("Justification", "LeftAlign")
                    ps.set("KeepLinesTogether", "true")
                    ps.set("KeepFirstAndLastLines", "true")
                    ps.set("MinLinesAtStart", "2")
                    ps.set("MinLinesAtEnd", "2")

            elif lname(ps.tag) == "CharacterStyle":
                sid = ps.attrib.get("Self", "")
                props = next((c for c in ps if lname(c.tag) == "Properties"), None)
                if sid == "CharacterStyle/boldtext":
                    ps.set("FontStyle", "Bold")
                    if "PointSize" in ps.attrib:
                        del ps.attrib["PointSize"]
                    if props is not None:
                        for af in list(props):
                            if lname(af.tag) == "AppliedFont":
                                props.remove(af)
                elif sid in ("CharacterStyle/italicalign", "CharacterStyle/italic"):
                    ps.set("FontStyle", "Italic")
                    if "PointSize" in ps.attrib:
                        del ps.attrib["PointSize"]
                    if props is not None:
                        for af in list(props):
                            if lname(af.tag) == "AppliedFont":
                                props.remove(af)
                elif sid == "CharacterStyle/underlinalign":
                    ps.set("Underline", "true")
                    if "PointSize" in ps.attrib:
                        del ps.attrib["PointSize"]
                    if props is not None:
                        for af in list(props):
                            if lname(af.tag) == "AppliedFont":
                                props.remove(af)
                elif sid == "CharacterStyle/dropcap":
                    ps.set("PointSize", "9.65")
                    if props is not None:
                        for af in list(props):
                            if lname(af.tag) == "AppliedFont":
                                af.text = "Palatino Linotype"
                elif "hyperlink" in sid.lower():
                    ps.set("Underline", "false")
                    ps.set("FillColor", "Swatch/Black")
                    if props is not None:
                        for c in list(props):
                            if lname(c.tag) in ("UnderlineColor", "UnderlineType"):
                                props.remove(c)

        # Ensure dedicated superscript and subscript CharacterStyles exist
        has_sup = any(c.attrib.get("Self") == "CharacterStyle/superscript" for c in sroot.iter() if lname(c.tag) == "CharacterStyle")
        if not has_sup:
            ET.SubElement(sroot, "CharacterStyle", {
                "Self": "CharacterStyle/superscript",
                "Name": "superscript",
                "Position": "Superscript",
                "FillColor": "Swatch/Black",
                "Underline": "false"
            })
        has_sub = any(c.attrib.get("Self") == "CharacterStyle/subscript" for c in sroot.iter() if lname(c.tag) == "CharacterStyle")
        if not has_sub:
            ET.SubElement(sroot, "CharacterStyle", {
                "Self": "CharacterStyle/subscript",
                "Name": "subscript",
                "Position": "Subscript",
                "FillColor": "Swatch/Black",
                "Underline": "false"
            })
        ET.ElementTree(sroot).write(styles_xml, encoding="utf-8", xml_declaration=True)


def enforce_preferences(tmp_dir):
    """Reset Preferences.xml TextDefault to the body paragraph/character style and 9.65pt."""
    pref_xml = tmp_dir / "Resources" / "Preferences.xml"
    if pref_xml.exists():
        proot = ET.parse(pref_xml).getroot()
        pref_changed = False
        for td in proot.iter():
            if lname(td.tag) == "TextDefault":
                td.set("AppliedParagraphStyle", "ParagraphStyle/body_text")
                td.set("AppliedCharacterStyle", r"CharacterStyle/$ID/[No character style]")
                if "FontStyle" in td.attrib:
                    td.set("FontStyle", "Regular")
                if "PointSize" in td.attrib:
                    td.set("PointSize", "9.65")
                if "RuleBelow" in td.attrib:
                    td.set("RuleBelow", "false")
                pref_changed = True
        if pref_changed:
            ET.ElementTree(proot).write(pref_xml, encoding="utf-8", xml_declaration=True)


def collect_toc_norms(tmp_dir):
    """Collect normalized TOC entry strings from the stories; return (toc_norms, toc_clean_norms)."""
    stories_dir = tmp_dir / "Stories"
    toc_norms = set()
    if stories_dir.is_dir():
        for sf in stories_dir.glob("*.xml"):
            try:
                r = ET.parse(sf).getroot()
            except Exception:
                continue
            for psr in r.iter():
                if lname(psr.tag) == "ParagraphStyleRange":
                    st = psr.attrib.get("AppliedParagraphStyle", "")
                    if any(k in st.lower() for k in ["toc", "content_ch", "tochead", "tocch"]):
                        hl = [h for h in psr.iter() if lname(h.tag) == "HyperlinkTextSource"]
                        if hl:
                            for h in hl:
                                t = "".join(c.text or "" for c in h.iter() if lname(c.tag) == "Content").strip()
                                if t:
                                    for part in re.split(r"\t\d*", t):
                                        part = part.strip()
                                        if part:
                                            s = re.sub(r"[\r\n\u2028]+", " ", part)
                                            s = re.sub(r"[^\w\s]", "", s.lower())
                                            s = re.sub(r"\s+", " ", s).strip()
                                            if s and not any(k in s for k in ["table of contents", "contents", "double 9 books"]):
                                                toc_norms.add(s)
                        else:
                            txt = "".join(c.text or "" for c in psr.iter() if lname(c.tag) == "Content").strip()
                            if txt:
                                for line in re.split(r"[\r\n\u2028]+", txt):
                                    line = line.strip()
                                    if line:
                                        for part in re.split(r"\t\d*", line):
                                            part = part.strip()
                                            if part:
                                                s = re.sub(r"[\r\n\u2028]+", " ", part)
                                                s = re.sub(r"[^\w\s]", "", s.lower())
                                                s = re.sub(r"\s+", " ", s).strip()
                                                if s and not any(k in s for k in ["table of contents", "contents", "double 9 books"]):
                                                     toc_norms.add(s)
        toc_clean_norms = {re.sub(r"[\s\.\-_]+", "", t) for t in toc_norms}
    return toc_norms, toc_clean_norms


__all__ = ['enforce_styles_xml', 'enforce_preferences', 'collect_toc_norms']

"""Word and Character Spacing Balancer for Justified Body Text.

Limits the compression on justified body lines so word spaces do not shrink by
more than -0.10 pt to -0.12 pt from the font's natural space width (2.41 pt for
Palatino Linotype 9.65 pt).
"""

import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Body style names to target
BODY_STYLE_NAMES = (
    "Normal",
    "NormalParagraphStyle",
    "[Normal Paragraph Style]",
    "[Basic Paragraph]",
    "body_text",
    "noindent",
    "noindentj",
    "noindent1",
    "bodytext_noendent",
    "bodytext_Noendent",
    "copybody",
)

# Default spacing parameters:
# At 9.65 pt Palatino Linotype, 100% space = 2.4125 pt.
# 95% space = 2.2919 pt (difference = -0.1206 pt).
# 96% space = 2.3160 pt (difference = -0.0965 pt).
# Setting min_word=95 bounds the compression difference strictly to -0.10 pt to -0.12 pt.
DEFAULT_MIN_WORD = 95
DEFAULT_DES_WORD = 100
DEFAULT_MAX_WORD = 120
DEFAULT_MIN_LETTER = -1
DEFAULT_DES_LETTER = 0
DEFAULT_MAX_LETTER = 4


def get_justification_spacing_js(
    min_word_pct: int = DEFAULT_MIN_WORD,
    des_word_pct: int = DEFAULT_DES_WORD,
    max_word_pct: int = DEFAULT_MAX_WORD,
    min_letter_pct: int = DEFAULT_MIN_LETTER,
    des_letter_pct: int = DEFAULT_DES_LETTER,
    max_letter_pct: int = DEFAULT_MAX_LETTER,
) -> str:
    """Return ExtendScript JavaScript to enforce bounded word and letter spacing in InDesign.

    Enforces minimum word spacing at min_word_pct (default 95%), ensuring word spaces
    never compress by more than -0.10 pt to -0.12 pt from natural font space.
    """
    body_styles_js = '["' + '","'.join(BODY_STYLE_NAMES) + '"]'
    return f"""
    try {{
        var _justBody = {body_styles_js};
        for (var _j = 0; _j < _justBody.length; _j++) {{
            var _bs = doc.paragraphStyles.itemByName(_justBody[_j]);
            if (_bs && _bs.isValid) {{
                try {{ _bs.justification = Justification.LEFT_JUSTIFIED; }} catch(e1) {{}}
                try {{ _bs.hyphenation = true; }} catch(e2) {{}}
                try {{ _bs.minimumWordSpacing = {min_word_pct}; _bs.desiredWordSpacing = {des_word_pct}; _bs.maximumWordSpacing = {max_word_pct}; }} catch(e3) {{}}
                try {{ _bs.minimumLetterSpacing = {min_letter_pct}; _bs.desiredLetterSpacing = {des_letter_pct}; _bs.maximumLetterSpacing = {max_letter_pct}; }} catch(e4) {{}}
            }}
        }}
        var _justBlock = ["quotes_normal"];
        for (var _qb = 0; _qb < _justBlock.length; _qb++) {{
            var _bsq = doc.paragraphStyles.itemByName(_justBlock[_qb]);
            if (_bsq && _bsq.isValid) {{ try {{ _bsq.justification = Justification.LEFT_JUSTIFIED; }} catch(e5b) {{}} }}
        }}
        var _justRag = ["verse","poem","block1","block","block2","blockleft"];
        for (var _q = 0; _q < _justRag.length; _q++) {{
            var _rs = doc.paragraphStyles.itemByName(_justRag[_q]);
            if (_rs && _rs.isValid) {{ try {{ _rs.justification = Justification.LEFT_ALIGN; }} catch(e5) {{}} }}
        }}
        var _spcStyles = ["Normal","body_text","block1","block","block2","copybody","quotes_normal","blockquote_italic","quote_italic_bold","blochquote_boldittalic","blockleft","bodytext_noendent","bodytext_Noendent"];
        for (var _si = 0; _si < _spcStyles.length; _si++) {{
            var _sst = doc.paragraphStyles.itemByName(_spcStyles[_si]);
            if (_sst && _sst.isValid) {{
                try {{ _sst.spaceBefore = 1.5; }} catch(eSb) {{}}
                try {{ _sst.spaceAfter = 3; }} catch(eSa) {{}}
            }}
        }}
        var _noHyph = ["chapter_name","chapter_name01","master_chapter_name","Sub-heading","after_chapter_name_heading","section_heading","Heading 1"];
        for (var _h = 0; _h < _noHyph.length; _h++) {{
            var _hs = doc.paragraphStyles.itemByName(_noHyph[_h]);
            if (_hs && _hs.isValid) {{ try {{ _hs.hyphenation = false; }} catch(e6) {{}} }}
        }}
    }} catch(eJust) {{}}
    """


def apply_balanced_word_spacing(
    styles_root: ET.Element,
    min_word: int = DEFAULT_MIN_WORD,
    des_word: int = DEFAULT_DES_WORD,
    max_word: int = DEFAULT_MAX_WORD,
    min_letter: int = DEFAULT_MIN_LETTER,
    des_letter: int = DEFAULT_DES_LETTER,
    max_letter: int = DEFAULT_MAX_LETTER,
) -> int:
    """Enforce bounded word and letter spacing on body paragraph styles in Styles.xml ElementTree.

    Returns the number of styles updated.
    """
    count = 0
    for ps in styles_root.iter():
        if not ps.tag.endswith("ParagraphStyle"):
            continue
        self_id = ps.attrib.get("Self", "")
        name = ps.attrib.get("Name", "")
        # Target body text, normal, and general paragraph styles
        is_target = any(b == name or b == self_id.replace("ParagraphStyle/", "") for b in BODY_STYLE_NAMES)
        if not is_target:
            sid_lower = self_id.lower()
            if any(k in sid_lower for k in ["body", "normal", "noindent"]) and not any(
                k in sid_lower for k in ["quote", "chapter", "sub-heading", "heading", "toc", "author", "title", "caption", "copy"]
            ):
                is_target = True

        if is_target:
            ps.set("MinimumWordSpacing", str(min_word))
            ps.set("DesiredWordSpacing", str(des_word))
            ps.set("MaximumWordSpacing", str(max_word))
            ps.set("MinimumLetterSpacing", str(min_letter))
            ps.set("DesiredLetterSpacing", str(des_letter))
            ps.set("MaximumLetterSpacing", str(max_letter))
            count += 1

    return count


def apply_spacing_to_idml(idml_path: str, min_word: int = DEFAULT_MIN_WORD) -> bool:
    """Update Resources/Styles.xml in an IDML file with the balanced word spacing settings."""
    path = Path(idml_path)
    if not path.is_file():
        return False

    with zipfile.ZipFile(str(path), "r") as zin:
        names = zin.namelist()
        if "Resources/Styles.xml" not in names:
            return False
        data = {n: zin.read(n) for n in names}

    styles_xml = data["Resources/Styles.xml"].decode("utf-8")
    root = ET.fromstring(styles_xml)
    updated = apply_balanced_word_spacing(root, min_word=min_word)

    if updated > 0:
        data["Resources/Styles.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        tmp = path.with_suffix(".spacing.tmp")
        with zipfile.ZipFile(str(tmp), "w") as zout:
            if "mimetype" in data:
                zout.writestr("mimetype", data["mimetype"], compress_type=zipfile.ZIP_STORED)
            for n in names:
                if n == "mimetype":
                    continue
                zout.writestr(n, data[n], compress_type=zipfile.ZIP_DEFLATED)
        os.replace(str(tmp), str(path))
        return True

    return False

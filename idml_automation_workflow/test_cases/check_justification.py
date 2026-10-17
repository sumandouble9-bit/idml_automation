import re as _re
import zipfile as _zip


def check(idml_path):
    """Verify body is fully justified with uniform word spacing: body_text style is
    LeftJustified + MaximumWordSpacing=100, and no body_text paragraph with real text
    and no forced line break (<Br/>) carries an explicit non-justified override."""
    bad = []
    try:
        with _zip.ZipFile(idml_path) as z:
            st = z.read("Resources/Styles.xml").decode("utf-8", "replace")
            m = _re.search(r'<ParagraphStyle\b[^>]*Self="ParagraphStyle/body_text".*?</ParagraphStyle>', st, _re.S)
            tag = m.group(0).split(">", 1)[0] if m else ""
            if 'Justification="LeftJustified"' not in tag:
                bad.append("style not LeftJustified")
            mm = _re.search(r'MaximumWordSpacing="([^"]+)"', tag)
            if not mm or abs(float(mm.group(1)) - 100) > 0.5:
                bad.append("style MaxWordSpacing!=100")
            unjust = 0
            for n in z.namelist():
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                x = z.read(n).decode("utf-8", "replace")
                for pm in _re.finditer(r"<ParagraphStyleRange\b([^>]*)>(.*?)</ParagraphStyleRange>", x, _re.S):
                    ptag, body = pm.group(1), pm.group(2)
                    if 'AppliedParagraphStyle="ParagraphStyle/body_text"' not in ptag:
                        continue
                    if _re.search(r'<Br\b', body):          # verse / forced line break: ragged is OK
                        continue
                    content = "".join(_re.findall(r"<Content>(.*?)</Content>", body, _re.S)).strip()
                    if len(content) < 60:                   # short list/table fragment, not prose
                        continue
                    jm = _re.search(r'Justification="([^"]+)"', ptag)
                    if jm and jm.group(1) != "LeftJustified":
                        unjust += 1
            if unjust:
                bad.append("%d body paragraphs overridden non-justified" % unjust)
    except Exception as e:
        return ["JUSTIFY_CHECK_ERROR=%s" % e]
    if bad:
        return ["JUSTIFY_WRONG=%s" % "; ".join(bad)]
    return []

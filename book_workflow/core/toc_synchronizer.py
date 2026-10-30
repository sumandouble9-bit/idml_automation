import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def lname(tag):
    return tag.split("}")[-1] if "}" in tag else tag


JS_TOC_SYNC = """
(function(){
    var doc = app.activeDocument;
    var chapMap = {};
    var chapList = [];

    // Helper: clean string
    function cleanStr(s){
        return s.replace(/[\\r\\n\\t\\u00A0\\u2028\\uFEFF]/g, " ").replace(/\\s+/g, " ").replace(/^\\s+|\\s+$/g, "");
    }

    // 1. Scan stories for chapter headings and record their actual page numbers
    for (var s = 0; s < doc.stories.length; s++) {
        var story = doc.stories[s];
        var paras = story.paragraphs;
        for (var p = 0; p < paras.length; p++) {
            var para = paras[p];
            var sName = para.appliedParagraphStyle.name.toLowerCase();
            var isChapStyle = (sName.indexOf("chapter") !== -1 || sName.indexOf("chap") !== -1 || sName.indexOf("sub-heading") !== -1);
            if (isChapStyle) {
                try {
                    var pFrame = (para.insertionPoints.length > 0 && para.insertionPoints[0].parentTextFrames.length > 0) ?
                                 para.insertionPoints[0].parentTextFrames[0] :
                                 (para.parentTextFrames.length > 0 ? para.parentTextFrames[0] : null);
                    if (pFrame !== null && pFrame.parentPage !== null) {
                        var pNum = pFrame.parentPage.name;
                        var rawTxt = cleanStr(para.contents);
                        if (rawTxt.length >= 1 && rawTxt.length <= 140) {
                            var low = rawTxt.toLowerCase();
                            chapMap[low] = pNum;
                            chapList.push({title: low, page: pNum, raw: rawTxt});
                            // Also map numeral
                            var m = low.match(/^(?:chapter|cap[íi]tulo)?\\s*([ivxlcdm0-9]+)\\b/);
                            if (m) {
                                chapMap[m[1]] = pNum;
                            }
                        }
                    }
                } catch(e) {}
            }
        }
    }

    // 2. Scan stories for TOC entries and update page numbers
    var updatedCount = 0;
    for (var s = 0; s < doc.stories.length; s++) {
        var story = doc.stories[s];
        var paras = story.paragraphs;
        for (var p = 0; p < paras.length; p++) {
            var para = paras[p];
            var sName = para.appliedParagraphStyle.name.toLowerCase();
            if (sName.indexOf("toc") !== -1 || sName.indexOf("content") !== -1) {
                var contents = para.contents;
                if (contents.indexOf("\\t") !== -1) {
                    var lines = contents.split(/[\\r\\n]/);
                    var newLines = [];
                    var paraChanged = false;
                    for (var li = 0; li < lines.length; li++) {
                        var line = lines[li];
                        if (line.indexOf("\\t") !== -1) {
                            var parts = line.split("\\t");
                            var entryTitle = cleanStr(parts[0]).toLowerCase();
                            var oldP = parts[1].replace(/^[\\s\\r\\n]+|[\\s\\r\\n]+$/g, "");
                            var matchedPage = null;

                            // 1. Exact match
                            if (chapMap[entryTitle]) {
                                matchedPage = chapMap[entryTitle];
                            } else {
                                // 2. Substring match (only for long titles)
                                if (entryTitle.length > 4) {
                                    for (var i = 0; i < chapList.length; i++) {
                                        var c = chapList[i];
                                        if (c.title.length > 4 && (c.title.indexOf(entryTitle) !== -1 || entryTitle.indexOf(c.title) !== -1)) {
                                            matchedPage = c.page;
                                            break;
                                        }
                                    }
                                }
                                // 2b. Whitespace-insensitive match (e.g. TIFÓN I vs TIFÓNI)
                                if (!matchedPage) {
                                    var cleanEntry = entryTitle.replace(/[\s\.\-_]+/g, "");
                                    if (cleanEntry.length > 3) {
                                        for (var i = 0; i < chapList.length; i++) {
                                            var cleanTitle = chapList[i].title.replace(/[\s\.\-_]+/g, "");
                                            if (cleanTitle === cleanEntry || cleanTitle.indexOf(cleanEntry) !== -1 || cleanEntry.indexOf(cleanTitle) !== -1) {
                                                matchedPage = chapList[i].page;
                                                break;
                                            }
                                        }
                                    }
                                }
                                // 3. Numeral match
                                if (!matchedPage) {
                                    var m1 = entryTitle.match(/^(?:chapter|cap[íi]tulo)?\\s*([ivxlcdm0-9]+)\\b/);
                                    if (m1 && chapMap[m1[1]]) {
                                        matchedPage = chapMap[m1[1]];
                                    }
                                }
                            }

                            if (matchedPage !== null && matchedPage !== oldP) {
                                newLines.push(parts[0] + "\\t" + matchedPage);
                                paraChanged = true;
                                updatedCount++;
                            } else {
                                newLines.push(line);
                            }
                        } else {
                            newLines.push(line);
                        }
                    }
                    if (paraChanged) {
                        para.contents = newLines.join("\\r") + "\\r";
                    }
                }
            }
        }
    }
    return updatedCount + "";
})();
"""


def sync_toc_via_indesign(app) -> int:
    """Live InDesign TOC sync is deferred to Step 4 (sync_idml_toc_from_pdf)
    which uses PyMuPDF on the exported PDF for 100% precision and stability."""
    return 0


import unicodedata

def normalize_heading(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\u2014\u2013\-\:\_\/\.\,\;\t\r\n\u2028]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.upper().split())


def extract_pdf_chapter_pages(pdf_path: Path):
    """
    Extracts real page numbers for each chapter heading directly from the generated PDF using PyMuPDF.
    Carefully isolates body chapters from multi-page TOCs and preserves sequential chapter order.
    """
    import pymupdf

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return []

    doc = pymupdf.open(str(pdf_path))
    toc_pages = set()
    for pno in range(min(12, len(doc))):
        txt = doc[pno].get_text()
        if any(k in txt.upper() for k in ["CONTENTS", "TABLE OF CONTENTS", "CONTENIDO", "ÍNDICE", "INDICE"]):
            toc_pages.add(pno + 1)
        elif toc_pages and (pno + 1) in [max(toc_pages) + 1]:
            if "...." in txt or txt.count(".") > 15:
                toc_pages.add(pno + 1)

    chaps = []
    curr_part = ""
    for pno in range(len(doc)):
        pnum = pno + 1
        if pnum in toc_pages or pnum <= 2:
            continue
        txt = doc[pno].get_text()
        lines = [l.strip() for l in txt.split("\n") if l.strip()]
        top_lines = [l for l in lines[:8] if "|" not in l and not l.isdigit()]
        if not top_lines:
            continue

        for idx, line in enumerate(top_lines):
            norm = normalize_heading(line)
            if not norm or len(norm) < 1:
                continue

            if re.match(r"^(?:BOOK|LIBRO|PART|PARTE)\b", norm):
                curr_part = norm

            is_chap = (
                re.match(r"^(?:CHAPTER|CAPITULO|BOOK|LIBRO|PART|PARTE|SECCION|PREFACE|PREFACIO|PROLOGO|INTRODUCCION|NOTA)\b", norm)
                or re.match(r"^(?:[IVXLCDM]+|\d{1,3}(?:\.|\s+[A-Z]))\b", norm)
            )
            if is_chap:
                sub = ""
                if idx + 1 < len(top_lines):
                    sub_norm = normalize_heading(top_lines[idx + 1])
                    if sub_norm and len(sub_norm) < 80 and not re.match(r"^(?:CHAPTER|CAPITULO|BOOK|LIBRO|PART|PARTE)\b", sub_norm):
                        sub = sub_norm

                m_num = re.match(r"^(?:CHAPTER|CAPITULO)?\s*([IVXLCDM0-9]+)\b", norm)
                chap_num = m_num.group(1) if m_num else ""

                chaps.append({
                    "page": pnum,
                    "raw": line,
                    "norm": norm,
                    "sub": sub,
                    "num": chap_num,
                    "part": curr_part,
                })

    doc.close()
    return chaps


def sync_idml_toc_from_pdf(idml_path: Path, pdf_path: Path) -> int:
    """
    Updates the TOC story in an IDML file directly based on real page numbers
    extracted from the generated PDF using PyMuPDF.
    Preserves dot leaders, tab stops, and guarantees monotonically non-decreasing page numbers.
    """
    import pymupdf
    idml_path = Path(idml_path)
    pdf_path = Path(pdf_path)
    if not idml_path.exists() or not pdf_path.exists():
        return 0

    doc = pymupdf.open(str(pdf_path))
    if len(doc) <= 2:
        return 0

    # 1. Identify front matter / TOC pages strictly in front matter
    toc_pages = set()
    for pno in range(2, min(7, len(doc))):
        lines = [l.strip() for l in doc[pno].get_text().split("\n") if l.strip()]
        top = [l.upper() for l in lines[:3]]
        if any(h in top for h in ["CONTENTS", "TABLE OF CONTENTS", "CONTENIDO", "ÍNDICE", "INDICE"]):
            toc_pages.add(pno + 1)
        elif toc_pages and (pno + 1) == max(toc_pages) + 1 and any("." * 4 in l for l in lines):
            toc_pages.add(pno + 1)

    last_toc_page = max(toc_pages) if toc_pages else 5
    if last_toc_page % 2 == 1:
        first_content_page = last_toc_page + 2
    else:
        first_content_page = last_toc_page + 1

    front_matter_pages = set(range(1, first_content_page))

    # Pre-parse body pages into normalized lines, skipping running headers
    pages_data = []
    for pno in range(len(doc)):
        pnum = pno + 1
        if pnum in front_matter_pages:
            pages_data.append((pnum, []))
            continue
        txt = doc[pno].get_text()
        raw_lines = [l.strip() for l in txt.split("\n") if l.strip()]
        clean_lines = [l for l in raw_lines if "|" not in l and not re.match(r"^\d+$", l)]
        norm_lines = [normalize_heading(l) for l in clean_lines]
        pages_data.append((pnum, norm_lines))

    doc.close()

    # 2. Extract TOC items from IDML story
    toc_items = []
    with zipfile.ZipFile(idml_path, "r") as zin:
        for item in zin.infolist():
            if item.filename.startswith("Stories/Story_"):
                raw = zin.read(item.filename).decode("utf-8", errors="ignore")
                if "toc" in raw.lower() or "content" in raw.lower():
                    try:
                        root = ET.fromstring(raw)
                        for psr in root.findall(".//ParagraphStyleRange"):
                            style = psr.attrib.get("AppliedParagraphStyle", "")
                            if "toc" in style.lower() or "content" in style.lower():
                                for csr in psr.findall(".//CharacterStyleRange"):
                                    for cnt in csr.findall(".//Content"):
                                        if cnt.text and "\t" in cnt.text:
                                            for line in cnt.text.split("\r"):
                                                if "\t" in line:
                                                    parts = line.split("\t")
                                                    t = parts[0].strip()
                                                    old_p = parts[1].strip()
                                                    if t:
                                                        toc_items.append((t, old_p))
                    except Exception:
                        pass

    if not toc_items:
        return 0

    # 3. Match each TOC item to its exact landing page in the PDF
    page_mapping = {}
    curr_min = max(front_matter_pages) + 1

    for title, old_p in toc_items:
        norm_t = normalize_heading(title)
        m_num = re.match(r"^(?:CHAPTER|CAPITULO)?\s*([IVXLCDM]+|\d{1,3})\b", norm_t)
        if not m_num:
            m_num = re.search(r"\b([IVXLCDM]+|\d{1,3})\b", norm_t)
        num_str = m_num.group(1) if m_num else ""
        words = [w for w in norm_t.split() if w not in {"CHAPTER", "CAPITULO", num_str} and len(w) >= 2]
        sub_title = " ".join(words)

        matched_p = None
        for pnum, norm_lines in pages_data:
            if pnum < curr_min:
                continue
            # Heading lines are strictly in the top block on a chapter start page
            top = norm_lines[:6]
            heading_block = " ".join(top)

            # Strategy 1: Exact full title in top heading block
            if norm_t in heading_block:
                matched_p = pnum
                break

            # Strategy 1b: Whitespace/punctuation-stripped match (e.g. TIFÓN I vs TIFÓNI)
            clean_norm_t = re.sub(r"[\s\.\-_]+", "", norm_t)
            clean_block = re.sub(r"[\s\.\-_]+", "", heading_block)
            if len(clean_norm_t) >= 4 and clean_norm_t in clean_block:
                matched_p = pnum
                break

            # Strategy 2: Numeral line in top[:3] + subtitle in heading block
            if num_str:
                has_num = any(re.match(rf"^(?:CHAPTER|CAPITULO)?\s*{re.escape(num_str)}$", l) for l in top[:3])
                if has_num:
                    if not sub_title or sub_title in heading_block or (len(words) >= 2 and " ".join(words[:2]) in heading_block):
                        matched_p = pnum
                        break

            # Strategy 3: Full subtitle phrase in heading block (contiguous phrase, NOT loose words)
            if sub_title and len(sub_title) >= 6:
                if sub_title in heading_block:
                    matched_p = pnum
                    break
                if len(words) >= 3 and " ".join(words[:3]) in heading_block:
                    matched_p = pnum
                    break

            # Strategy 4: Full title appears in page lines (for mid-page headings/appendices like POSDATA)
            if not matched_p and len(norm_t) >= 4:
                if any(norm_t == l or norm_t in l for l in norm_lines):
                    matched_p = pnum
                    break
                all_block = " ".join(norm_lines)
                if len(norm_t) >= 6 and norm_t in all_block:
                    matched_p = pnum
                    break

        if matched_p is not None:
            curr_min = matched_p
            page_mapping[title] = matched_p
        else:
            page_mapping[title] = curr_min

    # 4. Write synchronized page numbers back into IDML story
    updated_count = 0
    temp_zip = idml_path.with_suffix(".temp.idml")

    with zipfile.ZipFile(idml_path, "r") as zin, zipfile.ZipFile(temp_zip, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.startswith("Stories/Story_"):
                raw = data.decode("utf-8", errors="ignore")
                if "toc" in raw.lower() or "content" in raw.lower():
                    try:
                        root = ET.fromstring(data)
                        story_changed = False
                        for psr in root.findall(".//ParagraphStyleRange"):
                            style = psr.attrib.get("AppliedParagraphStyle", "")
                            if "toc" in style.lower() or "content" in style.lower():
                                for csr in psr.findall(".//CharacterStyleRange"):
                                    for cnt in csr.findall(".//Content"):
                                        if cnt.text and "\t" in cnt.text:
                                            lines = cnt.text.split("\r")
                                            new_lines = []
                                            cnt_changed = False
                                            for line in lines:
                                                if "\t" in line:
                                                    parts = line.split("\t")
                                                    t = parts[0].strip()
                                                    old_p = parts[1].strip()
                                                    if t in page_mapping:
                                                        real_p = str(page_mapping[t])
                                                        if real_p != old_p:
                                                            new_lines.append(f"{parts[0]}\t{real_p}")
                                                            cnt_changed = True
                                                            updated_count += 1
                                                        else:
                                                            new_lines.append(line)
                                                    else:
                                                        new_lines.append(line)
                                                else:
                                                    new_lines.append(line)

                                            if cnt_changed:
                                                cnt.text = "\r".join(new_lines)
                                                story_changed = True

                        if story_changed:
                            data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                    except Exception:
                        pass

            zout.writestr(item, data)

    temp_zip.replace(idml_path)
    return updated_count



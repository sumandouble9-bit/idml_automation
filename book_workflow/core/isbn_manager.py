import os
import re
import json
import io as _io
import zipfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

CACHE_FILE = Path(__file__).resolve().parent / "isbn_metadata_cache.json"
EXCEL_FILE = Path(__file__).resolve().parents[3] / "isbn_master_data.xlsx"
if not EXCEL_FILE.exists():
    EXCEL_FILE = Path(__file__).resolve().parents[2] / "isbn_master_data.xlsx"

# Live Google-Sheet source for ISBN / copyright / output-filename metadata.
# Exported to xlsx and parsed in memory (no file written) by _build_cache().
SHEET_ID = "17LJ5LVgH3eyjY2d4ApY-MAq0mUUjsAi0"
SHEET_XLSX_URL = "https://docs.google.com/spreadsheets/d/%s/export?format=xlsx" % SHEET_ID

_METADATA_BY_EPUB = None
_METADATA_BY_PRINT = None
_METADATA_BY_SR = None


def format_isbn(raw_isbn: str) -> str:
    """Formats a 13-digit ISBN into standard 3-2-5-2-1 hyphenated format (e.g. 978-81-65887-06-3)."""
    clean = re.sub(r'[^0-9xX]', '', str(raw_isbn or "")).strip()
    if len(clean) == 13:
        return f"{clean[:3]}-{clean[3:5]}-{clean[5:10]}-{clean[10:12]}-{clean[12:]}"
    return clean


def clean_sr_no(raw_sr: str) -> str:
    """Cleans serial number (e.g. '1503.0' -> '1503', '1 Old' -> '1 Old')."""
    s = str(raw_sr or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def clean_isbn(val: str) -> str:
    """Converts scientific notation or float string to clean 13-digit ISBN string."""
    s = str(val or "").strip()
    if not s:
        return ""
    try:
        return str(int(round(float(s))))
    except Exception:
        return re.sub(r'[^0-9xX]', '', s)


def _build_cache():
    """Builds the ISBN / copyright / output-filename cache. PRIMARY source is the
    live Google Sheet (exported to xlsx, parsed in memory); falls back to the
    on-disk JSON cache, then a local isbn_master_data.xlsx, if it cannot be reached."""
    global _METADATA_BY_EPUB, _METADATA_BY_PRINT, _METADATA_BY_SR

    _METADATA_BY_EPUB = {}
    _METADATA_BY_PRINT = {}
    _METADATA_BY_SR = {}

    # 1. Primary: fetch the Google Sheet as xlsx bytes (nothing written to disk).
    _zbytes = None
    try:
        _req = urllib.request.Request(SHEET_XLSX_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(_req, timeout=30) as _resp:
            _zbytes = _resp.read()
        print("[ISBN Manager] Loaded ISBN metadata from Google Sheet.")
    except Exception as e:
        print(f"[ISBN Manager] Could not reach Google Sheet ({e}); using cache/Excel fallback.")

    # 2. Fallback: on-disk JSON cache.
    if _zbytes is None:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    _METADATA_BY_EPUB = data.get("by_epub", {})
                    _METADATA_BY_PRINT = data.get("by_print", {})
                    _METADATA_BY_SR = data.get("by_sr", {})
                    return
            except Exception:
                pass
        # 3. Fallback: local Excel master.
        xlsx_path = EXCEL_FILE
        if not xlsx_path.exists():
            for cand in [
                Path("isbn_master_data.xlsx"),
                Path(__file__).resolve().parents[2] / "isbn_master_data.xlsx",
            ]:
                if cand.exists():
                    xlsx_path = cand
                    break
        if not xlsx_path.exists():
            print("[ISBN Manager] Warning: no Google Sheet, cache, or Excel source available.")
            return
        _zbytes = xlsx_path.read_bytes()

    with zipfile.ZipFile(_io.BytesIO(_zbytes), "r") as z:
        sst = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
                sst.append("".join(t.text or "" for t in si.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")))

        sheet_root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        rows = sheet_root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row")

        for r in rows[1:]:
            col_map = {}
            for c in r.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                ref = c.get("r") or ""
                col_letter = "".join(filter(str.isalpha, ref))
                v = c.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
                t = c.get("t")
                val = v.text if v is not None else ""
                if t == "s" and val.isdigit() and int(val) < len(sst):
                    val = sst[int(val)]
                col_map[col_letter] = val

            sr_no = clean_sr_no(col_map.get("A", ""))
            eng_epub = clean_isbn(col_map.get("B", ""))
            sp_print = clean_isbn(col_map.get("C", ""))
            sp_epub = clean_isbn(col_map.get("D", ""))
            title = col_map.get("E", "").strip()
            author = col_map.get("F", "").strip()

            if not sp_print and not sp_epub:
                continue

            entry = {
                "sr_no": sr_no,
                "eng_epub_isbn": eng_epub,
                "sp_print_isbn": sp_print,
                "sp_print_isbn_formatted": format_isbn(sp_print),
                "sp_epub_isbn": sp_epub,
                "sp_epub_isbn_formatted": format_isbn(sp_epub),
                "output_filename_base": f"{sr_no}_{sp_print}" if sr_no and sp_print else sp_print,
                "title": title,
                "author": author,
            }

            if sp_epub:
                _METADATA_BY_EPUB[sp_epub] = entry
            if sp_print:
                _METADATA_BY_PRINT[sp_print] = entry
            if sr_no:
                _METADATA_BY_SR[sr_no] = entry

    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "by_epub": _METADATA_BY_EPUB,
                "by_print": _METADATA_BY_PRINT,
                "by_sr": _METADATA_BY_SR,
            }, f, indent=2)
        print(f"[ISBN Manager] Saved cache ({len(_METADATA_BY_EPUB)} epub mappings) to {CACHE_FILE.name}")
    except Exception as e:
        print(f"[ISBN Manager] Note: Could not write cache: {e}")


def get_book_isbn_info(key_or_name: str) -> dict:
    """
    Looks up book metadata by epub ISBN, print ISBN, serial number, or book stem name.
    Returns metadata dict or None if not found.
    """
    global _METADATA_BY_EPUB, _METADATA_BY_PRINT, _METADATA_BY_SR
    if _METADATA_BY_EPUB is None:
        _build_cache()

    raw = str(key_or_name or "").strip()
    clean_key = re.sub(r'(_formatted|_normalized|_FINAL|_injected|\.idml|\.epub|\.pdf)$', '', raw, flags=re.I).strip()
    clean_digits = re.sub(r'[^0-9xX]', '', clean_key)

    # 1. Direct ePub ISBN lookup
    if clean_digits in _METADATA_BY_EPUB:
        return _METADATA_BY_EPUB[clean_digits]
    if clean_key in _METADATA_BY_EPUB:
        return _METADATA_BY_EPUB[clean_key]

    # 2. Direct Print ISBN lookup
    if clean_digits in _METADATA_BY_PRINT:
        return _METADATA_BY_PRINT[clean_digits]
    if clean_key in _METADATA_BY_PRINT:
        return _METADATA_BY_PRINT[clean_key]

    # 3. Serial Number lookup (e.g. '1503', '1 Old')
    if _METADATA_BY_SR:
        if clean_key in _METADATA_BY_SR:
            return _METADATA_BY_SR[clean_key]
        if clean_digits in _METADATA_BY_SR:
            return _METADATA_BY_SR[clean_digits]

    # 4. Embedded 13-digit ISBN extraction from compound filename (e.g. '1503_9788165887063')
    isbns = re.findall(r'978\d{10}', clean_key)
    for cand in isbns:
        if cand in _METADATA_BY_PRINT:
            return _METADATA_BY_PRINT[cand]
        if cand in _METADATA_BY_EPUB:
            return _METADATA_BY_EPUB[cand]

    # 5. Split by underscore or hyphen
    parts = [p.strip() for p in re.split(r'[-_]', clean_key) if p.strip()]
    for p in parts:
        p_dig = re.sub(r'[^0-9xX]', '', p)
        if p_dig in _METADATA_BY_EPUB:
            return _METADATA_BY_EPUB[p_dig]
        if p_dig in _METADATA_BY_PRINT:
            return _METADATA_BY_PRINT[p_dig]
        if _METADATA_BY_SR and (p in _METADATA_BY_SR or p_dig in _METADATA_BY_SR):
            return _METADATA_BY_SR.get(p) or _METADATA_BY_SR.get(p_dig)

    return None


def get_output_base_name(key_or_name: str) -> str:
    """Returns '{Sr No.}_{Spanish Print ISBN-13}' if mapped, otherwise original clean stem."""
    info = get_book_isbn_info(key_or_name)
    if info and info.get("output_filename_base"):
        return info["output_filename_base"]
    raw = str(key_or_name or "").strip()
    return re.sub(r'(_formatted|_normalized|_FINAL|_injected|\.idml|\.epub|\.pdf)$', '', raw, flags=re.I).strip()


if __name__ == "__main__":
    _build_cache()
    test_key = "9788166131264"
    info = get_book_isbn_info(test_key)
    print(f"Lookup for {test_key}:", info)
    print("Output base name:", get_output_base_name(test_key))

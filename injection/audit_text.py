import os
import re
import sys
import shutil
import time
import zipfile
import subprocess
import win32com.client
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import epub_tools



EPUB_INPUT_DIR = os.environ.get("EPUB_DIR", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "epub_input_files")

NORMALIZED_DIR = os.environ.get("AUDIT_SRC", "").strip() or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "page_resize_output")
RAW_INPUT_DIR  = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "input_files")

_IMG_TOKEN = re.compile(r"^(image|img|fig|figs|figure|plate|illustration)\d+$")
_EXT_TOKEN = {"jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "webp"}
_PH_TOKEN  = {"insert", "here", "image", "img", "fig", "figs", "figure", "figures",
              "plate", "plates", "illustration", "illustrations"}
_WORD_RE   = re.compile(r"[A-Za-z][A-Za-z0-9']*")
MISSING_RUN_LEN = 12
MISSING_OCC_THRESHOLD = 40


def _source_idml(book):
    """Locate the un-injected source IDML for a book (normalized first, then raw)."""
    for d in (NORMALIZED_DIR, RAW_INPUT_DIR):
        p = os.path.join(d, book + ".idml")
        if os.path.exists(p):
            return p
    return None


def _idml_story_token_lists(idml_path):
    """Per-story ordered lists of lowercase word tokens from an IDML's <Content> runs.

    An IDML is a zip; the visible text lives in Stories/Story_*.xml inside <Content>
    elements. Keeping tokens grouped by story preserves reading order within a story
    so a *consecutive* run of dropped words can be spotted.
    """
    stories = []
    try:
        with zipfile.ZipFile(idml_path) as z:
            for n in sorted(z.namelist()):
                if not (n.startswith("Stories/") and n.endswith(".xml")):
                    continue
                try:
                    xml = z.read(n).decode("utf-8", "replace")
                except Exception:
                    continue
                toks = []
                for seg in re.split(r"<Br\s*/>", xml):
                    runs = re.findall(r"<Content>(.*?)</Content>", seg, re.S)
                    txt = "".join(runs)
                    txt = re.sub(r"&#x?[0-9A-Fa-f]+;", " ", txt)
                    txt = txt.replace("&amp;", " ").replace("&lt;", " ").replace("&gt;", " ")
                    for w in _WORD_RE.findall(txt):
                        toks.append(w.lower().strip("'"))
                if toks:
                    stories.append(toks)
    except Exception:
        pass
    return stories


def missing_text_reason(source_idml, injected_idml, caption_map=None):
    """Return a MISSING_TEXT reason string if the injection dropped body text.

    Compares the source IDML's words with the injected IDML's words. Words that
    legitimately disappear are ignored: the placeholder tokens (Insert / here /
    imageNNN / file extensions) and every word used in an EPUB caption (the
    original caption is removed and replaced by the EPUB caption). A hit is
    reported when EITHER a large number of distinctive word-occurrences (length
    >= 5) are missing from the output (>= MISSING_OCC_THRESHOLD) — catches a
    dropped paragraph/heading even when its words recur elsewhere — OR a
    *consecutive run* of >= MISSING_RUN_LEN source words is entirely absent from
    the output — catches a localised unique passage. Returns None when nothing
    meaningful is lost.
    """
    if not (source_idml and os.path.exists(source_idml) and os.path.exists(injected_idml)):
        return None
    src_stories = _idml_story_token_lists(source_idml)
    out_stories = _idml_story_token_lists(injected_idml)
    if not src_stories or not out_stories:
        return None
    out_tokens, out_all = set(), []
    for toks in out_stories:
        out_tokens.update(toks)
        out_all.extend(toks)

    ignore = set(_PH_TOKEN) | set(_EXT_TOKEN)
    if caption_map:
        for v in caption_map.values():
            for w in _WORD_RE.findall(v):
                ignore.add(w.lower().strip("'-"))

    def keep(w):
        # Keep only meaningful words (>=5 chars, not ignored, not an image token).
        return len(w) >= 5 and w not in ignore and not _IMG_TOKEN.match(w)

    from collections import Counter
    cs = Counter(w for s in src_stories for w in s if keep(w))
    co = Counter(w for w in out_all if keep(w))
    lost_occ, lost_words = 0, []
    for w, c in cs.items():
        d = c - co.get(w, 0)
        if d > 0:
            lost_occ += d
            lost_words.append((d, w))

    def is_missing(w):
        # A source word counts as missing when it is absent from the output tokens.
        return len(w) >= 2 and w not in ignore and not _IMG_TOKEN.match(w) and w not in out_tokens
    spans = []
    for toks in src_stories:
        i, n = 0, len(toks)
        while i < n:
            if is_missing(toks[i]):
                j = i
                while j < n and is_missing(toks[j]):
                    j += 1
                anchor, k = [], i - 1
                while k >= 0 and len(anchor) < 3:
                    if not is_missing(toks[k]):
                        anchor.insert(0, toks[k])
                    k -= 1
                spans.append((j - i, anchor, toks[i:j]))
                i = j
            else:
                i += 1
    best_run = max((L for L, _, _ in spans), default=0)

    if lost_occ >= MISSING_OCC_THRESHOLD or best_run >= MISSING_RUN_LEN:
        lost_words.sort(reverse=True)
        sample = " ".join(w for _, w in lost_words[:15]) or ""
        msg = "MISSING_TEXT=lost_occ=%d,run=%d:[%s]" % (lost_occ, best_run, sample)
        spans.sort(key=lambda x: x[0], reverse=True)
        return (msg, spans, lost_words)
    return None


__all__ = [
    'EPUB_INPUT_DIR',
    'NORMALIZED_DIR',
    '_IMG_TOKEN',
    '_EXT_TOKEN',
    'MISSING_RUN_LEN',
    'MISSING_OCC_THRESHOLD',
    '_source_idml',
    '_idml_story_token_lists',
    'missing_text_reason',
]

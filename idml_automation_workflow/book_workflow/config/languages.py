"""Language registry and content-based detector.

Holds one LanguageConfig per supported language and reproduces the original
content-based language detection exactly (stem markers first, then a
keyword-frequency comparison), now driven by the registry instead of hard-coded
keyword lists.
"""

import re
import zipfile
from pathlib import Path

from .language_config import LanguageConfig

ENGLISH = LanguageConfig(
    code="en",
    display_name="ENGLISH (EN)",
    stem_markers=("_en", "english"),
    detection_keywords=(
        "chapter", "contents", "about the author", "copyright", "part one",
        "preface", "published by", " of ", " in ", " that ", " with ", " for ",
        " by ", " the ", " from ", " and ",
    ),
    front_matter_titles=("contents", "about the author", "copyright"),
    runs_internal_typography_postprocess=True,
)

SPANISH = LanguageConfig(
    code="es",
    display_name="SPANISH (ES)",
    stem_markers=("_es", "spanish"),
    detection_keywords=(
        "capítulo", "capitulo", "contenido", "sobre la autoría", "sobre la autoria",
        "derechos de autor", "parte primera", "prólogo", "prologo", " de ", " en ",
        " que ", " con ", " para ", " por ", " los ", " las ", " una ", " del ",
    ),
    front_matter_titles=("contenido", "sobre la autoría", "derechos de autor"),
)

LANGUAGES = {cfg.code: cfg for cfg in (ENGLISH, SPANISH)}
DEFAULT_LANGUAGE = "en"


def get_language(code):
    # Return the LanguageConfig for a code, falling back to the default language.
    return LANGUAGES.get(code, LANGUAGES[DEFAULT_LANGUAGE])


def _sample_story_text(idml_path):
    # Concatenate the <Content> text of the largest stories (same sampling the
    # original detector used: 8 biggest stories, first 150k chars each).
    with zipfile.ZipFile(idml_path, "r") as archive:
        story_files = [n for n in archive.namelist() if n.startswith("Stories/Story_")]
        story_files.sort(key=lambda n: archive.getinfo(n).file_size, reverse=True)
        samples = []
        for story in story_files[:8]:
            raw = archive.read(story).decode("utf-8", errors="ignore")
            contents = re.findall(r"<Content>(.*?)</Content>", raw[:150000])
            if contents:
                samples.append(" ".join(contents))
    return " ".join(samples).lower()


def detect_language(idml_path):
    # Reproduce the original detection order exactly: explicit stem marker wins,
    # otherwise the language with the higher keyword score (English on a tie or
    # on any read error).
    idml_path = Path(idml_path)
    stem = idml_path.stem.lower()
    if SPANISH.matches_stem(stem):
        return "es"
    if ENGLISH.matches_stem(stem):
        return "en"
    try:
        text = _sample_story_text(idml_path)
        es_score = SPANISH.detection_score(text)
        en_score = ENGLISH.detection_score(text)
        return "es" if es_score > en_score else "en"
    except Exception:
        return DEFAULT_LANGUAGE

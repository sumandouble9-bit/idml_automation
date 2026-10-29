"""Per-language configuration for the unified pipeline engine."""

from .language_config import LanguageConfig
from .languages import LANGUAGES, DEFAULT_LANGUAGE, detect_language, get_language

__all__ = [
    "LanguageConfig",
    "LANGUAGES",
    "DEFAULT_LANGUAGE",
    "detect_language",
    "get_language",
]

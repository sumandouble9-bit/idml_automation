"""Modular, language-configurable IDML publishing engine.

Single OOP pipeline that replaces the duplicated English/Spanish code paths.
Each language is expressed as a LanguageConfig; the same formatting, injection,
post-processing and export logic runs for every language (English, Spanish,
Portuguese, ...). Behaviour is preserved from the original scripts; only the
structure is modular.
"""

__version__ = "1.0.0"

from .pipeline import Pipeline, main

__all__ = ["Pipeline", "main"]

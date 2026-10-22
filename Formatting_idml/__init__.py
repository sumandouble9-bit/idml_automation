"""
Formatting_idml: 1st Module for Double Nine Books IDML Automation
Clean, organized, OOP architecture for IDML typography normalization,
EPUB inline styling extraction, atomic caption injection, table preservation,
and integrated PDF/X export & validation.
"""

from Formatting_idml.epub_parser import EpubParser, EpubFormattingMap
from Formatting_idml.caption_injector import CaptionInjector
from Formatting_idml.image_layout_manager import ImageLayoutManager
from Formatting_idml.text_style_normalizer import TextStyleNormalizer
from Formatting_idml.chapter_processor import ChapterProcessor, ChapterInfo
from Formatting_idml.pdf_exporter import PdfExporter
from Formatting_idml.pipeline import FormattingIDMLPipeline

__all__ = [
    "EpubParser",
    "EpubFormattingMap",
    "CaptionInjector",
    "ImageLayoutManager",
    "TextStyleNormalizer",
    "ChapterProcessor",
    "ChapterInfo",
    "PdfExporter",
    "FormattingIDMLPipeline",
]

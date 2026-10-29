"""Unified Core Publishing Infrastructure for IDML & InDesign automation.

Contains all shared utilities: InDesign COM integration, font resolution,
ISBN management, heading classification, TOC synchronization, and XML manipulation.
"""

from .indesign_app import InDesignApp, JS_LANGUAGE

__all__ = [
    "InDesignApp",
    "JS_LANGUAGE",
]

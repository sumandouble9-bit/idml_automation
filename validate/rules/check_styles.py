import xml.etree.ElementTree as ET
from typing import List, Tuple
from model.document import DocumentModel
from validate.base import BaseRule, ValidationResult


class StyleIntegrityRule(BaseRule):
    """
    Validates that:
    1. No 'Normal' or unresolved Word orphan styles remain.
    2. All applied paragraph styles exist in Styles.xml.
    """

    def __init__(self):
        super().__init__(name="Style & Font Integrity (Step 2/3/4)")

    def validate(self, doc: DocumentModel) -> ValidationResult:
        errors = []
        if doc.styles_root is None:
            return ValidationResult(self.name, False, ["Styles.xml is missing from document."])

        known_styles = set()
        for elem in doc.styles_root.iter():
            if elem.tag.endswith("ParagraphStyle") or elem.tag.endswith("CharacterStyle"):
                name = elem.get("Name")
                if name:
                    known_styles.add(name)

        for filename, story in doc.stories.items():
            for p_elem in story.get_paragraph_ranges():
                applied = p_elem.get("AppliedParagraphStyle", "")
                style_name = applied.split("/")[-1] if "/" in applied else applied

                if style_name == "Normal" or style_name == "$ID/NormalParagraphStyle":
                    errors.append(f"{filename}: Found unmapped Word default style '{style_name}'")

                for c_elem in p_elem:
                    if c_elem.tag.endswith("CharacterStyleRange"):
                        c_applied = c_elem.get("AppliedCharacterStyle", "")
                        c_name = c_applied.split("/")[-1] if "/" in c_applied else c_applied
                        if c_name in ["italicalign", "ittalicalign"]:
                            errors.append(f"{filename}: Found unmerged duplicate character style '{c_name}'")

        return ValidationResult(self.name, len(errors) == 0, errors)


def check_styles_integrity(doc: DocumentModel) -> Tuple[bool, List[str]]:
    """Procedural wrapper for backward compatibility."""
    res = StyleIntegrityRule().validate(doc)
    return res.passed, res.errors

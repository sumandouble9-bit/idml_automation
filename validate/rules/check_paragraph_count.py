from typing import List, Tuple, Dict, Optional
from model.document import DocumentModel
from validate.base import BaseRule, ValidationResult


class ParagraphStabilityRule(BaseRule):
    """
    Validates that the paragraph count across stories does not unexpectedly drop
    after transformations (preventing accidental loss of prose or chapter content).
    """

    def __init__(self, initial_counts: Optional[Dict[str, int]] = None):
        super().__init__(name="Paragraph Stability (Content Preservation)")
        self.initial_counts = initial_counts or {}

    def set_initial_counts(self, counts: Dict[str, int]):
        self.initial_counts = counts

    def validate(self, doc: DocumentModel) -> ValidationResult:
        errors = []
        for filename, story in doc.stories.items():
            initial = self.initial_counts.get(filename, 0)
            current = len(story.get_paragraph_ranges())

            # Allow slight differences if empty break paragraphs were cleaned or lines split
            if initial > 0 and current < (initial - 50):
                errors.append(
                    f"{filename}: Paragraph count dropped from {initial} to {current} (potential dropped content!)"
                )

        return ValidationResult(self.name, len(errors) == 0, errors)


def check_paragraph_stability(
    before_counts: Dict[str, int], 
    after_doc: DocumentModel
) -> Tuple[bool, List[str]]:
    """Procedural wrapper for backward compatibility."""
    rule = ParagraphStabilityRule(initial_counts=before_counts)
    res = rule.validate(after_doc)
    return res.passed, res.errors

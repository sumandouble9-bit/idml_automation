from typing import List, Tuple, Dict
from model.document import DocumentModel


def check_paragraph_stability(
    before_counts: Dict[str, int], 
    after_doc: DocumentModel
) -> Tuple[bool, List[str]]:
    """
    Validates that the paragraph count across stories does not unexpectedly drop
    after transformations.
    """
    errors = []
    for filename, story in after_doc.stories.items():
        initial = before_counts.get(filename, 0)
        current = len(story.get_paragraph_ranges())

        # Allow slight differences if empty break paragraphs were cleaned or lines were split
        if current < (initial - 50):
            errors.append(
                f"{filename}: Paragraph count dropped from {initial} to {current} (potential dropped content!)"
            )

    return len(errors) == 0, errors

from typing import Dict, List, Tuple
from model.document import DocumentModel
from validate.rules.check_styles import check_styles_integrity
from validate.rules.check_images import check_images_integrity, check_images_visibility_and_layout
from validate.rules.check_paragraph_count import check_paragraph_stability


class Validator:
    """
    Step 7: Rule Validator that acts as an automated quality gate.
    Runs rule checks across the document and routes failure back to the owning step.
    Supports both Pre-Layout (IDML XML) and Post-Layout (PDF output) validation.
    """

    def __init__(self):
        self.rules = [
            ("Style & Font Integrity (Step 2/3/4)", check_styles_integrity),
            ("Image Marker Integrity (Step 5)", check_images_integrity),
        ]

    def validate(self, doc: DocumentModel, initial_counts: Dict[str, int] = None) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Runs all pre-layout validation rules against the document model.
        Returns (is_valid, report_dict)
        """
        report: Dict[str, List[str]] = {}
        all_passed = True

        for rule_name, rule_fn in self.rules:
            passed, errors = rule_fn(doc)
            if not passed:
                all_passed = False
                report[rule_name] = errors

        if initial_counts:
            passed, errors = check_paragraph_stability(initial_counts, doc)
            if not passed:
                all_passed = False
                report["Paragraph Stability (Content Preservation)"] = errors

        return all_passed, report

    def validate_pdf(self, pdf_path: str) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Runs post-layout validation rules on the final exported PDF.
        Asserts image visibility/clarity thresholds and absence of unjustified dead white space.
        Returns (is_valid, report_dict)
        """
        report: Dict[str, List[str]] = {}
        passed, errors = check_images_visibility_and_layout(pdf_path)
        if not passed:
            report["Image Visibility & Zero White Space Gate"] = errors

        return len(report) == 0, report


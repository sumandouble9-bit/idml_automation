"""
validate: Validator
Orchestrates pre-layout (IDML XML) and post-layout (PDF output) quality gates
using polymorphic validation rules.
"""

from typing import Dict, List, Optional, Tuple
from model.document import DocumentModel
from validate.base import BaseRule, ValidationResult
from validate.rules.check_styles import StyleIntegrityRule
from validate.rules.check_images import ImageMarkerRule, PdfImageVisibilityRule
from validate.rules.check_paragraph_count import ParagraphStabilityRule


class Validator:
    """
    Automated Quality Gate orchestrator.
    Executes a collection of polymorphic BaseRule objects against IDML documents or exported PDFs.
    Allows custom rule injection for specialized book formatting requirements.
    """

    def __init__(
        self,
        document_rules: Optional[List[BaseRule]] = None,
        pdf_rules: Optional[List[BaseRule]] = None
    ):
        self.document_rules: List[BaseRule] = document_rules if document_rules is not None else [
            StyleIntegrityRule(),
            ImageMarkerRule(),
        ]
        self.pdf_rules: List[BaseRule] = pdf_rules if pdf_rules is not None else [
            PdfImageVisibilityRule(),
        ]
        self.stability_rule = ParagraphStabilityRule()

    def add_document_rule(self, rule: BaseRule):
        """Registers an additional pre-layout validation rule."""
        self.document_rules.append(rule)

    def add_pdf_rule(self, rule: BaseRule):
        """Registers an additional post-layout validation rule."""
        self.pdf_rules.append(rule)

    def validate(self, doc: DocumentModel, initial_counts: Optional[Dict[str, int]] = None) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Runs all pre-layout validation rules against the document model.
        Returns (is_valid, report_dict)
        """
        report: Dict[str, List[str]] = {}
        all_passed = True

        for rule in self.document_rules:
            result = rule.validate(doc)
            if not result.passed:
                all_passed = False
                report[rule.name] = result.errors

        if initial_counts:
            self.stability_rule.set_initial_counts(initial_counts)
            stability_res = self.stability_rule.validate(doc)
            if not stability_res.passed:
                all_passed = False
                report[self.stability_rule.name] = stability_res.errors

        return all_passed, report

    def validate_pdf(self, pdf_path: str) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Runs post-layout validation rules on the final exported PDF.
        Asserts image visibility/clarity thresholds and absence of unjustified dead white space.
        Returns (is_valid, report_dict)
        """
        report: Dict[str, List[str]] = {}
        all_passed = True

        for rule in self.pdf_rules:
            result = rule.validate(pdf_path)
            if not result.passed:
                all_passed = False
                report[rule.name] = result.errors

        return all_passed, report

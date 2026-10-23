"""
validate: Base Rule & Result Abstractions
Defines the polymorphic contract for document and PDF validation rules.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class ValidationResult:
    """Encapsulates the result of executing a single validation rule."""
    rule_name: str
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.passed


class BaseRule(ABC):
    """
    Abstract Base Class for all validation rules.
    Enforces the Strategy/Polymorphic pattern across pre-layout and post-layout checks.
    """

    def __init__(self, name: str = None):
        self.name = name or self.__class__.__name__

    @abstractmethod
    def validate(self, target: Any) -> ValidationResult:
        """
        Executes rule check against target (e.g. DocumentModel or PDF path).
        Returns a structured ValidationResult.
        """
        pass

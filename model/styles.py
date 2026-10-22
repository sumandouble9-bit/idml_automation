from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class ParagraphStyle:
    name: str
    font_family: Optional[str] = None
    font_style: Optional[str] = None
    point_size: Optional[str] = None
    leading: Optional[str] = None
    first_line_indent: Optional[str] = None
    justification: Optional[str] = None
    space_before: Optional[str] = None
    space_after: Optional[str] = None
    raw_attributes: Dict[str, str] = field(default_factory=dict)


@dataclass
class CharacterStyle:
    name: str
    font_style: Optional[str] = None
    point_size: Optional[str] = None
    position: Optional[str] = None
    raw_attributes: Dict[str, str] = field(default_factory=dict)

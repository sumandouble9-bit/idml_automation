from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class LanguageConfig:
    # Immutable description of one book language and the tokens used to detect,
    # classify and label its content. Fields are grouped by concern so later
    # refactor phases can attach style/font maps without changing call sites.
    code: str
    display_name: str
    stem_markers: Tuple[str, ...] = field(default_factory=tuple)
    detection_keywords: Tuple[str, ...] = field(default_factory=tuple)
    front_matter_titles: Tuple[str, ...] = field(default_factory=tuple)
    # True when the language's formatter applies the typography post-processor
    # internally at the end of formatting (English does; Spanish does not).
    runs_internal_typography_postprocess: bool = False

    def matches_stem(self, stem: str) -> bool:
        # True when a filename stem explicitly names this language (e.g. "_es").
        low = stem.lower()
        return any(marker in low for marker in self.stem_markers)

    def detection_score(self, text: str) -> int:
        # Sum of detection-keyword occurrences in lowercased content; the engine
        # picks the language with the highest score (same rule as the original
        # content-based detector).
        return sum(text.count(keyword) for keyword in self.detection_keywords)
